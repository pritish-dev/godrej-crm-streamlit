# 📧 Dashboard Email Trigger Guide

**Send Pending Delivery Emails Directly from Dashboard**

---

## ✨ Features

✅ **One-Click Email Sending** - Send from Franchise or 4S dashboard  
✅ **Combined Email** - Both Godrej + 4S data in single email  
✅ **Real-Time** - Immediate send, no GitHub Actions delays  
✅ **No Duplicates** - Same logic as scheduled emails  
✅ **Live Status** - Shows count of pending items sent  

---

## 🎯 How to Use

### **From Franchise Dashboard (Godrej)**

1. Go to: **Franchise B2C Sales** page (Left sidebar → Daily Franchise B2C Sales)
2. Look for the button: **"📧 Send Pending Delivery Email"**
3. Click the button
4. Wait for confirmation message
5. Email sent! Recipients receive immediately

**Result Message:**
```
✅ Email sent successfully!
• Godrej: X pending items
• 4S: Y pending items
```

### **From 4S Dashboard**

1. Go to: **4S Interiors Dashboard** (Left sidebar → 4SINTERIORS Sales Dashboard)
2. Look for the button: **"📧 Send Pending Delivery Email"**
3. Click the button
4. Wait for confirmation message
5. Email sent! Recipients receive immediately

**Result Message:**
```
✅ Email sent successfully!
• Godrej: X pending items
• 4S: Y pending items
```

---

## 📊 What Gets Sent

When you click the button, an email is generated containing:

### **Content Included:**
- ✅ Godrej pending deliveries (if any)
- ✅ 4S Interiors pending deliveries (if any)
- ✅ Item names, customer names, due dates
- ✅ Status and notes
- ✅ Summary table
- ✅ Timestamp of when email was sent
- ✅ Manual trigger indicator

### **Email Subject:**
```
[4s CRM] Pending Delivery Status - Manual Trigger
```

### **Email Recipients:**
Sent to: `EMAIL_RECIPIENTS` (configured in GitHub Secrets)

---

## 🔍 What Counts as "Pending"?

The email includes any item with status containing "Pending" (case-insensitive):
- "Pending Delivery"
- "Pending"
- "Pending Review"
- etc.

**Note:** Empty franchises show "✅ No pending deliveries"

---

## ✅ Requirements

For this to work, you need:

1. ✅ **EMAIL_SENDER** - Sender's Gmail address (in GitHub Secrets)
2. ✅ **EMAIL_PASSWORD** - Gmail App Password (in GitHub Secrets)
3. ✅ **EMAIL_RECIPIENTS** - Recipients list (in GitHub Secrets)
4. ✅ **GOOGLE_CREDENTIALS** - Google Sheets access (in GitHub Secrets)
5. ✅ **GODREJ Sheet** - Franchise data sheet
6. ✅ **4S Sheet** - 4S Interiors data sheet

---

## ⚠️ Error Messages

### **"❌ Email credentials not configured"**
- **Cause:** Missing EMAIL_SENDER, EMAIL_PASSWORD, or EMAIL_RECIPIENTS secrets
- **Fix:** Add secrets to GitHub Secrets in repository settings

### **"❌ Email authentication failed"**
- **Cause:** Wrong password or EMAIL_SENDER
- **Fix:** Verify credentials are correct (use Gmail App Password, not regular password)

### **"⚠️ Error loading data"**
- **Cause:** GODREJ or 4S sheet not found/accessible
- **Fix:** Verify sheet names exist and GOOGLE_CREDENTIALS has access

### **"❌ Error sending email"**
- **Cause:** Gmail SMTP error
- **Fix:** Check internet connection, verify Gmail account has 2FA and app password enabled

---

## 🔄 Comparison: Manual vs Scheduled

| Feature | Manual Button | Scheduled (10 AM) |
|---------|---------------|-------------------|
| **When** | On-demand | Daily at 10 AM IST |
| **Location** | Dashboard button | GitHub Actions |
| **Speed** | Immediate | ~1-2 min delay |
| **User** | Anyone on CRM | Automatic |
| **Frequency** | As needed | Once/day |
| **Email Content** | Same | Same |

---

## 📝 Technical Details

### **Files Involved**

1. **`services/email_trigger.py`** - Core email sending function
   - `send_combined_pending_delivery_email()` - Main function
   - `generate_combined_email_html()` - Email HTML generator

2. **`pages/10_Daily_Franchise_Sales.py`** - Franchise dashboard
   - Added button to trigger email

3. **`pages/2_4sinteriors_Dashboard.py`** - 4S dashboard
   - Added button to trigger email

### **Workflow**

```
User clicks button
    ↓
Streamlit calls: send_combined_pending_delivery_email()
    ↓
Function loads GODREJ + 4S sheets
    ↓
Filters for "Pending" status items
    ↓
Generates HTML email
    ↓
Connects to Gmail SMTP
    ↓
Sends to EMAIL_RECIPIENTS
    ↓
Returns success/error message to UI
```

---

## 🎨 Email Template

**Visual Layout:**

```
┌─────────────────────────────────────────┐
│ [4s CRM] Pending Delivery Status        │
│ Manual Trigger from Dashboard           │
├─────────────────────────────────────────┤
│ 📱 Triggered: Manual request            │
│ ⏰ Time: 14:30:45 IST                   │
├─────────────────────────────────────────┤
│ 🏢 GODREJ - Pending Deliveries (5)      │
├─────────────────────────────────────────┤
│ Item | Customer | Status | Due Date     │
├─────────────────────────────────────────┤
│ 🏠 4S INTERIORS - Pending Deliveries    │
├─────────────────────────────────────────┤
│ Item | Customer | Status | Due Date     │
├─────────────────────────────────────────┤
│ 📊 Summary                              │
│ Total: 5+3 = 8 pending items            │
└─────────────────────────────────────────┘
```

---

## 🚀 Best Practices

1. **Use for Ad-Hoc Needs** - Send when you need quick updates
2. **Check Before Sending** - Verify pending items in sheet first
3. **Monitor Recipients** - Ensure EMAIL_RECIPIENTS is correct
4. **Don't Spam** - Don't send too frequently (same data = redundant)
5. **Use Scheduled for Regular** - Let 10 AM scheduled email handle daily sends

---

## 🔐 Security Notes

✅ **Safe** - Uses same Gmail authentication as scheduled emails  
✅ **Credentials Protected** - Stored in GitHub Secrets (encrypted)  
✅ **No Data Exposed** - Only reads sheets, no data stored  
✅ **Audit Trail** - Email marked as "Manual Trigger" for tracking  

---

## ❓ FAQ

**Q: Will this send duplicate email if scheduled one also runs?**  
A: No conflict. Manual runs immediately. Scheduled runs at 10 AM. Both show "Manual Trigger" vs "Scheduled" in subject.

**Q: Can I customize who receives the email?**  
A: Currently sends to EMAIL_RECIPIENTS. Contact admin to modify recipient list in GitHub Secrets.

**Q: Does it check for duplicates like the scheduled email?**  
A: No. Manual trigger sends all pending items, regardless of history. Use scheduled email if you need duplicate prevention.

**Q: Can I send from mobile?**  
A: Yes! If accessing CRM from mobile, you can click the button the same way.

**Q: What if both sheets have no pending items?**  
A: Email still sends with "✅ No pending deliveries" messages for both franchises.

---

## 📞 Troubleshooting

**Problem:** Button doesn't appear
- Solution: Refresh page (Ctrl+F5 or Cmd+Shift+R)
- Or: Clear Streamlit cache (settings → Clear cache)

**Problem:** Email never arrives
- Solution: Check spam folder
- Or: Verify EMAIL_RECIPIENTS is correct in GitHub Secrets

**Problem:** Spinner keeps loading
- Solution: Wait 30 seconds (email sending takes time)
- Or: Check browser console for errors (F12 → Console)

**Problem:** Error message appears
- Solution: Read error message carefully (links to specific issue)
- Or: Check requirements section above

---

## 📅 Version Info

- **Created:** 29 Apr 2026
- **Feature:** Dashboard email trigger
- **Status:** ✅ Active
- **Maintenance:** Included with email automation
