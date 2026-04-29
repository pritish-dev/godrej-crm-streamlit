# 🎯 Leads Management Page - Setup & Features Guide

## Overview
Comprehensive sales lead management system integrated with email parsing and Google Sheets backend. Designed for sales teams to track, qualify, and convert leads efficiently.

---

## Quick Start

### 1. **Access the Leads Page**
- Open your Streamlit dashboard
- Navigate to **"🎯 Leads Management"** in the sidebar
- Page URL: `/Leads`

### 2. **Create Your First Lead**

#### Option A: Parse from Email
1. Click **"➕ Add New Lead"** expander
2. Go to **"📧 Parse from Email"** tab
3. Paste the entire email body containing the lead information
4. Click **"🔍 Parse Email"**
5. Review extracted details in JSON format
6. Click **"✏️ Manual Entry"** tab to proceed

#### Option B: Manual Entry
1. Click **"➕ Add New Lead"** expander
2. Go to **"✏️ Manual Entry"** tab
3. Fill in lead details:
   - **Lead Name** (Required)
   - **Company Name**
   - **Email Address**
   - **Phone Number**
   - **Status** (New → Contacted → Qualified → Proposal Sent → Converted/Lost)
   - **Priority** (High/Medium/Low)
   - **Assign to Sales Person**
   - **Follow Up Date**
   - **Expected Deal Value**
   - **Notes**
4. Click **"➕ Create Lead"**

---

## Features Explained

### 📊 Leads Overview Metrics
- **Total Leads:** Total leads in the system
- **New:** Leads not yet contacted
- **Qualified:** Leads in Qualified or Proposal Sent stage
- **Converted:** Closed-won leads
- **Conversion Rate:** % of leads converted to deals

### 🔍 Filtering & Sorting
**Filter by:**
- Status (New, Contacted, Qualified, Proposal Sent, Converted, Lost)
- Priority (High, Medium, Low)
- Sales Person (who the lead is assigned to)

**Sort by:**
- Lead Name (A-Z)
- Created Date (newest first)
- Follow Up Date (soonest first)
- Deal Value (highest first)

### 👤 Lead Details Expandable Card
When you click on a lead, it expands to show:
- **Contact Information:** Email, Phone, Company
- **Status & Assignment:** Current status, assigned sales person
- **Dates:** When created, last contact, follow-up date
- **Notes:** Any comments or activity notes
- **Salesforce Link:** Direct link to the lead in Salesforce CRM

#### Quick Update Section
- Update lead status immediately
- Change follow-up date
- System automatically records "Last Contact" when you save

### 📈 Sales Pipeline
Visual representation showing:
- Count of leads in each stage
- Percentage distribution across stages
- Conversion funnel (New → Contacted → Qualified → Converted)

**Pipeline Stages:**
1. 🟢 **New** - Just created, not contacted
2. 🔵 **Contacted** - Initial contact made
3. 🟡 **Qualified** - Assessed as potential customer
4. 🟣 **Proposal Sent** - Awaiting decision
5. 🟢 **Converted** - Closed-won deal
6. 🔴 **Lost** - Deal lost/disqualified

### 📅 Upcoming Follow-ups
Shows all leads with follow-up dates in the next 7 days:
- Lead name and company
- Follow-up date
- Assigned sales person
- Current status

**Use Case:** Plan your week and ensure no leads are forgotten!

### 👥 Performance by Sales Person
Table showing each sales person's metrics:
- **Total Leads:** How many leads assigned to them
- **Converted:** How many converted to deals
- **Conversion Rate %:** Conversion efficiency
- **Average Deal Value:** Expected value per deal

---

## Email Parsing Logic

### How Email Parsing Works
The system uses regex pattern matching to extract:

1. **Lead Name:** Looks for quoted text in pattern `"Lead Name"`
   - Example: `"Aparajeeta Tripathy"`

2. **Assigned To:** Extracts from `Queue - NAME` pattern
   - Example: `Queue - SUBRAT KUMAR SENAPATI`

3. **Salesforce URL:** Extracts first URL found
   - Example: `https://gnb.my.site.com/gbpartners/00QOW000...`

### Email Format Expectations
```
Hi,
The lead "Lead Name" is moved to your Queue - SALES PERSON NAME. 
You may click on the link to view details - https://url.to.lead
Thanks,
Company Name
```

### What Gets Extracted
```json
{
  "lead_name": "Aparajeeta Tripathy",
  "assigned_to": "SUBRAT KUMAR SENAPATI",
  "salesforce_url": "https://gnb.my.site.com/gbpartners/00QOW00000jskiH",
  "source": "Email"
}
```

---

## Lead Status Flow

```
🟢 New
  ↓
🔵 Contacted
  ↓
🟡 Qualified (or 🔴 Lost)
  ↓
🟣 Proposal Sent (or 🔴 Lost)
  ↓
🟢 Converted (or 🔴 Lost)
```

### Status Definitions

| Status | Meaning | Action |
|--------|---------|--------|
| 🟢 New | Lead just created, no contact | Call/Email to introduce |
| 🔵 Contacted | Initial conversation done | Qualify if suitable |
| 🟡 Qualified | Confirmed as potential customer | Send proposal/quotation |
| 🟣 Proposal Sent | Waiting for decision | Follow up on proposal |
| 🟢 Converted | Deal closed, won customer | Handover to fulfillment |
| 🔴 Lost | Lead rejected or disqualified | Archive and reason |

---

## Google Sheets Structure (LEADS Sheet)

The system stores leads in Google Sheets with these columns:

| Column | Type | Example | Notes |
|--------|------|---------|-------|
| LEAD ID | Number | 1, 2, 3... | Auto-generated |
| LEAD NAME | Text | Aparajeeta Tripathy | Required |
| COMPANY | Text | ABC Corp | Optional |
| EMAIL | Email | lead@company.com | Optional |
| PHONE | Phone | 9876543210 | Optional |
| STATUS | Dropdown | 🟢 New | Required |
| PRIORITY | Dropdown | High/Medium/Low | Default: Medium |
| SOURCE | Text | Email/Manual/LinkedIn | Auto-filled |
| ASSIGNED TO | Text | SUBRAT KUMAR SENAPATI | Optional |
| SALESFORCE URL | URL | https://... | Auto-extracted from email |
| CREATED DATE | Date | 28-Apr-2026 | Auto-timestamp |
| LAST CONTACT | Date | 28-Apr-2026 14:30 | Auto-updated |
| FOLLOW UP DATE | Date | 01-May-2026 | User-set |
| NOTES | Text | Customer interested... | Multi-line |
| CONVERSION DATE | Date | 05-May-2026 | Auto-filled on conversion |
| DEAL VALUE | Currency | 500000 | Expected revenue (₹) |

---

## Advanced Features

### 1. **Email Integration Options**

#### Option A: Manual Email Copy-Paste (Current)
- Copy email content and paste in the parse box
- Best for: Low volume, getting started quickly

#### Option B: Gmail API Integration (Future)
- Automatically reads emails from your Gmail account
- Filters emails with "Lead" in subject
- Scheduled task to check every hour
- Best for: High volume, automation

#### Option C: Outlook Integration (Future)
- Similar to Gmail but for Microsoft 365
- Scheduled sync

#### Option D: Email Forwarding
- Set up email forwarding rule to send lead emails to a specific address
- System monitors and auto-imports

### 2. **Salesforce URL Handling**

**Current:** URL stored as reference link
- Click to view full lead details in Salesforce
- Requires you to login to Salesforce separately

**Future Enhancement:** Salesforce API Integration
- Would auto-fetch lead details from Salesforce
- Sync lead status between systems
- Requires Salesforce API credentials

### 3. **Automated Follow-up Reminders**

**Current:** Upcoming Follow-ups section shows next 7 days

**Future:** Email reminders
- Daily email with all follow-ups due that day
- Customizable reminders per lead

### 4. **Lead Scoring**

**Planned Feature:** Automatic scoring based on:
- Response time to first contact
- Company size/industry
- Deal value
- Engagement level

---

## Best Practices

### 📋 Lead Organization

1. **Weekly Pipeline Review**
   - Check "Sales Pipeline" section
   - Identify bottlenecks
   - Move stuck deals forward

2. **Daily Follow-up Management**
   - Check "Upcoming Follow-ups" section
   - Schedule calls/emails accordingly
   - Update status after contact

3. **Regular Status Updates**
   - Don't leave leads in "New" too long
   - Contact within 24 hours of receiving
   - Update status after every interaction

### 🎯 Sales Best Practices

1. **Set Realistic Follow-up Dates**
   - New leads: within 24-48 hours
   - Qualified: within 1 week
   - Proposal sent: within 3-5 days

2. **Use Deal Values**
   - Helps prioritize leads by potential value
   - Track total pipeline value
   - Forecast revenue

3. **Document Everything**
   - Use Notes field for all interactions
   - Record call/email content
   - Help team continuity if lead reassigned

4. **Regular Performance Review**
   - Weekly: Check your conversion rate
   - Monthly: Compare team performance
   - Identify top performers and tactics

---

## Troubleshooting

### Issue: Email parsing not extracting lead name
**Solution:** 
- Ensure email contains text like `"Lead Name"` (with quotes)
- Check email format matches expected pattern
- Manually enter lead name in Manual Entry tab

### Issue: Sales person name not found in dropdown
**Solution:**
- Ensure sales person exists in "Sales Team" sheet
- Their role must be "SALES"
- Name must match exactly (case-insensitive)
- Wait for cache to refresh (60 seconds)

### Issue: Salesforce URL link not working
**Solution:**
- Verify URL is valid and accessible
- You must be logged into Salesforce
- URL format should be: `https://[instance].my.site.com/...`

### Issue: Follow-up dates not sorting correctly
**Solution:**
- Use date picker when entering follow-up dates
- Don't enter text dates manually
- Format should be: DD-MM-YYYY

---

## Integration Timeline

### ✅ Current (Implemented)
- Manual lead creation
- Email parsing from pasted content
- Lead filtering & sorting
- Status tracking
- Performance metrics
- Pipeline visualization
- Upcoming follow-ups

### 🔄 Planned (Next Phase)
- Gmail API integration for auto-import
- Outlook API integration
- Lead scoring system
- Automated email reminders
- Bulk lead import from CSV
- Lead reassignment bulk actions
- Custom fields per company
- Lead source attribution

### 🚀 Future (Phase 3)
- Salesforce real-time sync
- AI-powered lead scoring
- Prediction models
- Integration with payment gateway for conversions
- Mobile app support

---

## Tips & Tricks

✅ **Use Priority field strategically**
- High: Close ASAP, high value, decision-maker available
- Medium: Normal sales cycle, good fit
- Low: Long-term, exploratory, lower value

✅ **Set follow-up dates in the future**
- Helps you plan workload
- Upcoming Follow-ups section uses these dates
- System won't remind for past dates

✅ **Use consistent company names**
- Easier to filter and analyze
- Better reporting accuracy

✅ **Leverage deal values**
- Pipeline value = sum of all (converted leads × deal value)
- Helps forecast revenue
- Identify high-value opportunities

✅ **Document deal-blockers**
- Use Notes to record why leads were lost
- Learn patterns for future improvements

---

## Contact & Support

For questions or feature requests, contact your CRM administrator or development team.

Last Updated: 29 Apr 2026
