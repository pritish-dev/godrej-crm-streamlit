# ✅ Quick Start Checklist - Email Workflows

## 🔧 Setup Steps

- [ ] **Step 1: Push to GitHub**
  ```bash
  git add .github/workflows/
  git commit -m "Add 5 separate email workflows with fixed scheduling"
  git push origin main
  ```

- [ ] **Step 2: Add GitHub Secrets**
  - Go to: GitHub Repo → Settings → Secrets and variables → Actions
  - Add these 4 secrets:
    - [ ] `EMAIL_SENDER` = your-email@gmail.com
    - [ ] `EMAIL_PASSWORD` = your Gmail App Password (16 chars)
    - [ ] `EMAIL_RECIPIENTS` = recipient1@gmail.com,recipient2@gmail.com
    - [ ] `GOOGLE_CREDENTIALS` = (paste entire service account JSON)

- [ ] **Step 3: Manual Test**
  - Go to GitHub → Actions tab
  - Select "Godrej CRM Emails" workflow
  - Click "Run workflow" button
  - Watch the logs for success/error messages

- [ ] **Step 4: Verify**
  - Check your email inbox for test emails
  - All 4 secrets should be visible in Settings
  - No secrets should show in workflow logs

---

## 📧 Email Verification

After setup, you should receive emails at:

| Time | Email Type | Frequency |
|------|-----------|-----------|
| **10:00 AM IST** | Godrej Email 1 + Sales Tasks Email | Daily |
| **10:02 AM IST** | 4S Email 1 | Daily |
| **11:00 AM IST** | Godrej Email 2 | Daily |
| **11:02 AM IST** | 4S Email 2 | Daily |
| **5:00 PM IST** | Godrej Email 3 | Daily |
| **5:02 PM IST** | 4S Email 3 | Daily |
| **8:00 PM IST** | Sales Task Status Email | Daily |
| **Every 30 min** | Lead Import (10 AM - 10 PM IST) | Every 30 min |

---

## 🔐 Gmail Setup (if not already done)

### Generate Gmail App Password:
1. Go to https://myaccount.google.com/apppasswords
2. Select "Mail" and "Windows Computer"
3. Copy the 16-character password
4. Use this in `EMAIL_PASSWORD` secret (NOT your regular password)

### Enable 2FA on Gmail:
- Gmail requires 2-Factor Authentication for app passwords
- Set it up at https://myaccount.google.com/security

---

## 🧪 Testing Each Workflow

**Test Godrej Email:**
- Actions → "Godrej CRM Emails" → Run workflow

**Test 4S Email:**
- Actions → "4S Interiors CRM Emails" → Run workflow

**Test Sales Tasks Email:**
- Actions → "Sales Team Tasks Email" → Run workflow

**Test Sales Task Status Email:**
- Actions → "Sales Team Task Status Email" → Run workflow

**Test Lead Import:**
- Actions → "Lead Email Import" → Run workflow

---

## 🚨 Troubleshooting

| Issue | Solution |
|-------|----------|
| "Secrets not found" | Add secrets to GitHub Settings → Secrets |
| "Gmail auth failed" | Use App Password, not regular password |
| "Email not received" | Check spam folder, verify recipient emails |
| "Workflow doesn't run" | Push all 5 YAML files to `.github/workflows/` |
| "Wrong time execution" | Secrets loaded correctly? Run manual test. |

---

## 📁 Files Structure

```
.github/workflows/
├── godrej-email.yaml
├── fours-email.yaml
├── sales-tasks-email.yaml
├── sales-task-status-email.yaml
└── lead-email-import.yaml
```

All 5 files should exist in your repository.

---

## ✨ Summary

- ✅ 5 independent workflows (no cross-triggering)
- ✅ Each email runs ONLY at its scheduled time
- ✅ All use the SAME 4 GitHub secrets
- ✅ Easy to test, debug, and maintain
- ✅ Ready for production use

**Status:** Ready to deploy! 🚀
