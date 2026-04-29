# 🔐 GitHub Secrets Setup Guide

Your email workflows are now ready but need **GitHub Secrets** to be configured. Follow these steps:

---

## ✅ Required Secrets to Add

You need to add **4 secrets** to your GitHub repository:

| Secret Name | Value | Example |
|---|---|---|
| `EMAIL_SENDER` | Your Gmail address | `your-email@gmail.com` |
| `EMAIL_PASSWORD` | Gmail App Password (NOT regular password) | `xxxx xxxx xxxx xxxx` |
| `EMAIL_RECIPIENTS` | Recipient emails (comma-separated) | `recipient1@gmail.com,recipient2@gmail.com` |
| `GOOGLE_CREDENTIALS` | Google Service Account JSON | `{"type": "service_account", ...}` |

---

## 📋 Step-by-Step Setup

### **Step 1: Go to Repository Settings**
1. Go to your GitHub repository
2. Click **Settings** (top right)
3. Click **Secrets and variables** → **Actions** (left sidebar)

### **Step 2: Add `EMAIL_SENDER` Secret**
1. Click **New repository secret**
2. Name: `EMAIL_SENDER`
3. Value: Your Gmail address (e.g., `your-email@gmail.com`)
4. Click **Add secret**

### **Step 3: Add `EMAIL_PASSWORD` Secret**
1. Click **New repository secret**
2. Name: `EMAIL_PASSWORD`
3. Value: Your Gmail **App Password** (16-character password)
   - ⚠️ **IMPORTANT**: This is NOT your regular Gmail password!
   - To generate an App Password:
     - Go to https://myaccount.google.com/apppasswords
     - Select "Mail" and "Windows Computer"
     - Copy the 16-character password
4. Click **Add secret**

### **Step 4: Add `EMAIL_RECIPIENTS` Secret**
1. Click **New repository secret**
2. Name: `EMAIL_RECIPIENTS`
3. Value: Comma-separated email addresses
   - Example: `recipient1@gmail.com,recipient2@gmail.com,recipient3@gmail.com`
4. Click **Add secret**

### **Step 5: Add `GOOGLE_CREDENTIALS` Secret**
1. Click **New repository secret**
2. Name: `GOOGLE_CREDENTIALS`
3. Value: Paste your Google Service Account JSON file (entire content)
   - This should be a JSON object starting with `{"type": "service_account"`
4. Click **Add secret**

---

## 🔒 Security Notes

✅ **DO**:
- Use Gmail **App Password**, not your regular password
- Keep secrets private and never commit them to git
- Use a service account for Google Sheets API access

❌ **DON'T**:
- Use your actual Gmail password
- Commit secrets to the repository
- Share secrets publicly

---

## 🧪 Testing After Setup

Once secrets are added:

1. **Automatic Test**: Wait for the next scheduled time
2. **Manual Test**: 
   - Go to **Actions** tab in GitHub
   - Select any workflow (e.g., `Godrej CRM Emails`)
   - Click **Run workflow**
   - Check the logs to verify it runs successfully

---

## ✨ Verification Checklist

- [ ] `EMAIL_SENDER` secret added
- [ ] `EMAIL_PASSWORD` secret added (using App Password)
- [ ] `EMAIL_RECIPIENTS` secret added
- [ ] `GOOGLE_CREDENTIALS` secret added
- [ ] All 4 secrets visible in Settings → Secrets
- [ ] Manual workflow test completed successfully
- [ ] Check email inbox for test emails

---

## 📧 Expected Emails After Setup

Once secrets are configured, you'll receive:

| Time | Email Type | Frequency |
|---|---|---|
| 10:00 AM IST | Godrej Email 1 + Sales Tasks | Daily |
| 10:02 AM IST | 4S Email 1 | Daily |
| 11:00 AM IST | Godrej Email 2 | Daily |
| 11:02 AM IST | 4S Email 2 | Daily |
| 5:00 PM IST | Godrej Email 3 | Daily |
| 5:02 PM IST | 4S Email 3 | Daily |
| 8:00 PM IST | Sales Task Status | Daily |
| Every 30 min | Lead Import | 10 AM - 10 PM IST |

---

## 🚨 Troubleshooting

### **Error: "EMAIL_SENDER / EMAIL_PASSWORD not set in secrets"**
- ❌ Secrets not added to GitHub
- ✅ Add them following the steps above

### **Error: "Gmail authentication failed"**
- ❌ Using regular Gmail password instead of App Password
- ✅ Generate App Password at https://myaccount.google.com/apppasswords

### **Error: "GOOGLE_CREDENTIALS invalid"**
- ❌ Service account JSON is malformed or incomplete
- ✅ Verify the entire JSON is pasted correctly

### **Workflow runs but no email sent**
- Check workflow logs in GitHub Actions tab
- Verify all secrets are configured
- Check if email script is working (see email_job.py logs)

---

## ✅ All Set!

After completing these steps, all your email workflows will work automatically at their scheduled times!

Questions? Check your email logs in GitHub Actions → Select workflow → See step logs.
