import pandas as pd
from datetime import datetime, timedelta
from streamlit_app.services.sheets import get_all_records  # adjust based on your repo
from streamlit_app.services.email_service import send_email  # we will create this

def get_tomorrow_deliveries():
    df = get_all_records("CRM")  # your sheet name

    df['Delivery Date'] = pd.to_datetime(df['Delivery Date'], errors='coerce')

    tomorrow = datetime.now().date() + timedelta(days=1)

    filtered = df[
        (df['Delivery Date'].dt.date == tomorrow) &
        (df['Delivery Status'] != 'Delivered')
    ]

    return filtered


def build_email_html(df):
    if df.empty:
        return "<p>No deliveries scheduled for tomorrow ✅</p>"

    return df.to_html(index=False)


def run_delivery_alert():
    df = get_tomorrow_deliveries()
    html = build_email_html(df)

    send_email(
        subject="🚚 Delivery Reminder - Tomorrow",
        html_content=html
    )