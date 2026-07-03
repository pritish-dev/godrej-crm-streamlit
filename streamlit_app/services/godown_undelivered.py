"""
services/godown_undelivered.py

4S Godown Undelivered Items — enrichment, persistence and reminder helpers.

The item list is maintained (externally) in the OPS sheet
"4s Godown Undelivered Items" whose base headers are:

    Sales Order No. | Item Code | Item Description | Sales Order Qty |
    Total Net Basic | Sales Order Committed Qty | Customer Name | Contact Number

For every item this module:
  1. Matches "Sales Order No." against the CRM Franchise sheets' "GODREJ SO NO"
     column and pulls the associated SALES PERSON.
  2. Reads that order's Delivery Status from the same CRM row. When the CRM
     status reads "Delivered" / "Already Delivered", the item is marked
     "Delivered" here.
  3. Adds the two user-editable columns "Remarks" and "Final Delivery Date".

User edits (Remarks + Final Delivery Date) are persisted in a dedicated OPS
state sheet ("Godown Undelivered State", keyed by Sales Order No. + Item Code)
so they survive any re-import of the raw godown data. The enriched, sorted
table is written back to the "4s Godown Undelivered Items" sheet so the added
columns are visible there too.

Rows are sorted so the nearest approaching "Final Delivery Date" is on top;
items without a final delivery date sink to the bottom.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
import pandas as pd

from services.sheets import get_df, write_df

# ── Sheet names (all live in the OPS spreadsheet) ────────────────────────────
GODOWN_SHEET    = "4s Godown Undelivered Items"
DELIVERED_SHEET = "4S Godown items Delivered"
STATE_SHEET     = "Godown Undelivered State"
RECIPIENTS_SHEET = "Godown Undelivered reminder email"

# ── Column names ─────────────────────────────────────────────────────────────
BASE_COLS = [
    "Sales Order No.", "Item Code", "Item Description", "Sales Order Qty",
    "Total Net Basic", "Sales Order Committed Qty", "Customer Name", "Contact Number",
]
SALES_PERSON_COL    = "Sales Person"
DELIVERY_STATUS_COL = "Delivery Status"
REMARKS_COL         = "Remarks"
FINAL_DATE_COL      = "Final Delivery Date"
DELIVERED_DATE_COL  = "Delivered Date"

DISPLAY_COLS = BASE_COLS + [
    SALES_PERSON_COL, DELIVERY_STATUS_COL, REMARKS_COL, FINAL_DATE_COL,
]

# Columns of the separate "4S Godown items Delivered" sheet (no live Delivery
# Status — every row is delivered — but with the date delivery was detected).
DELIVERED_COLS = BASE_COLS + [
    SALES_PERSON_COL, REMARKS_COL, FINAL_DATE_COL, DELIVERED_DATE_COL,
]

STATE_HEADERS = [
    "Sales Order No.", "Item Code", REMARKS_COL, FINAL_DATE_COL,
    "Updated By", "Updated On",
]

REMINDER_WINDOW_DAYS = 7

IST = timezone(timedelta(hours=5, minutes=30))


# ═════════════════════════════════════════════════════════════════════════════
# Small helpers
# ═════════════════════════════════════════════════════════════════════════════

def _norm(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _row_key(so: str, item_code: str) -> str:
    return f"{_norm(so).upper()}||{_norm(item_code).upper()}"


def is_delivered(status) -> bool:
    """
    True when a CRM Delivery Status reads Delivered / Already Delivered.
    Matches the word 'deliver' at the start so 'Delivered' and
    'Already Delivered' both count, while 'PENDING' / '' do not.
    """
    s = _norm(status).lower()
    return "deliver" in s and "pending" not in s and "not deliver" not in s


def parse_date(v):
    """Parse a date-ish value into a datetime.date (or None)."""
    s = _norm(v)
    if not s:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    d = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return None if pd.isna(d) else d.date()


def fmt_date(d) -> str:
    """Render a date/parseable value as DD-MM-YYYY (blank if unparseable)."""
    if isinstance(d, (datetime, date)):
        return d.strftime("%d-%m-%Y")
    dd = parse_date(d)
    return dd.strftime("%d-%m-%Y") if dd else ""


# ═════════════════════════════════════════════════════════════════════════════
# CRM Franchise lookup:  GODREJ SO NO → { sales_person, delivered }
# ═════════════════════════════════════════════════════════════════════════════

_DELIVERY_STATUS_CANDIDATES = (
    "DELIVERY REMARKS(DELIVERED/PENDING)",
    "DELIVERY REMARKS (DELIVERED/PENDING)",
    "DELIVERY STATUS",
    "DELIVERY REMARKS",
)


def _franchise_sheet_names() -> list[str]:
    cfg = get_df("SHEET_DETAILS")
    if cfg is None or cfg.empty or "Franchise_sheets" not in cfg.columns:
        return []
    return (
        cfg["Franchise_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
    )


def build_crm_so_lookup() -> dict[str, dict]:
    """
    Return { GODREJ_SO_NO(upper, stripped): {"sales_person": str, "delivered": bool} }
    aggregated across every Franchise sheet. When a SO appears on multiple
    line items, sales_person is the first non-empty value and the order is
    considered delivered if ANY of its line items reads Delivered.
    """
    lookup: dict[str, dict] = {}

    for name in _franchise_sheet_names():
        try:
            df = get_df(name)
        except Exception:
            continue
        if df is None or df.empty:
            continue

        df = df.copy()
        df.columns = [str(c).strip().upper() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]

        so_col = next((c for c in df.columns if c == "GODREJ SO NO"), None)
        if so_col is None:
            continue
        sp_col = next(
            (c for c in df.columns if c in ("SALES PERSON", "SALES REP", "SALES EXECUTIVE")),
            None,
        )
        status_col = next(
            (c for c in df.columns if c in _DELIVERY_STATUS_CANDIDATES), None
        )
        if status_col is None:
            status_col = next(
                (c for c in df.columns
                 if str(c).replace(" ", "").startswith("DELIVERYREMARKS")),
                None,
            )

        for _, r in df.iterrows():
            so = _norm(r.get(so_col)).upper()
            if not so:
                continue
            sp = _norm(r.get(sp_col)) if sp_col else ""
            delivered = is_delivered(r.get(status_col)) if status_col else False

            entry = lookup.setdefault(so, {"sales_person": "", "delivered": False})
            if sp and not entry["sales_person"]:
                entry["sales_person"] = sp
            if delivered:
                entry["delivered"] = True

    return lookup


# ═════════════════════════════════════════════════════════════════════════════
# State sheet (durable Remarks / Final Delivery Date)
# ═════════════════════════════════════════════════════════════════════════════

def load_state() -> dict[str, dict]:
    """Return { row_key: {"Remarks": str, "Final Delivery Date": str} }."""
    try:
        df = get_df(STATE_SHEET)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    out: dict[str, dict] = {}
    for _, r in df.iterrows():
        key = _row_key(r.get("Sales Order No.", ""), r.get("Item Code", ""))
        if key == "||":
            continue
        out[key] = {
            REMARKS_COL: _norm(r.get(REMARKS_COL, "")),
            FINAL_DATE_COL: fmt_date(r.get(FINAL_DATE_COL, "")),
        }
    return out


def save_edits(edits: list[dict], updated_by: str = "") -> int:
    """
    Upsert Remarks / Final Delivery Date edits into the state sheet.

    Each dict in `edits` must carry: "Sales Order No.", "Item Code",
    "Remarks", "Final Delivery Date". Returns the number of rows written.
    """
    if not edits:
        return 0

    try:
        df = get_df(STATE_SHEET)
    except Exception:
        df = None
    if df is None or df.empty:
        df = pd.DataFrame(columns=STATE_HEADERS)
    else:
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        for col in STATE_HEADERS:
            if col not in df.columns:
                df[col] = ""
        df = df[STATE_HEADERS]

    df["_key"] = df.apply(
        lambda r: _row_key(r.get("Sales Order No.", ""), r.get("Item Code", "")), axis=1
    )
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

    written = 0
    for e in edits:
        so   = _norm(e.get("Sales Order No.", ""))
        code = _norm(e.get("Item Code", ""))
        if not so and not code:
            continue
        key = _row_key(so, code)
        new_row = {
            "Sales Order No.": so,
            "Item Code": code,
            REMARKS_COL: _norm(e.get(REMARKS_COL, "")),
            FINAL_DATE_COL: fmt_date(e.get(FINAL_DATE_COL, "")),
            "Updated By": _norm(updated_by),
            "Updated On": stamp,
        }
        mask = df["_key"] == key
        if mask.any():
            for col in STATE_HEADERS:
                df.loc[mask, col] = new_row[col]
        else:
            new_row["_key"] = key
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        written += 1

    df = df.drop(columns=["_key"], errors="ignore")[STATE_HEADERS]
    write_df(STATE_SHEET, df)
    return written


# ═════════════════════════════════════════════════════════════════════════════
# Enrichment + sorting
# ═════════════════════════════════════════════════════════════════════════════

def load_godown_raw() -> pd.DataFrame:
    """Load the raw '4s Godown Undelivered Items' sheet (may already carry the
    enriched columns from a previous run)."""
    try:
        df = get_df(GODOWN_SHEET)
    except Exception:
        df = None
    if df is None or df.empty:
        return pd.DataFrame(columns=BASE_COLS)
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _match_base_col(df: pd.DataFrame, target: str) -> str | None:
    """Find a column in df matching `target` (case/space-insensitive)."""
    norm = target.replace(" ", "").replace(".", "").upper()
    for c in df.columns:
        if str(c).replace(" ", "").replace(".", "").upper() == norm:
            return c
    return None


def enrich(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich the raw godown sheet with Sales Person, Delivery Status, Remarks and
    Final Delivery Date, then sort by nearest Final Delivery Date. Returns a
    DataFrame with exactly DISPLAY_COLS.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=DISPLAY_COLS)

    lookup = build_crm_so_lookup()
    state  = load_state()

    # Map each expected base column to whatever the sheet actually calls it.
    col_map = {c: _match_base_col(raw, c) for c in BASE_COLS}

    rows = []
    for _, r in raw.iterrows():
        out = {}
        for c in BASE_COLS:
            src = col_map.get(c)
            out[c] = _norm(r.get(src, "")) if src else ""

        so   = out["Sales Order No."].upper()
        code = out["Item Code"]
        info = lookup.get(so, {})

        out[SALES_PERSON_COL]    = info.get("sales_person", "")
        out[DELIVERY_STATUS_COL] = "Delivered" if info.get("delivered") else "Pending"

        key = _row_key(so, code)
        st_edit = state.get(key)
        if st_edit is not None:
            out[REMARKS_COL]    = st_edit.get(REMARKS_COL, "")
            out[FINAL_DATE_COL] = st_edit.get(FINAL_DATE_COL, "")
        else:
            # Fall back to whatever the sheet already holds (first migration).
            out[REMARKS_COL]    = _norm(r.get(REMARKS_COL, ""))
            out[FINAL_DATE_COL] = fmt_date(r.get(FINAL_DATE_COL, ""))

        rows.append(out)

    df = pd.DataFrame(rows, columns=DISPLAY_COLS)
    return sort_by_final_date(df)


def sort_by_final_date(df: pd.DataFrame) -> pd.DataFrame:
    """Sort ascending by Final Delivery Date (nearest on top); blanks last."""
    if df is None or df.empty:
        return df
    df = df.copy()
    parsed = df[FINAL_DATE_COL].apply(parse_date)
    # NaT sorts last regardless of ascending order.
    df["_sortkey"] = [pd.Timestamp(d) if d else pd.Timestamp.max for d in parsed]
    df = df.sort_values("_sortkey", kind="stable").drop(columns=["_sortkey"])
    return df.reset_index(drop=True)


# ═════════════════════════════════════════════════════════════════════════════
# Stats + reminder filtering
# ═════════════════════════════════════════════════════════════════════════════

def compute_stats(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"total": 0, "to_deliver": 0, "delivered": 0}
    delivered = int(df[DELIVERY_STATUS_COL].apply(is_delivered).sum())
    total = len(df)
    return {"total": total, "to_deliver": total - delivered, "delivered": delivered}


def due_within_window(df: pd.DataFrame, days: int = REMINDER_WINDOW_DAYS,
                      as_of: date | None = None) -> pd.DataFrame:
    """
    Return the undelivered rows whose Final Delivery Date falls within `days`
    from today, INCLUDING any that are already past due (overdue items keep
    getting added to the reminder until delivered). Rows without a Final
    Delivery Date are excluded (nothing has been scheduled yet).
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=DISPLAY_COLS)
    today   = as_of or datetime.now(IST).date()
    horizon = today + timedelta(days=days)

    keep = []
    for _, r in df.iterrows():
        if is_delivered(r.get(DELIVERY_STATUS_COL)):
            continue
        d = parse_date(r.get(FINAL_DATE_COL))
        if d is None:
            continue
        if d <= horizon:            # includes overdue (d < today)
            keep.append(r)
    out = pd.DataFrame(keep, columns=df.columns) if keep else pd.DataFrame(columns=df.columns)
    return sort_by_final_date(out)


# ═════════════════════════════════════════════════════════════════════════════
# Delivered sheet ("4S Godown items Delivered")
# ═════════════════════════════════════════════════════════════════════════════

def load_delivered() -> pd.DataFrame:
    """Load the accumulated '4S Godown items Delivered' sheet."""
    try:
        df = get_df(DELIVERED_SHEET)
    except Exception:
        df = None
    if df is None or df.empty:
        return pd.DataFrame(columns=DELIVERED_COLS)
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in DELIVERED_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[DELIVERED_COLS]


def _sort_delivered(df: pd.DataFrame) -> pd.DataFrame:
    """Newest Delivered Date on top; blanks last."""
    if df is None or df.empty:
        return df
    df = df.copy()
    parsed = df[DELIVERED_DATE_COL].apply(parse_date)
    df["_sortkey"] = [pd.Timestamp(d) if d else pd.Timestamp.min for d in parsed]
    df = df.sort_values("_sortkey", ascending=False, kind="stable").drop(columns=["_sortkey"])
    return df.reset_index(drop=True)


def _merge_delivered(newly_delivered: pd.DataFrame) -> pd.DataFrame:
    """
    Append newly-delivered items (from the enriched godown table) to the
    accumulated delivered sheet, keyed by Sales Order No. + Item Code. Items
    already recorded keep their original Delivered Date; brand-new ones are
    stamped with today's date (IST) — the date delivery was first detected.
    """
    existing = load_delivered()
    existing_keys = {
        _row_key(r.get("Sales Order No.", ""), r.get("Item Code", ""))
        for _, r in existing.iterrows()
    } if not existing.empty else set()

    today_str = datetime.now(IST).strftime("%d-%m-%Y")
    to_add = []
    for _, r in newly_delivered.iterrows():
        key = _row_key(r.get("Sales Order No.", ""), r.get("Item Code", ""))
        if key in existing_keys:
            continue
        row = {c: _norm(r.get(c, "")) for c in DELIVERED_COLS if c != DELIVERED_DATE_COL}
        row[DELIVERED_DATE_COL] = today_str
        to_add.append(row)
        existing_keys.add(key)

    if to_add:
        add_df = pd.DataFrame(to_add, columns=DELIVERED_COLS)
        merged = add_df if existing.empty else pd.concat([existing, add_df], ignore_index=True)
    else:
        merged = existing
    return _sort_delivered(merged)


# ═════════════════════════════════════════════════════════════════════════════
# Public entry point — refresh both sheets in place
# ═════════════════════════════════════════════════════════════════════════════

def refresh() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Read the godown sheet, enrich it (Sales Person + Delivery Status from CRM,
    Remarks + Final Delivery Date from state), then split it:

      • Delivered items are moved into the '4S Godown items Delivered' sheet
        (accumulated, stamped with a Delivered Date) and removed from the
        pending sheet.
      • The remaining Pending items are written back to
        '4s Godown Undelivered Items', sorted by nearest Final Delivery Date.

    Returns (pending_df, delivered_df, stats) where stats counts across both
    sheets: {"total", "to_deliver", "delivered"}.
    """
    raw = load_godown_raw()
    enriched = enrich(raw)

    if enriched.empty:
        pending  = pd.DataFrame(columns=DISPLAY_COLS)
        delivered = load_delivered()
    else:
        delivered_mask   = enriched[DELIVERY_STATUS_COL].apply(is_delivered)
        newly_delivered  = enriched[delivered_mask].copy()
        pending          = sort_by_final_date(enriched[~delivered_mask].copy())
        delivered        = _merge_delivered(newly_delivered)

        try:
            write_df(DELIVERED_SHEET, delivered)
        except Exception as exc:
            print(f"[Godown Undelivered] Warning — could not write delivered sheet: {exc}")
        try:
            write_df(GODOWN_SHEET, pending)
        except Exception as exc:
            print(f"[Godown Undelivered] Warning — could not write pending sheet: {exc}")

    stats = {
        "total":      len(pending) + len(delivered),
        "to_deliver": len(pending),
        "delivered":  len(delivered),
    }
    return pending, delivered, stats
