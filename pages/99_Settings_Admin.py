# pages/99_Settings_Admin.py
import streamlit as st
import bcrypt
from services.auth import AuthService
from services.sheets import upsert_user, get_users_df

st.set_page_config(layout="wide")
st.title("⚙️ Settings — Admin Tools")

auth = AuthService()
if not auth.login_block(min_role="Admin"):
    st.stop()

st.subheader("Create Password Hash")
with st.form("hash_form"):
    raw_pw = st.text_input("New Password", type="password")
    submitted = st.form_submit_button("Generate Hash")
if submitted:
    if not raw_pw:
        st.error("Enter a password.")
    else:
        hashed = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()
        st.code(hashed, language="text")
        st.success("Copy this hash into the Users sheet or use the form below to create/update a user.")

st.subheader("Create / Update User")
with st.form("user_form"):
    username = st.text_input("Username (email or handle)").strip().lower()
    full_name = st.text_input("Full Name")
    role = st.selectbox("Role", ["Viewer", "Editor", "Admin"])
    active = st.selectbox("Active", ["Y", "N"])
    password_hash = st.text_input("Password Hash (bcrypt)", help="Paste the generated hash above")
    submit_user = st.form_submit_button("Save User")

if submit_user:
    if not (username and full_name and role and password_hash):
        st.error("All fields (except Active) are required.")
    else:
        msg = upsert_user(username, password_hash, full_name, role, active)
        st.success(msg)

st.subheader("Users (read-only)")
try:
    st.dataframe(get_users_df(), use_container_width=True)
except Exception as e:
    st.error(f"Could not load Users: {e}")
