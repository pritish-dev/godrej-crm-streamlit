"""
services/google_reviews_service.py
Google Business Profile Reviews Integration for 4S Interiors CRM.

Fetches reviews via the Google Business Profile API, matches each reviewer
to a CRM sales record, stores the actual star rating (1–5) in the "REVIEW"
column of the 4S Sales sheet, and uses batch updates for performance.

Key improvements vs. previous version:
  - Stores real star rating (1–5) instead of a binary +1/-1 score so
    dashboards can show true averages and nuanced colour coding.
  - Standardised column name "REVIEW" (matches b2c_dashboard.py and
    30_Sales_Reports_and_Strategy.py expectations).
  - Phone matching removed — Google Business Profile API does not expose
    reviewer phone numbers, so that code path was always dead.
  - Fuzzy name threshold raised 0.80 → 0.90 to reduce false positives.
  - Pre-built index dicts for O(1) email lookup instead of O(n²) scans.
  - Single batch_update_cells() call instead of one API call per review.
  - Unmatched reviews logged to REVIEW_UNMATCHED sheet for manual follow-up.
  - Pagination support — fetches all pages of reviews, not just the first.
"""

import os
import json
import traceback
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import gspread
import requests
from difflib import SequenceMatcher
from google.oauth2.service_account import Credentials

# ── Constants ─────────────────────────────────────────────────────────────────

SCOPES                   = ["https://www.googleapis.com/auth/spreadsheets"]
GOOGLE_BUSINESS_API_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"

SHEET_CONFIG = {
    "4S_SALES_SHEET":  "FY 2026-27 4S Sales",
    "4S_REVIEW_COLUMN": "REVIEW",           # matches dashboard column expectations
    "UNMATCHED_SHEET":  "REVIEW_UNMATCHED", # audit trail for unmatched reviews
}

# Fuzzy name similarity threshold.
# 0.90 avoids false positives on short Indian names that matched at 0.80.
NAME_SIMILARITY_THRESHOLD = 0.90

# Google Business Profile API returns starRating as a string enum
STAR_RATING_MAP = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


# ── Credential Loading ────────────────────────────────────────────────────────

def _load_google_credentials() -> Credentials:
    """Load Google service-account credentials (env → Streamlit secrets → .env)."""

    # 1. Environment variable (GitHub Actions)
    try:
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            return Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    except Exception:
        pass

    # 2. Streamlit secrets
    try:
        import streamlit as st
        for key in ("admin", None):
            try:
                val = st.secrets[key]["GOOGLE_CREDENTIALS"] if key else st.secrets["GOOGLE_CREDENTIALS"]
                d = json.loads(val) if isinstance(val, str) else val
                return Credentials.from_service_account_info(d, scopes=SCOPES)
            except Exception:
                continue
    except Exception:
        pass

    # 3. .env file
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            return Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    except Exception:
        pass

    raise ValueError(
        "GOOGLE_CREDENTIALS not found in environment, Streamlit secrets, or .env file"
    )


def _get_sheets_client() -> gspread.Client:
    return gspread.authorize(_load_google_credentials())


# ── Customer Matching ─────────────────────────────────────────────────────────

def _normalize_email(email: str) -> str:
    return str(email).lower().strip() if email else ""


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    return " ".join(str(name).lower().strip().split())


def _string_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _build_lookup_indexes(
    sales_df: pd.DataFrame,
    email_col: str = "EMAIL",
    name_col:  str = "CUSTOMER NAME",
) -> Tuple[Dict[str, int], List[Tuple[str, int]]]:
    """
    Build O(1) email index and name list once before looping over reviews,
    avoiding an O(n²) scan per review.

    Returns:
        email_idx : {normalised_email: row_index}
        name_list : [(normalised_name, row_index), ...]
    """
    email_idx: Dict[str, int] = {}
    name_list: List[Tuple[str, int]] = []

    for idx, row in sales_df.iterrows():
        if email_col in sales_df.columns:
            e = _normalize_email(str(row.get(email_col, "")))
            if e and e not in email_idx:
                email_idx[e] = idx

        if name_col in sales_df.columns:
            n = _normalize_name(str(row.get(name_col, "")))
            if n:
                name_list.append((n, idx))

    return email_idx, name_list


def match_customer(
    review_customer_name:  str,
    review_customer_email: str,
    email_idx:             Dict[str, int],
    name_list:             List[Tuple[str, int]],
) -> Optional[Tuple[int, str]]:
    """
    Match a reviewer to a CRM row.

    Priority:
      1. Email — exact, O(1) dict lookup.
      2. Name  — fuzzy SequenceMatcher, threshold 0.90.

    Phone matching removed: Google Business Profile API does not expose
    reviewer phone numbers, so that lookup was always dead code.

    Returns (row_index, match_type) or None.
    """
    # 1. Email (exact)
    rev_email = _normalize_email(review_customer_email)
    if rev_email and rev_email in email_idx:
        return (email_idx[rev_email], "email")

    # 2. Name (fuzzy)
    rev_name = _normalize_name(review_customer_name)
    if rev_name:
        best_idx, best_score = None, NAME_SIMILARITY_THRESHOLD
        for sales_name, row_idx in name_list:
            score = _string_similarity(rev_name, sales_name)
            if score > best_score:
                best_score = score
                best_idx   = row_idx
        if best_idx is not None:
            return (best_idx, "name")

    return None


# ── Google Business Profile API ───────────────────────────────────────────────

def fetch_google_reviews(access_token: str, location_id: str) -> List[Dict]:
    """
    Fetch ALL reviews for a location (handles pagination automatically).

    Returns list of dicts with keys:
        rating, reviewer_name, reviewer_email, review_date, review_text, review_id
    """
    reviews:    List[Dict]       = []
    page_token: Optional[str]    = None

    while True:
        params: Dict = {"pageSize": 50}
        if page_token:
            params["pageToken"] = page_token

        try:
            resp = requests.get(
                f"{GOOGLE_BUSINESS_API_BASE}/{location_id}/reviews",
                headers={"Authorization": f"Bearer {access_token}",
                         "Content-Type": "application/json"},
                params=params,
                timeout=30,
            )
        except requests.RequestException as exc:
            print(f"  ⚠️  Network error fetching reviews: {exc}")
            break

        if resp.status_code != 200:
            print(f"  ⚠️  Reviews API returned {resp.status_code}: {resp.text[:300]}")
            break

        data = resp.json()

        for r in data.get("reviews", []):
            raw_rating = str(r.get("starRating", "")).upper()
            # API may return string enum ("FIVE") or integer
            rating = STAR_RATING_MAP.get(raw_rating, 0)
            if rating == 0:
                try:
                    rating = int(raw_rating)
                except ValueError:
                    rating = 0

            reviews.append({
                "rating":         rating,
                "reviewer_name":  r.get("reviewer", {}).get("displayName", ""),
                "reviewer_email": r.get("reviewer", {}).get("emailAddress", ""),
                "review_date":    r.get("createTime", ""),
                "review_text":    r.get("comment", ""),
                "review_id":      r.get("reviewId", ""),
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return reviews


# ── Sheet Update ──────────────────────────────────────────────────────────────

def _log_unmatched(
    client:         gspread.Client,
    spreadsheet_id: str,
    unmatched:      List[Dict],
) -> None:
    """Append unmatched reviews to REVIEW_UNMATCHED sheet for manual follow-up."""
    if not unmatched:
        return
    try:
        sh         = client.open_by_key(spreadsheet_id)
        sheet_name = SHEET_CONFIG["UNMATCHED_SHEET"]
        try:
            ws = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=sheet_name, rows=2000, cols=6)
            ws.append_row(["LOGGED AT", "RATING", "REVIEWER NAME",
                           "REVIEWER EMAIL", "REVIEW DATE", "REVIEW TEXT"])

        now  = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows = [
            [now, r["rating"], r["reviewer_name"], r["reviewer_email"],
             r["review_date"], r["review_text"][:300]]
            for r in unmatched
        ]
        ws.append_rows(rows, value_input_option="RAW")
        print(f"  → Logged {len(rows)} unmatched review(s) to '{sheet_name}'.")
    except Exception as exc:
        print(f"  ⚠️  Could not log unmatched reviews: {exc}")


def process_and_update_reviews(
    reviews:        List[Dict],
    spreadsheet_id: str,
    sales_df:       pd.DataFrame,
) -> Dict:
    """
    Match reviews to CRM rows and write the actual star rating (1–5) to the
    REVIEW column in a single batch API call.

    Returns: {total_reviews, matched, unmatched, errors}
    """
    stats = {
        "total_reviews": len(reviews),
        "matched":       0,
        "unmatched":     0,
        "errors":        0,
    }

    if not reviews:
        return stats

    try:
        client = _get_sheets_client()
        sh     = client.open_by_key(spreadsheet_id)
        ws     = sh.worksheet(SHEET_CONFIG["4S_SALES_SHEET"])

        all_rows = ws.get_all_values()
        if not all_rows:
            print("  ⚠️  Sales sheet is empty.")
            return stats

        headers         = [h.strip().upper() for h in all_rows[0]]
        review_col_name = SHEET_CONFIG["4S_REVIEW_COLUMN"].upper()

        # Add REVIEW column header if it doesn't exist yet
        if review_col_name not in headers:
            headers.append(review_col_name)
            ws.update("A1", [headers])

        review_col_idx = headers.index(review_col_name) + 1   # gspread 1-indexed

        # Normalise sales_df column names once
        norm_df         = sales_df.copy()
        norm_df.columns = [str(c).strip().upper() for c in norm_df.columns]

        # Build O(1) lookup indexes (avoids O(n²) per-review scan)
        email_idx, name_list = _build_lookup_indexes(norm_df)

        # Collect all cell writes first, then flush in one batch call
        cells_to_update: List[gspread.Cell] = []
        unmatched_reviews:  List[Dict]      = []

        for review in reviews:
            try:
                rating = int(review.get("rating", 0))

                result = match_customer(
                    review_customer_name  = review.get("reviewer_name", ""),
                    review_customer_email = review.get("reviewer_email", ""),
                    email_idx             = email_idx,
                    name_list             = name_list,
                )

                if result:
                    row_idx, match_type = result
                    sheet_row = row_idx + 2   # +1 header row, +1 for 0-indexed pandas
                    cells_to_update.append(
                        gspread.Cell(row=sheet_row, col=review_col_idx, value=str(rating))
                    )
                    stats["matched"] += 1
                    print(
                        f"  ✓ {rating}★ by '{review.get('reviewer_name', '?')}' "
                        f"→ sheet row {sheet_row} (matched via {match_type})"
                    )
                else:
                    stats["unmatched"] += 1
                    unmatched_reviews.append(review)
                    print(
                        f"  ✗ No match: '{review.get('reviewer_name', '?')}' "
                        f"<{review.get('reviewer_email', '')}>"
                    )

            except Exception as exc:
                stats["errors"] += 1
                print(f"  ⚠️  Error processing review: {exc}")

        # Single batch write — one API call regardless of number of reviews
        if cells_to_update:
            ws.update_cells(cells_to_update, value_input_option="RAW")
            print(f"  → Batch wrote {len(cells_to_update)} rating(s) in one API call.")

        # Persist unmatched reviews for manual review
        _log_unmatched(client, spreadsheet_id, unmatched_reviews)

    except Exception as exc:
        print(f"  ❌ Sheet update failed: {exc}")
        traceback.print_exc()
        stats["errors"] += 1

    return stats


# ── Public Entry Point ────────────────────────────────────────────────────────

def fetch_and_update_reviews_4s(
    access_token:   str,
    location_id:    str,
    spreadsheet_id: str,
    sales_df:       pd.DataFrame,
) -> Dict:
    """
    Called by google_reviews_update_job.py.
    Fetches all GMB reviews then writes star ratings back to the 4S Sales sheet.
    """
    ts = lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts()}] Starting Google Reviews fetch for 4S Interiors...")

    reviews = fetch_google_reviews(access_token, location_id)
    print(f"  → Fetched {len(reviews)} review(s) from Google Business Profile")

    stats = process_and_update_reviews(reviews, spreadsheet_id, sales_df)

    print(
        f"[{ts()}] ✅ Done — Matched: {stats['matched']}  "
        f"Unmatched: {stats['unmatched']}  Errors: {stats['errors']}"
    )
    return stats
