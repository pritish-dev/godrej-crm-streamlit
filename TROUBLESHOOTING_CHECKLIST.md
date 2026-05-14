# Google Reviews Troubleshooting Checklist

Use this checklist to diagnose and fix any Google reviews issues.

---

## 🔴 Error: "Auth failure"

### Checklist
- [ ] Added `GOOGLE_PLACES_API_KEY` to `.streamlit/secrets.toml`?
- [ ] Added `GOOGLE_PLACE_ID` to `.streamlit/secrets.toml`?
- [ ] Restarted the Streamlit app after adding secrets?
- [ ] API key is correct (no typos, full string)?
- [ ] Place ID is correct (no typos)?
- [ ] Secrets file path is correct: `.streamlit/secrets.toml`?

### Fix
```toml
# Make sure these are in .streamlit/secrets.toml
GOOGLE_PLACES_API_KEY = "AIzaSyD_..."
GOOGLE_PLACE_ID = "ChIJ..."
```

Then restart: `Ctrl+C` and run again

---

## 🔴 Error: "Places API returned 403"

### Causes & Fixes

| Cause | Fix |
|-------|-----|
| **API key doesn't have Places API enabled** | Go to Google Cloud → Enable "Places API" |
| **API key restrictions too strict** | Ensure "Places API" is in allowed APIs |
| **Invalid API key format** | Copy exact key from Google Cloud Console |
| **API key restricted to wrong referrer** | Add `localhost:*` and your Streamlit Cloud domain |

### Steps to Fix
1. Google Cloud Console → Select project `crm4sinteriors`
2. APIs & Services → Credentials
3. Click your API Key
4. Under "API restrictions", make sure "Places API" is selected
5. Under "Application restrictions", check referrer URLs
6. Regenerate key if needed and copy the exact string

---

## 🔴 Error: "Invalid GOOGLE_PLACE_ID"

### Checklist
- [ ] Searched for your business on Google Maps?
- [ ] Found the correct location: "4S Interiors Bhubaneswar"?
- [ ] Copied the `cid` value from URL exactly?
- [ ] No spaces or extra characters?

### Fix Steps
1. Go to [Google Maps](https://maps.google.com/)
2. Search: "4S Interiors Bhubaneswar"
3. Click the business listing
4. Look at the URL: `maps.google.com/?cid=**PLACE_ID**`
5. Copy the full `cid` value (usually 17-21 digits)
6. Paste into `secrets.toml`:
```toml
GOOGLE_PLACE_ID = "ChIJ1234567890..."
```

---

## 🔴 Error: "Reviews aren't showing up"

### Check #1: Is the review source configured?
```bash
# In Streamlit app → Daily B2C Sales page
# Look for: "Review source: places" or "Review source: gmb_v4"
# If it says "Review source: none", credentials are missing
```

### Check #2: Does your business have reviews?
1. Go to [Google Maps](https://maps.google.com/)
2. Search "4S Interiors Bhubaneswar"
3. Check if there are any review ratings showing
4. If no reviews exist, nothing to fetch

### Check #3: Are reviews being matched?
1. Click **"Fetch Reviews Now"** button
2. Check the status message for:
   - Total reviews found
   - Matched count
   - Unmatched count

### If reviews aren't matching customers:
- Customer names in CRM must be similar to reviewer names
- The matcher uses fuzzy matching (handles variations)
- Exact email/phone match has highest priority
- Check `REVIEW_DETAILS` sheet for unmatched reviews

---

## 🔴 Error: "Could not read sync log"

### Causes
- `REVIEW_SYNC_LOG` sheet doesn't exist yet
- First-time setup (sheet will be created on first fetch)

### Fix
1. Click **"Fetch Reviews Now"** button
2. The sheet will be auto-created
3. Run again

---

## 🟡 Warning: Only 5 reviews showing

This is **normal** for Google Places API (it caps at 5 most-recent reviews per call).

### If you need full history:
Switch to GMB v4 API (see GOOGLE_REVIEWS_SETUP.md → Option 2)

---

## 🟡 Warning: "Auth failure: no review source configured"

### Causes
- Neither Places API nor GMB v4 credentials set
- OR both sets of credentials are incomplete

### Fix
Choose ONE path:

**Path A: Google Places API (Recommended)**
```toml
GOOGLE_PLACES_API_KEY = "AIzaSyD_..."
GOOGLE_PLACE_ID = "ChIJ..."
```

**Path B: Google My Business v4 API (Full history)**
```toml
GMB_CLIENT_ID = "..."
GMB_CLIENT_SECRET = "..."
GMB_REFRESH_TOKEN = "..."
GMB_ACCOUNT_ID = "123456789"
GMB_LOCATION_ID = "987654321"
```

Then restart the app.

---

## ✅ Verification Checklist

Once you think everything is fixed, verify with this:

- [ ] Edit `.streamlit/secrets.toml` and confirm credentials are there
- [ ] Restart the Streamlit app
- [ ] Go to **Daily B2C Sales** page
- [ ] Check the review source line: should say "places" or "gmb_v4"
- [ ] Click **"Fetch Reviews Now"** button
- [ ] See status message with review count (not an error)
- [ ] Check `REVIEW_SYNC_LOG` sheet for the fetch record

---

## 📞 Still Having Issues?

1. **Check the logs:**
   - See what the exact error message is
   - Copy the full message
   - Check this file for that specific error

2. **Read the full setup guide:**
   - GOOGLE_REVIEWS_SETUP.md has detailed instructions
   - QUICK_FIX.md has a 5-minute version

3. **Check source code comments:**
   - `streamlit_app/services/google_reviews_service.py`
   - Has detailed comments explaining each step

4. **Verify API is enabled:**
   ```
   Google Cloud Console → APIs & Services → Library
   Search: "Places API"
   Should show "Enabled"
   ```

5. **Test with Places API first:**
   - Easier to debug than GMB v4
   - No allow-listing needed
   - Just needs API key + Place ID

---

## 🔐 Security Reminders

✅ Recommended:
- Use Google Places API (free, simple)
- Keep API key restricted to Places API only
- Use domain/referrer restrictions on API key

❌ Don't do this:
- Commit `secrets.toml` to GitHub
- Share credentials via email
- Use global/unrestricted API keys

---

Last Updated: 2026-05-14
See GOOGLE_REVIEWS_SETUP.md for comprehensive guide
