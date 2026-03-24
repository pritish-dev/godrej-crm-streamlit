# pages/40_Daily_Sales_By_Executive.py
import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily B2C Sales by Executive")

# ---------- helpers ----------
def _to_dt(s):
    return pd.to_datetime(s, errors="coerce")

def _to_amount(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series([], dtype=float)
    s = series.astype(str).str.replace("[₹,]", "", regex=True).str.strip()
    return pd.to_numeric(s, errors="coerce").fillna(0.0)

def _fmt_currency(x: float) -> str:
    return f"₹{x:,.0f}"

# ---------- data ----------
crm = get_df("CRM")

if crm is None or crm.empty:
    st.info("CRM is empty. Please add order data.")
    st.stop()

crm = crm.copy()
crm.columns = [c.strip() for c in crm.columns]

# ✅ REQUIRED NEW COLUMNS
required_cols = {"DATE", "SALES PERSON", "ORDER AMOUNT", "B2B/B2C"}
missing = [c for c in required_cols if c not in crm.columns]

if missing:
    st.error(f"Missing required columns: {', '.join(missing)}")
    st.stop()

# ---------- preprocessing ----------
crm["DATE_DT"] = _to_dt(crm["DATE"]).dt.date
crm["ORDER_VALUE"] = _to_amount(crm["ORDER AMOUNT"])

# ✅ FILTER ONLY B2C
crm["B2B/B2C"] = crm["B2B/B2C"].astype(str).str.strip().str.upper()
crm = crm[crm["B2B/B2C"] == "B2C"]

# ---------- controls ----------
today = datetime.today().date()
month_start = today.replace(day=1)

c1, c2, c3 = st.columns([2, 2, 8])

with c1:
    start = st.date_input("Start date", value=month_start)

with c2:
    end = st.date_input("End date", value=today)

with c3:
    st.caption(f"Showing B2C sales from {start} to {end}")

# ---------- filter ----------
df = crm[
    (crm["DATE_DT"] >= start) &
    (crm["DATE_DT"] <= end)
].copy()

# ---------- executives ----------
executives = (
    df["SALES PERSON"]
    .dropna()
    .astype(str)
    .str.strip()
    .unique()
    .tolist()
)

executives = sorted(executives)

# ---------- pivot ----------
if df.empty:
    date_index = pd.date_range(start, end, freq="D").date
    pivot = pd.DataFrame(0.0, index=date_index, columns=executives)
else:
    pivot = (
        df.groupby(["DATE_DT", "SALES PERSON"])["ORDER_VALUE"]
        .sum()
        .unstack(fill_value=0)
    )

    full_dates = pd.date_range(start, end, freq="D").date
    pivot = pivot.reindex(full_dates, fill_value=0)

# ensure all exec columns exist
for e in executives:
    if e not in pivot.columns:
        pivot[e] = 0.0

pivot = pivot[executives]

# ---------- totals ----------
pivot["Total (Daily)"] = pivot.sum(axis=1)
monthly_total = float(pivot["Total (Daily)"].sum())

# ---------- display ----------
disp = pivot.copy()
disp.index.name = "Date"
disp = disp.reset_index()

for col in executives + ["Total (Daily)"]:
    disp[col] = disp[col].map(_fmt_currency)

# footer
footer = {
    "Date": "Monthly Total",
    **{col: "" for col in executives},
    "Total (Daily)": _fmt_currency(monthly_total),
}

disp = pd.concat([disp, pd.DataFrame([footer])], ignore_index=True)

# ---------- UI ----------
st.dataframe(disp, use_container_width=True)

# ---------- summary ----------
st.success(f"💰 Total B2C Sales: {_fmt_currency(monthly_total)}")