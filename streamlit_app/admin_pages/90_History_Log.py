import streamlit as st
import pandas as pd
from services.sheets import get_df

# 1. PAGE CONFIG
st.set_page_config(layout="wide", page_title="Admin | Change History")

# 2. 🔐 ADMIN RESTRICTION CHECK
# This looks at the session state we set in app.py
if "admin_logged_in" not in st.session_state or not st.session_state.admin_logged_in:
    st.title("📝 Change History")
    st.error("🚫 **Access Denied.** This page is restricted to Administrators only.")
    st.info("Please go to the **Home Page** and login with the Admin password to view this log.")
    st.stop() # Stops the rest of the code from running

# 3. ADMIN CONTENT (Only runs if logged in)
st.title("📝 Change History (Admin View)")
st.success(f"Logged in as Admin")

log_df = get_df("History Log")

if log_df is None or log_df.empty:
    st.info("No history recorded yet.")
    st.stop()

# ---- Clean + Format ----
df = log_df.copy()

# Convert timestamp
if "Timestamp" in df.columns:
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")

# Sort latest first
df = df.sort_values(by="Timestamp", ascending=False)

# Optional filters
st.sidebar.subheader("🔍 Filters")

if "User" in df.columns:
    users = ["All"] + sorted(df["User"].dropna().unique().tolist())
    selected_user = st.sidebar.selectbox("Filter by User", users)
    if selected_user != "All":
        df = df[df["User"] == selected_user]

if "Sheet" in df.columns:
    sheets = ["All"] + sorted(df["Sheet"].dropna().unique().tolist())
    selected_sheet = st.sidebar.selectbox("Filter by Sheet", sheets)
    if selected_sheet != "All":
        df = df[df["Sheet"] == selected_sheet]

if "Action" in df.columns:
    actions = ["All"] + sorted(df["Action"].dropna().unique().tolist())
    selected_action = st.sidebar.selectbox("Filter by Action", actions)
    if selected_action != "All":
        df = df[df["Action"] == selected_action]

# ---- Display ----
st.dataframe(df, use_container_width=True)

st.caption("Tracks all INSERT / UPDATE actions across CRM, Leads & Services with user tracking.")