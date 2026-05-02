"""
streamlit_app/email_job.py

Unified CRM email job — called by GitHub Actions to send pending-delivery
emails covering BOTH Franchise and 4S Interiors records from a single run.

Routing priority:
  1. MANUAL_JOB env var  (workflow_dispatch UI trigger)
  2. SLOT env var        (set by workflow step — immune to clock drift)
  3. IST hour fallback   (±1 hr window, catches GitHub Actions delays)

Schedule:
  10:00 AM IST → Email 1: Pending Delivery Report     [SLOT=morning]
  11:00 AM IST → Email 2: Update Delivery Status      [SLOT=reminder]
   5:00 PM IST → Email 1: Pending Delivery (evening)  [SLOT=evening]
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender_4s import (
    send_pending_delivery_email_4s,
    send_update_delivery_status_email_4s,
)

# ── IST time ──────────────────────────────────────────────────────────────────
IST          = timezone(timedelta(hours=5, minutes=30))
now_ist      = datetime.now(IST)
current_hour = now_ist.hour

print(f"[CRM Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

MANUAL_JOB = os.getenv("MANUAL_JOB", "").strip()
SLOT       = os.getenv("SLOT", "").strip().lower()   # "morning" | "reminder" | "evening"

print(f"[CRM Job] SLOT={SLOT!r}  MANUAL_JOB={MANUAL_JOB!r}  hour={current_hour}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_mixed_dates(series):
    """Safely parse mixed-format date strings (DD-MM-YYYY, DD-Mon-YYYY, etc.).

    Always operates on a flat Series so it never hits the
    'ValueError: cannot assemble with duplicate keys' that pd.to_datetime()
    raises when passed a DataFrame (i.e. duplicate column names).
    """
    series = series.astype(str).str.strip()
    parsed = []
    for val in series:
        d = pd.NaT
        for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y"):
            try:
                d = datetime.strptime(val, fmt)
                break
            except Exception:
                pass
        if pd.isna(d):
            d = pd.to_datetime(val, dayfirst=True, errors="coerce")
        parsed.append(d)
    return pd.Series(parsed, dtype="datetime64[ns]")


def _group_by_order_no(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse multiple line-items sharing an ORDER NO into one row."""
    if df.empty or "ORDER NO" not in df.columns:
        return df

    valid_mask = (
        df["ORDER NO"].notna() &
        (~df["ORDER NO"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"]))
    )
    has_no = df[valid_mask].copy()
    no_no  = df[~valid_mask].copy()

    if has_no.empty:
        return df

    agg = {}
    if "PRODUCT NAME" in has_no.columns:
        agg["PRODUCT NAME"] = lambda x: ",\n".join(
            x.dropna().astype(str).str.strip().unique()
        )

    for col in ["QTY", "ORDER VALUE", "GROSS AMT EX-TAX", "ADVANCE RECEIVED"]:
        if col in has_no.columns:
            agg[col] = "sum"

    for col in ["ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
                "CATEGORY", "SALES PERSON", "DELIVERY DATE",
                "DELIVERY STATUS", "REMARKS", "SOURCE"]:
        if col in has_no.columns and col not in agg:
            agg[col] = "first"

    if not agg:
        return df

    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    return pd.concat([grouped, no_no], ignore_index=True)


# ── Data loader ───────────────────────────────────────────────────────────────

def fetch_all_pending():
    """
    Load pending delivery records from BOTH Franchise and 4S Interiors sheets.
    Returns a grouped DataFrame (one row per ORDER NO) ready for emailing.
    """
    print("  → Fetching data from Google Sheets (Franchise + 4S Interiors)...")

    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
        print("  → SHEET_DETAILS not found or empty.")
        return pd.DataFrame()

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
        if "Franchise_sheets" in config_df.columns else []
    )
    fours_sheets = (
        config_df["four_s_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
        if "four_s_sheets" in config_df.columns else []
    )

    dfs = []
    for source_label, sheet_list in [("Franchise", franchise_sheets), ("4S Interiors", fours_sheets)]:
        for name in sheet_list:
            try:
                df = get_df(name)
                if df is None or df.empty:
                    continue
                df.columns = [str(col).strip().upper() for col in df.columns]
                df = df.loc[:, ~df.columns.duplicated()]
                df = df.dropna(axis=1, how="all")
                df["SOURCE"] = source_label
                dfs.append(df)
                print(f"  → Loaded '{name}' ({source_label}): {len(df)} rows")
            except Exception as e:
                print(f"  → Skipping sheet '{name}': {e}")
                continue

    if not dfs:
        print("  → No data found in any sheet.")
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # ── Step 1: Rename all known column variants to working names ─────────────
    crm = crm.rename(columns={
        # Amount columns
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER VALUE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
        # Date columns
        "DATE":                                            "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CUSTOMER DELIVERY DATE":                          "DELIVERY DATE",
        # People
        "SALES REP":                                       "SALES PERSON",
        "SALES EXECUTIVE":                                 "SALES PERSON",
        # Payment
        "ADV RECEIVED":                                    "ADVANCE RECEIVED",
    })

    # Drop any duplicate columns produced by the rename above
    crm = crm.loc[:, ~crm.columns.duplicated()]

    # ── Step 2: Fuzzy-resolve the delivery status column ──────────────────────
    # Column name varies across sheet versions — may have extra spaces, different
    # punctuation, or a slightly different label ("REMARKS", "DELIVERY STATUS", etc.)
    if "DELIVERY STATUS" not in crm.columns:
        def _norm(s):
            return str(s).upper().strip().replace(" ", "")

        found = None
        for col in crm.columns:
            n = _norm(col)
            if n.startswith("DELIVERYREMARKS") or n in ("REMARKS", "DELIVERYSTATUS"):
                found = col
                break
        if found:
            crm = crm.rename(columns={found: "DELIVERY STATUS"})
            print(f"  → Resolved delivery-status column: '{found}' → 'DELIVERY STATUS'")
        else:
            print(
                f"  ⚠ Delivery status column not found. "
                f"Available columns: {list(crm.columns)[:20]}\n"
                f"  Defaulting all rows to PENDING."
            )
            crm["DELIVERY STATUS"] = "PENDING"

    # ── Step 3: Numeric cleanup ────────────────────────────────────────────────
    for col in ("ORDER VALUE", "ADVANCE RECEIVED", "GROSS AMT EX-TAX"):
        if col in crm.columns:
            crm[col] = pd.to_numeric(
                crm[col].astype(str).str.replace(r"[₹,\s]", "", regex=True),
                errors="coerce",
            ).fillna(0)

    # Fall back: use GROSS AMT EX-TAX if ORDER VALUE is missing
    if "ORDER VALUE" not in crm.columns and "GROSS AMT EX-TAX" in crm.columns:
        crm["ORDER VALUE"] = crm["GROSS AMT EX-TAX"]

    # ── Step 4: Date cleanup ───────────────────────────────────────────────────
    for date_col in ("ORDER DATE", "DELIVERY DATE"):
        if date_col in crm.columns:
            crm[date_col] = parse_mixed_dates(crm[date_col])

    # ── Step 5: Filter valid orders (non-zero amount) ──────────────────────────
    if "ORDER VALUE" in crm.columns:
        crm = crm[crm["ORDER VALUE"] > 0].copy()

    # ── Step 6: Default empty DELIVERY STATUS → PENDING ───────────────────────
    empty_mask = crm["DELIVERY STATUS"].astype(str).str.strip().isin(
        ["", "nan", "NaN", "None", "none"]
    )
    crm.loc[empty_mask, "DELIVERY STATUS"] = "PENDING"

    # ── Step 7: Filter PENDING rows only ──────────────────────────────────────
    pending = crm[
        crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
    ].copy()

    franchise_cnt = int((pending.get("SOURCE", pd.Series()) == "Franchise").sum())
    fours_cnt     = int((pending.get("SOURCE", pd.Series()) == "4S Interiors").sum())
    print(f"  → {len(pending)} pending line-items "
          f"(Franchise: {franchise_cnt}, 4S Interiors: {fours_cnt})")

    # ── Step 8: Group by ORDER NO ──────────────────────────────────────────────
    pending = _group_by_order_no(pending)
    print(f"  → {len(pending)} pending orders after grouping by ORDER NO.")
    return pending


# ── Fetch combined pending data ───────────────────────────────────────────────

pending = fetch_all_pending()

if pending.empty:
    print("[CRM Job] No pending deliveries found across all sheets. Skipping email.")
    sys.exit(0)


# ── Route to correct email ────────────────────────────────────────────────────

# PRIORITY 1: Manual trigger via GitHub Actions workflow_dispatch UI
# Accept old job names (godrej_*/fours_*) and new unified names (crm_*)
if MANUAL_JOB in ("crm_email1", "godrej_email1", "fours_email1"):
    print("Manual trigger → Sending Pending Delivery Report (all sources)...")
    send_pending_delivery_email_4s(pending)

elif MANUAL_JOB in ("crm_email2", "godrej_email2", "fours_email2"):
    print("Manual trigger → Sending Update Delivery Status Reminder (all sources)...")
    send_update_delivery_status_email_4s(pending)

elif MANUAL_JOB in ("crm_email3", "godrej_email3", "fours_email3"):
    print("Manual trigger → Sending Evening Pending Delivery Report (all sources)...")
    send_pending_delivery_email_4s(pending)

# PRIORITY 2: SLOT env var (set by workflow step — immune to clock drift)
elif SLOT == "morning":
    print("SLOT=morning → Sending Morning Pending Delivery Report...")
    send_pending_delivery_email_4s(pending)

elif SLOT == "reminder":
    print("SLOT=reminder → Sending Update Delivery Status Reminder...")
    send_update_delivery_status_email_4s(pending)

elif SLOT == "evening":
    print("SLOT=evening → Sending Evening Pending Delivery Report...")
    send_pending_delivery_email_4s(pending)

# PRIORITY 3: IST hour fallback (±1 hr window handles GitHub Actions delays)
elif current_hour in (9, 10):
    print(f"Hour-fallback ({current_hour}h IST) → Sending Morning Pending Delivery Report...")
    send_pending_delivery_email_4s(pending)

elif current_hour == 11:
    print(f"Hour-fallback (11h IST) → Sending Update Delivery Status Reminder...")
    send_update_delivery_status_email_4s(pending)

elif current_hour in (16, 17, 18):
    print(f"Hour-fallback ({current_hour}h IST) → Sending Evening Pending Delivery Report...")
    send_pending_delivery_email_4s(pending)

else:
    print(
        f"[CRM Job] No email mapped for IST hour {current_hour}. "
        f"Set SLOT='morning', 'reminder', or 'evening' in the workflow step."
    )
    sys.exit(1)
