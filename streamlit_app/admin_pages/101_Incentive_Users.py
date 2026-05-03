"""
admin_pages/101_Incentive_Users.py
─────────────────────────────────────────────────────────────────────────────
Admin tool to create / update accounts that can sign in to the
**Sales Incentive Dashboard** (page 100).

Storage: "Incentive_Users" tab in the CRM Google Sheet.
Hash:    bcrypt (same library used elsewhere).
Roles:   ADMIN | MANAGER | OWNER | PROPRIETOR
         (only these can access the Incentive Dashboard).

This page itself is gated behind `st.session_state.admin_logged_in`,
matching the convention of `99_Settings_Admin.py`.
"""
import os
import sys
import bcrypt
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.incentive_store import (
    ensure_users_tab,
    get_incentive_users_df,
    upsert_incentive_user,
)

ALLOWED_ROLES = ["ADMIN", "MANAGER", "OWNER", "PROPRIETOR"]

st.set_page_config(layout="wide", page_title="Admin | Incentive Users")

# ── Gate ────────────────────────────────────────────────────────────────────
if not st.session_state.get("admin_logged_in"):
    st.title("👤 Incentive Dashboard — User Management")
    st.error("🚫 **Access denied.** Sign in as Admin from the home page first.")
    st.stop()

ensure_users_tab()

st.title("👤 Incentive Dashboard — User Management")
st.caption(
    "These accounts are scoped specifically to the **Sales Incentive "
    "Dashboard** (page 100). Passwords are stored as bcrypt hashes in the "
    "`Incentive_Users` tab of the CRM Google Sheet."
)

# ── 1. Generate hash ────────────────────────────────────────────────────────
st.subheader("🔑 Generate bcrypt hash")
with st.form("hash_form"):
    raw_pw = st.text_input("New password", type="password",
                           help="Enter the password the user will type in.")
    submit_hash = st.form_submit_button("Generate hash")
if submit_hash:
    if not raw_pw:
        st.error("Enter a password first.")
    else:
        h = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()
        st.success("Generated. Copy this string into the form below.")
        st.code(h, language="text")

st.divider()

# ── 2. Create / update user ─────────────────────────────────────────────────
st.subheader("➕ Create or update an Incentive user")
with st.form("user_form"):
    c1, c2 = st.columns(2)
    username = c1.text_input(
        "Username",
        help="Email / handle the user will type at the Incentive page login.",
    ).strip().lower()
    full_name = c2.text_input(
        "Full name",
        help="Used for the welcome banner and audit log.",
    ).strip()
    c3, c4 = st.columns(2)
    role = c3.selectbox(
        "Role",
        ALLOWED_ROLES,
        help="Only these roles can access the Sales Incentive Dashboard.",
    )
    active = c4.selectbox(
        "Active",
        ["Y", "N"],
        help="Set to N to immediately disable the account.",
    )
    pw_hash = st.text_input(
        "Password hash (bcrypt)",
        help="Paste the hash generated above. Never store raw passwords.",
    ).strip()
    submit_user = st.form_submit_button("Save user")

if submit_user:
    if not (username and full_name and role and pw_hash):
        st.error("Username, full name, role and password hash are all required.")
    elif not pw_hash.startswith("$2"):
        st.error("That doesn't look like a bcrypt hash (should start with `$2`).")
    else:
        try:
            msg = upsert_incentive_user(username, pw_hash, full_name, role, active)
            st.success(f"✔️ {msg}")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Failed to save user: {e}")

st.divider()

# ── 3. Read-only listing ────────────────────────────────────────────────────
st.subheader("📋 Registered Incentive users")
try:
    users_df = get_incentive_users_df()
    if users_df.empty:
        st.info(
            "No accounts yet. Generate a hash above, then add the first user."
        )
    else:
        # Hide hash column for readability
        view = users_df.copy()
        view["passwordhash"] = view["passwordhash"].str[:12] + "…"
        st.dataframe(view, use_container_width=True, hide_index=True)
except Exception as e:
    st.error(f"Could not load users: {e}")

st.caption("Incentive User Manager v1.0 — bcrypt-hashed, audited via Incentive_Audit_Log")
