import urllib.parse
import pandas as pd
from datetime import datetime, timedelta
import pytz
from services.sheets import get_df

# --- CONTACT CONSTANTS ---
PRITISH_NUMBER = "918867143707" # Your Number
SHAKTIMAN_NUMBER = "919000000000" # Replace with actual Shaktiman Number

def format_phone(num):
    if not num: return ""
    digits = "".join(filter(str.isdigit, str(num)))
    if len(digits) == 10: return "91" + digits
    return digits

def clean_headers(df):
    df.columns = [c.strip().upper() for c in df.columns]
    return df

def create_whatsapp_tabular_list(df_group):
    """Creates a clean text-based table for WhatsApp"""
    table_text = "*DD | Customer | Phone | Products | OrderDate*\n"
    table_text += "------------------------------------------\n"
    
    for _, row in df_group.iterrows():
        dd = row["CUSTOMER DELIVERY DATE (TO BE)"].strftime('%d-%b')
        cust = row["CUSTOMER NAME"][:12] # Truncate for mobile view
        ph = str(row["CONTACT NUMBER"])[-10:]
        prods = row["PRODUCT NAME"][:15]
        od = row["DATE"].strftime('%d-%b') if pd.notnull(row["DATE"]) else "N/A"
        
        table_text += f"📅 {dd} | {cust} | {ph} | {prods} | 📝 {od}\n"
    
    table_text += "------------------------------------------\n"
    return table_text

def get_delivery_alerts_list(is_test=False):
    """Generates the tabular alerts for SP, Manager, and Pritish"""
    df = get_df("CRM")
    team_df = get_df("Sales Team")
    if df is None or df.empty: return []
    
    df = clean_headers(df)
    # Standardize types
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors='coerce')
    
    # Filter for Pending
    df = df[df["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"]
    df = df.dropna(subset=["CUSTOMER DELIVERY DATE (TO BE)"])

    # Sales Team Contacts
    contacts = {str(r.get("NAME", "")).strip().lower(): format_phone(r.get("CONTACT NUMBER", "")) 
                for _, r in team_df.iterrows()} if team_df is not None else {}

    alerts = []
    # Group by Sales Person to send them their specific list
    for sp_name, group in df.groupby("SALES PERSON"):
        sp_name_clean = str(sp_name).strip().lower()
        sp_phone = contacts.get(sp_name_clean)
        
        # Create Table
        table_content = create_whatsapp_tabular_list(group)
        
        message = (
            f"Dear *{sp_name}*,\n\n"
            f"Below are the pending Deliveries that need to be scheduled:\n\n"
            f"{table_content}\n"
            f"Please take necessary action."
        )

        # Recipients: 1. Sales Person, 2. Shaktiman, 3. Pritish
        recipients = [
            (f"SP: {sp_name}", sp_phone),
            ("Manager Shaktiman", SHAKTIMAN_NUMBER),
            ("Pritish (Me)", PRITISH_NUMBER)
        ]

        for label, phone in recipients:
            if phone:
                alerts.append((label, phone, message))
                
    return alerts

def get_payment_alerts_list():
    """Same logic for Payments if needed, or focused on balance"""
    # Reuse the tabular logic above but filtered for payments
    return get_delivery_alerts_list() # Redirecting for simplicity or customize similarly

def generate_whatsapp_link(phone, message):
    encoded_msg = urllib.parse.quote(message)
    return f"https://api.whatsapp.com/send?phone={phone}&text={encoded_msg}"