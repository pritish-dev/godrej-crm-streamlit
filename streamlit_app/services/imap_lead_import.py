"""
IMAP Email Lead Import Service

Reads emails from 4sinteriorsbbsr@gmail.com and imports lead information.
Uses same credential loading pattern as email_sender.py
"""

import imaplib
import email
import os
import re
import pandas as pd
from email.header import decode_header
from datetime import datetime
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df, write_df


# ═════════════════════════════════════════════════════════════════════════════
# CREDENTIAL LOADING (Same pattern as email_sender.py)
# ═════════════════════════════════════════════════════════════════════════════

SENDER_EMAIL = None
SENDER_PASSWORD = None

# 1. Try environment variables (GitHub Actions)
try:
    env_email = os.getenv("EMAIL_SENDER", "").strip()
    env_password = os.getenv("EMAIL_PASSWORD", "").strip()

    if env_email and env_password:
        SENDER_EMAIL = env_email
        SENDER_PASSWORD = env_password
except Exception:
    pass

# 2. Try Streamlit secrets (local development)
if SENDER_EMAIL is None:
    try:
        import streamlit as st
        try:
            SENDER_EMAIL = st.secrets["admin"]["EMAIL_SENDER"]
            SENDER_PASSWORD = st.secrets["admin"]["EMAIL_PASSWORD"]
        except:
            SENDER_EMAIL = st.secrets["EMAIL_SENDER"]
            SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    except Exception:
        pass

# 3. Try .env file (local development)
if SENDER_EMAIL is None:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
        env_email = os.getenv("EMAIL_SENDER", "").strip()
        env_password = os.getenv("EMAIL_PASSWORD", "").strip()

        if env_email and env_password:
            SENDER_EMAIL = env_email
            SENDER_PASSWORD = env_password
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# EMAIL PARSING
# ═════════════════════════════════════════════════════════════════════════════

def parse_email_body(body_text: str) -> dict:
    """Extract lead details from email body"""

    result = {
        "lead_name": "",
        "assigned_to": "",
        "salesforce_url": "",
        "company": "",
        "email": "",
        "phone": ""
    }

    # Extract lead name - look for quoted text "Lead Name"
    lead_match = re.search(r'lead\s+"([^"]+)"', body_text, re.IGNORECASE)
    if lead_match:
        result["lead_name"] = lead_match.group(1).strip()

    # Extract assigned to - look for "Queue - NAME" pattern
    assigned_match = re.search(r'Queue\s*[-:]?\s*([A-Z][A-Z\s]+?)(?:\.|,|$)', body_text, re.IGNORECASE)
    if assigned_match:
        assigned_name = assigned_match.group(1).strip()
        if assigned_name:
            result["assigned_to"] = assigned_name

    # Extract Salesforce URL
    url_match = re.search(r'https?://[^\s\)]+', body_text)
    if url_match:
        result["salesforce_url"] = url_match.group(0)

    # Extract email if present
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', body_text)
    if email_match:
        result["email"] = email_match.group(0)

    # Extract phone if present
    phone_match = re.search(r'\b\d{10}\b|\+91\s?\d{10}\b', body_text)
    if phone_match:
        result["phone"] = phone_match.group(0)

    return result


def decode_email_content(payload):
    """Decode email content (handle different encodings)"""
    try:
        if isinstance(payload, str):
            return payload

        data = payload.get('data', '')
        if data:
            import base64
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        return ""
    except Exception as e:
        print(f"Error decoding email: {e}")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# IMAP CONNECTION & LEAD IMPORT
# ═════════════════════════════════════════════════════════════════════════════

def connect_to_gmail(email_user: str, app_password: str):
    """Connect to Gmail via IMAP using app password"""
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com', 993)
        mail.login(email_user, app_password)
        return mail
    except imaplib.IMAP4.error as e:
        print(f"❌ Failed to connect to Gmail: {e}")
        raise


def fetch_lead_emails(mail):
    """Fetch unread emails with 'Lead' in subject"""
    try:
        # Select inbox
        mail.select('INBOX')

        # Search for unread emails with 'Lead' in subject
        status, messages = mail.search(None, '(UNSEEN SUBJECT "Lead")')

        if status != 'OK':
            print("No unread emails found")
            return []

        message_ids = messages[0].split()
        print(f"Found {len(message_ids)} unread emails with 'Lead' in subject")

        lead_emails = []

        for msg_id in message_ids[-10:]:  # Last 10 emails
            try:
                status, msg_data = mail.fetch(msg_id, '(RFC822)')

                if status != 'OK':
                    continue

                msg = email.message_from_bytes(msg_data[0][1])

                # Extract subject
                subject = decode_header(msg.get('Subject', ''))[0][0]
                if isinstance(subject, bytes):
                    subject = subject.decode('utf-8', errors='ignore')

                # Extract body
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == 'text/plain':
                            body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                            break
                else:
                    body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

                if body.strip():
                    parsed = parse_email_body(body)
                    if parsed['lead_name']:
                        lead_emails.append({
                            'msg_id': msg_id,
                            'subject': subject,
                            'parsed': parsed
                        })

            except Exception as e:
                print(f"Error processing email {msg_id}: {e}")
                continue

        return lead_emails

    except Exception as e:
        print(f"Error fetching emails: {e}")
        return []


def import_lead_to_sheet(lead_data: dict):
    """Import lead to LEADS sheet"""
    try:
        df = get_df("LEADS")

        if df is None or df.empty:
            df = pd.DataFrame()
            next_id = 1
        else:
            df.columns = [str(c).strip().upper() for c in df.columns]
            next_id = len(df) + 1

        # NOTE: ASSIGNED TO is intentionally left empty.
        # Sales team will manually assign leads after viewing Salesforce details.
        # The assigned_to info from email is stored in notes for reference.
        assigned_to_from_email = lead_data.get("assigned_to", "")

        new_lead = {
            "LEAD ID": str(next_id),
            "LEAD NAME": lead_data.get("lead_name", ""),
            "COMPANY": lead_data.get("company", ""),
            "EMAIL": lead_data.get("email", ""),
            "PHONE": lead_data.get("phone", ""),
            "ADDRESS": lead_data.get("address", ""),
            "STATUS": "🟢 New",
            "PRIORITY": "Medium",
            "SOURCE": "Email (OneCRM)",
            "SOURCE_DETAILS": "Salesforce Lead Assignment",
            "ASSIGNED TO": "",  # ← Intentionally empty - manual assignment by sales team
            "SALESFORCE URL": lead_data.get("salesforce_url", ""),
            "CREATED DATE": datetime.now().strftime("%d-%m-%Y %H:%M"),
            "LAST CONTACT": "",
            "FOLLOW UP DATE": (datetime.now() + pd.Timedelta(days=1)).strftime("%d-%m-%Y"),
            "NOTES": f"Salesforce Lead Assignment: {assigned_to_from_email}\nSalesforce URL: {lead_data.get('salesforce_url', 'N/A')}\nImported from email - Sales team to assign manually.",
            "CONVERSION DATE": "",
            "DEAL VALUE": "0"
        }

        df = pd.concat([df, pd.DataFrame([new_lead])], ignore_index=True)
        write_df("LEADS", df)

        print(f"✅ Lead '{lead_data.get('lead_name')}' imported successfully (Unassigned - Manual assignment pending)")
        return True

    except Exception as e:
        print(f"❌ Error importing lead: {e}")
        return False


def mark_email_as_read(mail, msg_id):
    """Mark email as read"""
    try:
        mail.store(msg_id, '+FLAGS', '\\Seen')
    except Exception as e:
        print(f"Error marking email as read: {e}")


def process_lead_emails():
    """Main function to fetch and import lead emails"""
    print("\n" + "="*70)
    print("🔍 Starting Lead Email Import Process")
    print(f"📧 Email: {SENDER_EMAIL}")
    print("="*70)

    # Validate credentials
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("❌ Email credentials not found in environment, secrets, or .env file")
        return 0

    try:
        # Connect to Gmail
        mail = connect_to_gmail(SENDER_EMAIL, SENDER_PASSWORD)

        # Fetch lead emails
        lead_emails = fetch_lead_emails(mail)

        if not lead_emails:
            print("✅ No new lead emails to process")
            mail.close()
            mail.logout()
            return 0

        # Process each email
        imported_count = 0
        for email_data in lead_emails:
            if import_lead_to_sheet(email_data['parsed']):
                mark_email_as_read(mail, email_data['msg_id'])
                imported_count += 1

        mail.close()
        mail.logout()

        print(f"\n✅ Successfully imported {imported_count} leads from email")
        print("="*70 + "\n")

        return imported_count

    except Exception as e:
        print(f"❌ Error in email import process: {e}")
        return 0


# ═════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    process_lead_emails()
