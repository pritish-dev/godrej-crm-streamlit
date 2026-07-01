"""
streamlit_app/mis_commitment_reminder_job.py

Committed Delivery Reminder Job — called by GitHub Actions.

For every PENDING FRANCHISE order (4S orders are excluded) whose GODREJ SO
has been FULLY committed in MIS (every line item's Sales Order Qty ==
Sales Order Committed Qty), sends one email — sectioned by Sales Person —
reminding that the order must be delivered within 15 days of the date it
became fully committed in MIS.

Runs daily at 11 AM IST, right after the scheduled MIS Daily Import
(mis-daily-import.yaml, ~10:55/11:15 IST). Before computing anything this
job checks whether today's MIS_Daily cache is actually fresh:
  • If the scheduled import already ran today  → uses the cached data.
  • If it hasn't (import job skipped/failed/still pending) → this job
    triggers the MIS fetch itself (fetch_and_cache_mis) and then proceeds
    with the freshly fetched data.
  • If a fresh fetch isn't possible either (e.g. no MIS email has been
    sent yet today) → falls back to whatever is already cached so the
    reminder still goes out using the latest known commitment state.

Idempotent by design: the job re-evaluates every PENDING order on every
run, so an order stops being mentioned (and the reminder stops) the
moment its Delivery Status is updated to Delivered in the CRM sheet.
No separate "already reminded" state needs to be tracked. A same-day
send guard (EMAIL_LOG) prevents duplicate emails if the workflow's
drift-backup cron also fires.

Schedule (mis-commitment-reminder-email.yaml):
  11:00 AM IST — daily
"""
import sys
import os
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df, was_email_sent_today
from services.mis_email_import import load_cached_mis, fetch_and_cache_mis, MIS_CACHE_SHEET
from services.delivery_readiness import customer_to_godrej_so, mis_commitment_date_map
from services.email_sender_mis_commitment import send_committed_delivery_reminder_email

# ── IST clock ─────────────────────────────────────────────────────────────────
IST     = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today   = now_ist.date()

JOB_NAME = "Committed Delivery Reminder"

print(f"[MIS Commitment Reminder] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

# ── Idempotency guard ─────────────────────────────────────────────────────────
# The workflow fires a couple of times in the 11 AM window to absorb GitHub
# Actions cron drift. Only the first successful run of the day should
# actually send the email — every run after that would just re-send the
# same reminder.
if was_email_sent_today(JOB_NAME):
    print(f"  → Already sent '{JOB_NAME}' today. Skipping duplicate trigger.")
    sys.exit(0)


# ── Ensure today's MIS is loaded — self-trigger the fetch if the scheduled
#    11 AM import hasn't run / hasn't landed yet. ─────────────────────────────

def _mis_cache_is_fresh(as_of_date) -> bool:
    """True when MIS_Daily's 'Fetched On' timestamp is for `as_of_date`."""
    try:
        raw = get_df(MIS_CACHE_SHEET)
    except Exception:
        return False
    if raw is None or raw.empty or "Fetched On" not in raw.columns:
        return False
    fetched_on = str(raw["Fetched On"].iloc[0]).strip()
    if not fetched_on:
        return False
    parsed = pd.to_datetime(fetched_on, errors="coerce")
    return bool(pd.notna(parsed) and parsed.date() == as_of_date)


def _trigger_mis_fetch() -> pd.DataFrame:
    """Fetch + cache today's MIS. Returns the fetched df (empty if unavailable)."""
    fetched_df, fetch_status = fetch_and_cache_mis()
    print(f"  → {fetch_status}")
    return fetched_df if fetched_df is not None else pd.DataFrame()


if _mis_cache_is_fresh(today):
    print("  → MIS_Daily cache is already fresh for today — using it.")
    mis_df, mis_status = load_cached_mis()
    print(f"  → {mis_status}")
else:
    print("  → MIS_Daily cache is stale/missing for today — triggering MIS fetch now …")
    fetched_df = _trigger_mis_fetch()

    # Today's MIS email can land a few minutes late — retry once after a
    # short wait before falling back to (possibly stale) cached data.
    if fetched_df.empty:
        print("  → MIS email not found yet — waiting 10 minutes before retrying …")
        time.sleep(10 * 60)
        fetched_df = _trigger_mis_fetch()

    if not fetched_df.empty:
        # Bust the get_df cache so the reload below picks up what we just wrote.
        get_df.clear()
        mis_df, mis_status = load_cached_mis()
        print(f"  → {mis_status}")
    else:
        print("  → Still could not fetch today's MIS. Falling back to whatever is "
              "already cached (may be from a previous day) …")
        mis_df, mis_status = load_cached_mis()
        print(f"  → {mis_status}")


# ── Helpers (mirrors email_job.py's loader, with GODREJ SO NO retained) ───────

def _parse_dates(series: pd.Series) -> pd.Series:
    series = series.astype(str).str.strip()
    parsed = []
    for val in series:
        d = pd.NaT
        for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
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
    """Collapse line-items sharing an ORDER NO into one row (keeps GODREJ SO NO)."""
    if df.empty or "ORDER NO" not in df.columns:
        return df
    valid = df["ORDER NO"].notna() & (
        ~df["ORDER NO"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])
    )
    has_no, no_no = df[valid].copy(), df[~valid].copy()
    if has_no.empty:
        return df

    agg = {}
    if "PRODUCT NAME" in has_no.columns:
        agg["PRODUCT NAME"] = lambda x: ",\n".join(
            x.dropna().astype(str).str.strip().unique()
        )
    for col in ("QTY", "ORDER VALUE", "GROSS AMT EX-TAX", "ADV RECEIVED"):
        if col in has_no.columns:
            agg[col] = "sum"
    for col in ("ORDER DATE", "GODREJ SO NO", "CUSTOMER NAME", "CONTACT NUMBER",
                "EMAIL ADDRESS", "CATEGORY", "SALES PERSON", "DELIVERY DATE",
                "DELIVERY STATUS", "REMARKS", "SOURCE"):
        if col in has_no.columns and col not in agg:
            agg[col] = "first"

    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    return pd.concat([grouped, no_no], ignore_index=True)


def fetch_all_pending() -> pd.DataFrame:
    """
    Load all PENDING delivery records from every Franchise sheet listed in
    SHEET_DETAILS. 4S orders are intentionally excluded — this reminder is
    Franchise-only, since MIS commitment tracking applies to Franchise
    orders (see services/delivery_readiness.py). Returns grouped-by-ORDER-NO
    DataFrame with GODREJ SO NO retained so it can be cross-referenced
    against MIS.
    """
    print("  → Fetching Franchise delivery data from Google Sheets …")
    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
        print("  → SHEET_DETAILS not found.")
        return pd.DataFrame()

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
        if "Franchise_sheets" in config_df.columns else []
    )

    dfs = []
    for label, sheet_list in [("Franchise", franchise_sheets)]:
        for name in sheet_list:
            try:
                df = get_df(name)
                if df is None or df.empty:
                    continue
                df.columns = [str(c).strip().upper() for c in df.columns]
                df = df.loc[:, ~df.columns.duplicated()].dropna(axis=1, how="all")
                df["SOURCE"] = label
                dfs.append(df)
                print(f"  → Loaded '{name}' ({label}): {len(df)} rows")
            except Exception as exc:
                print(f"  → Skipping '{name}': {exc}")

    if not dfs:
        print("  → No data found.")
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    crm = crm.rename(columns={
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER VALUE",
        "ORDER AMOUNT (WITH TAX AND AFTER DISC)":          "ORDER VALUE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
        "DATE":                                            "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CUSTOMER DELIVERY DATE":                          "DELIVERY DATE",
        "SALES REP":                                       "SALES PERSON",
        "SALES EXECUTIVE":                                 "SALES PERSON",
        "ADVANCE RECEIVED":                                "ADV RECEIVED",
        "DELIVERY REMARKS(DELIVERED/PENDING)":             "DELIVERY STATUS",
        "DELIVERY REMARKS (DELIVERED/PENDING)":            "DELIVERY STATUS",
        "DELIVERY REMARKS":                                "DELIVERY STATUS",
    })
    crm = crm.loc[:, ~crm.columns.duplicated()]

    if "DELIVERY STATUS" not in crm.columns:
        for col in crm.columns:
            n = str(col).upper().strip().replace(" ", "")
            if n.startswith("DELIVERYREMARKS") or n in ("REMARKS", "DELIVERYSTATUS"):
                crm = crm.rename(columns={col: "DELIVERY STATUS"})
                break
        else:
            crm["DELIVERY STATUS"] = "PENDING"

    for col in ("ORDER VALUE", "ADV RECEIVED", "GROSS AMT EX-TAX"):
        if col in crm.columns:
            crm[col] = pd.to_numeric(
                crm[col].astype(str).str.replace(r"[₹,\s]", "", regex=True),
                errors="coerce",
            ).fillna(0)
    if "ORDER VALUE" not in crm.columns and "GROSS AMT EX-TAX" in crm.columns:
        crm["ORDER VALUE"] = crm["GROSS AMT EX-TAX"]

    for date_col in ("ORDER DATE", "DELIVERY DATE"):
        if date_col in crm.columns:
            crm[date_col] = _parse_dates(crm[date_col])

    if "ORDER VALUE" in crm.columns:
        crm = crm[crm["ORDER VALUE"] > 0].copy()

    crm["DELIVERY STATUS"] = crm["DELIVERY STATUS"].astype(str).str.strip()
    crm.loc[
        crm["DELIVERY STATUS"].isin(["", "nan", "NaN", "None", "none"]),
        "DELIVERY STATUS",
    ] = "PENDING"

    if "FREE STOCK" in crm.columns:
        crm = crm[crm["FREE STOCK"].astype(str).str.strip().str.upper() != "FREE STOCK"].copy()

    pending = crm[
        crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
    ].copy()

    print(f"  → {len(pending)} pending line-item(s) before grouping.")
    pending = _group_by_order_no(pending)
    print(f"  → {len(pending)} pending order(s) after grouping.")
    return pending


# ── Execute ───────────────────────────────────────────────────────────────────

pending = fetch_all_pending()
if pending.empty:
    print("[MIS Commitment Reminder] No pending orders found. Nothing to check.")
    sys.exit(0)

if mis_df.empty:
    print("[MIS Commitment Reminder] MIS_Daily is empty — cannot determine commitment. Exiting.")
    sys.exit(0)

cust_so_map = customer_to_godrej_so(pending)
commit_map  = mis_commitment_date_map(mis_df)
if not commit_map:
    print("[MIS Commitment Reminder] No fully-committed SOs in MIS. Nothing to remind about.")
    sys.exit(0)


def _commit_date_for_row(row):
    sos = []
    row_so = str(row.get("GODREJ SO NO", "")).strip()
    if row_so and row_so.lower() not in ("nan", "none", ""):
        sos.append(row_so)
    cust_key = str(row.get("CUSTOMER NAME", "")).strip().upper()
    if cust_key:
        sos.extend(cust_so_map.get(cust_key, []))
    for so in sos:
        if so in commit_map:
            return commit_map[so]
    return pd.NaT


pending["MIS_COMMIT_DATE"] = pending.apply(_commit_date_for_row, axis=1)
committed = pending[pending["MIS_COMMIT_DATE"].notna()].copy()

if committed.empty:
    print("[MIS Commitment Reminder] No pending orders match a fully-committed SO. Email skipped.")
    sys.exit(0)

print(f"[MIS Commitment Reminder] Sending reminder for {len(committed)} fully-committed order(s).")
send_committed_delivery_reminder_email(committed)
print("[MIS Commitment Reminder] Done.")
