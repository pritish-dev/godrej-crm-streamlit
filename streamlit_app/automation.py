import time
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from services.sheets import get_df

# =============================
# 📲 LOAD SALES TEAM CONTACTS
# =============================
team_df = get_df("Sales Team")

CONTACTS = {}
MANAGER_NUMBER = None
OWNER_NUMBER = None

for _, row in team_df.iterrows():
    name = str(row.get("Name", "")).strip()
    role = str(row.get("Role", "")).strip().lower()
    number = str(row.get("Contact Number", "")).strip()

    if not name or not number:
        continue

    CONTACTS[name] = number

    if role == "manager":
        MANAGER_NUMBER = number
    elif role == "owner":
        OWNER_NUMBER = number

# Fallback safety
if not MANAGER_NUMBER:
    raise Exception("❌ Manager number not found in Sales Team sheet")

if not OWNER_NUMBER:
    raise Exception("❌ Owner number not found in Sales Team sheet")

# =============================
# 🌐 START WHATSAPP DRIVER
# =============================
def start_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--user-data-dir=chrome-data")  # saves login

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    driver.get("https://web.whatsapp.com")
    input("👉 Scan QR (only first time) and press ENTER...")

    return driver

# =============================
# 📤 SEND MESSAGE FUNCTION
# =============================
def send_message(driver, number, message):
    try:
        url = f"https://web.whatsapp.com/send?phone=91{number}&text={message}"
        driver.get(url)

        time.sleep(8)

        send_btn = driver.find_element(By.XPATH, '//span[@data-icon="send"]')
        send_btn.click()

        time.sleep(3)

        print(f"✅ Sent to {number}")

    except Exception as e:
        print(f"❌ Failed for {number}: {e}")

# =============================
# 📊 LOAD CRM DATA
# =============================
df = get_df("CRM")

if df.empty:
    print("No CRM data found")
    exit()

# -----------------------------
# DATE FORMAT (dd-mm-yyyy)
# -----------------------------
df["DATE"] = pd.to_datetime(df["DATE"], format="%d-%m-%Y", errors="coerce")
df["DELIVERY DATE"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], format="%d-%m-%Y", errors="coerce")

# -----------------------------
# NUMERIC CLEANUP
# -----------------------------
df["ORDER AMOUNT"] = pd.to_numeric(df["ORDER AMOUNT"], errors="coerce").fillna(0)
df["ADV RECEIVED"] = pd.to_numeric(df["ADV RECEIVED"], errors="coerce").fillna(0)

df["DUE"] = df["ORDER AMOUNT"] - df["ADV RECEIVED"]

# =============================
# 🚀 START DRIVER
# =============================
driver = start_driver()

today = datetime.today()

# =============================
# 🚚 DELIVERY REMINDER (1 DAY BEFORE)
# =============================
delivery_df = df[
    (df["DELIVERY REMARKS"].str.lower() == "pending") &
    ((df["DELIVERY DATE"] - today).dt.days == 1)
]

print(f"Delivery reminders: {len(delivery_df)}")

for _, row in delivery_df.iterrows():

    msg = f"""
🚚 DELIVERY REMINDER

Customer: {row['CUSTOMER NAME']}
Product: {row['PRODUCT NAME']}
Delivery Date: {row['CUSTOMER DELIVERY DATE (TO BE)']}
"""

    sales = str(row.get("SALES PERSON", "")).strip()
    number = CONTACTS.get(sales, MANAGER_NUMBER)

    send_message(driver, number, msg)
    send_message(driver, MANAGER_NUMBER, msg)
    send_message(driver, OWNER_NUMBER, msg)

# =============================
# 💰 PAYMENT REMINDER (7 DAYS BEFORE)
# =============================
due_df = df[
    (df["DUE"] > 0) &
    ((df["DELIVERY DATE"] - today).dt.days == 7)
]

print(f"Payment reminders: {len(due_df)}")

for _, row in due_df.iterrows():

    msg = f"""
💰 PAYMENT REMINDER

Customer: {row['CUSTOMER NAME']}
Order Value: ₹{row['ORDER AMOUNT']}
Advance: ₹{row['ADV RECEIVED']}
Pending: ₹{row['DUE']}

Please collect before delivery.
"""

    sales = str(row.get("SALES PERSON", "")).strip()
    number = CONTACTS.get(sales, MANAGER_NUMBER)

    send_message(driver, number, msg)
    send_message(driver, MANAGER_NUMBER, msg)
    send_message(driver, OWNER_NUMBER, msg)

# =============================
# 📊 DAILY REPORT
# =============================
today_df = df[df["DATE"].dt.date == today.date()]

total_sales = today_df["ORDER AMOUNT"].sum()
order_count = len(today_df)

msg = f"""
📊 DAILY SALES REPORT

Total Sales: ₹{total_sales:,.0f}
Orders Count: {order_count}
"""

send_message(driver, MANAGER_NUMBER, msg)
send_message(driver, OWNER_NUMBER, msg)

# =============================
# ✅ DONE
# =============================
print("✅ Automation completed successfully")
driver.quit()