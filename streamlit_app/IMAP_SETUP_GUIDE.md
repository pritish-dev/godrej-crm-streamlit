# 📧 Gmail IMAP Setup Guide - Lead Auto-Import

## Overview
Automated lead import from `4sinteriorsbbsr@gmail.com` emails with "Lead" in the subject.

---

## What's Already Implemented

✅ **IMAP Email Reader** - `services/imap_lead_import.py`  
✅ **Scheduled Job** - `lead_email_import_job.py`  
✅ **Credential Loading** - Uses same pattern as email_sender.py  
✅ **Lead Import** - Auto-creates leads in LEADS sheet  

---

## What You Need to Do

### Step 1: Generate Gmail App Password

**For Gmail Account:** `4sinteriorsbbsr@gmail.com`

#### On Your Computer:
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Look for **"2-Step Verification"**
   - If not enabled: Enable it first
3. Go to **"App passwords"** (if you don't see it, 2FA might not be enabled)
4. Select:
   - **App:** Mail
   - **Device:** Windows Computer / Mac / Linux
5. Google generates a **16-character password**
   - Example: `abcd efgh ijkl mnop` (without spaces)

#### Copy the Password
```
Example App Password:
abcdefghijklmnop
```

---

### Step 2: Add to GitHub Secrets

The system uses the same EMAIL_SENDER and EMAIL_PASSWORD you already have set up!

**What's already there:**
```
EMAIL_SENDER: 4sinteriorsbbsr@gmail.com
EMAIL_PASSWORD: [your-app-password-here]
EMAIL_RECIPIENTS: [where to send reports]
```

**If not already configured:**

1. Go to GitHub Repository Settings
2. Click **"Secrets and variables"** → **"Actions"**
3. Click **"New repository secret"**

Add these (if missing):
```
NAME: EMAIL_SENDER
VALUE: 4sinteriorsbbsr@gmail.com

NAME: EMAIL_PASSWORD
VALUE: [paste-the-16-character-app-password]

NAME: EMAIL_RECIPIENTS
VALUE: your-email@gmail.com
```

---

### Step 3: Update GitHub Actions Workflow

Add the scheduled email import job to `.github/workflows/send_email.yaml`:

```yaml
  lead-email-import:
    runs-on: ubuntu-latest
    if: |
      github.event_name == 'schedule' || 
      github.event.inputs.manual_job == 'lead_email_import'
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Import leads from Gmail
        env:
          EMAIL_SENDER: ${{ secrets.EMAIL_SENDER }}
          EMAIL_PASSWORD: ${{ secrets.EMAIL_PASSWORD }}
          GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}
        run: python lead_email_import_job.py
```

Add to the workflow's `schedule` section:
```yaml
  schedule:
    # ... existing schedules ...
    # Lead email import - Every 30 minutes
    - cron: '*/30 * * * *'  # Every 30 minutes UTC
```

---

### Step 4: Test the Setup

#### Local Test (Before Deploying):

1. **Set environment variables locally:**
```bash
export EMAIL_SENDER="4sinteriorsbbsr@gmail.com"
export EMAIL_PASSWORD="your-app-password"
export GOOGLE_CREDENTIALS='...'  # Your existing creds
```

2. **Run the import job:**
```bash
python lead_email_import_job.py
```

3. **Expected output:**
```
======================================================================
🔍 Starting Lead Email Import Process
📧 Email: 4sinteriorsbbsr@gmail.com
======================================================================
Found 2 unread emails with 'Lead' in subject
✅ Lead 'Aparajeeta Tripathy' imported successfully
✅ Lead 'Rahul Sharma' imported successfully

✅ Successfully imported 2 leads from email
======================================================================
```

#### GitHub Actions Test:

1. Go to GitHub Repository → **Actions** tab
2. Select **"Send Emails"** workflow
3. Click **"Run workflow"** → **"Run workflow"**
4. Select **"lead_email_import"** from dropdown
5. Click **"Run workflow"**

**Check results:**
- Look for green ✅ check mark
- Click on job to view logs
- Should see imported lead count

---

## How It Works

### Email Check Process

1. **IMAP Connection** (every 30 minutes)
   ```
   Gmail (imap.gmail.com:993)
   ↓
   Authentication (EMAIL_SENDER + EMAIL_PASSWORD)
   ↓
   INBOX selection
   ↓
   Search: UNSEEN + SUBJECT "Lead"
   ```

2. **Email Parsing**
   ```
   Extract from email body:
   - Lead name: "Lead Name" → Aparajeeta Tripathy
   - Assigned to: Queue - NAME → SUBRAT KUMAR SENAPATI
   - Salesforce URL: https://...
   - Email: [if present]
   - Phone: [if present]
   ```

3. **Lead Creation**
   ```
   Create in LEADS sheet:
   - Lead ID: Auto-increment
   - Lead Name: From email
   - Status: 🟢 New
   - Source: Email (OneCRM)
   - Assigned To: From email
   - Follow-up Date: Tomorrow
   ```

4. **Mark as Read**
   ```
   Email marked as read in Gmail
   → Won't be imported again
   ```

---

## Email Format Expected

The system expects emails in this format:

```
FROM: oneCRM@company.com
SUBJECT: Lead Aparajeeta Tripathy is assigned to you

BODY:
Hi,
The lead "Aparajeeta Tripathy" is moved to your Queue - SUBRAT KUMAR SENAPATI. 
You may click on the link to view details - https://gnb.my.site.com/gbpartners/00QOW00000jskiH
Thanks,
Godrej & Boyce
```

### Regex Patterns Used for Parsing

**Lead Name:**
```regex
lead\s+"([^"]+)"
```
Looks for: `lead "name"` → extracts name

**Assigned To:**
```regex
Queue\s*[-:]?\s*([A-Z][A-Z\s]+?)(?:\.|,|$)
```
Looks for: `Queue - NAME` → extracts name

**Salesforce URL:**
```regex
https?://[^\s\)]+
```
Looks for: Any valid HTTP(S) URL

---

## Troubleshooting

### Issue: "Failed to connect to Gmail"
**Possible causes:**
- App password is wrong
- 2FA not enabled
- EMAIL_PASSWORD secret not set
- Wrong email format in EMAIL_SENDER

**Solution:**
1. Verify app password is correct (copy from Google account)
2. Ensure 2FA is enabled on account
3. Check GitHub secrets are set correctly
4. Run local test to verify credentials work

### Issue: "No unread emails found"
**Possible causes:**
- No emails with "Lead" in subject
- All emails already read
- IMAP search issue

**Solution:**
1. Send test email to 4sinteriorsbbsr@gmail.com with "Lead" in subject
2. Wait 1-2 minutes
3. Run job again
4. Check email is marked unread in Gmail

### Issue: "Email parsed but lead not created"
**Possible causes:**
- Lead name couldn't be extracted
- Google Sheets write permission issue
- Invalid data format

**Solution:**
1. Check email contains lead name in `"quotes"`
2. Verify GOOGLE_CREDENTIALS secret is set
3. Check LEADS sheet exists in Google Sheets
4. Manually create test lead to verify sheets connection

### Issue: "Lead created but with wrong data"
**Possible causes:**
- Email format doesn't match expected pattern
- Parsing regex didn't work
- Multiple leads in one email

**Solution:**
1. Check email format matches examples
2. Ensure "Queue - NAME" pattern is exact
3. Test with single lead per email
4. Check parsing patterns in `parse_email_body()`

---

## Monitoring & Logging

### Check Import Status

**In GitHub Actions:**
1. Repository → Actions tab
2. Find "Send Emails" workflow
3. Click latest run
4. Expand "Import leads from Gmail" job
5. View full logs

**Output to look for:**
```
✅ Successfully imported 2 leads from email
```

### Manual Testing Logs

When you run locally:
```bash
python lead_email_import_job.py
```

Output shows:
- Number of emails found
- Lead names imported
- Any errors encountered

---

## Scheduled Execution

### How Often Does It Run?

**Frequency:** Every 30 minutes (UTC)

**Cron Expression:** `*/30 * * * *`

**Actual Times:** 
- 00:00, 00:30, 01:00, 01:30, ... 23:30 UTC

**IST Time:** Add 5.5 hours
- 5:30 AM, 6:00 AM, 6:30 AM, ... IST

### Adjusting Frequency

To check **every hour:**
```yaml
cron: '0 * * * *'
```

To check **every 15 minutes:**
```yaml
cron: '*/15 * * * *'
```

To check **once daily at 9 AM UTC:**
```yaml
cron: '0 9 * * *'
```

---

## Disabling Email Import

To pause auto-import temporarily:

1. Edit `.github/workflows/send_email.yaml`
2. Comment out the `lead-email-import` job:
   ```yaml
   # lead-email-import:
   #   runs-on: ubuntu-latest
   ```
3. Push changes
4. Workflow won't run

To re-enable:
1. Uncomment the job
2. Push changes
3. Workflow runs again at next scheduled time

---

## Security Notes

✅ **Credentials stored securely:**
- GitHub Secrets (encrypted)
- Never logged in output
- App password can be revoked anytime

✅ **Data handling:**
- Emails are only read, never modified (except marked as read)
- Leads created in Google Sheets (your account)
- No data sent to external services

✅ **If compromised:**
- Revoke app password: Google Account → App passwords → Remove
- New app password needed for next run
- Nothing else needs to be changed

---

## Next Steps

### Immediate (Today)
1. ✅ Generate app password from Google Account
2. ✅ Add EMAIL_PASSWORD to GitHub Secrets
3. ✅ Test locally with sample email

### This Week
1. ✅ Update GitHub Actions workflow
2. ✅ Test automated import
3. ✅ Verify leads appear in LEADS sheet

### Ongoing
1. Monitor import success
2. Adjust email format if needed
3. Check lead quality
4. Fine-tune schedule if needed

---

## Questions?

1. **App password not showing in Google Account?**
   - Ensure 2-Step Verification is enabled first
   - Go to [myaccount.google.com/security](https://myaccount.google.com/security)

2. **Workflow not triggering?**
   - Check cron syntax is valid
   - GitHub Actions have a UTC timezone
   - First run might take 5 minutes to appear

3. **Leads not appearing?**
   - Check GOOGLE_CREDENTIALS is set (from email_sender setup)
   - Verify email format matches expected pattern
   - Run local test to get error messages

---

Last Updated: 29 Apr 2026
Maintained by: Development Team
