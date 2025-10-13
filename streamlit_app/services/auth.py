# services/auth.py
import streamlit as st
import pandas as pd
import bcrypt
from services.sheets import get_users_df

ROLES = ["Viewer", "Editor", "Admin"]

def _role_at_least(user_role: str, min_role: str) -> bool:
    try:
        return ROLES.index((user_role or "Viewer")) >= ROLES.index(min_role)
    except ValueError:
        return False

def _get_user_record(username: str):
    df = get_users_df()
    if df is None or df.empty:
        return None
    m = df.get("username", pd.Series(dtype=str)).astype(str).str.lower() == (username or "").strip().lower()
    if not m.any():
        return None
    return df.iloc[m[m].index[0]].to_dict()

class AuthService:
    def __init__(self):
        if "auth_user" not in st.session_state:
            st.session_state.auth_user = None

    def current_user(self):
        return st.session_state.auth_user

    def logout(self):
        st.session_state.auth_user = None
        st.success("Logged out.")
        st.rerun()

    def _login_form(self):
        st.subheader("🔐 Sign in")
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")
        if submit:
            rec = _get_user_record(u)
            if not rec:
                st.error("User not found.")
                return False
            if str(rec.get("active", "Y")).strip().upper() not in ("Y", "YES", "TRUE", "1"):
                st.error("User inactive.")
                return False
            pw_hash = str(rec.get("password_hash", "")).encode()
            if bcrypt.checkpw(p.encode(), pw_hash):
                st.session_state.auth_user = {
                    "username": rec.get("username"),
                    "role": rec.get("role", "Viewer"),
                    "full_name": rec.get("full_name", rec.get("username"))
                }
                st.success("Authenticated.")
                st.rerun()
                return True
            else:
                st.error("Invalid password.")
        return False

    def login_block(self, min_role: str = "Editor") -> bool:
        user = self.current_user()
        if not user:
            return self._login_form()
        if not _role_at_least(user.get("role", "Viewer"), min_role):
            st.error(f"Insufficient role. Requires: {min_role}. You are: {user.get('role')}.")
            if st.button("Logout"):
                self.logout()
            return False
        with st.expander("Account", expanded=False):
            st.write(f"Signed in as **{user['full_name']}** ({user['username']}) — role: **{user['role']}**")
            if st.button("Logout"):
                self.logout()
        return True

def current_user_badge(auth: AuthService):
    u = auth.current_user()
    if u:
        st.sidebar.success(f"User: {u['full_name']} ({u['role']})")
        if st.sidebar.button("Logout"):
            auth.logout()
    else:
        st.sidebar.warning("Not signed in")
