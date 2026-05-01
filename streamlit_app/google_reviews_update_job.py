"""
streamlit_app/google_reviews_update_job.py
Scheduled job to fetch and update Google reviews daily at 10 PM IST.
Runs via GitHub Actions workflow.
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime
from services.google_reviews_service import fetch_and_update_reviews_4s
from services.sheets import fetch_4s_sales_data, load_spreadsheet_config

def main():
    """Main job entry point."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 🔄 Google Reviews Update Job Started")
    
    try:
        # Load configuration
        config = load_spreadsheet_config()
        spreadsheet_id = config.get('SPREADSHEET_ID')
        
        if not spreadsheet_id:
            raise ValueError("SPREADSHEET_ID not configured")
        
        # Fetch current 4S sales data
        sales_df = fetch_4s_sales_data(spreadsheet_id)
        print(f"  → Loaded {len(sales_df)} records from 4S Sales sheet")
        
        # Get Google Business Profile credentials
        # You'll need to set up OAuth2 token refresh in your system
        # For now, this uses an access token passed via environment
        access_token = os.getenv("GOOGLE_ACCESS_TOKEN")
        location_id = os.getenv("GOOGLE_LOCATION_ID")
        
        if not access_token or not location_id:
            print("⚠️  GOOGLE_ACCESS_TOKEN or GOOGLE_LOCATION_ID not set")
            print("  → Skipping review fetch. Configure these in GitHub secrets/env.")
            return
        
        # Fetch and update reviews
        stats = fetch_and_update_reviews_4s(
            access_token=access_token,
            location_id=location_id,
            spreadsheet_id=spreadsheet_id,
            sales_df=sales_df
        )
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Job completed successfully")
        print(f"  Summary: {stats}")
    
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ❌ Job failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()