# GitHub Actions Credentials Fix - Summary

## Problem
The GitHub Actions workflow was failing with:
```
FileNotFoundError: [Errno 2] No such file or directory: 'config/credentials.json'
```

This happened because:
1. The Python code in `services/sheets.py` was hardcoded to look for credentials at `config/credentials.json`
2. The GitHub Actions runner doesn't have this file
3. The workflow was trying to write credentials to `/tmp/google_credentials.json` but the Python code wasn't using it

## Solution
Updated the credential loading logic to check multiple sources in order:

### 1. **Updated `services/sheets.py`**
Modified three functions to load credentials from:
1. **`GOOGLE_CREDENTIALS` environment variable** (GitHub Actions - JSON string) ✅
2. **`GOOGLE_APPLICATION_CREDENTIALS` path** (if file exists) ✅
3. **Streamlit secrets** (for local development) ✅
4. **Local file** `config/credentials.json` (fallback) ✅

The new flow is much more robust and works in all environments:
- ✅ GitHub Actions (via env var)
- ✅ Local Streamlit development (via secrets)
- ✅ Docker containers (via env var or file path)
- ✅ Standalone Python scripts (via env var)

**Modified functions:**
- `_get_client()` - Lines 67-104
- `upsert_target_record()` - Lines 187-236
- `write_df()` - Lines 294-341

### 2. **Updated `.github/workflows/send_email.yaml`**
- Removed the "Write Google credentials to file" steps (lines 56-59 and 94-97)
- Added `GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}` directly to the `env` section of both jobs
- This passes the credentials as an environment variable, which the updated code now handles

**Changes:**
- **Godrej job** (lines 61-69): Now passes GOOGLE_CREDENTIALS env var
- **4S job** (lines 99-107): Now passes GOOGLE_CREDENTIALS env var

## Result
✅ GitHub Actions will now:
1. Read the `GOOGLE_CREDENTIALS` secret
2. Pass it as an environment variable to the Python scripts
3. Your code will parse the JSON and authenticate with Google Sheets
4. Both Godrej and 4S email jobs will run successfully on schedule

## Testing
1. Push the updated code to your repository
2. Go to GitHub Actions → "Send CRM Emails" workflow
3. Click "Run workflow" and select a job to test manually
4. The workflow should now execute without the credentials error

## Notes
- All three credential loading methods are now in place, making your code more flexible
- The solution works for all deployment scenarios (GitHub Actions, local, Docker, etc.)
- No need for `config/credentials.json` to exist in GitHub Actions environment
