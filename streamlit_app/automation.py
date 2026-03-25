import time
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from services.sheets import get_df

# -----------------------------
# CONTACTS (SAME AS app.py)
# -----------------------------
CONTACTS = {
    "Pritish": "8867143707",
    "Shaktiman": "9778022570",
    "Swati": "8280175104",
    "Archita": "7606877236"
}

DEFAULT_MANAGER = "Shaktiman"
OWNER = "Pritish"

# -----------------------------
# OPEN WHATSAPP WEB
# -----------------------------
def start_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--user-data-dir=chrome-data")  # keeps login session
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://web.whatsapp.com")
    input("👉 Scan QR once and press ENTER...")
    return driver

# -----------------------------
# SEND MESSAGE
# -----------------------------
def send_message(driver, number, message):
    try:
        url = f"https://web.whatsapp.com/send?phone=91{number}&text={message}"
        driver.get(url)
        time.sleep(10)

        send_btn = driver.find_element(By.XPATH, '//span[@data-icon="send"]')
        send_btn.click()
        time.sleep(3)

    except Exception as e:
        print("Error sending:", e)

# -----------------------------
# LOAD DATA
# -----------------------------
df = get_df("CRM")

df["DATE"] = pd.to_datetime(df["DATE"], format="%d-%m-%Y", errors="coerce")
df["DELIVERY DATE"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], format="%d-%m-%Y", errors="coerce")

df["ORDER AMOUNT"] = pd.to_numeric(df["ORDER AMOUNT"], errors="coerce").fillna(0)
df["ADV RECEIVED"] = pd.to_numeric(df["ADV RECEIVED"], errors="coerce").fillna(0)

df["DUE"] = df["ORDER AMOUNT"] - df["ADV RECEIVED"]

# -----------------------------
# START
# -----------------------------
driver = start_driver()

today = datetime.today()

# =============================
# 🚚 DELIVERY REMINDER (1 DAY BEFORE)
# =============================
delivery_df = df[
    (df["DELIVERY REMARKS"].str.lower() == "pending") &
    ((df["DELIVERY DATE"] - today).dt.days == 1)
]

for _, row in delivery_df.iterrows():

    msg = f"""
🚚 DELIVERY REMINDER

Customer: {row['CUSTOMER NAME']}
Product: {row['PRODUCT NAME']}
Delivery Date: {row['CUSTOMER DELIVERY DATE (TO BE)']}
"""

    sales = row["SALES PERSON"]
    number = CONTACTS.get(sales, CONTACTS[DEFAULT_MANAGER])

    send_message(driver, number, msg)
    send_message(driver, CONTACTS[DEFAULT_MANAGER], msg)
    send_message(driver, CONTACTS[OWNER], msg)

# =============================
# 💰 PAYMENT REMINDER (7 DAYS BEFORE)
# =============================
due_df = df[
    (df["DUE"] > 0) &
    ((df["DELIVERY DATE"] - today).dt.days == 7)
]

for _, row in due_df.iterrows():

    msg = f"""
💰 PAYMENT REMINDER

Customer: {row['CUSTOMER NAME']}
Order: ₹{row['ORDER AMOUNT']}
Advance: ₹{row['ADV RECEIVED']}
Pending: ₹{row['DUE']}
"""

    sales = row["SALES PERSON"]
    number = CONTACTS.get(sales, CONTACTS[DEFAULT_MANAGER])

    send_message(driver, number, msg)
    send_message(driver, CONTACTS[DEFAULT_MANAGER], msg)
    send_message(driver, CONTACTS[OWNER], msg)

# =============================
# 📊 DAILY REPORT
# =============================
today_df = df[df["DATE"].dt.date == today.date()]

msg = f"""
📊 DAILY REPORT

Total Sales: ₹{today_df['ORDER AMOUNT'].sum()}
Orders: {len(today_df)}
"""

send_message(driver, CONTACTS["Shaktiman"], msg)
send_message(driver, CONTACTS["Pritish"], msg)

print("✅ Automation completed")