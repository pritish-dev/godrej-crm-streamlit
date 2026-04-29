# 📧 Email Integration Guide - Lead Auto-Import

## Current Status: Manual Email Parsing ✅
Currently, you can paste email content to extract lead details. This guide explains how to set up automated email checking.

---

## Option 1: Gmail API Integration (Recommended)

### Prerequisites
- Google Workspace or Gmail account
- Access to Google Cloud Console
- Enable Gmail API

### Setup Steps

#### Step 1: Create Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project: **"Lead Import Automation"**
3. Enable Gmail API:
   - Search "Gmail API"
   - Click "Enable"

#### Step 2: Create OAuth 2.0 Credentials
1. Go to **Credentials** → **Create Credentials**
2. Choose **"OAuth client ID"**
3. Application type: **"Desktop application"**
4. Download JSON credentials file
5. Add to your project: `config/gmail_credentials.json`

#### Step 3: Create Lead Import Job
Create file: `services/gmail_lead_import.py`

```python
import base64
import re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pandas as pd
from services.sheets import get_df, write_df

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def authenticate_gmail():
    """Authenticate with Gmail API"""
    flow = InstalledAppFlow.from_client_secrets_file(
        'config/gmail_credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)
    return creds

def get_gmail_service(creds):
    """Build Gmail service"""
    return build('gmail', 'v1', credentials=creds)

def parse_email_body(body):
    """Extract lead details from email body"""
    result = {
        "lead_name": "",
        "assigned_to": "",
        "salesforce_url": "",
        "source": "Email"
    }
    
    lead_match = re.search(r'lead\s+"([^"]+)"', body, re.IGNORECASE)
    if lead_match:
        result["lead_name"] = lead_match.group(1).strip()
    
    assigned_match = re.search(r'Queue\s*[-:]?\s*([A-Z][A-Z\s]+?)(?:\.|$)', body)
    if assigned_match:
        result["assigned_to"] = assigned_match.group(1).strip()
    
    url_match = re.search(r'https?://[^\s\)]+', body)
    if url_match:
        result["salesforce_url"] = url_match.group(0)
    
    return result

def fetch_lead_emails(service):
    """Fetch emails with 'Lead' in subject"""
    try:
        results = service.users().messages().list(
            userId='me',
            q='subject:Lead is:unread',
            maxResults=10
        ).execute()
        
        messages = results.get('messages', [])
        
        for message in messages:
            msg = service.users().messages().get(
                userId='me',
                id=message['id'],
                format='full'
            ).execute()
            
            headers = msg['payload']['headers']
            subject = next(h['value'] for h in headers if h['name'] == 'Subject')
            
            if 'parts' in msg['payload']:
                data = msg['payload']['parts'][0]['body'].get('data', '')
            else:
                data = msg['payload']['body'].get('data', '')
            
            if data:
                email_body = base64.urlsafe_b64decode(data).decode('utf-8')
                
                lead_details = parse_email_body(email_body)
                
                if lead_details['lead_name']:
                    # Import to LEADS sheet
                    import_lead(lead_details)
                    
                    # Mark email as read
                    service.users().messages().modify(
                        userId='me',
                        id=message['id'],
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
        
        return len(messages)
    
    except Exception as e:
        print(f"Error fetching emails: {e}")
        return 0

def import_lead(lead_data):
    """Import lead to LEADS sheet"""
    df = get_df("LEADS")
    
    if df is None or df.empty:
        df = pd.DataFrame()
        next_id = 1
    else:
        df.columns = [str(c).strip().upper() for c in df.columns]
        next_id = len(df) + 1
    
    new_lead = {
        "LEAD ID": str(next_id),
        "LEAD NAME": lead_data.get("lead_name", ""),
        "STATUS": "🟢 New",
        "PRIORITY": "Medium",
        "SOURCE": "Email",
        "ASSIGNED TO": lead_data.get("assigned_to", "").upper(),
        "SALESFORCE URL": lead_data.get("salesforce_url", ""),
        "CREATED DATE": pd.Timestamp.now().strftime("%d-%m-%Y %H:%M"),
        "FOLLOW UP DATE": (pd.Timestamp.now() + pd.Timedelta(days=1)).strftime("%d-%m-%Y")
    }
    
    df = pd.concat([df, pd.DataFrame([new_lead])], ignore_index=True)
    write_df("LEADS", df)
    print(f"✅ Lead '{lead_data['lead_name']}' imported from email")

# Main execution
if __name__ == "__main__":
    creds = authenticate_gmail()
    service = get_gmail_service(creds)
    count = fetch_lead_emails(service)
    print(f"Processed {count} new lead emails")
```

#### Step 4: Schedule Job in GitHub Actions
Add to `.github/workflows/send_email.yaml`:

```yaml
  gmail-lead-import:
    runs-on: ubuntu-latest
    if: ${{ github.event_name == 'schedule' || github.event.inputs.manual_job == 'gmail_lead_import' }}
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: pip install google-auth google-auth-oauthlib google-auth-httplib2
      - name: Import leads from Gmail
        env:
          GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}
        run: python services/gmail_lead_import.py
```

---

## Option 2: Outlook Integration

### Similar to Gmail but using:
- Microsoft Graph API
- Outlook email service
- OAuth 2.0 with Azure AD

### Prerequisites
- Microsoft 365 account
- Azure AD application registration

### Setup (Similar process to Gmail)
1. Register app in Azure AD
2. Grant `Mail.Read` permissions
3. Implement similar to Gmail service

---

## Option 3: Email Forwarding

### Simplest Approach (No API needed)
1. Set up email filter in your email client
2. Forward all emails with "Lead" in subject to: `lead-import@yoursystem.com`
3. Create webhook to process forwarded emails
4. Extract lead details and store in LEADS sheet

### Advantages
- No API credentials needed
- Works with any email provider
- Easy to set up

---

## Option 4: Zapier/Make.com Integration

### Cloud-based Automation (No coding needed)

#### Steps:
1. Create account at [Zapier](https://zapier.com) or [Make](https://make.com)
2. Set trigger: **"New Email from Gmail/Outlook with Lead in subject"**
3. Set actions:
   - Parse email body
   - Extract lead name, assigned to, URL
   - Add row to Google Sheets (LEADS sheet)
4. Activate automation

**Cost:** Free tier available, usually $20-50/month for production

**Advantage:** No coding required, very quick setup

---

## Current Implementation Roadmap

### ✅ Phase 1 (Complete)
- Manual email parsing
- Lead creation form
- Status tracking
- Pipeline visualization

### 🔄 Phase 2 (Recommended Next)
Option: **Zapier Integration (Easiest)**
- Cost: Free or low monthly fee
- Setup time: 30 minutes
- Maintenance: Minimal

**Alternative:** Gmail API (More control, free)
- Setup time: 2-3 hours
- Maintenance: Moderate
- Cost: Free

### 🚀 Phase 3 (Future)
- Salesforce data sync
- Lead scoring automation
- Email reminders

---

## Configuration for Your Environment

### If you choose Gmail API:

1. **Store credentials in secrets:**
   ```yaml
   GMAIL_CREDENTIALS: <base64_encoded_credentials_json>
   ```

2. **Update `services/gmail_lead_import.py`:**
   ```python
   # Load from environment variable
   import json
   import base64
   creds_json = base64.b64decode(os.getenv('GMAIL_CREDENTIALS')).decode()
   creds_dict = json.loads(creds_json)
   ```

3. **Schedule frequency:**
   - Hourly: `0 * * * *` (every hour)
   - Every 30 minutes: `*/30 * * * *`
   - Every 4 hours: `0 */4 * * *`

---

## Testing Email Import

### Manual Test
1. Create test email with:
   ```
   Subject: Lead John Doe is assigned
   Body: The lead "John Doe" is moved to your Queue - TEST USER. 
   https://example.com/lead/123
   ```

2. Run import job manually

3. Check LEADS sheet for new entry

---

## Troubleshooting

### Gmail API errors:
- Check credentials are valid
- Ensure Gmail API is enabled in Google Cloud Console
- Verify scopes are correct

### Email not being imported:
- Check email subject contains "Lead"
- Verify email body format matches parsing rules
- Check job logs in GitHub Actions

### Salesforce URL extraction:
- Format must be valid URL
- Common formats:
  - `https://gnb.my.site.com/gbpartners/...`
  - `https://[instance].salesforce.com/...`

---

## My Recommendation

**For quick setup (Today):** Use Zapier
- No coding
- Reliable
- Minimal setup
- $0-50/month

**For full control (This week):** Implement Gmail API
- More powerful
- Customizable
- Free
- Requires some setup

**Next steps:**
1. Choose integration method
2. Provide me necessary credentials/access
3. I'll implement and test
4. Deploy to GitHub Actions

Let me know which option works best for your team!

---

Last Updated: 29 Apr 2026
