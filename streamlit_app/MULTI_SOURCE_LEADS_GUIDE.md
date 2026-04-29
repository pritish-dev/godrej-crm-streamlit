# 🎯 Multi-Source Leads System - Complete Guide

## Overview
The enhanced Leads Management system now supports leads from multiple sources with automated email import via IMAP and dedicated forms for each channel.

---

## Lead Sources Supported

| Source | Icon | Entry Method | Auto-Import |
|--------|------|--------------|-------------|
| **Email (OneCRM)** | 📧 | Email parsing | ✅ Yes (IMAP) |
| **Showroom Walk-in** | 🏪 | Dedicated form | Manual |
| **Instagram** | 📱 | Social Media form | Future |
| **Facebook** | 👍 | Social Media form | Future |
| **Website** | 🌐 | Website form | Future |
| **Phone Call** | ☎️ | Call form | Manual |
| **LinkedIn** | 🔗 | Manual entry | Future |
| **Referral** | 👥 | Manual entry | Manual |
| **Event** | 🎯 | Manual entry | Manual |
| **Other** | 🛍️ | Manual entry | Manual |

---

## How to Add Leads

### ⚡ QUICK ENTRY (Sidebar)
**Best for:** Fast capture during showroom visits or calls

1. **Sidebar Widget** - Always visible on the left
2. Select **Lead Source** (Showroom, Instagram, etc.)
3. Enter **Lead Name** (required)
4. Enter **Phone** (optional)
5. Enter **Product Interest** (optional)
6. Click **"➕ Add Lead"**

✅ Lead is immediately created and assigned to follow-up in 1 day

---

### 📋 DETAILED ENTRY (Expandable Forms)
**Best for:** Complete information capture

Click **"➕ Add New Lead - Detailed Entry"** expander

#### TAB 1: 📧 EMAIL
**For leads from OneCRM (Salesforce)**
- Paste complete email body
- Click "Parse Email"
- System extracts: Lead name, Assigned To, Salesforce URL
- Review extracted data and proceed to Manual Entry tab if needed

**Example Email:**
```
Hi,
The lead "Aparajeeta Tripathy" is moved to your Queue - SUBRAT KUMAR SENAPATI. 
You may click on the link to view details - https://gnb.my.site.com/gbpartners/00QOW00000jskiH
Thanks,
Godrej & Boyce
```

**Auto-Import:** Every 30 minutes from 4sinteriorsbbsr@gmail.com ✅

---

#### TAB 2: 🏪 SHOWROOM
**For walk-in visitors at showroom**

| Field | Required | Example |
|-------|----------|---------|
| Visitor Name * | ✅ | Rahul Sharma |
| Phone Number | | 9876543210 |
| Product Interest | | Modular Kitchen |
| Showroom Location | | Bangalore Main |
| Budget Range | | 5-10 Lakhs |
| Visit Date | | 29-Apr-2026 |
| Notes | | Interested in consultation |

**Auto-generated:**
- Status: 🟢 New
- Follow-up: 2 days
- Source: 🏪 Showroom Walk-in

---

#### TAB 3: 📱 SOCIAL MEDIA
**For leads from Instagram, Facebook, etc.**

| Field | Required | Example |
|-------|----------|---------|
| Lead Name * | ✅ | Priya Mehta |
| Platform | | Instagram |
| Username/Profile | | @priya_designs |
| Email | | priya@email.com |
| Phone | | 9876543210 |
| Engagement Level | | 🟢 High |
| Post/Message Link | | https://instagram.com/p/... |
| Notes | | DM inquiry about furniture |

**Auto-generated:**
- Status: 🟢 New
- Follow-up: 3 days
- Source: 📱 [Platform]

---

#### TAB 4: 🌐 WEBSITE
**For website form submissions and inquiries**

| Field | Required | Example |
|-------|----------|---------|
| Lead Name * | ✅ | Amit Kumar |
| Email Address | | amit@company.com |
| Traffic Source | | Google Search |
| Phone Number | | 9876543210 |
| Form Page | | /product/kitchen-designs |
| Company | | TechCorp Solutions |
| Inquiry/Message | | Interested in custom design |

**Auto-generated:**
- Status: 🟢 New
- Follow-up: 1 day
- Source: 🌐 Website

---

#### TAB 5: ☎️ CALL
**For inbound or outbound calls**

| Field | Required | Example |
|-------|----------|---------|
| Caller Name * | ✅ | Neha Singh |
| Phone Number | | 9876543210 |
| Company | | ABC Interior Design |
| Call Time | | 14:30 |
| Call Duration | | 15 minutes |
| Call Outcome | | Interested |
| Call Details & Notes | | Customer interested in consultation |

**Auto-generated:**
- Status: 🔵 Contacted (pre-filled)
- Follow-up: 2 days
- Source: ☎️ Phone Call

---

#### TAB 6: ✏️ MANUAL
**For any other source or custom entry**

- Select **Lead Source** from dropdown (LinkedIn, Referral, Event, etc.)
- Fill in all available fields
- Set custom follow-up date
- Add notes

---

## Automated Email Import (IMAP)

### Setup Required

**Email:** `4sinteriorsbbsr@gmail.com`

**What's needed:**
1. Gmail App Password
2. Add to GitHub Actions secrets

### How It Works

1. **Every 30 minutes**, system connects to Gmail via IMAP
2. **Searches** for unread emails with "Lead" in subject
3. **Parses** email body to extract:
   - Lead name (from `"Lead Name"` pattern)
   - Assigned sales person (from `Queue - NAME`)
   - Salesforce URL
4. **Automatically creates** lead in LEADS sheet
5. **Marks email as read** in Gmail

### Email Pattern Expected

```
Subject: Lead Aparajeeta Tripathy is assigned to you

Body:
Hi,
The lead "Aparajeeta Tripathy" is moved to your Queue - SUBRAT KUMAR SENAPATI. 
You may click on the link to view details - https://gnb.my.site.com/gbpartners/00QOW00000jskiH
Thanks,
Company Name
```

### What Gets Created

```
Lead ID: [auto]
Lead Name: Aparajeeta Tripathy
Status: 🟢 New
Source: Email (OneCRM)
Source Details: Salesforce Lead Assignment
Assigned To: SUBRAT KUMAR SENAPATI
Salesforce URL: https://gnb.my.site.com/gbpartners/00QOW00000jskiH
Follow-up Date: Tomorrow
Created Date: [today]
```

### Troubleshooting Email Import

**Email not importing?**
- Check "Lead" is in email subject line
- Verify email contains lead name in quotes
- Ensure Salesforce URL is valid
- Check Gmail IMAP is enabled
- Verify app password is correct

**To manually check:**
- Run: `python services/imap_lead_import.py`
- Check: GitHub Actions logs

---

## Lead Data Fields

### Core Fields
| Field | Type | Required | Auto-filled |
|-------|------|----------|-------------|
| Lead ID | Number | ✅ | ✅ Auto |
| Lead Name | Text | ✅ | |
| Company | Text | | |
| Email | Email | | |
| Phone | Phone | | |
| Status | Dropdown | ✅ | 🟢 New |
| Priority | Dropdown | ✅ | Medium |

### Source Tracking
| Field | Type | Purpose |
|-------|------|---------|
| SOURCE | Text | Primary source (Email, Showroom, etc.) |
| SOURCE_DETAILS | Text | Sub-details (Platform, Location, etc.) |
| SALESFORCE URL | URL | Reference to original Salesforce lead |

### Timeline
| Field | Type | Purpose |
|-------|------|---------|
| Created Date | DateTime | When lead was added |
| Last Contact | DateTime | Last interaction |
| Follow Up Date | Date | When to contact next |
| Conversion Date | Date | When deal was closed |

### Notes & Value
| Field | Type | Purpose |
|-------|------|---------|
| Notes | LongText | All interaction notes and details |
| Deal Value | Currency | Expected revenue (₹) |

---

## Lead Workflow

### Status Progression
```
🟢 New (Just created)
   ↓ (Call/Email sent)
🔵 Contacted (First contact made)
   ↓ (Assessed fit)
🟡 Qualified (Has potential)
   ↓ (Sent offer)
🟣 Proposal Sent (Awaiting response)
   ↓ (Customer agrees)
🟢 Converted (Deal closed)
   
OR at any stage → 🔴 Lost (Disqualified)
```

### Status Definitions by Source

**Email/OneCRM Leads:**
- Start: 🟢 New
- After contact: 🔵 Contacted
- If qualified: 🟡 Qualified → 🟣 Proposal Sent → 🟢 Converted

**Showroom Leads:**
- Start: 🟢 New (visitor collected info)
- If callback done: 🔵 Contacted
- If interested: 🟡 Qualified

**Phone Call Leads:**
- Start: 🔵 Contacted (already on call)
- If interested: 🟡 Qualified
- If wants quote: 🟣 Proposal Sent

**Website Leads:**
- Start: 🟢 New (form submitted)
- After contact: 🔵 Contacted
- If interested: 🟡 Qualified

---

## Lead Source Analytics

### What Gets Tracked
✅ **Lead count by source** - How many from each channel?  
✅ **Conversion rate by source** - Which channel converts best?  
✅ **Revenue by source** - Which channel generates most value?  
✅ **Lead quality by source** - Average deal size per source  

### Dashboard Sections

**Leads by Source** - Percentage distribution
```
🏪 Showroom Walk-in:      25% (10 leads)
📧 Email (OneCRM):        35% (14 leads)
📱 Instagram:             20% (8 leads)
🌐 Website:               15% (6 leads)
☎️ Phone Call:            5%  (2 leads)
```

**Conversion by Source** - Which channels work best?
```
Email (OneCRM):  40% conversion rate
Showroom:        35% conversion rate
Website:         30% conversion rate
Instagram:       25% conversion rate
Phone:           20% conversion rate
```

---

## Best Practices by Source

### 📧 Email (OneCRM)
✅ Set follow-up within 24 hours  
✅ Check Salesforce for full details  
✅ Update status after contact  
✅ Use consistent assignment  

### 🏪 Showroom
✅ Capture visitor info immediately  
✅ Get phone number (critical!)  
✅ Note product interest  
✅ Follow-up call within 2 days  

### 📱 Social Media
✅ Add engagement level  
✅ Include post/profile link  
✅ More time-sensitive (respond within hours)  
✅ May need social follow-up first  

### 🌐 Website
✅ Quick follow-up (same day)  
✅ Check traffic source for insights  
✅ Personalize based on page they filled  
✅ Automated response helpful  

### ☎️ Phone
✅ Document call outcome  
✅ Record if callback needed  
✅ Immediate action required  
✅ High conversion potential  

---

## Integration Timeline

### ✅ Current (Live Now)
- Manual entry for all sources
- Quick sidebar entry
- Email parsing (paste content)
- Source tracking
- Analytics by source

### 🔄 Phase 2 (This Month)
- IMAP automatic email import (Gmail integration)
- Scheduled job every 30 minutes
- *(Other sources can be added similarly)*

### 🚀 Phase 3 (Next Quarter)
- Instagram API auto-import
- Facebook Pixel integration
- Website form auto-capture
- Webhook integrations

---

## Reporting & Insights

### Weekly Review Checklist
- [ ] Check leads by source distribution
- [ ] Review conversion rate by channel
- [ ] Identify best performing source
- [ ] Check for bottlenecks in pipeline
- [ ] Ensure follow-ups are on schedule

### Monthly Analysis
- [ ] Compare source performance
- [ ] Calculate cost-per-lead (if applicable)
- [ ] Identify trends
- [ ] Adjust marketing focus
- [ ] Plan optimizations

---

## Tips & Tricks

✅ **Use priorities strategically:**
- High: High-value leads from best channels
- Medium: Regular leads
- Low: Initial interest, long-term

✅ **Leverage source details:**
- Showroom location for regional analysis
- Social platform for engagement strategy
- Website traffic source for marketing ROI
- Call outcome for script improvement

✅ **Set realistic follow-ups:**
- Email: 1 day
- Showroom: 2 days
- Social: 2-3 hours
- Website: Same day
- Call: 1 day

✅ **Use notes effectively:**
- Record all interactions
- Document objections
- Track engagement level
- Link to follow-up actions

---

## FAQ

**Q: Can I edit a lead after creation?**  
A: Yes, click on the lead in the list → "Quick Update" section

**Q: How do I change a lead's source?**  
A: Edit lead → update SOURCE field in Google Sheets

**Q: Why isn't email import working?**  
A: Check app password is correct in GitHub secrets

**Q: Can I bulk import leads?**  
A: Currently manual, but can be added. Let me know!

**Q: How long is data kept?**  
A: All leads kept in LEADS sheet. Archive in separate sheet if needed.

---

## Contact & Support

For questions about lead management, email integration, or feature requests, contact your development team.

Last Updated: 29 Apr 2026
