"""
services/godrej_booking_import.py

Monthly Godrej Booking report.

Reads the "Order Booked" confirmation emails from Gmail via IMAP.  Each such
email carries a Godrej Sales Order number (``WON…``) in its subject, e.g.:

    "Order Booked-Order Number <WON043581>"

For every SO number found in the selected date range we build one report row:

    Date | SO No | Sales Person | Net Basic Value | Source

* Date          — the booking date (the email's own date, in IST).
* SO No         — the Godrej SO number (WON…) parsed from the subject/body.
* Sales Person  — looked up from the Franchise/4S order sheets via the SO number
                  (reuses ``invoice_email_import.lookup_sales_executive``).
* Net Basic Value / Source — resolved from MIS only (never from invoices):
      1. Today's MIS — the ``MIS_Daily`` cache (overwritten daily). For every SO
         present there, sum its "Total Net Basic" across all its line items.
         Source = "MIS".
      2. For an SO NOT in today's MIS, read the daily BR_MIS email attachments
         (they arrive every day except Sunday) over the fetch date range,
         newest-first, and take the SO's summed Total Net Basic from the most
         recent MIS snapshot that contains it.  Source = "MIS Email".
      3. Otherwise leave the value blank so it can be typed in from the CRM
         dashboard.  A hand-typed value is stored with Source = "Manual" and is
         never overwritten by a later fetch.

The rows are written to a per-month Google Sheet in the OPS spreadsheet named
``Monthly Godrej Booking <Month>`` (created automatically on first fetch).
"""

from __future__ import annotations

import calendar
import email
import imaplib
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Reuse the battle-tested SO normalisation + salesperson lookup from the invoice
# importer so booking SO numbers match the CRM sheets exactly the same way.
from services.invoice_email_import import (  # noqa: E402
    _normalize_so,
    _so_tokens,
    lookup_sales_executive,
    _load_imap_accounts,
    configured_invoice_inboxes,
)

IMAP_HOST            = "imap.gmail.com"
# Gmail IMAP SUBJECT search is a substring match, so "Order Booked" matches
# "Order Booked-Order Number <WON043581>".
BOOKING_SUBJECT      = "Order Booked"
BOOKING_SHEET_PREFIX = "Monthly Godrej Booking "
IST                  = timezone(timedelta(hours=5, minutes=30))

# Canonical column order written to the "Monthly Godrej Booking <Month>" sheet.
SHEET_COLS = [
    "Date",
    "SO No",
    "Sales Person",
    "Net Basic Value",
    "Source",
]

# A Godrej SO token — a WON/WON-like prefix + digits.  Kept broad enough to
# survive angle-brackets, colons and surrounding words in the subject line.
_SO_IN_SUBJECT_RE = re.compile(r"\b([A-Z]{2,4}\d{4,})\b", re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _decode_str(value) -> str:
    if value is None:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _email_date_ist(msg) -> "date | None":
    """Return the email's Date header as an IST calendar date (booking date)."""
    raw = msg.get("Date", "")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            # Assume already IST if the header carried no timezone.
            return dt.date()
        return dt.astimezone(IST).date()
    except Exception:
        return None


def _get_body_text(msg) -> str:
    """Best-effort plain-text body extraction (for the SO-number fallback)."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disp  = str(part.get("Content-Disposition", ""))
                if ctype == "text/plain" and "attachment" not in disp:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
            # Fall back to the first text/html part, stripped of tags.
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        html = payload.decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                        return re.sub(r"<[^>]+>", " ", html)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(
                    msg.get_content_charset() or "utf-8", errors="replace"
                )
    except Exception:
        pass
    return ""


def _extract_so_number(subject: str, body: str = "") -> str:
    """
    Pull the Godrej SO number out of an "Order Booked" email.

    Priority:
      1. The number right after "Order Number" in the subject
         (``Order Booked-Order Number <WON043581>``).
      2. Any WON… token anywhere in the subject.
      3. Any WON… token in the body (last resort).
    Returns "" when nothing matches.
    """
    subject = subject or ""

    # 1) Explicit "Order Number <...>" label
    m = re.search(
        r"Order\s*Number\s*[:\-–—]?\s*[<\[\(]?\s*([A-Z]{2,4}\d{4,})",
        subject,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).upper()

    # 2) Any SO-looking token in the subject — prefer a WON prefix if present.
    subj_tokens = [t.upper() for t in _SO_IN_SUBJECT_RE.findall(subject)]
    won = next((t for t in subj_tokens if t.startswith("WON")), "")
    if won:
        return won
    if subj_tokens:
        return subj_tokens[0]

    # 3) Body fallback
    if body:
        body_tokens = [t.upper() for t in _SO_IN_SUBJECT_RE.findall(body)]
        won = next((t for t in body_tokens if t.startswith("WON")), "")
        if won:
            return won
        if body_tokens:
            return body_tokens[0]

    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL FETCHER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_search_query(month_start: date, month_end: date) -> str:
    since_str  = month_start.strftime("%d-%b-%Y")
    before_str = (month_end + timedelta(days=1)).strftime("%d-%b-%Y")
    return f'(SUBJECT "{BOOKING_SUBJECT}" SINCE {since_str} BEFORE {before_str})'


def _fetch_from_account(
    imap_email: str,
    imap_password: str,
    query: str,
) -> tuple[list[dict], int, str]:
    """
    Read Order-Booked emails from a single Gmail account.

    Returns (rows, email_count, login_error).  Each row is
    ``{"Date": date|None, "SO No": str}``.  ``login_error`` is "" on success.
    """
    rows: list[dict] = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(imap_email, imap_password)
        mail.select("inbox")
    except Exception as e:
        return rows, 0, f"{imap_email}: IMAP login failed: {e}"

    try:
        _, data = mail.search(None, query)
    except Exception as e:
        try:
            mail.logout()
        except Exception:
            pass
        return rows, 0, f"{imap_email}: IMAP search error: {e}"

    email_ids = data[0].split() if data and data[0] else []
    if not email_ids:
        try:
            mail.logout()
        except Exception:
            pass
        return rows, 0, ""

    for eid in email_ids:
        try:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = _decode_str(msg.get("Subject", ""))
            so_no   = _extract_so_number(subject)
            if not so_no:
                # Only crack the body open when the subject didn't yield an SO.
                so_no = _extract_so_number(subject, _get_body_text(msg))
            if not so_no:
                continue

            rows.append({"Date": _email_date_ist(msg), "SO No": so_no})
        except Exception:
            continue

    try:
        mail.logout()
    except Exception:
        pass

    return rows, len(email_ids), ""


def fetch_booking_emails(
    month_start: date, month_end: date
) -> tuple[pd.DataFrame, str]:
    """
    Fetch "Order Booked" emails received between ``month_start`` and
    ``month_end`` (inclusive) from every configured Gmail inbox.

    Returns (DataFrame[Date, SO No], status_message).  The frame is
    de-duplicated on SO number (earliest booking date kept).
    """
    accounts = _load_imap_accounts()
    if not accounts:
        return pd.DataFrame(columns=["Date", "SO No"]), (
            "❌ Email credentials not configured. "
            "Check EMAIL_SENDER / EMAIL_PASSWORD (and EMAIL_SENDER_2 / EMAIL_PASSWORD_2)."
        )

    if month_start > month_end:
        month_start, month_end = month_end, month_start

    query = _build_search_query(month_start, month_end)

    all_rows: list[dict] = []
    total_emails = 0
    login_errors: list[str] = []

    for acct_email, acct_password in accounts:
        rows, n_emails, login_err = _fetch_from_account(acct_email, acct_password, query)
        if login_err:
            login_errors.append(login_err)
            continue
        all_rows.extend(rows)
        total_emails += n_emails

    if login_errors and not all_rows and total_emails == 0 and len(login_errors) == len(accounts):
        return pd.DataFrame(columns=["Date", "SO No"]), "❌ " + "; ".join(login_errors)

    if not all_rows:
        suffix = f"\n⚠️ {'; '.join(login_errors)}" if login_errors else ""
        return pd.DataFrame(columns=["Date", "SO No"]), (
            f"⚠️ No 'Order Booked' emails with a Godrej SO number found for the "
            f"selected period across {len(accounts)} account(s).\n"
            f"Subject searched: **{BOOKING_SUBJECT}**{suffix}"
        )

    df = pd.DataFrame(all_rows)
    # Normalise SO for de-dup, then keep the earliest booking date per SO.
    df["_norm"] = df["SO No"].map(_normalize_so)
    df = df[df["_norm"].astype(bool)].copy()

    # Sort so the earliest-dated row per SO is kept.
    df["_sort_date"] = df["Date"].map(lambda d: d if isinstance(d, date) else date.max)
    df = df.sort_values("_sort_date").drop_duplicates(subset=["_norm"], keep="first")
    df = df.drop(columns=["_norm", "_sort_date"]).reset_index(drop=True)

    status_msg = (
        f"✅ {len(df)} Godrej SO number(s) found in {total_emails} 'Order Booked' "
        f"email(s) across {len(accounts)} account(s)"
    )
    if login_errors:
        status_msg += f"  ⚠️ {len(login_errors)} account(s) failed to log in: {'; '.join(login_errors)}"

    return df, status_msg


# ═══════════════════════════════════════════════════════════════════════════════
# VALUE LOOKUPS  (MIS ONLY)
#
# The Net Basic Value for each Godrej SO number comes exclusively from the MIS
# data — never from the invoice table.
#
#   1. Today's MIS  (the MIS_Daily cache, overwritten every day) — for every SO
#      present there, sum its "Total Net Basic" across all of its line items.
#   2. For any SO NOT in today's MIS, read the daily BR_MIS email attachments
#      (they arrive every day except Sunday) over the fetch date range, newest
#      first, and take the SO's summed Total Net Basic from the most recent MIS
#      snapshot that contains it.
#   3. If still not found, the value is left blank for manual entry.
# ═══════════════════════════════════════════════════════════════════════════════

def _to_float(v) -> "float | None":
    try:
        s = str(v).replace("₹", "").replace(",", "").strip()
        if not s or s.lower() in ("nan", "none"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _find_mis_cols(df: pd.DataFrame) -> "tuple[str | None, str | None]":
    """Return (so_column, net_basic_column) for a MIS DataFrame, or (None, None)."""
    cols = [str(c).strip() for c in df.columns]
    df.columns = cols
    so_col = next(
        (c for c in cols if c.lower() in ("sales order no.", "sales order no")),
        None,
    )
    net_col = next(
        (c for c in cols if c.lower() in ("total net basic", "net basic value", "net basic")),
        next((c for c in cols if "net" in c.lower() and "basic" in c.lower()), None),
    )
    return so_col, net_col


def _aggregate_mis_df(df: pd.DataFrame) -> dict[str, float]:
    """
    normalized SO -> summed "Total Net Basic" across every line item of that SO
    in a single MIS snapshot (one day's data).
    """
    result: dict[str, float] = {}
    if df is None or df.empty:
        return result
    so_col, net_col = _find_mis_cols(df)
    if not so_col or not net_col:
        return result
    for _, r in df.iterrows():
        val = _to_float(r[net_col])
        if val is None:
            continue
        for norm in _so_tokens(r[so_col]):
            result[norm] = result.get(norm, 0.0) + val
    return result


def _today_mis_value_map() -> dict[str, float]:
    """normalized SO -> summed Total Net Basic from the MIS_Daily cache."""
    from services.mis_email_import import load_cached_mis
    try:
        df, _ = load_cached_mis()
    except Exception:
        df = None
    return _aggregate_mis_df(df)


def _mis_email_value_map(
    start_date: "date | None",
    end_date: "date | None",
    needed_norms: set[str],
) -> dict[str, float]:
    """
    For SO numbers not present in today's MIS, look them up in the daily BR_MIS
    email attachments received between ``start_date`` and ``end_date``.

    Emails are read newest-first; each SO takes its summed Total Net Basic from
    the MOST RECENT MIS snapshot that contains it (so the same SO repeated in
    several days' emails is never double-counted).

    Returns ``{normalized_SO: value}`` for the SOs that were found.
    """
    result: dict[str, float] = {}
    if not needed_norms:
        return result
    if start_date is None or end_date is None:
        return result
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    from services.mis_email_import import fetch_mis_emails_in_range

    try:
        emails = fetch_mis_emails_in_range(start_date, end_date)  # newest first
    except Exception:
        emails = []

    pending = set(needed_norms)
    for _email_date, df in emails:
        if not pending:
            break
        per_so = _aggregate_mis_df(df)
        for norm in list(pending):
            if norm in per_so:
                result[norm] = per_so[norm]
                pending.discard(norm)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_date(d) -> str:
    if isinstance(d, date):
        return d.strftime("%d-%m-%Y")
    return str(d or "").strip()


def build_report(
    bookings: pd.DataFrame,
    mis_email_start: "date | None" = None,
    mis_email_end: "date | None" = None,
) -> pd.DataFrame:
    """
    Enrich fetched bookings (Date, SO No) into full report rows:
    Date | SO No | Sales Person | Net Basic Value | Source.

    Net Basic Value is resolved from MIS only — today's MIS_Daily first, then
    (for SOs missing from it) the daily BR_MIS email attachments between
    ``mis_email_start`` and ``mis_email_end``.  Values that can't be found are
    left blank.  Source is "MIS" (today's cache), "MIS Email" (historical email)
    or "" (unresolved).
    """
    if bookings is None or bookings.empty:
        return pd.DataFrame(columns=SHEET_COLS)

    bookings = bookings.copy()

    # If no explicit MIS-email window was given, derive one from the bookings'
    # own dates (extended to today) so the fallback still has a range to search.
    if mis_email_start is None or mis_email_end is None:
        booked_dates = [d for d in bookings["Date"] if isinstance(d, date)]
        today = datetime.now(IST).date()
        mis_email_start = min(booked_dates) if booked_dates else today.replace(day=1)
        mis_email_end = today

    today_map = _today_mis_value_map()
    exec_map  = lookup_sales_executive(bookings["SO No"].astype(str).tolist())

    # Work out which SOs today's MIS could not value, then look those up in the
    # historical MIS emails in one pass.
    norm_by_so: dict[str, str] = {}
    for so in bookings["SO No"].astype(str):
        norm_by_so[so.strip()] = _normalize_so(so)
    missing_norms = {
        n for n in norm_by_so.values() if n and n not in today_map
    }
    email_map = _mis_email_value_map(mis_email_start, mis_email_end, missing_norms)

    out_rows: list[dict] = []
    for _, r in bookings.iterrows():
        so_raw = str(r["SO No"]).strip()
        norm   = norm_by_so.get(so_raw, _normalize_so(so_raw))

        value: "float | None" = None
        source = ""
        if norm and norm in today_map:
            value, source = today_map[norm], "MIS"
        elif norm and norm in email_map:
            value, source = email_map[norm], "MIS Email"

        out_rows.append({
            "Date":            _fmt_date(r["Date"]),
            "SO No":           so_raw,
            "Sales Person":    exec_map.get(so_raw, ""),
            "Net Basic Value": "" if value is None else round(value, 2),
            "Source":          source,
        })

    df = pd.DataFrame(out_rows, columns=SHEET_COLS)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def booking_sheet_name(month: str) -> str:
    return f"{BOOKING_SHEET_PREFIX}{month}"


def _parse_row_date(v) -> "date | None":
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        d = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.notna(d):
            return d.date()
    except Exception:
        pass
    return None


def _empty(v) -> bool:
    return str(v).strip().lower() in ("", "nan", "none")


def save_bookings_to_sheet(df_new: pd.DataFrame, month: str) -> tuple[str, int, int]:
    """
    Merge report rows into ``Monthly Godrej Booking <Month>`` (OPS spreadsheet,
    created if absent).  Matching is on the normalised SO number.

    Preservation rules (so a fetch never clobbers a human's entry):
      * A row already saved with Source == "Manual" keeps its Net Basic Value
        and Source untouched.
      * An auto (Invoice/MIS) value refreshes an existing auto/blank value.
      * A non-blank Sales Person is filled in when it was previously blank; an
        existing non-blank name is kept.

    Returns (status_message, added_count, updated_count).
    """
    from services.sheets import get_df, write_df

    sheet = booking_sheet_name(month)

    new = df_new.copy()
    for c in SHEET_COLS:
        if c not in new.columns:
            new[c] = ""
    new = new[SHEET_COLS]

    try:
        existing = get_df(sheet)
    except Exception:
        existing = None

    if existing is None or existing.empty:
        merged = new.drop_duplicates(subset=["SO No"], keep="first").reset_index(drop=True)
        merged = _sort_by_date(merged)
        try:
            write_df(sheet, merged)
        except Exception as e:
            return f"❌ Save to sheet **{sheet}** failed: {e}", 0, 0
        return f"✅ Created **{sheet}** with {len(merged)} order(s).", len(merged), 0

    existing.columns = [str(c).strip() for c in existing.columns]
    for c in SHEET_COLS:
        if c not in existing.columns:
            existing[c] = ""
    existing = existing[SHEET_COLS].copy()
    # Force plain-object columns.  On newer pandas (with the Arrow-backed
    # string dtype) ``get_df`` returns ``str``-dtype columns that reject a
    # non-string ``.at[...]`` assignment with a TypeError; the booking sheet
    # is entirely text, so object dtype is both correct and assignment-safe.
    existing = existing.astype(object)

    # Index existing rows by normalised SO for quick lookup.
    idx_by_norm: dict[str, int] = {}
    for i, r in existing.iterrows():
        n = _normalize_so(r["SO No"])
        if n and n not in idx_by_norm:
            idx_by_norm[n] = i

    added = 0
    updated = 0
    append_rows: list[dict] = []
    for _, r in new.iterrows():
        norm = _normalize_so(r["SO No"])
        if not norm:
            continue
        if norm in idx_by_norm:
            i = idx_by_norm[norm]
            row_changed = False
            src_existing = str(existing.at[i, "Source"]).strip().lower()

            # Value / source — never touch a manual entry.
            if src_existing != "manual":
                if not _empty(r["Net Basic Value"]):
                    if str(existing.at[i, "Net Basic Value"]).strip() != str(r["Net Basic Value"]).strip():
                        existing.at[i, "Net Basic Value"] = str(r["Net Basic Value"])
                        row_changed = True
                    if str(existing.at[i, "Source"]).strip() != str(r["Source"]).strip():
                        existing.at[i, "Source"] = str(r["Source"])
                        row_changed = True

            # Sales person — fill only when currently blank.
            if _empty(existing.at[i, "Sales Person"]) and not _empty(r["Sales Person"]):
                existing.at[i, "Sales Person"] = str(r["Sales Person"])
                row_changed = True

            # Date — fill only when currently blank.
            if _empty(existing.at[i, "Date"]) and not _empty(r["Date"]):
                existing.at[i, "Date"] = str(r["Date"])
                row_changed = True

            if row_changed:
                updated += 1
        else:
            append_rows.append(r.to_dict())
            idx_by_norm[norm] = -1  # guard against dup SOs within this batch
            added += 1

    if append_rows:
        merged = pd.concat([existing, pd.DataFrame(append_rows)], ignore_index=True)
    else:
        merged = existing

    merged = _sort_by_date(merged)

    try:
        write_df(sheet, merged)
    except Exception as e:
        return f"❌ Save to sheet **{sheet}** failed: {e}", added, updated

    msg = f"✅ **{sheet}** — {added} new, {updated} updated (of {len(merged)} total)."
    return msg, added, updated


def _sort_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """Sort a booking frame by parsed Date ascending, blanks last."""
    if df is None or df.empty or "Date" not in df.columns:
        return df
    order = df["Date"].map(lambda v: _parse_row_date(v) or date.max)
    return df.assign(_o=order.values).sort_values("_o").drop(columns=["_o"]).reset_index(drop=True)


def load_booking_sheet(month: str) -> pd.DataFrame:
    """Load ``Monthly Godrej Booking <Month>``; empty DataFrame on any error."""
    from services.sheets import get_df
    try:
        df = get_df(booking_sheet_name(month))
    except Exception:
        return pd.DataFrame(columns=SHEET_COLS)
    if df is None or df.empty:
        return pd.DataFrame(columns=SHEET_COLS)
    df.columns = [str(c).strip() for c in df.columns]
    for c in SHEET_COLS:
        if c not in df.columns:
            df[c] = ""
    df = df[SHEET_COLS]
    df = df[df["SO No"].fillna("").astype(str).str.strip().ne("")].reset_index(drop=True)
    return df


def save_manual_net_basic(month: str, so_to_value: dict[str, str]) -> str:
    """
    Persist hand-typed Net Basic Value(s) from the CRM dashboard into the
    ``Monthly Godrej Booking <Month>`` sheet, matched on SO number.  Written
    values are stamped Source = "Manual" so a later fetch never overwrites them.

    Only non-blank incoming values are written, so clearing a cell never wipes
    an existing value.  Returns a human-readable status message.
    """
    from services.sheets import get_df, write_df

    updates: dict[str, str] = {}
    for so, val in (so_to_value or {}).items():
        so_norm = _normalize_so(so)
        if so_norm and not _empty(val):
            updates[so_norm] = str(val).strip()
    if not updates:
        return "no net basic values to save (nothing typed)."

    sheet = booking_sheet_name(month)
    try:
        df = get_df(sheet)
    except Exception as e:
        return f"❌ Could not read **{sheet}**: {e}"
    if df is None or df.empty:
        return f"⚠️ **{sheet}** has no rows to update."

    df.columns = [str(c).strip() for c in df.columns]
    for c in SHEET_COLS:
        if c not in df.columns:
            df[c] = ""
    df = df[SHEET_COLS].copy()

    changed = 0
    not_found: list[str] = []
    seen: set[str] = set()
    for i, r in df.iterrows():
        norm = _normalize_so(r["SO No"])
        if norm in updates:
            new_val = updates[norm]
            if str(df.at[i, "Net Basic Value"]).strip() != new_val or \
               str(df.at[i, "Source"]).strip().lower() != "manual":
                df.at[i, "Net Basic Value"] = new_val
                df.at[i, "Source"] = "Manual"
                changed += 1
            seen.add(norm)

    for norm in updates:
        if norm not in seen:
            not_found.append(norm)

    if changed == 0:
        msg = "no changes — the typed value(s) already match the sheet."
        if not_found:
            msg += f" ⚠️ {len(not_found)} SO(s) not found."
        return msg

    try:
        write_df(sheet, df)
    except Exception as e:
        return f"❌ Matched {changed} row(s) but writing **{sheet}** failed: {e}"

    msg = f"✅ Saved Net Basic Value on {changed} order(s) in **{sheet}**"
    if not_found:
        msg += f" · ⚠️ {len(not_found)} SO(s) not found"
    return msg + "."


# ═══════════════════════════════════════════════════════════════════════════════
# TOP-LEVEL ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_and_save_bookings_range(
    start_date: date, end_date: date
) -> tuple[pd.DataFrame, str]:
    """
    Fetch "Order Booked" emails between ``start_date`` and ``end_date``, enrich
    each SO into a report row, and save it to the ``Monthly Godrej Booking
    <Month>`` sheet(s) matching each booking's month.

    Returns (combined_report_df, status_message).
    """
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    bookings, status = fetch_booking_emails(start_date, end_date)
    if bookings is None or bookings.empty:
        return pd.DataFrame(columns=SHEET_COLS), status

    # Search the daily MIS emails from the range start up to today: an order can
    # first appear in an MIS snapshot dated after its booking date, so we widen
    # the MIS-email window to now rather than stopping at the booking end date.
    _today = datetime.now(IST).date()
    _mis_end = max(end_date, _today)
    report = build_report(bookings, mis_email_start=start_date, mis_email_end=_mis_end)
    if report is None or report.empty:
        return pd.DataFrame(columns=SHEET_COLS), status

    # Group report rows by their booking month and save each to its sheet.
    def _month_of(v) -> str:
        d = _parse_row_date(v)
        return d.strftime("%B") if d else end_date.strftime("%B")

    report = report.copy()
    report["_month"] = report["Date"].map(_month_of)

    save_msgs: list[str] = []
    for month, sub in report.groupby("_month"):
        sub = sub.drop(columns=["_month"]).reset_index(drop=True)
        msg, _a, _u = save_bookings_to_sheet(sub, month)
        save_msgs.append(msg)

    report = report.drop(columns=["_month"])
    return report, status + "\n" + "\n".join(save_msgs)


def fetch_and_save_month_bookings() -> tuple[pd.DataFrame, str]:
    """Fetch the current month's Order-Booked emails and save them (scheduler entry)."""
    now  = datetime.now(IST)
    last = calendar.monthrange(now.year, now.month)[1]
    return fetch_and_save_bookings_range(
        date(now.year, now.month, 1),
        date(now.year, now.month, last),
    )
