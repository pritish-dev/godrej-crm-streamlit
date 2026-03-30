import streamlit as st
import bcrypt
from services.sheets import upsert_user, get_users_df

# 1. PAGE CONFIG
st.set_page_config(layout="wide", page_title="Admin | System Settings")

# 2. 🔐 ADMIN RESTRICTION CHECK
# Validates the session state established in app.py
if "admin_logged_in" not in st.session_state or not st.session_state.admin_logged_in:
    st.title("⚙️ System Settings")
    st.error("🚫 **Access Denied.** Administrative privileges are required to access user management tools.")
    st.info("Please return to the **Home Page** and log in as an Admin to continue.")
    st.stop() # Prevents any bcrypt or sheet functions from loading

# 3. ADMIN CONTENT (Only runs if logged in)
st.title("⚙️ Settings — Admin Tools")
st.success("Authorized: Administrator Access Active")

st.subheader("🔑 Create Password Hash")
with st.form("hash_form"):
    raw_pw = st.text_input("New Password", type="password")
    submitted = st.form_submit_button("Generate Hash")

if submitted:
    if not raw_pw:
        st.error("Please enter a password to generate a hash.")
    else:
        # Generate the bcrypt hash
        hashed = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()
        st.info("Generated Hash:")
        st.code(hashed, language="text")
        st.success("Copy this hash to use in the form below or manually update the Users sheet.")

st.divider()

st.subheader("👤 Create / Update User")
with st.form("user_form"):
    username = st.text_input("Username (email or handle)").strip().lower()
    full_name = st.text_input("Full Name")
    role = st.selectbox("Role", ["Viewer", "Editor", "Admin"])
    active = st.selectbox("Active", ["Y", "N"])
    passwordhash = st.text_input("Password Hash (bcrypt)", help="Paste the generated hash from above")
    submit_user = st.form_submit_button("Save User")

if submit_user:
    if not (username and full_name and role and passwordhash):
        st.error("All fields (except Active) are required to save a user.")
    else:
        try:
            msg = upsert_user(username, passwordhash, full_name, role, active)
            st.success(f"✔️ {msg}")
        except Exception as e:
            st.error(f"Failed to update user: {e}")

st.divider()

st.subheader("📋 Registered Users (Read-Only)")
try:
    users_df = get_users_df()
    if users_df is not None and not users_df.empty:
        # Hide the actual hash column for better UI, or keep it if you need to see it
        st.dataframe(users_df, use_container_width=True)
    else:
        st.info("No user records found in the database.")
except Exception as e:
    st.error(f"Could not load Users: {e}")

st.caption("Admin Tool v2.1 — Secure User Management for Godrej CRM")