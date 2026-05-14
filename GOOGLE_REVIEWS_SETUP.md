# Google Reviews Setup Guide

## Issue
Your CRM is missing Google Places API credentials. The reviews feature won't work until you configure one of these authentication methods.

---

## Option 1: Google Places API (RECOMMENDED ✅)

**Advantages:**
- Free (under $200/month credit from Google)
- No Google allow-listing needed
- Works immediately
- Simple to set up
- Supports up to 5 recent reviews per call

**Disadvantages:**
- Only fetches 5 most recent reviews per call
- Shows only newest reviews (sorted by date)

### Step 1: Get Your Google Places API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing one: `crm4sinteriors`)
3. Enable the **Places API**:
   - Search for "Places API" in the API Library
   - Click "Enable"
4. Go to **Credentials** → **Create Credentials** → **API Key**
5. Restrict the key to:
   - **Application restrictions**: HTTP referrers
   - **Add an HTTP referrer**: `localhost:*` (for local) and your Streamlit Cloud domain
   - **API restrictions**: Select "Places API"
6. Copy the API key

### Step 2: Get Your Google Place ID

1. Go to [Google Maps](https://maps.google.com/)
2. Search for your business: **4S Interiors Bhubaneswar**
3. When you find it, click the business name to open details
4. Look at the URL in your browser bar: `https://maps.google.com/?cid=PLACE_ID`
5. The long number is your **PLACE_ID** (e.g., `15234567890123456789`)

**Alternative method:**
1. Use [Google Places API Explorer](https://developers.google.com/maps/documentation/places/web-service/overview)
2. Search for your business by name/address
3. Find the `place_id` in the response

### Step 3: Update secrets.toml

Add these two lines to `.streamlit/secrets.toml`:

```toml
GOOGLE_PLACES_API_KEY = "AIzaSyD..."  # Your API key from Step 1
GOOGLE_PLACE_ID = "ChIJ1234567..."    # Your Place ID from Step 2
```

**Then restart the Streamlit app** (Ctrl+C and run again, or wait for auto-reload)

---

## Option 2: Google My Business v4 API (GMB)

**Advantages:**
- Fetches ALL reviews (full history)
- No review limit per call
- Shows complete review timeline

**Disadvantages:**
- Requires Google's explicit allow-listing
- Takes 1-2 weeks for Google approval
- More complex setup (OAuth flow)

### Step 1: Request GMB API Allow-Listing

1. Fill out [this Google form](https://support.google.com/business/contact/gmb_api_request) to request access
2. Wait 1-2 weeks for approval
3. Google will email you OAuth credentials

### Step 2: Generate OAuth Refresh Token

Once allow-listed, run this script:

```bash
python generate_gmb_refresh_token.py
```

This opens a browser. Log in with your Google account, grant permissions, and the script saves your refresh token.

### Step 3: Update secrets.toml

Add these to `.streamlit/secrets.toml`:

```toml
GMB_CLIENT_ID = "..."           # From OAuth credentials
GMB_CLIENT_SECRET = "..."       # From OAuth credentials
GMB_REFRESH_TOKEN = "..."       # Generated from script above
GMB_ACCOUNT_ID = "123456789"    # Your GMB account ID
GMB_LOCATION_ID = "987654321"   # Your GMB location ID
```

To find your account/location IDs:
1. Go to [Google My Business](https://www.google.com/business/)
2. Open your location
3. Click the three-dot menu → **Settings**
4. Look for "Account ID" and "Location ID"

---

## How the CRM Decides Which Method to Use

The CRM checks in this order:

1. **Places API** (if `GOOGLE_PLACES_API_KEY` + `GOOGLE_PLACE_ID` are set) ← PREFERRED
2. **GMB v4** (if `GMB_REFRESH_TOKEN` + location info are set)
3. **None** (error if neither is configured)

---

## Testing

Once you've added credentials and restarted the app:

1. Go to **Daily B2C Sales** page
2. Click **"Fetch Reviews Now"** button
3. You should see reviews start appearing
4. Check the sync log to see how many matched/unmatched

---

## Troubleshooting

### "Auth failure" Error
- Credentials not saved to `.streamlit/secrets.toml`
- Secrets need `EXACT` key names (case-sensitive)
- App wasn't restarted after adding secrets
- **Fix:** Add credentials, save, restart app (`Ctrl+C`, then run again)

### "Places API returned 403"
- API key is invalid or expired
- Places API not enabled in Google Cloud
- API key restrictions too strict
- **Fix:** Re-generate API key with correct restrictions

### "Invalid GOOGLE_PLACE_ID"
- Place ID copied incorrectly
- Business not found in Google Maps
- **Fix:** Search business on Google Maps again, copy exact ID from URL

### Reviews Aren't Matching
- Customer names in CRM don't match reviewer names exactly
- The matcher uses fuzzy matching (handles common variations)
- Check **REVIEW_DETAILS** sheet for unmatched reviews
- **Fix:** Manually review + update REVIEW column in 4S Sales sheet

---

## File Locations

- **Secrets config**: `.streamlit/secrets.toml`
- **Source code**: `streamlit_app/services/google_reviews_service.py`
- **Audit logs**: 
  - `REVIEW_SYNC_LOG` sheet (when each fetch ran)
  - `REVIEW_DETAILS` sheet (every review + match status)
  - `REVIEW_UNMATCHED` sheet (reviews that didn't match)

---

## Need Help?

See the inline comments in `google_reviews_service.py` for details on:
- How reviews are matched to CRM customers
- What each matching strategy does
- How idempotency prevents duplicate updates
