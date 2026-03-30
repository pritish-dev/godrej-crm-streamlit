import urllib.parse
import pandas as pd
from datetime import datetime, timedelta
import pytz
from services.sheets import get_df

def format_phone(num):
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

def create_whatsapp_table(df_group, type="DELIVERY"):
    """Creates a text-based table for WhatsApp messages with safe numeric handling"""
    table_text = f"*Pending {type.title()}s:*\n"
    table_text += "--------------------------\n"
    
    for _, row in df_group.iterrows():
        # Helper to safely convert currency strings to numbers
        def clean_val(val):
            try:
                if pd.isna(val): return 0.0
                # Remove symbols and commas, then convert to float
                clean = str(val).replace('₹', '').replace(',', '').strip()
                return float(clean) if clean else 0.0
            except:
                return 0.0

        d_date = row["CUSTOMER DELIVERY DATE (TO BE)"].strftime('%d-%b') if pd.notnull(row["CUSTOMER DELIVERY DATE (TO BE)"]) else "N/A"
        order_amt = clean_val(row.get("ORDER AMOUNT", 0))
        adv_rec = clean_val(row.get("ADV RECEIVED", 0))
        due = order_amt - adv_rec
        
        if type == "DELIVERY":
            p_date = row["DATE"].strftime('%d-%b') if pd.notnull(row.get("DATE")) else "N/A"
            table_text += f"📅 *DD:* {d_date} | *PD:* {p_date}\n"
            table_text += f"👤 *Cust:* {row.get('CUSTOMER NAME', 'N/A')}\n"
            table_text += f"📞 *Ph:* {row.get('CONTACT NUMBER', 'N/A')}\n"
            table_text += f"🛋️ *Item:* {row.get('PRODUCT NAME', 'N/A')}\n"
            table_text += f"💰 *Adv:* ₹{adv_rec:,.0f} | *Due:* ₹{due:,.0f}\n"
        else: # PAYMENT
            table_text += f"📅 *Delivery Date:* {d_date}\n"
            table_text += f"👤 *Cust:* {row.get('CUSTOMER NAME', 'N/A')}\n"
            table_text += f"💰 *Balance Due:* ₹{due:,.0f}\n"
            
        table_text += "--------------------------\n"
    return table_text

def get_delivery_alerts_list():
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    IST = pytz.timezone('Asia/Kolkata')
    target_date = datetime.now(IST).date() + timedelta(days=1)
    
    df.columns = [c.strip().upper() for c in df.columns]
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors='coerce')
    
    mask = (df["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING") & \
           (df["CUSTOMER DELIVERY DATE (TO BE)"].dt.date == target_date)
    tomorrow_df = df[mask].copy()
    
    if tomorrow_df.empty: return []

    alerts = []
    for sp_name, group in tomorrow_df.groupby("SALES PERSON"):
        sp_name_clean = str(sp_name).strip().lower()
        table_msg = create_whatsapp_table(group, type="DELIVERY")
        final_msg = f"🚚 *DAILY DELIVERY ALERT*\n\nHello {sp_name.title()},\n\n{table_msg}\n⚠️ Please confirm transport!"
        
        recipients = set()
        if sp_name_clean in contacts: recipients.add(contacts[sp_name_clean])
        if "shaktiman" in contacts: recipients.add(contacts["shaktiman"])
        if "swati" in contacts: recipients.add(contacts["swati"])

        for phone in recipients:
            alerts.append((phone, final_msg))
    return alerts

def get_payment_alerts_list():
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    IST = pytz.timezone('Asia/Kolkata')
    target_date = datetime.now(IST).date() + timedelta(days=7) # Remind 7 days before
    
    df.columns = [c.strip().upper() for c in df.columns]
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    
    df["PENDING_AMT"] = pd.to_numeric(df["ORDER AMOUNT"], errors='coerce').fillna(0) - \
                        pd.to_numeric(df["ADV RECEIVED"], errors='coerce').fillna(0)
    
    mask = (df["PENDING_AMT"] > 0) & (df["CUSTOMER DELIVERY DATE (TO BE)"].dt.date == target_date)
    due_df = df[mask].copy()
    
    if due_df.empty: return []

    alerts = []
    for sp_name, group in due_df.groupby("SALES PERSON"):
        sp_name_clean = str(sp_name).strip().lower()
        table_msg = create_whatsapp_table(group, type="PAYMENT")
        final_msg = f"💰 *PAYMENT REMINDER*\n\nHello {sp_name.title()},\n\n{table_msg}\n⚠️ Follow up for payments before delivery!"
        
        recipients = set()
        if sp_name_clean in contacts: recipients.add(contacts[sp_name_clean])
        if "shaktiman" in contacts: recipients.add(contacts["shaktiman"])
        if "swati" in contacts: recipients.add(contacts["swati"])

        for phone in recipients:
            alerts.append((phone, final_msg))
    return alerts

def get_test_alerts_list():
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    df.columns = [c.strip().upper() for c in df.columns]
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors='coerce')
    
    test_df = df[df["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING"].head(3)
    if test_df.empty: return []
    
    sample_table = create_whatsapp_table(test_df, type="DELIVERY")
    test_msg = f"🧪 *TEST ALERT: TABULAR FORMAT*\n\n{sample_table}\n✅ Link is working!"
    
    alerts = []
    for boss in ["shaktiman", "swati"]:
        if boss in contacts:
            alerts.append((contacts[boss], test_msg))
    return alerts

def generate_whatsapp_link(phone, message):
    encoded_msg = urllib.parse.quote(message)
    return f"https://wa.me/{phone}?text={encoded_msg}"