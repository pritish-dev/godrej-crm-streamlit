"""
services/google_reviews_service.py
Google Business Profile Reviews Integration for 4S Interiors CRM.
Fetches reviews, matches customers, calculates scores, and updates Google Sheets.
"""

import os
import json
import pandas as pd
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
import gspread
from difflib import SequenceMatcher
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
import requests

# ── Constants ────────────────────────────────────────────────────────────────

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
GOOGLE_BUSINESS_API_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"

# Sheet configuration
SHEET_CONFIG = {
    '4S_SALES_SHEET': 'FY 2026-27 4S Sales',
    '4S_REVIEW_COLUMN': 'REVIEW RATING'  # New column to add/update
}

# Review scoring system
REVIEW_SCORE = {
    5: 1,   # 5-star review
    4: 1,   # 4-star review
    3: -1,  # 3-star review
    2: -1,  # 2-star review
    1: -1,  # 1-star review
    0: 0    # No review
}

# ── Credential Loading ────────────────────────────────────────────────────────

def _load_google_credentials():
    """Load Google credentials from environment/secrets."""
    try:
        # Try environment variable (GitHub Actions)
        creds_json = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if creds_json:
            creds_dict = json.loads(creds_json)
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        pass
    
    try:
        # Try Streamlit secrets (local development)
        import streamlit as st
        try:
            creds_dict = st.secrets["admin"]["GOOGLE_CREDENTIALS"]
            if isinstance(creds_dict, str):
                creds_dict = json.loads(creds_dict)
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        except Exception:
            creds_dict = st.secrets["GOOGLE_CREDENTIALS"]
            if isinstance(creds_dict, str):
                creds_dict = json.loads(creds_dict)
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        pass
    
    try:
        # Try .env file (local development)
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        creds_json = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if creds_json:
            creds_dict = json.loads(creds_json)
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        pass
    
    raise ValueError("GOOGLE_CREDENTIALS not found in environment, Streamlit secrets, or .env file")


def _get_sheets_client():
    """Get authenticated gspread client."""
    credentials = _load_google_credentials()
    return gspread.authorize(credentials)


# ── Customer Matching Logic ────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Normalize phone number for matching (digits only, last 10)."""
    if not phone:
        return ""
    digits = ''.join(c for c in str(phone) if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _normalize_email(email: str) -> str:
    """Normalize email for matching (lowercase)."""
    return str(email).lower().strip() if email else ""


def _normalize_name(name: str) -> str:
    """Normalize name for matching (lowercase, no extra spaces)."""
    if not name:
        return ""
    return ' '.join(str(name).lower().strip().split())


def _string_similarity(a: str, b: str) -> float:
    """Calculate string similarity ratio (0-1)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match_customer(
    review_customer_name: str,
    review_customer_email: str,
    review_customer_phone: str,
    sales_df: pd.DataFrame,
    name_col: str = "CUSTOMER NAME",
    email_col: str = "EMAIL",
    phone_col: str = "CONTACT NUMBER"
) -> Optional[Tuple[int, str]]:
    """
    Match a review customer to a sales record using phone→email→name priority.
    Returns: (row_index, match_type) or None if no match found
    match_type: 'phone', 'email', 'name'
    """
    
    # Normalize review data
    rev_phone = _normalize_phone(review_customer_phone)
    rev_email = _normalize_email(review_customer_email)
    rev_name = _normalize_name(review_customer_name)
    
    if not rev_phone and not rev_email and not rev_name:
        return None
    
    # Priority 1: Match by phone (exact)
    if rev_phone:
        for idx, row in sales_df.iterrows():
            if phone_col in sales_df.columns:
                sales_phone = _normalize_phone(row.get(phone_col, ""))
                if rev_phone and sales_phone and rev_phone == sales_phone:
                    return (idx, 'phone')
    
    # Priority 2: Match by email (exact)
    if rev_email:
        for idx, row in sales_df.iterrows():
            if email_col in sales_df.columns:
                sales_email = _normalize_email(row.get(email_col, ""))
                if rev_email and sales_email and rev_email == sales_email:
                    return (idx, 'email')
    
    # Priority 3: Match by name (fuzzy, >80% similarity)
    if rev_name:
        best_match = None
        best_score = 0.8
        for idx, row in sales_df.iterrows():
            if name_col in sales_df.columns:
                sales_name = _normalize_name(row.get(name_col, ""))
                if sales_name:
                    score = _string_similarity(rev_name, sales_name)
                    if score > best_score:
                        best_score = score
                        best_match = (idx, 'name')
        if best_match:
            return best_match
    
    return None


# ── Google Business Profile API Integration ────────────────────────────────────

def fetch_google_reviews(access_token: str, location_id: str) -> List[Dict]:
    """
    Fetch reviews from Google Business Profile API.
    access_token: OAuth2 access token with Google My Business scope
    location_id: Google Business Profile location ID (format: "accounts/{accountId}/locations/{locationId}")
    
    Returns: List of review dicts with keys: rating, reviewer_name, reviewer_email, review_date, review_text
    """
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Fetch reviews
        url = f"{GOOGLE_BUSINESS_API_BASE}/{location_id}/reviews"
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            print(f"Error fetching reviews: {response.status_code} - {response.text}")
            return []
        
        data = response.json()
        reviews = []
        
        for review in data.get('reviews', []):
            reviews.append({
                'rating': review.get('starRating', 0),
                'reviewer_name': review.get('reviewer', {}).get('displayName', 'Unknown'),
                'reviewer_email': review.get('reviewer', {}).get('emailAddress', ''),
                'review_date': review.get('createTime', ''),
                'review_text': review.get('comment', '')
            })
        
        return reviews
    
    except Exception as e:
        print(f"Exception fetching Google reviews: {e}")
        return []


# ── Review Processing & Sheet Update ────────────────────────────────────────

def process_and_update_reviews(
    reviews: List[Dict],
    spreadsheet_id: str,
    sales_df: pd.DataFrame
) -> Dict:
    """
    Process fetched reviews, match customers, calculate scores, and update sheet.
    Returns: Summary dict with matched/unmatched/error counts
    """
    
    try:
        client = _get_sheets_client()
        sheet = client.open_by_key(spreadsheet_id)
        sales_sheet = sheet.worksheet(SHEET_CONFIG['4S_SALES_SHEET'])
        
        # Get current sheet data
        all_rows = sales_sheet.get_all_values()
        headers = all_rows[0] if all_rows else []
        
        # Ensure REVIEW RATING column exists
        if SHEET_CONFIG['4S_REVIEW_COLUMN'] not in headers:
            headers.append(SHEET_CONFIG['4S_REVIEW_COLUMN'])
            sales_sheet.insert_rows([headers], 1)
        
        review_col_idx = headers.index(SHEET_CONFIG['4S_REVIEW_COLUMN']) + 1  # gspread uses 1-indexed
        name_col_idx = headers.index('CUSTOMER NAME') + 1 if 'CUSTOMER NAME' in headers else None
        phone_col_idx = headers.index('CONTACT NUMBER') + 1 if 'CONTACT NUMBER' in headers else None
        email_col_idx = headers.index('EMAIL') + 1 if 'EMAIL' in headers else None
        date_col_idx = headers.index('ORDER DATE') + 1 if 'ORDER DATE' in headers else None
        
        stats = {
            'total_reviews': len(reviews),
            'matched': 0,
            'unmatched': 0,
            'errors': 0
        }
        
        today = date.today()
        today_str = today.strftime('%d-%b-%Y').upper()
        
        # Process each review
        for review in reviews:
            try:
                rating = review.get('rating', 0)
                
                # Match customer
                match_result = match_customer(
                    review_customer_name=review.get('reviewer_name', ''),
                    review_customer_email=review.get('reviewer_email', ''),
                    review_customer_phone=review.get('reviewer_phone', ''),  # Adjust if API returns phone
                    sales_df=sales_df,
                    name_col='CUSTOMER NAME',
                    email_col='EMAIL',
                    phone_col='CONTACT NUMBER'
                )
                
                if match_result:
                    row_idx, match_type = match_result
                    review_score = REVIEW_SCORE.get(rating, 0)
                    
                    # Update sheet
                    # Row index is for dataframe (0-indexed), but gspread is 1-indexed
                    # Add 2 to account for header row and 0-indexing
                    sheet_row = row_idx + 2
                    sales_sheet.update_cell(sheet_row, review_col_idx, str(review_score))
                    
                    stats['matched'] += 1
                    print(f"✓ Matched review ({rating}★) to customer at row {sheet_row} via {match_type}")
                
                else:
                    stats['unmatched'] += 1
                    print(f"✗ Could not match review: {review.get('reviewer_name', 'Unknown')}")
            
            except Exception as e:
                stats['errors'] += 1
                print(f"Error processing review: {e}")
        
        return stats
    
    except Exception as e:
        print(f"Error updating sheet: {e}")
        return {'total_reviews': len(reviews), 'matched': 0, 'unmatched': len(reviews), 'errors': 1}


# ── Main Entry Point ────────────────────────────────────────────────────────

def fetch_and_update_reviews_4s(
    access_token: str,
    location_id: str,
    spreadsheet_id: str,
    sales_df: pd.DataFrame
) -> Dict:
    """
    Main function: Fetch reviews from Google Business Profile and update 4S sheet.
    
    Args:
        access_token: OAuth2 access token
        location_id: Google Business Profile location ID
        spreadsheet_id: Google Sheet ID containing sales data
        sales_df: DataFrame of current sales data
    
    Returns: Summary statistics
    """
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Starting Google Reviews fetch for 4S Interiors...")
    
    # Fetch reviews
    reviews = fetch_google_reviews(access_token, location_id)
    print(f"  → Fetched {len(reviews)} reviews from Google Business Profile")
    
    # Process and update
    stats = process_and_update_reviews(reviews, spreadsheet_id, sales_df)
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Review update complete")
    print(f"  → Matched: {stats['matched']}, Unmatched: {stats['unmatched']}, Errors: {stats['errors']}")
    
    return stats