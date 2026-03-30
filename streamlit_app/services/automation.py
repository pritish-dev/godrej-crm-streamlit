import urllib.parse
import pandas as pd
from datetime import datetime, timedelta
import pytz
from services.sheets import get_df

# Your specific number as the 'Me' contact
MY_NUMBER = "918867143707"

def format_phone(num):
    if not num: return ""
    digits = "".join(filter(str.isdigit, str(num)))
    if len(digits) == 10: return "91" + digits
    return digits

def get_sales_team_contacts():
    df = get_df("Sales Team")
    contacts = {}
    if df is not None and not df.empty:
        df.columns = [c.strip().upper() for c in df.columns]
        for _, row in df.iterrows():
            name = str(row.get("NAME", "")).strip().lower()
            phone = format_phone(row.get("CONTACT NUMBER", ""))
            if name and phone: contacts[name] = phone
    return contacts

def create_whatsapp_table(df_group, type_label="DELIVERY"):
    """Creates a text-based table for WhatsApp messages with safe numeric handling"""
    table_text = f"*Pending {type_label.title()}s List:*\n"
    table_text += "--------------------------\n"
    
    for _, row in df_group.iterrows():
        def clean_val(val):
            try:
                if pd.isna(val): return 0.0
                clean = str(val).replace('₹', '').replace(',', '').strip()
                return float(clean) if clean else 0.0
            except: return 0.0

        d_date = row["CUSTOMER DELIVERY DATE (TO BE)"].strftime('%d-%b') if pd.notnull(row["CUSTOMER DELIVERY DATE (TO BE)"]) else "N/A"
        p_date = row["DATE"].strftime('%d-%b') if pd.notnull(row.get("DATE")) else "N/A"
        
        order_amt = clean_val(row.get("ORDER AMOUNT", 0))
        adv_rec = clean_val(row.get("ADV RECEIVED", 0))
        due = order_amt - adv_rec
        
        table_text += f"📅 *DD:* {d_date} | *PD:* {p_date}\n"
        table_text += f"👤 *Cust:* {row.get('CUSTOMER NAME', 'N/A')}\n"
        table_text += f"📞 *Ph:* {row.get('CONTACT NUMBER', 'N/A')}\n"
        table_text += f"🛋️ *Item:* {row.get('PRODUCT NAME', 'N/A')}\n"
        table_text += f"💰 *Adv:* ₹{adv_rec:,.0f} | *Due:* ₹{due:,.0f}\n"
        table_text += "--------------------------\n"
    return table_text

def get_delivery_alerts_list(is_test=False):
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    IST = pytz.timezone('Asia/Kolkata')
    
    df.columns = [c.strip().upper() for c in df.columns]
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors='coerce')
    
    if is_test:
        mask = (df["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING")
        display_label = "TEST RUN"
        alert_df = df[mask].head(10).copy() 
    else:
        target_date = datetime.now(IST).date() + timedelta(days=1)
        mask = (df["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING") & \
               (df["CUSTOMER DELIVERY DATE (TO BE)"].dt.date == target_date)
        display_label = "DAILY ALERT"
        alert_df = df[mask].copy()
    
    if alert_df.empty: return []

    alerts = []
    for sp_name, group in alert_df.groupby("SALES PERSON"):
        sp_name_clean = str(sp_name).strip().lower()
        table_msg = create_whatsapp_table(group, type_label="DELIVERY")
        final_msg = f"🚚 *{display_label}*\n\nHello {sp_name.title()},\n\nBelow are the pending deliveries to be scheduled:\n\n{table_msg}\n⚠️ Confirm transport for these orders!"
        
        recipients = [
            (sp_name.title(), contacts.get(sp_name_clean)),
            ("Manager Shaktiman", contacts.get("shaktiman")),
            ("Pritish (Admin)", MY_NUMBER)
        ]

        for label, phone in recipients:
            if phone:
                alerts.append((f"{label} ({phone})", phone, final_msg))
    return alerts

def get_payment_alerts_list():
    """Groups payment reminders for deliveries happening in 7 days"""
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    IST = pytz.timezone('Asia/Kolkata')
    target_date = datetime.now(IST).date() + timedelta(days=7)
    
    df.columns = [c.strip().upper() for c in df.columns]
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors='coerce')
    
    # Filter: Has Pending Amount AND Delivery is in 7 days
    df["TEMP_DUE"] = pd.to_numeric(df["ORDER AMOUNT"].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0) - \
                     pd.to_numeric(df["ADV RECEIVED"].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    mask = (df["TEMP_DUE"] > 0) & (df["CUSTOMER DELIVERY DATE (TO BE)"].dt.date == target_date)
    pay_df = df[mask].copy()
    
    if pay_df.empty: return []

    alerts = []
    for sp_name, group in pay_df.groupby("SALES PERSON"):
        sp_name_clean = str(sp_name).strip().lower()
        table_msg = create_whatsapp_table(group, type_label="PAYMENT")
        final_msg = f"💰 *PAYMENT REMINDER*\n\nHello {sp_name.title()},\n\nBelow are orders with pending payments due for delivery in 7 days:\n\n{table_msg}\n⚠️ Please follow up for balance payments!"
        
        recipients = [
            (sp_name.title(), contacts.get(sp_name_clean)),
            ("Manager Shaktiman", contacts.get("shaktiman")),
            ("Swati (Admin)", MY_NUMBER)
        ]

        for label, phone in recipients:
            if phone:
                alerts.append((f"{label} ({phone})", phone, final_msg))
    return alerts

def generate_whatsapp_link(phone, message):
    """Generates the link specifically for WhatsApp Web direct messaging"""
    encoded_msg = urllib.parse.quote(message)
    # Using 'web.whatsapp.com/send' instead of 'wa.me' for better desktop behavior
    return f"https://web.whatsapp.com/send?phone={phone}&text={encoded_msg}"