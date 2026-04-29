# 📧 Email Schedule Analysis - CRM Automation

**Last Updated:** 29 Apr 2026  
**Total Emails Per Day:** 11 emails  
**Total Runs Per Day:** 9 scheduled jobs + Lead Import (48 times/day)

---

## 📊 Email Breakdown

### 1️⃣ GODREJ CRM EMAILS (3 emails/day)

| Time | UTC | IST | Email Name | Content | File |
|------|-----|-----|-----------|---------|------|
| **30 4 * * *** | 04:30 UTC | 10:00 AM | Godrej Email 1 (Morning) | Daily CRM status, open leads, tasks | `email_job.py` |
| **30 5 * * *** | 05:30 UTC | 11:00 AM | Godrej Email 2 (Update Reminder) | Update reminder for morning leads | `email_job.py` |
| **30 11 * * *** | 11:30 UTC | 5:00 PM | Godrej Email 3 (Evening) | End of day CRM summary | `email_job.py` |

---

### 2️⃣ 4S INTERIORS CRM EMAILS (3 emails/day)

| Time | UTC | IST | Email Name | Content | File |
|------|-----|-----|-----------|---------|------|
| **32 4 * * *** | 04:32 UTC | 10:02 AM | 4S Email 1 (Morning) | Daily CRM status, open leads, tasks | `email_job_4s.py` |
| **32 5 * * *** | 05:32 UTC | 11:02 AM | 4S Email 2 (Update Reminder) | Update reminder for morning leads | `email_job_4s.py` |
| **32 11 * * *** | 11:32 UTC | 5:02 PM | 4S Email 3 (Evening) | End of day CRM summary | `email_job_4s.py` |

**Note:** 4S emails offset by +2 minutes to avoid concurrent execution with Godrej emails

---

### 3️⃣ SALES TEAM TASK EMAILS (2 emails/day)

| Time | UTC | IST | Email Name | Content | File |
|------|-----|-----|-----------|---------|------|
| **30 4 * * *** | 04:30 UTC | 10:00 AM | Sales Tasks (Morning) | • Tasks assigned for today<br>• Overdue pending tasks<br>• Task assignments by person | `sales_tasks_email_job.py` |
| **30 14 * * *** | 14:30 UTC | 8:00 PM | Sales Task Status (Evening) | • Task completion status for today<br>• Summary counts (total, done, pending, overdue)<br>• Detailed task table | `sales_tasks_status_email_job.py` |

---

### 4️⃣ LEAD EMAIL IMPORT (Every 30 minutes)

| Frequency | UTC | IST | Function | File |
|-----------|-----|-----|----------|------|
| ***/30 * * * *** | Every 30 min | Every 30 min | Check `4sinteriorsbbsr@gmail.com` for emails with "Lead" subject<br>Auto-import new leads to LEADS sheet<br>Process last 7 days of emails | `lead_email_import_job.py` |

**Daily Executions:** 48 times/day (00:00, 00:30, 01:00, ... 23:30)

---

## 📈 Daily Email Schedule Timeline

```
10:00 AM IST (04:30 UTC)
├─ 📧 Godrej Email 1 (Morning)
├─ 📧 Sales Tasks Email (Morning)
└─ 🔄 Lead Import Check #20 (approx)

10:02 AM IST (04:32 UTC)
└─ 📧 4S Email 1 (Morning)

11:00 AM IST (05:30 UTC)
├─ 📧 Godrej Email 2 (Update Reminder)
└─ 🔄 Lead Import Check #21 (approx)

11:02 AM IST (05:32 UTC)
└─ 📧 4S Email 2 (Update Reminder)

[Throughout the day: Lead imports every 30 minutes]

5:00 PM IST (11:30 UTC)
├─ 📧 Godrej Email 3 (Evening)
└─ 🔄 Lead Import Check #45 (approx)

5:02 PM IST (11:32 UTC)
└─ 📧 4S Email 3 (Evening)

8:00 PM IST (14:30 UTC)
├─ 📧 Sales Task Status (Evening)
└─ 🔄 Lead Import Check #48 (approx)
```

---

## 📋 Email Count Summary

### By Frequency
- **Daily (Business Days):** 8 scheduled emails
  - 3 Godrej emails
  - 3 4S Interiors emails
  - 2 Sales Team Task emails

- **Every 30 minutes (24/7):** 48 lead import checks/day

### Total Email Triggers Per Day
- **Scheduled emails sent:** 8/day
- **Lead import checks:** 48/day (may create emails to sales team if new leads found)
- **Total GitHub Actions runs:** 56+/day

### Total Per Week
- **Scheduled emails:** 56/week
- **Lead import checks:** 336/week

### Total Per Month
- **Scheduled emails:** 240/month
- **Lead import checks:** 1,440/month

---

## 🎯 Email Recipients

From `EMAIL_RECIPIENTS` GitHub secret:
- All 8 scheduled emails go to: **${EMAIL_RECIPIENTS}** (configured in GitHub Secrets)
- Lead import is silent - only creates records in LEADS sheet, no email sent

---

## 🔄 Concurrent Email Handling

**Potential Overlaps at 10:00 AM IST:**
```
10:00:00 - Godrej Email 1
10:00:00 - Sales Tasks Email
10:02:00 - 4S Email 1 (offset by 2 minutes)
```

**Status:** ✅ Handled properly - different jobs run in parallel on GitHub Actions

---

## ⚙️ Job Execution Details

### Email Job Workflow
Each scheduled email goes through:
1. GitHub Actions workflow triggered by cron
2. Job environment setup (Python, dependencies)
3. Google Sheets data fetch (`get_df()`)
4. Email content generation
5. Send via `EMAIL_SENDER` account to `EMAIL_RECIPIENTS`

### Lead Import Workflow
Each 30-minute check goes through:
1. GitHub Actions workflow triggered by cron
2. Connect to Gmail IMAP (4sinteriorsbbsr@gmail.com)
3. Search for emails with "Lead" in subject from last 7 days
4. Parse email body for lead details
5. Check for duplicates (Salesforce URL)
6. Create/skip lead silently in LEADS sheet
7. Mark email as read

---

## 🚀 Performance Notes

**Email Sending Time:** ~30-60 seconds per job
**Lead Import Time:** ~10-20 seconds per check

**GitHub Actions Resources:**
- Concurrent jobs: Typically 1-2 at a time
- Build time: ~2 minutes per job (setup + execution)
- Overall load: Low (8 emails/day is minimal)

---

## 🔐 Email Authentication

- **Sender Account:** `${secrets.EMAIL_SENDER}`
- **Sender Password:** `${secrets.EMAIL_PASSWORD}` (Gmail App Password)
- **Recipients:** `${secrets.EMAIL_RECIPIENTS}`
- **Google Sheets Auth:** `${secrets.GOOGLE_CREDENTIALS}` (Service Account JSON)

---

## ✅ Testing Emails Manually

From GitHub Actions UI:
1. Go to "Actions" tab → "Send CRM Emails"
2. Click "Run workflow"
3. Select job from dropdown:
   - `godrej_email1` / `godrej_email2`
   - `fours_email1` / `fours_email2`
   - `sales_tasks_email`
   - `sales_tasks_status_email`
   - `lead_email_import`
4. Click "Run workflow"

---

## 📝 Subject Lines

All emails include **[4s CRM]** prefix for easy filtering:
- `[4s CRM] Godrej Daily Summary - 10:00 AM`
- `[4s CRM] 4S Interiors Daily Summary - 10:02 AM`
- `[4s CRM] Sales Team Tasks - 10:00 AM`
- `[4s CRM] Sales Task Status - 8:00 PM`

---

**Questions?**
- To add more emails: Edit `.github/workflows/send_email.yaml` and add new cron schedule
- To change timing: Modify cron expression (IST = UTC + 5:30)
- To disable an email: Comment out the cron schedule
