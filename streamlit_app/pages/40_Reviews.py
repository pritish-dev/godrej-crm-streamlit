import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

st.set_page_config(page_title="Reviews (Staging)", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = Credentials.from_service_account_info(st.secrets["gspread"]["sa_json"], scopes=SCOPES)
gc = gspread.authorize(creds)

REV_SPREAD_ID = st.secrets["reviews"]["spreadsheet_id"]
RAW_SHEET = st.secrets["reviews"]["raw_sheet"]
MAP_SHEET = st.secrets["reviews"]["mapped_sheet"]
SUM_SHEET = st.secrets["reviews"]["summary_sheet"]

@st.cache_data(ttl=60)  # frequent in staging; bump to 3600 later
def load_sheets():
    sh = gc.open_by_key(REV_SPREAD_ID)
    raw = pd.DataFrame(sh.worksheet(RAW_SHEET).get_all_records())
    mapped = pd.DataFrame(sh.worksheet(MAP_SHEET).get_all_records())
    summary = pd.DataFrame(sh.worksheet(SUM_SHEET).get_all_records())
    # normalize types
    for df in (raw, mapped, summary):
        for c in df.columns:
            if c.lower().endswith("time") or c.lower()=="date":
                try:
                    df[c] = pd.to_datetime(df[c]).dt.date
                except Exception:
                    pass
    return raw, mapped, summary

raw, mapped, summary = load_sheets()

st.title("⭐ Customer Reviews – Staging")

# KPIs
c1, c2, c3, c4 = st.columns(4)
today = date.today()
this_month = today.replace(day=1)

month_reviews = mapped[mapped["date"] >= this_month] if "date" in mapped else pd.DataFrame()
avg_rating = raw["starRating"].map({"ONE":1,"TWO":2,"THREE":3,"FOUR":4,"FIVE":5}).dropna()
c1.metric("Reviews this month", int(month_reviews.shape[0]))
c2.metric("Avg rating (all time)", f"{avg_rating.mean():.2f}" if not avg_rating.empty else "—")
c3.metric("Mapped to CRM", int((mapped["matchedCustomer"]!="").sum()) if "matchedCustomer" in mapped else 0)
c4.metric("Anonymous reviews", int((mapped["anonymous"]==True).sum()) if "anonymous" in mapped else 0)

# Leaderboard
st.subheader("🏆 Reviews collected per Sales Executive (this month)")
if not summary.empty:
    sm = summary.copy()
    sm["date"] = pd.to_datetime(sm["date"])
    sm = sm[sm["date"].dt.date >= this_month]
    board = sm.groupby("salesExecutive", dropna=False)["reviewsCount"].sum().reset_index().sort_values("reviewsCount", ascending=False)
    st.dataframe(board, use_container_width=True, hide_index=True)
else:
    st.info("No summary yet.")

# Daily trend (this month)
st.subheader("📈 Daily reviews trend (by executive)")
if not summary.empty:
    sm = summary.copy()
    sm["date"] = pd.to_datetime(sm["date"]).dt.date
    sm = sm[sm["date"] >= this_month]
    pivot = sm.pivot_table(index="date", columns="salesExecutive", values="reviewsCount", aggfunc="sum").fillna(0)
    st.line_chart(pivot)
else:
    st.info("No summary yet.")

# Raw & mapped tables
with st.expander("🔎 Latest Mapped Reviews"):
    show = mapped.sort_values("date", ascending=False).head(200) if not mapped.empty else mapped
    st.dataframe(show, use_container_width=True, hide_index=True)

with st.expander("🧾 Raw GBP Reviews"):
    show = raw.sort_values("createTime", ascending=False).head(200) if not raw.empty else raw
    st.dataframe(show, use_container_width=True, hide_index=True)
