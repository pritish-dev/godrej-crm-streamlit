"""
services/google_reviews_service.py
Google Business Profile (GMB) Reviews Integration for 4S Interiors CRM.

What this module does
─────────────────────
1. Authenticates to the Google My Business v4 API using an OAuth 2.0
   refresh-token (the only auth flow Google supports for the Reviews API —
   service accounts cannot read GMB reviews).
2. Pulls every review for the configured GMB location (with pagination).
3. Matches each reviewer to a CRM row in the 4S Sales sheet using a
   robust multi-strategy matcher:
       Priority 1 — exact email match (when reviewer email is exposed)
       Priority 2 — exact phone match (when reviewer name contains digits
                    that look like a phone number — rare but cheap to try)
       Priority 3 — exact normalised-name match
       Priority 4 — fuzzy SequenceMatcher name match (≥ NAME_THRESHOLD)
       Priority 5 — token-overlap match (first/last name swap-tolerant)
4. Writes the actual star rating (1–5) to the "REVIEW" column of the
   4S Sales sheet in a single batch update (one API call no matter how
   many reviews are processed).
5. Logs every sync run to REVIEW_SYNC_LOG and every review (matched or
   not) to REVIEW_DETAILS for full traceability and manual follow-up.

This module is safe to call from:
   • A scheduled GitHub Actions workflow (10 PM IST daily)
   • The Streamlit "Fetch Reviews Now" button (Daily B2C Sales page)

Idempotency
───────────
Each review carries a stable Google `reviewId`. We write only when the
rating in the sheet differs from the rating from the API, so re-running
the job is a no-op when nothing has changed.

Failure isolation
─────────────────
Any exception is caught, logged, and reported back through the stats
dict so callers (UI button, scheduler) can show a friendly message
without ever wiping the sheet.
"""

from __future__ import annotations

import os
import re
import json
import time
import traceback
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple, Iterable

import pandas as pd
import requests
import gspread
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceCredentials
from google.auth.transport.requests import Request as GoogleAuthRequest

# ── Constants ─────────────────────────────────────────────────────────────────

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GMB_SCOPES    = ["https://www.googleapis.com/auth/business.manage"]

# Google Places API — the recommended, free, always-available reviews source.
# Returns up to 5 MOST-RECENT reviews per call (set `reviews_sort=newest`).
# Free under Google Maps Platform's $200/month credit (your ~30 calls/month
# usage = well under 1% of the free quota).
PLACES_API_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Google My Business v4 — older endpoint that returns FULL history, but
# is hidden from the API Library and requires per-project allow-listing.
# Used only if GMB_REFRESH_TOKEN is set; otherwise we use Places API.
GMB_API_BASE  = "https://mybusiness.googleapis.com/v4"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

SHEET_CONFIG = {
    "4S_SALES_SHEET":    "FY 2026-27 4S Sales",
    "4S_REVIEW_COLUMN":  "REVIEW",            # 1–5 star rating, 0/blank = none
    "DETAILS_SHEET":     "REVIEW_DETAILS",    # audit log of every review
    "SYNC_LOG_SHEET":    "REVIEW_SYNC_LOG",   # one row per fetch run
    "UNMATCHED_SHEET":   "REVIEW_UNMATCHED",  # legacy — kept for back-compat
}

# Fuzzy name similarity threshold. Loosened from 0.85 → 0.78 because typical
# Indian customer-name variations (initial-only middle names, surname order
# swaps, "Sushil Kumar Mohanty" vs "Sushil K Mohanty", location suffixes like
# "Pritish Sahoo Patia") score in the 0.78–0.84 band. The token-overlap rule
# below adds an extra safety net so a single first-name collision can never
# alone produce a match.
NAME_SIMILARITY_THRESHOLD = 0.78

# Token-overlap threshold. Loosened to 0.66 ("at least 2 of 3 tokens overlap")
# so a review from "Pritish Sahoo" still matches a CRM customer recorded as
# "Pritish Kumar Sahoo, Patia". The TOKEN_MIN_SHORT_LEN guard below ensures
# we never match on a single-token review name.
TOKEN_OVERLAP_THRESHOLD   = 0.66
TOKEN_MIN_SHORT_LEN       = 2        # both sides must have ≥ 2 name tokens

# Stop-words / noise tokens that appear in CRM names but carry no signal
# (showroom area names, salutations, customer-type tags). Stripped before
# token-overlap so they don't dilute the score.
NAME_NOISE_TOKENS = {
    "bhubaneswar", "patia", "cuttack", "khordha", "puri", "bhubaneswari",
    "interio", "godrej", "4s", "showroom", "store", "interiors",
    "customer", "client", "sir", "madam", "ji",
}

# Star-rating enum from the GMB API (may also arrive as plain int)
STAR_RATING_MAP = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

IST = timezone(timedelta(hours=5, minutes=30))


# ═════════════════════════════════════════════════════════════════════════════
# 1.  CREDENTIAL LOADING
# ═════════════════════════════════════════════════════════════════════════════

def _load_secret(name: str) -> str:
    """
    Resolve a secret in this order:
        1. Plain environment variable (GitHub Actions injects these)
        2. Streamlit secrets    (used when running inside Streamlit)
        3. .env file            (local dev fallback)
    Returns "" if not found anywhere — callers decide what to do.
    """
    val = (os.getenv(name) or "").strip()
    if val:
        return val

    # Streamlit secrets (only available inside Streamlit runtime)
    try:
        import streamlit as st  # type: ignore
        # Try flat keys, then a nested [gmb] section
        try:
            v = st.secrets.get(name, "")
            if v:
                return str(v).strip()
        except Exception:
            pass
        try:
            section = st.secrets.get("gmb", {}) or {}
            v = section.get(name, "")
            if v:
                return str(v).strip()
        except Exception:
            pass
    except Exception:
        pass

    # .env fallback
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    except Exception:
        pass

    return ""


def _load_sheets_credentials() -> ServiceCredentials:
    """Load the service-account creds used for Google Sheets writes."""
    raw = _load_secret("GOOGLE_CREDENTIALS")
    if raw:
        try:
            info = json.loads(raw)
            return ServiceCredentials.from_service_account_info(info, scopes=SHEETS_SCOPES)
        except Exception as e:
            raise ValueError(f"GOOGLE_CREDENTIALS is not valid JSON: {e}")

    # Streamlit nested-dict format (used elsewhere in this codebase)
    try:
        import streamlit as st  # type: ignore
        info = dict(st.secrets["google"])  # raises if missing
        return ServiceCredentials.from_service_account_info(info, scopes=SHEETS_SCOPES)
    except Exception:
        pass

    raise ValueError(
        "Sheets credentials missing. Set GOOGLE_CREDENTIALS env var "
        "or st.secrets['google']."
    )


def _get_sheets_client() -> gspread.Client:
    return gspread.authorize(_load_sheets_credentials())


def get_gmb_access_token() -> str:
    """
    Exchange a refresh token for a fresh GMB access token.

    Required secrets (env / Streamlit / .env):
        GMB_CLIENT_ID
        GMB_CLIENT_SECRET
        GMB_REFRESH_TOKEN

    A static GMB_ACCESS_TOKEN is also accepted as a one-off override (handy
    for local debugging) but should NOT be used in production because access
    tokens expire every 60 minutes.
    """
    # One-off override (debug only)
    static_token = _load_secret("GMB_ACCESS_TOKEN") or _load_secret("GOOGLE_ACCESS_TOKEN")
    if static_token:
        return static_token

    client_id     = _load_secret("GMB_CLIENT_ID")
    client_secret = _load_secret("GMB_CLIENT_SECRET")
    refresh_token = _load_secret("GMB_REFRESH_TOKEN")

    missing = [k for k, v in (
        ("GMB_CLIENT_ID", client_id),
        ("GMB_CLIENT_SECRET", client_secret),
        ("GMB_REFRESH_TOKEN", refresh_token),
    ) if not v]
    if missing:
        raise ValueError(
            "Missing GMB OAuth secrets: " + ", ".join(missing)
            + ". See GOOGLE_REVIEWS_SETUP.md for how to generate a refresh token."
        )

    resp = requests.post(
        GOOGLE_OAUTH_TOKEN_URL,
        data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to refresh GMB access token "
            f"(HTTP {resp.status_code}): {resp.text[:300]}"
        )
    token = resp.json().get("access_token", "")
    if not token:
        raise RuntimeError("Token endpoint returned no access_token")
    return token


def get_gmb_location_path() -> str:
    """
    Build the GMB resource path used by the v4 reviews endpoint:
        accounts/{accountId}/locations/{locationId}

    Accepts either a pre-built full path in GMB_LOCATION_PATH, or two
    separate IDs in GMB_ACCOUNT_ID + GMB_LOCATION_ID.
    """
    full = _load_secret("GMB_LOCATION_PATH")
    if full:
        return full.strip().lstrip("/")

    account_id  = _load_secret("GMB_ACCOUNT_ID")
    location_id = _load_secret("GMB_LOCATION_ID") or _load_secret("GOOGLE_LOCATION_ID")

    if not account_id or not location_id:
        raise ValueError(
            "Missing GMB_ACCOUNT_ID and/or GMB_LOCATION_ID. "
            "See GOOGLE_REVIEWS_SETUP.md."
        )

    # Strip any accidental "accounts/" / "locations/" prefixes
    account_id  = account_id.replace("accounts/", "").strip("/")
    location_id = location_id.replace("locations/", "").strip("/")
    return f"accounts/{account_id}/locations/{location_id}"


# ═════════════════════════════════════════════════════════════════════════════
# 2.  TEXT NORMALISATION HELPERS
# ═════════════════════════════════════════════════════════════════════════════

_NAME_PREFIX_RE = re.compile(
    r"^\s*(mr|mrs|ms|miss|dr|er|smt|shri|sri|prof)\.?\s+",
    flags=re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
_DIGIT_ONLY_RE = re.compile(r"\D+")


def _normalize_email(email: object) -> str:
    if not email:
        return ""
    return str(email).strip().lower()


def _normalize_name(name: object) -> str:
    """Lowercase, strip salutations, drop punctuation, collapse whitespace,
    and remove low-signal noise tokens (location names, salutations etc.)
    so the token-overlap matcher works on real name parts only."""
    if not name:
        return ""
    s = str(name).strip().lower()
    s = _NAME_PREFIX_RE.sub("", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    tokens = [t for t in s.split() if t and t not in NAME_NOISE_TOKENS]
    return " ".join(tokens)


def _normalize_phone(phone: object) -> str:
    """Keep only digits; trim to last 10 digits (Indian mobile format)."""
    if not phone:
        return ""
    digits = _DIGIT_ONLY_RE.sub("", str(phone))
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def _string_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _token_overlap(a: str, b: str) -> float:
    """
    Tolerant token overlap. Returns intersection / min(set_size) so that
    a shorter name fully contained in a longer one (e.g. "Pritish Sahoo"
    inside "Pritish Kumar Sahoo") scores 1.0 — handles dropped middle
    names and first/last-name swaps.
    """
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _extract_phone_from_text(text: str) -> str:
    """Pull a 10-digit Indian-style phone out of arbitrary text. Empty if none."""
    if not text:
        return ""
    digits = _DIGIT_ONLY_RE.sub("", str(text))
    # Keep last 10 digits if there are at least 10 (covers +91-prefixed numbers)
    if len(digits) >= 10:
        candidate = digits[-10:]
        if candidate[0] in "6789":   # Indian mobile numbers start with 6-9
            return candidate
    return ""


# ═════════════════════════════════════════════════════════════════════════════
# 3.  CRM LOOKUP INDEXES
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_column(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    """Return the first matching column name (case-insensitive), or None."""
    upper_map = {c.upper(): c for c in df.columns}
    for cand in candidates:
        if cand.upper() in upper_map:
            return upper_map[cand.upper()]
    return None


def _build_lookup_indexes(
    sales_df: pd.DataFrame,
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int], List[Tuple[str, int]]]:
    """
    Pre-build indexes once, so we don't scan the whole DataFrame for every
    review (which would be O(n × m)).

    Returns:
        email_idx     : {normalised_email   → row_index}
        phone_idx     : {normalised_phone10 → row_index}
        exact_name_idx: {normalised_name    → row_index}
        name_list     : [(normalised_name, row_index), ...] for fuzzy scan
    """
    email_idx:      Dict[str, int]            = {}
    phone_idx:      Dict[str, int]            = {}
    exact_name_idx: Dict[str, int]            = {}
    name_list:      List[Tuple[str, int]]     = []

    name_col  = _resolve_column(sales_df, "CUSTOMER NAME", "CUSTOMER_NAME", "NAME")
    email_col = _resolve_column(sales_df, "EMAIL ADDRESS", "EMAIL", "CUSTOMER EMAIL")
    phone_col = _resolve_column(sales_df, "CONTACT NUMBER", "CONTACT NO", "PHONE",
                                "MOBILE", "MOBILE NUMBER", "CUSTOMER PHONE")

    for idx, row in sales_df.iterrows():
        if email_col:
            e = _normalize_email(row.get(email_col, ""))
            if e and "@" in e and e not in email_idx:
                email_idx[e] = idx

        if phone_col:
            p = _normalize_phone(row.get(phone_col, ""))
            if p and len(p) == 10 and p not in phone_idx:
                phone_idx[p] = idx

        if name_col:
            n = _normalize_name(row.get(name_col, ""))
            if n:
                if n not in exact_name_idx:
                    exact_name_idx[n] = idx
                name_list.append((n, idx))

    return email_idx, phone_idx, exact_name_idx, name_list


def match_customer(
    review_name:  str,
    review_email: str,
    email_idx:    Dict[str, int],
    phone_idx:    Dict[str, int],
    exact_name_idx: Dict[str, int],
    name_list:    List[Tuple[str, int]],
    review_text:  str = "",
) -> Optional[Tuple[int, str, float]]:
    """
    Multi-strategy reviewer → CRM row matcher.

    Returns (row_index, match_type, confidence_0_to_1) or None.

    The Google Places API does NOT expose a reviewer phone number, but
    reviewers themselves frequently paste their number either in their
    display name ("Rakesh 9876543210") or, more commonly, in the body of
    the review itself ("Thanks team — 9876543210 - Rakesh").  We scan both
    fields so the contact-number match strategy actually catches those.
    """
    # 1. Email exact match
    e = _normalize_email(review_email)
    if e and e in email_idx:
        return (email_idx[e], "email", 1.00)

    # 2. Phone match — try the display name first, then the review text body
    phone_in_name = _extract_phone_from_text(review_name)
    if phone_in_name and phone_in_name in phone_idx:
        return (phone_idx[phone_in_name], "phone_name", 1.00)
    phone_in_text = _extract_phone_from_text(review_text)
    if phone_in_text and phone_in_text in phone_idx:
        return (phone_idx[phone_in_text], "phone_text", 1.00)

    n = _normalize_name(review_name)
    if not n:
        return None

    # 3. Name exact match (after normalisation)
    if n in exact_name_idx:
        return (exact_name_idx[n], "name_exact", 0.99)

    # 4. Name fuzzy match (SequenceMatcher)
    best_idx, best_score, best_strategy = None, NAME_SIMILARITY_THRESHOLD, ""
    for sales_name, row_idx in name_list:
        score = _string_similarity(n, sales_name)
        if score > best_score:
            best_score, best_idx, best_strategy = score, row_idx, "name_fuzzy"

    # 5. Token overlap — handles middle-name drops and first/last swaps.
    #    Requires BOTH sides to have ≥ TOKEN_MIN_SHORT_LEN tokens (so a one-
    #    word review name like "Rakesh" can't accidentally pick a "Rakesh
    #    Singh" row) and at least TOKEN_OVERLAP_THRESHOLD of the smaller set
    #    to overlap. With the loosened 0.66 threshold this catches "Pritish
    #    Sahoo" ↔ "Pritish Kumar Sahoo Patia" (2/2 overlap after noise strip)
    #    but still rejects pure single-name matches.
    rev_tokens = set(n.split())
    if len(rev_tokens) >= TOKEN_MIN_SHORT_LEN:
        for sales_name, row_idx in name_list:
            sales_tokens = set(sales_name.split())
            if len(sales_tokens) < TOKEN_MIN_SHORT_LEN:
                continue
            overlap_count = len(rev_tokens & sales_tokens)
            if overlap_count < TOKEN_MIN_SHORT_LEN:
                # At least 2 name tokens must actually overlap — protects
                # against false positives from single-first-name collisions.
                continue
            min_size = min(len(rev_tokens), len(sales_tokens))
            score = overlap_count / min_size
            if score >= TOKEN_OVERLAP_THRESHOLD and score > best_score:
                best_score, best_idx, best_strategy = score, row_idx, "name_tokens"

    # 6. Initial-tolerant match — last resort for Indian-style abbreviations
    #    like "S K Mohanty" ↔ "Sushil Kumar Mohanty". We check that every
    #    single-character review token matches the FIRST LETTER of some
    #    sales token AND that all multi-char review tokens are exactly
    #    present in the sales name. This is conservative: needs ≥2 review
    #    tokens AND a multi-character anchor to fire.
    if rev_tokens and best_idx is None:
        rev_full   = [t for t in n.split() if len(t) > 1]
        rev_init   = [t for t in n.split() if len(t) == 1]
        if rev_full and (len(rev_full) + len(rev_init)) >= 2:
            for sales_name, row_idx in name_list:
                stoks = sales_name.split()
                if len(stoks) < 2:
                    continue
                if not all(t in stoks for t in rev_full):
                    continue
                sales_initials = {st[0] for st in stoks}
                if not all(ri in sales_initials for ri in rev_init):
                    continue
                # Confidence scaled by how complete the multi-char match is
                cscore = 0.80 + 0.05 * min(len(rev_full), 3)
                if cscore > best_score:
                    best_score, best_idx, best_strategy = cscore, row_idx, "name_initials"

    if best_idx is not None:
        return (best_idx, best_strategy, round(best_score, 2))

    return None


# ═════════════════════════════════════════════════════════════════════════════
# 4.  GOOGLE BUSINESS PROFILE API
# ═════════════════════════════════════════════════════════════════════════════

def fetch_google_reviews(
    access_token: str,
    location_path: str,
    page_size: int = 50,
    max_pages: int = 200,
) -> List[Dict]:
    """
    Fetch ALL reviews for a location, transparently handling pagination.

    `location_path` must be of the form 'accounts/{aid}/locations/{lid}'.
    Returns a list of dicts with keys:
        review_id, rating, reviewer_name, reviewer_email,
        review_date, review_text, reply_text, reply_date
    """
    out: List[Dict]       = []
    page_token: Optional[str] = None
    pages_fetched = 0

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }
    url = f"{GMB_API_BASE}/{location_path.strip('/')}/reviews"

    while True:
        params: Dict = {"pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as exc:
            print(f"  ⚠️  Network error fetching reviews: {exc}")
            break

        # Retry once on transient 5xx
        if 500 <= resp.status_code < 600:
            time.sleep(2.0)
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=30)
            except requests.RequestException as exc:
                print(f"  ⚠️  Retry failed: {exc}")
                break

        if resp.status_code == 401:
            raise RuntimeError(
                "GMB API returned 401 Unauthorized. Refresh token may be revoked "
                "or scopes are wrong. Re-run the OAuth setup script."
            )
        if resp.status_code == 403:
            raise RuntimeError(
                f"GMB API returned 403 Forbidden: {resp.text[:300]}\n"
                f"Common causes: business.manage scope missing, account "
                f"doesn't own the location, or API not enabled in GCP."
            )
        if resp.status_code != 200:
            print(f"  ⚠️  Reviews API returned {resp.status_code}: {resp.text[:300]}")
            break

        data = resp.json()
        for r in data.get("reviews", []):
            raw_rating = str(r.get("starRating", "")).upper()
            rating = STAR_RATING_MAP.get(raw_rating, 0)
            if rating == 0:
                try:
                    rating = int(raw_rating)
                except ValueError:
                    rating = 0

            reviewer = r.get("reviewer", {}) or {}
            reply    = r.get("reviewReply", {}) or {}

            out.append({
                "review_id":      r.get("reviewId", "") or r.get("name", ""),
                "rating":         rating,
                "reviewer_name":  reviewer.get("displayName", "") or "",
                "reviewer_email": reviewer.get("emailAddress", "") or "",
                "review_date":    r.get("createTime", "") or "",
                "review_text":    r.get("comment", "") or "",
                "reply_text":     reply.get("comment", "") or "",
                "reply_date":     reply.get("updateTime", "") or "",
            })

        page_token = data.get("nextPageToken")
        pages_fetched += 1
        if not page_token or pages_fetched >= max_pages:
            break

    return out


# ─── Places API path (the DEFAULT / recommended one) ──────────────────────────

import hashlib


def _places_review_id(author_name: str, unix_time: int, text: str) -> str:
    """
    Build a stable synthetic review_id for Places-API reviews.

    Places API doesn't expose a real review_id, so we hash author + time +
    text-prefix into a 16-hex-char digest. Stable across runs ⇒ the
    REVIEW_DETAILS sheet de-dups correctly on re-fetch.
    """
    raw = f"{(author_name or '').strip().lower()}|{int(unix_time or 0)}|{(text or '')[:80]}"
    return "places_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def fetch_google_reviews_via_places(
    api_key:  str,
    place_id: str,
    language: str = "en",
) -> List[Dict]:
    """
    Fetch up to 5 most-recent reviews via the Google Places API.

    Pros: No allow-listing needed. Works the moment an API key + Place ID
          are configured. Free at any realistic showroom volume.
    Cons: API caps the response at 5 reviews per call (Google's limit, not
          ours). Running the job daily means anything beyond ≥6 reviews/day
          for a single business gets missed — at your volume this never
          happens. For full history, switch to the v4 path once allow-listed.

    Returns the same dict shape as `fetch_google_reviews()` so the matcher
    and sheet writer don't need to know which source produced the data.
    """
    out: List[Dict] = []
    if not api_key or not place_id:
        return out

    params = {
        "place_id":     place_id,
        "fields":       "name,reviews,user_ratings_total,rating",
        "reviews_sort": "newest",       # newest-first ⇒ best fit for daily fetch
        "language":     language,
        "key":          api_key,
    }

    try:
        resp = requests.get(PLACES_API_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        print(f"  ⚠️  Network error calling Places API: {exc}")
        return out

    if resp.status_code != 200:
        print(f"  ⚠️  Places API returned {resp.status_code}: {resp.text[:300]}")
        return out

    data = resp.json()
    status = data.get("status", "UNKNOWN")
    if status != "OK":
        # Common statuses: ZERO_RESULTS (no reviews yet), REQUEST_DENIED
        # (API key/restrictions bad), INVALID_REQUEST (place_id wrong),
        # OVER_QUERY_LIMIT (quota exhausted).
        err = data.get("error_message", "")
        print(f"  ⚠️  Places API status='{status}'  msg='{err}'")
        if status in {"REQUEST_DENIED", "INVALID_REQUEST"}:
            raise RuntimeError(
                f"Places API rejected the request (status={status}): {err}. "
                f"Check that GOOGLE_PLACES_API_KEY is valid, Places API is "
                f"enabled on the GCP project, and GOOGLE_PLACE_ID is correct."
            )
        return out

    result = data.get("result", {}) or {}
    biz_name = result.get("name", "")
    print(f"  → Places API: business='{biz_name}', total_ratings="
          f"{result.get('user_ratings_total', 0)}, avg={result.get('rating', 0)}")

    for r in result.get("reviews", []) or []:
        try:
            rating = int(r.get("rating", 0) or 0)
        except Exception:
            rating = 0

        unix_t = int(r.get("time", 0) or 0)
        iso_date = (
            datetime.fromtimestamp(unix_t, tz=timezone.utc).isoformat()
            if unix_t > 0 else ""
        )

        out.append({
            "review_id":      _places_review_id(
                                  r.get("author_name", ""), unix_t, r.get("text", "")
                              ),
            "rating":         rating,
            "reviewer_name":  r.get("author_name", "") or "",
            "reviewer_email": "",                          # not exposed by Places
            "review_date":    iso_date,
            "review_text":    r.get("text", "") or "",
            "reply_text":     "",
            "reply_date":     "",
        })

    return out


# ═════════════════════════════════════════════════════════════════════════════
# 5.  SHEET I/O
# ═════════════════════════════════════════════════════════════════════════════

def _ensure_review_column(ws: gspread.Worksheet, headers: List[str]) -> Tuple[int, List[str]]:
    """
    Ensure the REVIEW column exists in the sheet header row.
    Returns (1-indexed column number, possibly-updated headers list).
    """
    review_col = SHEET_CONFIG["4S_REVIEW_COLUMN"].upper()
    upper_headers = [h.upper() for h in headers]
    if review_col not in upper_headers:
        headers = list(headers) + [SHEET_CONFIG["4S_REVIEW_COLUMN"]]
        ws.update("A1", [headers])
        upper_headers = [h.upper() for h in headers]
    return upper_headers.index(review_col) + 1, headers


def _log_review_details(
    client: gspread.Client,
    spreadsheet_id: str,
    matched_rows: List[Dict],
    unmatched_rows: List[Dict],
) -> None:
    """Append every processed review to REVIEW_DETAILS for traceability."""
    if not matched_rows and not unmatched_rows:
        return
    try:
        sh = client.open_by_key(spreadsheet_id)
        sheet_name = SHEET_CONFIG["DETAILS_SHEET"]
        try:
            ws = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=sheet_name, rows=5000, cols=11)
            ws.append_row([
                "LOGGED AT (IST)", "REVIEW ID", "RATING", "REVIEWER NAME",
                "REVIEWER EMAIL", "REVIEW DATE", "REVIEW TEXT",
                "MATCH STATUS", "MATCH TYPE", "MATCH CONFIDENCE",
                "MATCHED CRM ROW",
            ])

        # De-dup against existing review_ids so re-runs don't pile rows up
        existing = set()
        try:
            existing_data = ws.col_values(2)[1:]   # skip header
            existing = {x.strip() for x in existing_data if x.strip()}
        except Exception:
            pass

        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
        rows: List[List[str]] = []

        for r in matched_rows:
            rid = str(r.get("review_id", ""))
            if rid and rid in existing:
                continue
            rows.append([
                now, rid, r.get("rating", 0),
                r.get("reviewer_name", ""), r.get("reviewer_email", ""),
                r.get("review_date", ""), str(r.get("review_text", ""))[:500],
                "MATCHED", r.get("_match_type", ""), str(r.get("_match_conf", "")),
                str(r.get("_sheet_row", "")),
            ])
        for r in unmatched_rows:
            rid = str(r.get("review_id", ""))
            if rid and rid in existing:
                continue
            rows.append([
                now, rid, r.get("rating", 0),
                r.get("reviewer_name", ""), r.get("reviewer_email", ""),
                r.get("review_date", ""), str(r.get("review_text", ""))[:500],
                "UNMATCHED", "", "", "",
            ])

        if rows:
            ws.append_rows(rows, value_input_option="RAW")
            print(f"  → Logged {len(rows)} review row(s) to '{sheet_name}'.")
    except Exception as exc:
        print(f"  ⚠️  Could not log review details: {exc}")


def _log_sync_run(
    client: gspread.Client,
    spreadsheet_id: str,
    stats: Dict,
    triggered_by: str,
) -> None:
    """One row per fetch run — used by the UI to show 'last synced' time."""
    try:
        sh = client.open_by_key(spreadsheet_id)
        sheet_name = SHEET_CONFIG["SYNC_LOG_SHEET"]
        try:
            ws = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=sheet_name, rows=2000, cols=7)
            ws.append_row([
                "TIMESTAMP (IST)", "TRIGGERED BY",
                "TOTAL REVIEWS", "MATCHED", "UNMATCHED", "ERRORS", "STATUS",
            ])

        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
        ws.append_row([
            now, triggered_by,
            int(stats.get("total_reviews", 0)),
            int(stats.get("matched", 0)),
            int(stats.get("unmatched", 0)),
            int(stats.get("errors", 0)),
            stats.get("status", "ok"),
        ], value_input_option="RAW")
    except Exception as exc:
        print(f"  ⚠️  Could not log sync run: {exc}")


def get_last_sync_info(spreadsheet_id: Optional[str] = None) -> Dict:
    """
    Read the most recent row from REVIEW_SYNC_LOG.

    Returned dict (always present, fields may be empty strings):
        {timestamp, triggered_by, total, matched, unmatched, errors, status}
    """
    empty = {"timestamp": "", "triggered_by": "", "total": 0, "matched": 0,
             "unmatched": 0, "errors": 0, "status": ""}
    try:
        if spreadsheet_id is None:
            from services.sheets import SPREADSHEET_ID  # late import
            spreadsheet_id = SPREADSHEET_ID
        client = _get_sheets_client()
        sh = client.open_by_key(spreadsheet_id)
        try:
            ws = sh.worksheet(SHEET_CONFIG["SYNC_LOG_SHEET"])
        except gspread.WorksheetNotFound:
            return empty
        rows = ws.get_all_values()
        if len(rows) < 2:
            return empty
        last = rows[-1]
        # pad if shorter
        last = last + [""] * max(0, 7 - len(last))
        def _to_int(x):
            try: return int(x)
            except Exception: return 0
        return {
            "timestamp":    last[0],
            "triggered_by": last[1],
            "total":        _to_int(last[2]),
            "matched":      _to_int(last[3]),
            "unmatched":    _to_int(last[4]),
            "errors":       _to_int(last[5]),
            "status":       last[6],
        }
    except Exception as exc:
        print(f"  ⚠️  Could not read sync log: {exc}")
        return empty


# ═════════════════════════════════════════════════════════════════════════════
# 6.  MAIN PROCESSOR
# ═════════════════════════════════════════════════════════════════════════════

def _discover_sales_sheets(client: gspread.Client, spreadsheet_id: str) -> List[str]:
    """
    Return the union of every sales-sheet name listed in SHEET_DETAILS
    (Franchise_sheets + four_s_sheets).  Falls back to the legacy single
    4S sheet if SHEET_DETAILS is missing.
    """
    try:
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.worksheet("SHEET_DETAILS")
        rows = ws.get_all_records()
    except Exception:
        return [SHEET_CONFIG["4S_SALES_SHEET"]]

    out: List[str] = []
    for r in rows:
        for col in ("Franchise_sheets", "four_s_sheets",
                    "FRANCHISE_SHEETS", "FOUR_S_SHEETS"):
            v = str(r.get(col, "") or "").strip()
            if v and v not in out:
                out.append(v)
    if not out:
        out = [SHEET_CONFIG["4S_SALES_SHEET"]]
    return out


def process_and_update_reviews(
    reviews:        List[Dict],
    spreadsheet_id: str,
    sales_df:       pd.DataFrame,   # accepted for back-compat — no longer used
) -> Dict:
    """
    Match reviews against every sales sheet listed in SHEET_DETAILS
    (Franchise + 4S) and write each matched star rating into the REVIEW
    column of whichever sheet contains the customer.

    Matching strategies (in priority order, per review):
        1. Email exact match
        2. Phone exact match (extracted from reviewer name OR review text)
        3. Customer name exact / fuzzy / token-overlap match

    The first sheet that yields a match wins.  Unmatched reviews are logged
    to REVIEW_DETAILS but no rating is written anywhere.

    Returns {total_reviews, matched, unmatched, errors, written, status}.
    """
    stats = {
        "total_reviews":  len(reviews),
        "matched":        0,
        "unmatched":      0,
        "errors":         0,
        "written":        0,
        "status":         "ok",
        # Per-sheet breakdown so the UI can prove BOTH 4S and Franchise
        # sheets are being scanned and updated on every fetch.
        "sheets_scanned": [],
        "by_sheet":       {},   # { sheet_name: {"matched": n, "written": n} }
    }
    if not reviews:
        return stats

    try:
        client = _get_sheets_client()
        sh     = client.open_by_key(spreadsheet_id)

        # ── Discover every sales sheet from SHEET_DETAILS ────────────────────
        sheet_names = _discover_sales_sheets(client, spreadsheet_id)
        stats["sheets_scanned"] = list(sheet_names)
        for _sn in sheet_names:
            stats["by_sheet"][_sn] = {"matched": 0, "written": 0}
        print(f"  → Will scan {len(sheet_names)} sales sheet(s): {sheet_names}")

        # Per-sheet context (worksheet, header, REVIEW column idx, dataframe,
        # lookup indexes, existing REVIEW values).  Built lazily but cached
        # so we never re-fetch the same sheet twice in one run.
        sheet_ctx: Dict[str, Dict] = {}

        def _ctx_for(sheet_name: str) -> Dict | None:
            """Load + cache the per-sheet context, or return None if unusable."""
            if sheet_name in sheet_ctx:
                return sheet_ctx[sheet_name]
            try:
                ws = sh.worksheet(sheet_name)
            except gspread.WorksheetNotFound:
                print(f"  ⚠️  Sheet '{sheet_name}' not found — skipping.")
                sheet_ctx[sheet_name] = None
                return None

            all_rows = ws.get_all_values()
            if not all_rows:
                print(f"  ⚠️  Sheet '{sheet_name}' is empty — skipping.")
                sheet_ctx[sheet_name] = None
                return None

            headers = [h.strip() for h in all_rows[0]]
            review_col_idx, headers = _ensure_review_column(ws, headers)

            existing: Dict[int, str] = {}
            for i, row in enumerate(all_rows[1:], start=2):
                existing[i] = (
                    str(row[review_col_idx - 1]).strip()
                    if review_col_idx - 1 < len(row) else ""
                )

            # Build a DataFrame from the rows so the lookup indexes work
            data_rows = all_rows[1:]
            max_cols = max(len(headers), max((len(r) for r in data_rows), default=0))
            padded_headers = headers + [f"_col{i}" for i in range(len(headers), max_cols)]
            normalised_rows = [
                r + [""] * (max_cols - len(r)) for r in data_rows
            ]
            df = pd.DataFrame(normalised_rows, columns=padded_headers)
            df.columns = [str(c).strip().upper() for c in df.columns]
            df = df.loc[:, ~df.columns.duplicated()]

            email_idx, phone_idx, exact_name_idx, name_list = _build_lookup_indexes(df)

            ctx = {
                "ws":             ws,
                "review_col_idx": review_col_idx,
                "existing":       existing,
                "email_idx":      email_idx,
                "phone_idx":      phone_idx,
                "exact_name_idx": exact_name_idx,
                "name_list":      name_list,
                "pending_cells":  [],   # gspread.Cell to write at the end
            }
            sheet_ctx[sheet_name] = ctx
            return ctx

        matched_rows_log:   List[Dict] = []
        unmatched_rows_log: List[Dict] = []

        # ── Iterate each review and try every sheet until a match wins ───────
        for review in reviews:
            try:
                rating = int(review.get("rating", 0) or 0)
                if rating < 1 or rating > 5:
                    stats["unmatched"] += 1
                    unmatched_rows_log.append(review)
                    continue

                hit: Tuple[str, int, str, float] | None = None  # (sheet, row, type, conf)

                for sheet_name in sheet_names:
                    ctx = _ctx_for(sheet_name)
                    if ctx is None:
                        continue
                    result = match_customer(
                        review_name    = review.get("reviewer_name", ""),
                        review_email   = review.get("reviewer_email", ""),
                        email_idx      = ctx["email_idx"],
                        phone_idx      = ctx["phone_idx"],
                        exact_name_idx = ctx["exact_name_idx"],
                        name_list      = ctx["name_list"],
                        review_text    = review.get("review_text", ""),
                    )
                    if result is not None:
                        row_idx_pd, match_type, confidence = result
                        hit = (sheet_name, int(row_idx_pd) + 2, match_type, confidence)
                        break

                if hit is None:
                    stats["unmatched"] += 1
                    unmatched_rows_log.append(review)
                    print(
                        f"  ✗ No match: '{review.get('reviewer_name', '?')}' "
                        f"<{review.get('reviewer_email', '')}>"
                    )
                    continue

                sheet_name, sheet_row, match_type, confidence = hit
                ctx = sheet_ctx[sheet_name]

                review["_match_type"] = match_type
                review["_match_conf"] = confidence
                review["_sheet_row"]  = sheet_row
                review["_sheet_name"] = sheet_name
                matched_rows_log.append(review)
                stats["matched"] += 1
                # Per-sheet match counter (proves both 4S + Franchise are scanned)
                if sheet_name in stats["by_sheet"]:
                    stats["by_sheet"][sheet_name]["matched"] += 1

                # Idempotency: only queue a write if the rating differs
                if ctx["existing"].get(sheet_row, "") != str(rating):
                    ctx["pending_cells"].append(
                        gspread.Cell(row=sheet_row, col=ctx["review_col_idx"],
                                     value=str(rating))
                    )

                _snippet = (review.get("review_text", "") or "").strip().replace("\n", " ")
                if len(_snippet) > 80:
                    _snippet = _snippet[:80] + "…"
                print(
                    f"  ✓ {rating}★ '{review.get('reviewer_name', '?')}' → "
                    f"'{sheet_name}' row {sheet_row} "
                    f"(match={match_type}, conf={confidence})"
                    + (f"  text: \"{_snippet}\"" if _snippet else "")
                )

            except Exception as exc:
                stats["errors"] += 1
                print(f"  ⚠️  Error processing review: {exc}")

        # ── One batch write per sheet that had pending updates ──────────────
        for sheet_name, ctx in sheet_ctx.items():
            if not ctx or not ctx["pending_cells"]:
                continue
            ctx["ws"].update_cells(ctx["pending_cells"], value_input_option="RAW")
            _n_written = len(ctx["pending_cells"])
            stats["written"] += _n_written
            if sheet_name in stats["by_sheet"]:
                stats["by_sheet"][sheet_name]["written"] += _n_written
            print(f"  → Wrote {_n_written} rating(s) to '{sheet_name}'.")
        if stats["written"] == 0:
            print("  → No new ratings to write (already up-to-date or no matches).")

        # Audit log
        _log_review_details(client, spreadsheet_id, matched_rows_log, unmatched_rows_log)

    except Exception as exc:
        stats["errors"]  += 1
        stats["status"]   = f"error: {exc}"
        print(f"  ❌ Sheet update failed: {exc}")
        traceback.print_exc()

    return stats


# ═════════════════════════════════════════════════════════════════════════════
# 7.  PUBLIC ENTRY POINTS
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_review_source() -> str:
    """
    Decide which API to call based on which secrets are configured.

    Priority order:
        1. "places"  if GOOGLE_PLACES_API_KEY + GOOGLE_PLACE_ID are set
                     (free, always available — the recommended path)
        2. "gmb_v4"  if GMB_REFRESH_TOKEN + GMB_LOCATION info are set
                     (requires Google allow-listing of the legacy GMB API;
                      gives full review history when available)
        3. "none"    otherwise

    """
    places_key = _load_secret("GOOGLE_PLACES_API_KEY")
    place_id   = _load_secret("GOOGLE_PLACE_ID")
    if places_key and place_id:
        return "places"

    refresh_tok = _load_secret("GMB_REFRESH_TOKEN")
    static_tok  = _load_secret("GMB_ACCESS_TOKEN") or _load_secret("GOOGLE_ACCESS_TOKEN")
    has_loc     = bool(_load_secret("GMB_LOCATION_PATH") or
                       (_load_secret("GMB_ACCOUNT_ID") and
                        (_load_secret("GMB_LOCATION_ID") or _load_secret("GOOGLE_LOCATION_ID"))))
    if (refresh_tok or static_tok) and has_loc:
        return "gmb_v4"

    return "none"


def fetch_and_update_reviews_4s(
    access_token:   Optional[str] = None,
    location_id:    Optional[str] = None,    # may be either bare id or full path
    spreadsheet_id: Optional[str] = None,
    sales_df:       Optional[pd.DataFrame] = None,
    triggered_by:   str = "scheduler",
) -> Dict:
    """
    Top-level entry point used by the scheduled job and the Streamlit
    'Fetch Reviews Now' button.

    Auto-selects the review source based on configured secrets:
        • Google Places API (preferred — free, no allow-listing)
        • Google My Business v4 (only if allow-listed by Google)

    All four parameters are optional — when omitted, we resolve everything
    from secrets / env / sheets so this 'just works' from either context.
    """
    ts = lambda: datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    print(f"[{ts()}] ▶ Google Reviews fetch started (triggered_by={triggered_by})")

    # ── Resolve which source we'll use ───────────────────────────────────────
    source = _resolve_review_source()
    print(f"  → Review source: {source}")

    def _fail(msg: str) -> Dict:
        print(f"  ❌ {msg}")
        s = {"total_reviews": 0, "matched": 0, "unmatched": 0,
             "errors": 1, "written": 0, "status": msg}
        try:
            client = _get_sheets_client()
            sid = spreadsheet_id
            if sid is None:
                from services.sheets import SPREADSHEET_ID
                sid = SPREADSHEET_ID
            _log_sync_run(client, sid, s, triggered_by)
        except Exception:
            pass
        return s

    if source == "none":
        return _fail(
            "Auth failure: no review source configured. "
            "Set GOOGLE_PLACES_API_KEY + GOOGLE_PLACE_ID (recommended) "
            "or GMB_REFRESH_TOKEN + GMB_ACCOUNT_ID + GMB_LOCATION_ID."
        )

    if spreadsheet_id is None:
        from services.sheets import SPREADSHEET_ID  # late import to avoid cycles
        spreadsheet_id = SPREADSHEET_ID

    if sales_df is None:
        try:
            from services.sheets import get_df  # late import
            sales_df = get_df(SHEET_CONFIG["4S_SALES_SHEET"])
        except Exception as exc:
            return _fail(f"Could not load 4S Sales sheet: {exc}")

    if sales_df is None or sales_df.empty:
        print("  ⚠️  Sales DataFrame is empty — but the per-sheet matcher will still scan SHEET_DETAILS sheets directly.")
        sales_df = pd.DataFrame()

    # ── Fetch reviews from whichever source is configured ────────────────────
    try:
        if source == "places":
            api_key  = _load_secret("GOOGLE_PLACES_API_KEY")
            place_id = _load_secret("GOOGLE_PLACE_ID")
            reviews  = fetch_google_reviews_via_places(api_key, place_id)
            print(f"  → Fetched {len(reviews)} review(s) from Google Places API")
        else:   # gmb_v4
            try:
                token = (access_token or "").strip() or get_gmb_access_token()
            except Exception as exc:
                return _fail(f"Auth failure: {exc}")

            if location_id and "/" in location_id:
                location_path = location_id.lstrip("/")
            else:
                try:
                    location_path = get_gmb_location_path()
                except Exception as exc:
                    return _fail(f"Location resolve failure: {exc}")

            reviews = fetch_google_reviews(token, location_path)
            print(f"  → Fetched {len(reviews)} review(s) from GMB v4 API")

    except Exception as exc:
        traceback.print_exc()
        return _fail(f"Fetch failure: {exc}")

    # ── Match + write (across every sales sheet in SHEET_DETAILS) ───────────
    stats = process_and_update_reviews(reviews, spreadsheet_id, sales_df)

    # ── Persist a sync-log row (used by UI to show last-synced time) ────────
    try:
        client = _get_sheets_client()
        _log_sync_run(client, spreadsheet_id, stats, triggered_by)
    except Exception as exc:
        print(f"  ⚠️  Sync-log write failed (non-fatal): {exc}")

    print(
        f"[{ts()}] ✅ Done — Total: {stats.get('total_reviews', 0)}  "
        f"Matched: {stats.get('matched', 0)}  "
        f"Unmatched: {stats.get('unmatched', 0)}  "
        f"Written: {stats.get('written', 0)}  "
        f"Errors: {stats.get('errors', 0)}"
    )
    return stats


def fetch_and_update_reviews_now() -> Dict:
    """
    Convenience wrapper for the Streamlit 'Fetch Now' button. Resolves
    everything from secrets and the configured sheet, then runs the same
    pipeline as the scheduler.
    """
    return fetch_and_update_reviews_4s(triggered_by="manual_streamlit")
