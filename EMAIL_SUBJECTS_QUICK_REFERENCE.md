# 📧 Email Subjects - Quick Reference

## All Standardized with [4s CRM] Prefix

---

## 📬 Daily Email Schedule

### **10:00 AM IST**
```
[4s CRM] Franchise Pending Delivery Report - 29 Apr 2026 - 5 Pending
```
From: `email_sender.py` (Godrej CRM Email 1)

---

### **10:00 AM IST**
```
[4s CRM] Sales Team Tasks Assigned - 29 April 2026
```
From: `email_sender_sales_tasks.py` (Sales Email 1)

---

### **10:02 AM IST**
```
[4s CRM] 4S Pending Delivery Report - 29 Apr 2026 - 7 Pending
```
From: `email_sender_4s.py` (4S Email 1)

---

### **11:00 AM IST**
```
[4s CRM] Franchise Overdue Delivery Update - 29 Apr 2026 - 3 Overdue
```
From: `email_sender.py` (Godrej CRM Email 2)

---

### **11:02 AM IST**
```
[4s CRM] 4S Overdue Delivery Update - 29 Apr 2026 - 2 Overdue
```
From: `email_sender_4s.py` (4S Email 2)

---

### **5:00 PM IST**
```
[4s CRM] Franchise Pending Delivery Report - 29 Apr 2026 - 8 Pending
```
From: `email_sender.py` (Godrej CRM Email 3 - Evening)

---

### **5:02 PM IST**
```
[4s CRM] 4S Pending Delivery Report - 29 Apr 2026 - 10 Pending
```
From: `email_sender_4s.py` (4S Email 3 - Evening)

---

### **8:00 PM IST**
```
[4s CRM] Sales Team Task Status - 29 April 2026
```
From: `email_sender_sales_tasks.py` (Sales Email 2)

---

## 🎯 Subject Line Format

### **Pattern:**
```
[4s CRM] {Module} {Action} - {Date} - {Metric}
```

### **Examples:**

| Module | Action | Example |
|--------|--------|---------|
| Franchise | Pending Delivery | `[4s CRM] Franchise Pending Delivery Report - 29 Apr 2026 - 5 Pending` |
| Franchise | Overdue Delivery | `[4s CRM] Franchise Overdue Delivery Update - 29 Apr 2026 - 3 Overdue` |
| 4S | Pending Delivery | `[4s CRM] 4S Pending Delivery Report - 29 Apr 2026 - 7 Pending` |
| 4S | Overdue Delivery | `[4s CRM] 4S Overdue Delivery Update - 29 Apr 2026 - 2 Overdue` |
| Sales Team | Tasks Assigned | `[4s CRM] Sales Team Tasks Assigned - 29 April 2026` |
| Sales Team | Task Status | `[4s CRM] Sales Team Task Status - 29 April 2026` |

---

## ✅ Common [4s CRM] Prefix

Every email across the entire CRM system now starts with:
```
[4s CRM]
```

This ensures:
- ✅ Easy recognition of internal CRM emails
- ✅ Consistent branding across all modules
- ✅ Professional appearance
- ✅ Easy filtering/searching in email clients
- ✅ Clear identification as in-house system

---

## 📊 Email Modules

| Module | Prefix | Emails | Time |
|--------|--------|--------|------|
| **Franchise** | [4s CRM] Franchise | 3 emails | 10AM, 11AM, 5PM |
| **4S Interiors** | [4s CRM] 4S | 3 emails | 10:02AM, 11:02AM, 5:02PM |
| **Sales Team** | [4s CRM] Sales Team | 2 emails | 10AM, 8PM |

---

## 🔍 Filter by Prefix

In your email client, you can now filter all CRM emails:

**Gmail:**
```
subject:[4s CRM]
```

**Outlook:**
```
subject:[4s CRM]
```

This will show ALL emails from your CRM system!

---

## 📱 Mobile View

Even on mobile phones, the [4s CRM] prefix is visible and clear:

```
[4s CRM] Franchise Pending...
[4s CRM] 4S Overdue...
[4s CRM] Sales Team Tasks...
```

Instantly recognizable! ✨

---

## ✨ Professional Branding

Your in-house CRM now has a professional, consistent brand across all communications:

- Email 1: `[4s CRM] ✓`
- Email 2: `[4s CRM] ✓`
- Email 3: `[4s CRM] ✓`
- Email 4: `[4s CRM] ✓`
- Email 5: `[4s CRM] ✓`
- Email 6: `[4s CRM] ✓`
- Email 7: `[4s CRM] ✓`
- Email 8: `[4s CRM] ✓`

**Everything from 4s CRM!** 🎉

---

## 📋 Files with Updated Subjects

1. ✅ `services/email_sender.py` - Godrej CRM
2. ✅ `services/email_sender_4s.py` - 4S Interiors CRM
3. ✅ `services/email_sender_sales_tasks.py` - Sales Team CRM

---

## 🚀 Deploy Changes

```bash
git add -A
git commit -m "Standardize: All email subjects now use [4s CRM] prefix"
git push origin main
```

---

Done! Your CRM emails are now professionally unified. 🎉
