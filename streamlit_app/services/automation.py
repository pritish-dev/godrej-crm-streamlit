# services/automation.py
import urllib.parse
import pandas as pd
from datetime import datetime, timedelta
from services.sheets import get_df

def format_phone(num):
    digits = "".join(filter(str.isdigit, str(num)))
    if len(digits) == 10:
        return "91" + digits
    return digits

def get_sales_team_contacts():
    df = get_df("Sales Team")
    contacts = {}
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            name = str(row.get("NAME", row.get("Name", ""))).strip().lower()
            phone = format_phone(row.get("CONTACT NUMBER", row.get("Contact Number", "")))
            if name and phone:
                contacts[name] = phone
    return contacts

def generate_whatsapp_link(phone, message):
    # This creates a link that opens WhatsApp with the message pre-filled
    encoded_msg = urllib.parse.quote(message)
    return f"https://wa.me/{phone}?text={encoded_msg}"

def get_delivery_alerts_list():
    """Returns a list of (phone, message) tuples for tomorrow's deliveries"""
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    today = datetime.today().date()
    target_date = today + timedelta(days=1)
    
    alerts = []
    
    # Standardizing column names to match your app.py logic
    df.columns = [c.strip().upper() for c in df.columns]
    
    for _, row in df.iterrows():
        try:
            # Match the date format you use in app.py (%d-%m-%Y)
            d_date = pd.to_datetime(row.get("CUSTOMER DELIVERY DATE (TO BE)"), format="%d-%m-%Y", errors='coerce').date()
        except: continue

        if d_date == target_date and str(row.get("DELIVERY REMARKS")).upper() == "PENDING":
            msg = f"🚚 *DELIVERY ALERT*\n\n*Customer:* {row.get('CUSTOMER NAME')}\n*Product:* {row.get('PRODUCT NAME')}\n*Order No:* {row.get('ORDER NO')}\n*Date:* {d_date}\n\n⚠️ Scheduled for tomorrow!"
            
            # Add Salesperson
            sp = str(row.get("SALES PERSON")).strip().lower()
            if sp in contacts:
                alerts.append((contacts[sp], msg))
            
            # Add Manager/Admin (Always CC these people)
            for boss in ["shaktiman", "pritish", "swati"]:
                if boss in contacts:
                    alerts.append((contacts[boss], msg))
    return alerts

def get_payment_alerts_list():
    """Returns a list of (phone, message) tuples for payments due in 7 days"""
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    target_date = datetime.today().date() + timedelta(days=7)
    
    alerts = []
    df.columns = [c.strip().upper() for c in df.columns]

    for _, row in df.iterrows():
        try:
            d_date = pd.to_datetime(row.get("CUSTOMER DELIVERY DATE (TO BE)"), format="%d-%m-%Y", errors='coerce').date()
        except: continue

        if d_date == target_date:
            try:
                order_amt = float(str(row.get("ORDER AMOUNT")).replace(",",""))
                adv = float(str(row.get("ADV RECEIVED")).replace(",",""))
                due = order_amt - adv
            except: due = 0

            if due > 0:
                msg = f"💰 *PAYMENT REMINDER*\n\n*Customer:* {row.get('CUSTOMER NAME')}\n*Due:* ₹{due:,.2f}\n*Delivery Date:* {d_date}\n\n⚠️ Payment required before delivery!"
                
                sp = str(row.get("SALES PERSON")).strip().lower()
                if sp in contacts:
                    alerts.append((contacts[sp], msg))
                
                for boss in ["shaktiman", "pritish", "swati"]:
                    if boss in contacts:
                        alerts.append((contacts[boss], msg))
    return alerts