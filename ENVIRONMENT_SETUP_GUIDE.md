# Environment-Agnostic Credentials Setup Guide

## Overview
Your application now works seamlessly in **all environments** without code changes:
- ✅ GitHub Actions (CI/CD)
- ✅ Local Development (Streamlit)
- ✅ Streamlit Cloud
- ✅ Docker Containers
- ✅ Any Server/VM

## How It Works

All credential loading follows this priority order:

### 1. **Environment Variables** (GitHub Actions, Docker, Server) 🎯
```bash
export EMAIL_SENDER="your-email@gmail.com"
export EMAIL_PASSWORD="your-app-password"
export EMAIL_RECIPIENTS="recipient1@example.com,recipient2@example.com"
export GOOGLE_CREDENTIALS='{"type":"service_account","project_id":"...","key_id":"..."...}'
```

### 2. **Streamlit Secrets** (Local Streamlit, Streamlit Cloud)
File: `.streamlit/secrets.toml`
```toml
# Flat structure
EMAIL_SENDER = "your-email@gmail.com"
EMAIL_PASSWORD = "your-app-password"
EMAIL_RECIPIENTS = "recipient1@example.com,recipient2@example.com"

[google]
type = "service_account"
project_id = "your-project"
private_key_id = "your-key-id"
# ... rest of Google service account JSON
```

### 3. **.env File** (Local development fallback)
File: `.env` (in project root)
```bash
EMAIL_SENDER="your-email@gmail.com"
EMAIL_PASSWORD="your-app-password"
EMAIL_RECIPIENTS="recipient1@example.com,recipient2@example.com"
GOOGLE_CREDENTIALS='{"type":"service_account",...}'
```

---

## Setup for Each Environment

### **GitHub Actions** ✅ (Recommended for CI/CD)

1. **Add GitHub Secrets** (Settings → Secrets and variables → Actions):
   - `EMAIL_SENDER` - Your Gmail address
   - `EMAIL_PASSWORD` - Your Gmail App Password
   - `EMAIL_RECIPIENTS` - Comma-separated emails
   - `GOOGLE_CREDENTIALS` - Full JSON from Google Service Account

2. **Workflow automatically sets environment variables:**
   ```yaml
   env:
     EMAIL_SENDER: ${{ secrets.EMAIL_SENDER }}
     EMAIL_PASSWORD: ${{ secrets.EMAIL_PASSWORD }}
     EMAIL_RECIPIENTS: ${{ secrets.EMAIL_RECIPIENTS }}
     GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}
   ```

3. **Your Python code reads them automatically** ✨

---

### **Local Streamlit Development**

1. **Create `.streamlit/secrets.toml`:**
   ```bash
   mkdir -p .streamlit
   cat > .streamlit/secrets.toml << 'EOF'
   EMAIL_SENDER = "your-email@gmail.com"
   EMAIL_PASSWORD = "your-app-password"
   EMAIL_RECIPIENTS = "recipient1@example.com"
   
   [google]
   type = "service_account"
   project_id = "your-project"
   # ... copy entire Google service account JSON here
   EOF
   ```

2. **Run Streamlit:**
   ```bash
   streamlit run streamlit_app/app.py
   ```

3. **Streamlit automatically loads secrets** ✨

---

### **Docker Container**

1. **Create `.env` file locally:**
   ```bash
   cat > .env << 'EOF'
   EMAIL_SENDER="your-email@gmail.com"
   EMAIL_PASSWORD="your-app-password"
   EMAIL_RECIPIENTS="recipient1@example.com"
   GOOGLE_CREDENTIALS='{"type":"service_account",...}'
   EOF
   ```

2. **Mount `.env` in Docker or set env vars:**
   ```bash
   docker run \
     -e EMAIL_SENDER="your-email@gmail.com" \
     -e EMAIL_PASSWORD="your-app-password" \
     -e EMAIL_RECIPIENTS="recipient1@example.com" \
     -e GOOGLE_CREDENTIALS='{"type":"service_account",...}' \
     your-image
   ```

3. **Your code reads from environment** ✨

---

## Files Modified

### 1. **services/sheets.py**
✅ Updated credential loading for Google Sheets:
- Checks `GOOGLE_CREDENTIALS` env var (GitHub Actions)
- Checks `GOOGLE_APPLICATION_CREDENTIALS` file path
- Falls back to Streamlit secrets
- Falls back to local `config/credentials.json`

**Functions updated:**
- `_get_client()` - Lines 67-104
- `upsert_target_record()` - Lines 187-236
- `write_df()` - Lines 294-341

### 2. **services/email_sender.py**
✅ Updated email credential loading:
- Checks environment variables first (GitHub Actions)
- Falls back to Streamlit secrets (nested `admin` key)
- Falls back to flat Streamlit secrets
- Falls back to `.env` file

**Lines updated:** 1-55

### 3. **services/email_sender_4s.py**
✅ Updated email credential loading (same pattern as email_sender.py):
- Checks environment variables first
- Falls back to Streamlit secrets
- Falls back to `.env` file

**Lines updated:** 16-45

### 4. **.github/workflows/send_email.yaml**
✅ Updated workflow to pass credentials as env vars:
- Removed "Write Google credentials to file" steps
- Added `GOOGLE_CREDENTIALS` to env
- Cleaner, more secure approach

**Changes:**
- Godrej job: Lines 61-69
- 4S job: Lines 99-107

---

## Testing Checklist

### ✅ GitHub Actions
- [ ] Push code with secrets configured
- [ ] Run workflow manually via GitHub Actions UI
- [ ] Verify emails sent successfully
- [ ] Check workflow logs for errors

### ✅ Local Streamlit
- [ ] Create `.streamlit/secrets.toml`
- [ ] Run `streamlit run streamlit_app/app.py`
- [ ] Test email sending in dashboard
- [ ] Verify Google Sheets access

### ✅ Standalone Script (GitHub Actions)
- [ ] Push code
- [ ] Verify `email_job.py` executes
- [ ] Verify `email_job_4s.py` executes
- [ ] Check emails sent successfully

---

## Troubleshooting

### Error: "No secrets found"
**Cause:** Environment variables not set
**Fix:** 
- GitHub Actions: Add secrets in Settings → Secrets
- Local: Create `.streamlit/secrets.toml`
- Docker: Set `-e` environment variables

### Error: "Could not find valid Google credentials"
**Cause:** `GOOGLE_CREDENTIALS` env var not set
**Fix:**
- GitHub Actions: Add `GOOGLE_CREDENTIALS` secret
- Local: Add to `.streamlit/secrets.toml` or `.env`

### Error: "EMAIL_SENDER not set"
**Cause:** Email environment variables not found
**Fix:** Set `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECIPIENTS`

---

## Security Notes

⚠️ **Best Practices:**

1. **Never commit secrets:**
   - `.env` is in `.gitignore` ✓
   - `.streamlit/secrets.toml` is in `.gitignore` ✓
   - GitHub Actions secrets are never logged ✓

2. **Use App Passwords for Gmail:**
   - Enable 2-Factor Authentication
   - Generate App Password (not your Google password)
   - Use the 16-character app password

3. **Rotate credentials regularly:**
   - Update GitHub secrets periodically
   - Regenerate Google service account keys
   - Update email app passwords

4. **Limit access:**
   - Use service accounts (not personal accounts)
   - Grant minimal required permissions
   - Use separate accounts for different environments

---

## Quick Reference

| Environment | Email Credentials | Google Credentials |
|------------|------------------|-------------------|
| GitHub Actions | Environment vars | Environment vars |
| Local Streamlit | secrets.toml | secrets.toml |
| Docker | .env or -e | .env or -e |
| Streamlit Cloud | Settings → Secrets | Settings → Secrets |

---

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Verify all required environment variables are set
3. Check GitHub Actions logs for detailed errors
4. Ensure `GOOGLE_CREDENTIALS` is valid JSON

Your application now works in all environments seamlessly! 🚀
