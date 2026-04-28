import streamlit as st

import os
from dotenv import load_dotenv

load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

def admin_login():
    if "admin_logged_in" not in st.session_state:
        st.session_state.admin_logged_in = False

    if not st.session_state.admin_logged_in:
        st.subheader("🔐 Admin Login Required")

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                st.session_state.admin_logged_in = True
                st.success("Login successful")
                st.rerun()
            else:
                st.error("Invalid credentials")

        st.stop()


def admin_logout_button():
    if st.session_state.get("admin_logged_in"):
        if st.sidebar.button("🚪 Logout (Admin)"):
            st.session_state.admin_logged_in = False
            st.rerun()