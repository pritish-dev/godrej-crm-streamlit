"""
streamlit_app/email_job.py

Standalone script called by GitHub Actions to send Godrej CRM emails.
Routing priority:
  1. MANUAL_JOB env var  (workflow_dispatch UI trigger)
  2. SLOT env var        (set by workflow step — "morning", "reminder", "evening")
  3. IST hour fallback   (±1 hr window — catches GitHub Actions scheduler delays)

Schedule:
  10:00 AM IST → Email 1: Pending Delivery Report (Morning)   [SLOT=morning]
  11:00 AM IST → Email 2: Update Delivery Status Reminder     [SLOT=reminder]
   5:00 PM IST → Email 1: Pending Delivery Report (Evening)   [SLOT=evening]
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender import (
    send_pending_delivery_email,
    send_update_delivery_status_email,
)

# ── IST time ──────────────────────────────────────────────────────────────────
IST          = timezone(timedelta(hours=5, minutes=30))
now_ist      = datetime.now(IST)
current_hour = now_ist.hour

print(f"[Godrej Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

# Routing env vars — SLOT is set by the workflow step; MANUAL_JOB from UI dispatch
MANUAL_JOB = os.getenv("MANUAL_JOB", "").strip()
SLOT       = os.getenv("SLOT", "").strip().lower()  # "morning" | "reminder" | "evening"

print(f"[Godrej Job] SLOT={SLOT!r}  MANUAL_JOB={MANUAL_JOB!r}  hour={current_hour}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_mixed_dates(series):
    """Safely parse a Series of date strings in mixed formats (DD-MM-YYYY, DD-Mon-YYYY, etc.).

    Unlike calling pd.to_datetime() directly on crm.get("DATE"), this helper always
    receives a flat Series — so it can never crash with
    'ValueError: cannot assemble with duplicate keys', which happens when
    crm.get("DATE") returns a DataFrame (i.e. when duplicate "DATE" columns exist
    after pd.concat + rename).
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


def fix_duplicate_columns(df):
    cols, count = [], {}
    for col in df.columns:
        col_name = str(col).strip().upper()
        if col_name in count:
            count[col_name] += 1
            cols.append(f"{col_name}_{count[col_name]}")
        else:
            count[col_name] = 0
            cols.append(col_name)
    df.columns = cols
    return df


def fetch_pending_grouped():
    """
    Fetches Godrej CRM data from Google Sheets and returns
    the pending_grouped DataFrame matching app.py logic.
    """
    print("  → Fetching Godrej data from Google Sheets...")

    config_df = get_df("SHEET_DETAILS")
    dfs = []
    for name in config_df["Franchise_sheets"].dropna().unique():
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            # FIX: fix_duplicate_columns renames dupes but doesn't drop them;
            # after pd.concat + rename, a sheet with both "DATE" and "ORDER DATE"
            # columns causes rename to produce two "DATE" columns, making
            # crm.get("DATE") return a DataFrame → pd.to_datetime crashes.
            # Drop any remaining per-sheet duplicates here as a second guard.
            df = df.loc[:, ~df.columns.duplicated()]
            dfs.append(df)

    if not dfs:
        print("  → No data found.")
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True)

    # ── Step 1: Rename well-known column variants to working names ───────────────
    crm = crm.rename(columns={
        "ORDER UNIT PRICE=(AFTER DISC + TAX)": "ORDER AMOUNT",
        "ORDER DATE":                          "DATE",   # normalise to DATE for grouping
    })

    # FIX: the rename above maps "ORDER DATE" → "DATE", but some sheets already
    # have a "DATE" column — after pd.concat this creates two "DATE" columns.
    # Drop any post-rename duplicates before any column access.
    crm = crm.loc[:, ~crm.columns.duplicated()]

    # ── Step 2: Fuzzy-resolve the delivery status column ─────────────────────────
    # The column name varies across sheet versions and may have extra spaces,
    # different punctuation, or a slightly different label. We search for the
    # first column whose normalised name starts with "DELIVERY REMARKS" or
    # equals "REMARKS" / "DELIVERY STATUS", then canonicalise it.
    if "DELIVERY REMARKS" not in crm.columns:
        def _strip(s):
            return str(s).upper().strip().replace(" ", "")

        found = None
        for col in crm.columns:
            n = _strip(col)
            if n.startswith("DELIVERYREMARKS") or n in ("REMARKS", "DELIVERYSTATUS"):
                found = col
                break
        if found:
            crm = crm.rename(columns={found: "DELIVERY REMARKS"})
            print(f"  → Resolved delivery-status column: '{found}' → 'DELIVERY REMARKS'")
        else:
            # Column missing entirely — default all rows to PENDING so nothing
            # is silently filtered out; the email will show all orders.
            print(
                f"  ⚠ 'DELIVERY REMARKS' column not found in any sheet. "
                f"Available columns: {list(crm.columns)[:20]}\n"
                f"  Defaulting all rows to PENDING."
            )
            crm["DELIVERY REMARKS"] = "PENDING"

    # ── Step 3: Numeric cleanup ───────────────────────────────────────────────────
    crm["ORDER AMOUNT"] = pd.to_numeric(
        crm.get("ORDER AMOUNT", pd.Series("0")).astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0)
    crm["ADV RECEIVED"] = pd.to_numeric(
        crm.get("ADV RECEIVED", pd.Series("0")).astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0)

    # ── Step 4: Date cleanup ──────────────────────────────────────────────────────
    # FIX: use parse_mixed_dates() instead of pd.to_datetime(crm.get("DATE"), ...)
    # crm.get("DATE") returns a DataFrame when duplicate columns exist, causing
    # "ValueError: cannot assemble with duplicate keys" in pd.to_datetime.
    if "DATE" in crm.columns:
        crm["DATE"] = parse_mixed_dates(crm["DATE"])
    if "CUSTOMER DELIVERY DATE (TO BE)" in crm.columns:
        crm["CUSTOMER DELIVERY DATE (TO BE)"] = parse_mixed_dates(
            crm["CUSTOMER DELIVERY DATE (TO BE)"]
        )

    # ── Step 5: Filter PENDING rows ───────────────────────────────────────────────
    mask = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
    pending = crm[mask].copy()

    if pending.empty:
        print("  → No pending deliveries found.")
        return pd.DataFrame()

    # ── Group by ORDER NO so each order is one row in the email table ──────────
    # Products belonging to the same ORDER NO are joined with ',\n' so they
    # render on separate lines in the HTML email (the email_sender converts
    # '\n' to <br>).
    if "ORDER NO" in pending.columns:
        valid_mask = (
            pending["ORDER NO"].notna() &
            (~pending["ORDER NO"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"]))
        )
        has_no = pending[valid_mask].copy()
        no_no  = pending[~valid_mask].copy()

        agg = {}
        if "PRODUCT NAME" in has_no.columns:
            agg["PRODUCT NAME"] = lambda x: ",\n".join(
                x.dropna().astype(str).str.strip().unique()
            )
        for col in ["CONTACT NUMBER", "SALES PERSON",
                    "CUSTOMER NAME", "DELIVERY REMARKS"]:
            if col in has_no.columns:
                agg[col] = "first"
        if "DATE" in has_no.columns:
            agg["DATE"] = "min"
        if "CUSTOMER DELIVERY DATE (TO BE)" in has_no.columns:
            agg["CUSTOMER DELIVERY DATE (TO BE)"] = "first"

        if agg and not has_no.empty:
            grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
            pending_grouped = pd.concat([grouped, no_no], ignore_index=True)
        else:
            pending_grouped = pending.copy()
    else:
        # Fallback: legacy grouping by customer + delivery date
        pending_grouped = pending.groupby(
            ["CUSTOMER NAME", "CUSTOMER DELIVERY DATE (TO BE)"]
        ).agg({
            "PRODUCT NAME":  lambda x: ",\n".join(x.dropna().astype(str).str.strip().unique()),
            "CONTACT NUMBER": "first",
            "SALES PERSON":   "first",
            "DATE":           "min",
            "DELIVERY REMARKS": "first"
        }).reset_index()

    pending_grouped.rename(columns={
        "DATE":                              "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)":    "DELIVERY DATE"
    }, inplace=True)

    print(f"  → {len(pending_grouped)} pending records (grouped by ORDER NO).")
    return pending_grouped


# ── Decide which job to run ───────────────────────────────────────────────────

df = fetch_pending_grouped()

if df.empty:
    print("No pending deliveries. Skipping email.")
    sys.exit(0)

# ── PRIORITY 1: Manual trigger via GitHub Actions UI ─────────────────────────
if MANUAL_JOB == "godrej_email1":
    print("Manual trigger → Sending Email 1 (Pending Delivery Report)...")
    send_pending_delivery_email(df)

elif MANUAL_JOB == "godrej_email2":
    print("Manual trigger → Sending Email 2 (Update Delivery Status Reminder)...")
    send_update_delivery_status_email(df)

elif MANUAL_JOB == "godrej_email3":
    print("Manual trigger → Sending Email 3 (Evening Pending Delivery Report)...")
    send_pending_delivery_email(df)

# ── PRIORITY 2: SLOT env var (set by workflow step — immune to clock drift) ──
elif SLOT == "morning":
    print("SLOT=morning → Sending Email 1 (Morning Pending Delivery Report)...")
    send_pending_delivery_email(df)

elif SLOT == "reminder":
    print("SLOT=reminder → Sending Email 2 (Update Delivery Status Reminder)...")
    send_update_delivery_status_email(df)

elif SLOT == "evening":
    print("SLOT=evening → Sending Email 1 (Evening Pending Delivery Report)...")
    send_pending_delivery_email(df)

# ── PRIORITY 3: IST hour fallback (±1 hr window handles GitHub delay) ────────
elif current_hour in (9, 10):
    print(f"Hour-fallback ({current_hour}h IST) → Sending Email 1 (Morning)...")
    send_pending_delivery_email(df)

elif current_hour == 11:
    print(f"Hour-fallback (11h IST) → Sending Email 2 (Reminder)...")
    send_update_delivery_status_email(df)

elif current_hour in (16, 17, 18):
    print(f"Hour-fallback ({current_hour}h IST) → Sending Email 1 (Evening)...")
    send_pending_delivery_email(df)

else:
    print(
        f"[Godrej Job] No email mapped for IST hour {current_hour}. "
        f"Set SLOT env var to 'morning', 'reminder', or 'evening' in the workflow."
    )
    sys.exit(1)  # Fail visibly so GitHub marks run red — not silently green