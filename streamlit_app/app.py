import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, upsert_record
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales Dashboard")

# -----------------------------
# LOAD DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")
targets_sheet = get_df("Targets")

crm.columns = [c.strip().upper() for c in crm.columns]

# -----------------------------
# CLEAN DATA
# -----------------------------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    crm[col] = (
        crm[col].astype(str)
        .str.replace(",", "")
        .str.replace("₹", "")
        .str.strip()
    )
    crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")

crm["DELIVERY DATE"] = pd.to_datetime(
    crm["CUSTOMER DELIVERY DATE (TO BE)"],
    format="%d-%m-%Y",
    errors="coerce"
)

crm = crm.sort_values("DATE", ascending=False)

# -----------------------------
# SALES TEAM LIST
# -----------------------------
team.columns = [c.strip().upper() for c in team.columns]

sales_people = (
    team[team["ROLE"] == "SALES"]["NAME"]
    .dropna()
    .str.strip()
    .str.upper()
    .unique()
    .tolist()
)

# -----------------------------
# HELPERS
# -----------------------------
def format_money(x):
    return f"₹{x:,.0f}"

def format_date(x):
    try:
        return pd.to_datetime(x).strftime("%d-%b-%Y")
    except:
        return ""

# -----------------------------
# TARGET VS ACHIEVEMENT
# -----------------------------
st.subheader("🎯 Target vs Achievement")

today = datetime.today()
month = today.strftime("%B")
year = today.year
month_start = today.replace(day=1)

# Ensure targets sheet structure
if targets_sheet.empty:
    targets_sheet = pd.DataFrame(columns=["MONTH", "YEAR", "SALES PERSON", "TARGET"])

targets_sheet.columns = [c.strip().upper() for c in targets_sheet.columns]

# FILTER CURRENT MONTH
targets_current = targets_sheet[
    (targets_sheet["MONTH"] == month) &
    (targets_sheet["YEAR"].astype(str) == str(year))
]

# AUTO CREATE DEFAULT ROWS
rows = []
for sp in sales_people:
    if sp not in targets_current["SALES PERSON"].values:
        rows.append({
            "MONTH": month,
            "YEAR": year,
            "SALES PERSON": sp,
            "TARGET": 0
        })

if rows:
    for r in rows:
        upsert_record("Targets",
            {"SALES PERSON": r["SALES PERSON"], "MONTH": r["MONTH"], "YEAR": r["YEAR"]},
            r
        )
    targets_sheet = get_df("Targets")
    targets_sheet.columns = [c.strip().upper() for c in targets_sheet.columns]
    targets_current = targets_sheet[
        (targets_sheet["MONTH"] == month) &
        (targets_sheet["YEAR"].astype(str) == str(year))
    ]

# -----------------------------
# INPUT TARGET
# -----------------------------
col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target", min_value=0, step=50000)

if st.button("Update Target"):
    upsert_record("Targets",
        {
            "SALES PERSON": selected_sales,
            "MONTH": month,
            "YEAR": year
        },
        {
            "TARGET": target_value
        }
    )
    st.success("Target Updated")
    st.rerun()

# -----------------------------
# CALCULATE ACHIEVEMENT
# -----------------------------
def calc_achievement(person):
    df = crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"].str.upper() == person)
    ]
    return df["ORDER AMOUNT"].sum()

def category_split(person, cat):
    return crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"].str.upper() == person) &
        (crm["CATEGORY"].str.upper() == cat)
    ]["ORDER AMOUNT"].sum()

df_targets = targets_current.copy()

df_targets["ACHIEVEMENT"] = df_targets["SALES PERSON"].apply(calc_achievement)
df_targets["HOME FURNITURE"] = df_targets["SALES PERSON"].apply(lambda x: category_split(x, "HOME FURNITURE"))
df_targets["HOME STORAGE"] = df_targets["SALES PERSON"].apply(lambda x: category_split(x, "HOME STORAGE"))

# -----------------------------
# RANKING
# -----------------------------
df_targets = df_targets.sort_values("ACHIEVEMENT", ascending=False)

medals = ["🥇", "🥈", "🥉"]
df_targets["RANK"] = ""

for i in range(min(3, len(df_targets))):
    df_targets.iloc[i, df_targets.columns.get_loc("RANK")] = medals[i]

# -----------------------------
# FORMAT
# -----------------------------
for col in ["TARGET", "ACHIEVEMENT", "HOME FURNITURE", "HOME STORAGE"]:
    df_targets[col] = df_targets[col].apply(format_money)

# HIGHLIGHT
def highlight(row):
    ach = int(row["ACHIEVEMENT"].replace("₹", "").replace(",", ""))
    tar = int(row["TARGET"].replace("₹", "").replace(",", ""))
    if ach >= tar:
        return ["background-color:#dcfce7"] * len(row)
    return [""] * len(row)

# ADD MONTH DISPLAY
df_targets["MONTH DISPLAY"] = month + " " + str(year)

st.dataframe(
    df_targets[
        ["MONTH DISPLAY", "SALES PERSON", "TARGET", "ACHIEVEMENT",
         "HOME FURNITURE", "HOME STORAGE", "RANK"]
    ].style.apply(highlight, axis=1),
    use_container_width=True
)

# -----------------------------
# PENDING DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

pending = crm[crm["DELIVERY REMARKS"].str.upper() == "PENDING"]
pending = pending.sort_values("DELIVERY DATE")

pending["CUSTOMER DELIVERY DATE (TO BE)"] = pending["DELIVERY DATE"].apply(format_date)

st.dataframe(pending, use_container_width=True)

if st.button("📲 Send Delivery Alerts"):
    send_delivery_alerts()
    st.success("Delivery Alerts Sent")

# -----------------------------
# PAYMENT DUE
# -----------------------------
st.subheader("💰 Payment Due")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]

due = crm[crm["PENDING AMOUNT"] > 0]

due["PENDING AMOUNT"] = due["PENDING AMOUNT"].apply(format_money)

st.dataframe(due, use_container_width=True)

if st.button("📲 Send Payment Alerts"):
    send_payment_alerts()
    st.success("Payment Alerts Sent")