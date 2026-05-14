# Email & MIS Workflows — Diagnostic Checklist

**Updated:** May 14, 2026  
**Status:** Investigating credential issues after `.streamlit/secrets.toml` update

---

## Where Are Your Workflows Running?

**Please answer:** Where does your Streamlit app actually run?

- [ ] **A) Locally on my machine** (for testing)
- [ ] **B) On Streamlit Cloud** (deployed cloud version)
- [ ] **C) GitHub Actions scheduled jobs** (cron-based automation)
- [ ] **D) Multiple places above**

---

## Issue #1: GitHub Actions Secrets (If you use GitHub Actions)

If your scheduled email/MIS jobs run on GitHub Actions (7 AM delivery alerts, 4 PM alerts, 11 AM MIS import), they **do NOT use** your `.streamlit/secrets.toml` file.

### ❓ Check Your GitHub Repository Secrets:

Go to: **GitHub Repo → Settings → Secrets and variables → Actions**

**Required secrets for email workflows:**
- `EMAIL_SENDER` = `4sinteriorsbbsr@gmail.com`
- `EMAIL_PASSWORD` = `jcfz rhfw mkxt xttc` (the app password)
- `EMAIL_RECIPIENTS` = `4sinteriorsbbsr@gmail.com,pritish.sec@gmail.com`

**Required secrets for MIS workflow:**
- `EMAIL_SENDER` = `4sinteriorsbbsr@gmail.com`
- `EMAIL_PASSWORD` = `jcfz rhfw mkxt xttc`
- `GOOGLE_CREDENTIALS` = (your Google service account JSON)

### If these are missing or wrong:
1. Go to GitHub → Settings → Secrets and variables → Actions
2. Click "New repository secret" for each missing secret
3. Add the correct values
4. Re-run the workflow from GitHub Actions UI

---

## Issue #2: Gmail App Password Expiration/Revocation

Google can invalidate app passwords in certain scenarios:

### ❓ Verify Your App Password is Still Valid:

**Steps:**
1. Go to: https://myaccount.google.com/apppasswords
   - Login as `4sinteriorsbbsr@gmail.com`
   - Select App: **Mail**, Device: **Other (custom name)**
2. Check if the app password exists and is active
3. If it's missing or revoked, generate a new one

**Common reasons for revocation:**
- Account security changes (password reset)
- 2FA settings changed
- Google disabled the app password for security reasons
- Last update to security settings

### If you need a new app password:
1. Ensure 2FA is enabled on the Gmail account
2. Go to https://myaccount.google.com/apppasswords
3. Select App: **Mail**, Device: **Other**
4. Copy the new 16-character password
5. Update it in:
   - `.streamlit/secrets.toml` (line 6) ✅ Already done
   - `.env` (line 2) ✅ Already done
   - **GitHub Secrets → EMAIL_PASSWORD** ❌ Need to check

---

## Issue #3: Streamlit Cloud Secrets (If deployed there)

If your app runs on Streamlit Cloud, `.streamlit/secrets.toml` is **ignored**. Instead:

1. Go to **Streamlit Cloud → App Settings → Secrets**
2. Add your secrets in TOML format:
   ```toml
   EMAIL_SENDER = "4sinteriorsbbsr@gmail.com"
   EMAIL_PASSWORD = "jcfz rhfw mkxt xttc"
   EMAIL_RECIPIENTS = "4sinteriorsbbsr@gmail.com,pritish.sec@gmail.com"
   ```

---

## Detailed Diagnostic Steps

### Step 1: Test Email Send (Local)
```bash
cd streamlit_app
python email_job.py
```
**Expected:** Email sent successfully or specific error message
**Capture:** Full error output (copy-paste it)

---

### Step 2: Test MIS Fetch (Local)
```bash
cd streamlit_app
python mis_daily_import_job.py
```
**Expected:** ✅ MIS data loaded or specific error message
**Capture:** Full output (copy-paste it)

---

### Step 3: Check GitHub Actions Logs
1. Go to GitHub repo → **Actions** tab
2. Find failed workflow runs (e.g., "CRM Pending Delivery Alerts", "MIS Daily Import")
3. Click on the failed run → **Logs** section
4. Look for error messages like:
   - `SMTP login failed`
   - `IMAP login failed`
   - `invalid credentials`
   - `connection refused`
   - `timeout`
5. **Capture:** The exact error message

---

### Step 4: Verify Network Connectivity
```bash
# Test if Gmail SMTP/IMAP are reachable
python3 << 'EOF'
import socket

hosts = [
    ("smtp.gmail.com", 465),
    ("imap.gmail.com", 993)
]

for host, port in hosts:
    try:
        sock = socket.create_connection((host, port), timeout=5)
        print(f"✅ {host}:{port} — REACHABLE")
        sock.close()
    except Exception as e:
        print(f"❌ {host}:{port} — FAILED: {e}")
EOF
```

---

## Information Needed From You

Please provide:

1. **Where are your email workflows running?**
   - Locally, Streamlit Cloud, GitHub Actions, or multiple?

2. **What is the exact error message?**
   - When you run email_job.py locally
   - When you run mis_daily_import_job.py locally
   - From GitHub Actions logs (if available)

3. **Have you checked GitHub Secrets?**
   - Are EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS set?
   - What values do they have? (can share just first/last char for password)

4. **Gmail App Password Status:**
   - Is the app password still listed in myaccount.google.com/apppasswords?
   - Has it been revoked or is it active?

5. **Recent Changes:**
   - When did this start failing? (specific date/time)
   - Did anything change before the failures? (password reset, 2FA settings, etc.)

---

## Common Fix Patterns

### Pattern A: GitHub Actions + Wrong/Missing Secrets
**Fix:** Update GitHub repository secrets
**Time to fix:** 5 minutes

### Pattern B: Gmail App Password Revoked
**Fix:** Generate new app password, update all locations
**Time to fix:** 10 minutes

### Pattern C: Streamlit Cloud + Wrong Secrets Location
**Fix:** Use Streamlit Cloud UI to set secrets (not local file)
**Time to fix:** 5 minutes

### Pattern D: Gmail Account Security Lockout
**Fix:** Verify account, re-enable less secure app access, or check 2FA settings
**Time to fix:** 15-30 minutes

---

## Next Steps

1. **Answer the questions above**
2. **Run local tests** (email_job.py and mis_daily_import_job.py)
3. **Share the exact error messages**
4. **Check GitHub Secrets** (if using GitHub Actions)
5. **Verify Gmail app password** status

Once you provide this information, I can pinpoint the exact cause and fix it! 🎯
