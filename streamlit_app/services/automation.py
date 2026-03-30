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

def create_whatsapp_table(df_group):
    """Creates a text-based table for WhatsApp messages"""
    table_text = "*Deliveries to Schedule:*\n"
    table_text += "--------------------------\n"
    
    for _, row in df_group.iterrows():
        d_date = row["CUSTOMER DELIVERY DATE (TO BE)"].strftime('%d-%b') if pd.notnull(row["CUSTOMER DELIVERY DATE (TO BE)"]) else "N/A"
        p_date = row["DATE"].strftime('%d-%b') if pd.notnull(row["DATE"]) else "N/A"
        due = row["ORDER AMOUNT"] - row["ADV RECEIVED"]
        
        table_text += f"📅 *DD:* {d_date} | *PD:* {p_date}\n"
        table_text += f"👤 *Cust:* {row['CUSTOMER NAME']}\n"
        table_text += f"📞 *Ph:* {row['CONTACT NUMBER']}\n"
        table_text += f"🛋️ *Item:* {row['PRODUCT NAME']}\n"
        table_text += f"💰 *Adv:* ₹{row['ADV RECEIVED']:,} | *Due:* ₹{due:,}\n"
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
    
    # Filter for tomorrow's pending deliveries
    mask = (df["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING") & \
           (df["CUSTOMER DELIVERY DATE (TO BE)"].dt.date == target_date)
    tomorrow_df = df[mask].copy()
    
    if tomorrow_df.empty: return []

    alerts = []
    # Group by Sales Person
    for sp_name, group in tomorrow_df.groupby("SALES PERSON"):
        sp_name_clean = str(sp_name).strip().lower()
        table_msg = create_whatsapp_table(group)
        final_msg = f"🚚 *DAILY DELIVERY ALERT*\n\nHello {sp_name.title()},\n\n{table_msg}\n⚠️ Please confirm transport for these orders!"
        
        # Determine who gets this specific salesperson's list
        recipients = set()
        if sp_name_clean in contacts: recipients.add(contacts[sp_name_clean])
        if "shaktiman" in contacts: recipients.add(contacts["shaktiman"])
        if "swati" in contacts: recipients.add(contacts["swati"]) # 'Me'

        for phone in recipients:
            alerts.append((phone, final_msg))
            
    return alerts

def get_test_alerts_list():
    """Generates a sample table using the first 3 pending orders for testing"""
    df = get_df("CRM")
    contacts = get_sales_team_contacts()
    df.columns = [c.strip().upper() for c in df.columns]
    
    # Clean data for formatting
    df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce')
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors='coerce')
    
    test_df = df[df["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING"].head(3)
    
    if test_df.empty: return []
    
    sample_table = create_whatsapp_table(test_df)
    test_msg = f"🧪 *TEST ALERT: TABULAR FORMAT*\n\n{sample_table}\n✅ Link is working!"
    
    alerts = []
    # Test only sends to Shaktiman and Swati to avoid disturbing the team
    for boss in ["shaktiman", "swati"]:
        if boss in contacts:
            alerts.append((contacts[boss], test_msg))
    return alerts

def generate_whatsapp_link(phone, message):
    encoded_msg = urllib.parse.quote(message)
    return f"https://wa.me/{phone}?text={encoded_msg}"