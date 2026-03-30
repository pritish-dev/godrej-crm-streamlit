import urllib.parse
import pandas as pd
from datetime import datetime, timedelta
import pytz
from services.sheets import get_df

MY_NUMBER = "918867143707"

def format_phone(num):
    if not num: return ""
    digits = "".join(filter(str.isdigit, str(num)))
    if len(digits) == 10: return "91" + digits
    return digits

def create_whatsapp_table(df_group, type_label="DELIVERY"):
    """Groups items by Customer and creates a text table"""
    table_text = f"*Pending {type_label.title()}s List:*\n"
    table_text += "--------------------------\n"
    
    # --- NEW CLUBBING LOGIC ---
    # Group by Customer Name and Number to combine multiple items
    grouped_cust = df_group.groupby(["CUSTOMER NAME", "CONTACT NUMBER"])
    
    for (cust_name, cust_phone), cust_data in grouped_cust:
        def clean_val(val):
            try:
                if pd.isna(val): return 0.0
                clean = str(val).replace('₹', '').replace(',', '').strip()
                return float(clean) if clean else 0.0
            except: return 0.0

        # Club multiple products into one string
        items_list = ", ".join(cust_data["PRODUCT NAME"].astype(str).unique())
        
        # Take the earliest dates and sum the amounts
        d_date = cust_data["CUSTOMER DELIVERY DATE (TO BE)"].min().strftime('%d-%b') if pd.notnull(cust_data["CUSTOMER DELIVERY DATE (TO BE)"].min()) else "N/A"
        order_amt = cust_data["ORDER AMOUNT"].apply(clean_val).sum()
        adv_rec = cust_data["ADV RECEIVED"].apply(clean_val).sum()
        due = order_amt - adv_rec
        
        table_text += f"👤 *Cust:* {cust_name}\n"
        table_text += f"📞 *Ph:* {cust_phone}\n"
        table_text += f"🛋️ *Items:* {items_list}\n"
        table_text += f"📅 *DD:* {d_date}\n"
        table_text += f"💰 *Total Due:* ₹{due:,.0f}\n"
        table_text += "--------------------------\n"
    return table_text

def get_delivery_alerts_list(is_test=False):
    df = get_df("CRM")
    team_df = get_df("Sales Team")
    contacts = {}
    if team_df is not None and not team_df.empty:
        team_df.columns = [c.strip().upper() for c in team_df.columns]
        for _, r in team_df.iterrows():
            name = str(r.get("NAME", "")).strip().lower()
            phone = format_phone(r.get("CONTACT NUMBER", ""))
            if name and phone: contacts[name] = phone

    IST = pytz.timezone('Asia/Kolkata')
    df.columns = [c.strip().upper() for c in df.columns]
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    
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
        final_msg = f"🚚 *{display_label}*\n\nHello {sp_name.title()},\n\nGrouped pending deliveries:\n\n{table_msg}\n⚠️ Confirm transport!"
        
        rec_list = [(sp_name.title(), contacts.get(sp_name_clean)), ("Manager Shaktiman", contacts.get("shaktiman")), ("Swati (Admin)", MY_NUMBER)]
        for label, phone in rec_list:
            if phone: alerts.append((label, phone, final_msg))
    return alerts

def get_payment_alerts_list():
    df = get_df("CRM")
    team_df = get_df("Sales Team")
    contacts = {str(r.get("NAME", "")).strip().lower(): format_phone(r.get("CONTACT NUMBER", "")) 
                for _, r in team_df.iterrows()} if team_df is not None else {}

    IST = pytz.timezone('Asia/Kolkata')
    target_date = datetime.now(IST).date() + timedelta(days=7)
    df.columns = [c.strip().upper() for c in df.columns]
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    
    mask = (df["CUSTOMER DELIVERY DATE (TO BE)"].dt.date == target_date)
    pay_df = df[mask].copy()
    if pay_df.empty: return []

    alerts = []
    for sp_name, group in pay_df.groupby("SALES PERSON"):
        sp_name_clean = str(sp_name).strip().lower()
        table_msg = create_whatsapp_table(group, type_label="PAYMENT")
        final_msg = f"💰 *PAYMENT REMINDER*\n\nHello {sp_name.title()},\n\nGrouped payments due in 7 days:\n\n{table_msg}"
        
        rec_list = [(sp_name.title(), contacts.get(sp_name_clean)), ("Manager Shaktiman", contacts.get("shaktiman")), ("Swati (Admin)", MY_NUMBER)]
        for label, phone in rec_list:
            if phone: alerts.append((label, phone, final_msg))
    return alerts

def generate_whatsapp_link(phone, message):
    encoded_msg = urllib.parse.quote(message)
    return f"https://api.whatsapp.com/send?phone={phone}&text={encoded_msg}"