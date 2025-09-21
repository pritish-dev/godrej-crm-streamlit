import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, timedelta

st.set_page_config(page_title="Reviews (Staging)", layout="wide")

# ── secrets.toml (staging) ───────────────────────────────────────────
# [gspread]
# sa_json = """{ ... your service account json ... }"""
# [reviews_staging]
# spreadsheet_id = "YOUR_REVIEW_STAGING_SHEET_ID"
# review_sheet = "Review_staging"
# weekly_sheet = "Weekly_Summary"
# monthly_sheet = "Monthly_Summary"
# ────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = Credentials.from_service_account_info(st.secrets["gspread"]["sa_json"], scopes=SCOPES)
gc = gspread.authorize(creds)

REV_SSID  = st.secrets["reviews_staging"]["spreadsheet_id"]
S_REVIEW  = st.secrets["reviews_staging"]["review_sheet"]
S_WEEKLY  = st.secrets["reviews_staging"]["weekly_sheet"]
S_MONTHLY = st.secrets["reviews_staging"]["monthly_sheet"]

@st.cache_data(ttl=3600)
def load_data():
    sh = gc.open_by_key(REV_SSID)
    review = pd.DataFrame(sh.worksheet(S_REVIEW).get_all_records())
    weekly = pd.DataFrame(sh.worksheet(S_WEEKLY).get_all_records())
    monthly = pd.DataFrame(sh.worksheet(S_MONTHLY).get_all_records())
    # normalize types
    if "Date" in review:
        review["Date"] = pd.to_datetime(review["Date"], errors="coerce").dt.date
    for df in (weekly, monthly):
        if not df.empty:
            df["periodStart"] = pd.to_datetime(df["periodStart"]).dt.date
            df["periodEnd"]   = pd.to_datetime(df["periodEnd"]).dt.date
    return review, weekly, monthly

review, weekly, monthly = load_data()

st.title("⭐ Reviews – Staging")

# KPIs
c1, c2, c3 = st.columns(3)
today = date.today()
month_start = today.replace(day=1)

# Count mapped this month
mapped_month = review[(review.get("Mapped in CRM", "").astype(str).str.lower() == "yes") &
                      (review["Date"] >= month_start) if "Date" in review else False]
c1.metric("Mapped Reviews (This Month)", 0 if review.empty else int(mapped_month.shape[0]))

# Avg rating this month
def to_num_rating(s):
    m = {"ONE":1,"TWO":2,"THREE":3,"FOUR":4,"FIVE":5}
    return m.get(str(s).strip().upper(), None)
if not review.empty:
    month_rows = review[review["Date"] >= month_start] if "Date" in review else review
    ratings = month_rows["Rating"].map(to_num_rating).dropna()
    c2.metric("Avg Rating (This Month)", f"{ratings.mean():.2f}" if not ratings.empty else "—")
else:
    c2.metric("Avg Rating (This Month)", "—")

c3.metric("Total Reviews (All Time)", 0 if review.empty else int(review.shape[0]))

st.divider()

# Leaderboard (weekly)
st.subheader("🏆 Weekly Leaderboard (Sales Executive)")
if weekly.empty:
    st.info("No weekly summary yet.")
else:
    # show latest week first
    last_period_start = weekly["periodStart"].max()
    latest_week = weekly[weekly["periodStart"] == last_period_start]
    board = latest_week.groupby("salesExecutive", dropna=False)["reviewsCount"].sum() \
                       .reset_index().sort_values("reviewsCount", ascending=False)
    st.dataframe(board, use_container_width=True, hide_index=True)

    with st.expander("All weekly periods"):
        st.dataframe(weekly.sort_values(["periodStart","salesExecutive"]),
                     use_container_width=True, hide_index=True)

# Leaderboard (monthly)
st.subheader("📅 Monthly Leaderboard (Sales Executive)")
if monthly.empty:
    st.info("No monthly summary yet.")
else:
    last_month_start = monthly["periodStart"].max()
    latest_month = monthly[monthly["periodStart"] == last_month_start]
    board_m = latest_month.groupby("salesExecutive", dropna=False)["reviewsCount"].sum() \
                          .reset_index().sort_values("reviewsCount", ascending=False)
    st.dataframe(board_m, use_container_width=True, hide_index=True)

    with st.expander("All monthly periods"):
        st.dataframe(monthly.sort_values(["periodStart","salesExecutive"]),
                     use_container_width=True, hide_index=True)

st.divider()
with st.expander("🔎 Latest Reviews (mapped + raw)"):
    if not review.empty:
        show = review.sort_values(["Date"], ascending=False).head(200) if "Date" in review else review
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.info("No reviews found.")
