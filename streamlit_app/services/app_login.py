"""
services/app_login.py — one login for the whole CRM (web, Android app, iPhone app).

Team members sign in with the SAME username + password they use in the
4S ordering app. Credentials are read (read-only) from the OPS spreadsheet:

    1. "APP_ORDERING_CREDS" tab   Sales Person Name | username | Password |
                                  password_hash | Active | (Role)
    2. "Staff" tab (fallback)     username | password | name | code | role

Password checks mirror the ordering app's Apps Script backend (Code.gs):
    • pbkdf2$<iter>$<salt>$<b64>  iterated HMAC-SHA256 (the format the ordering
                                  app upgrades everyone to on login)
    • bcrypt ($2a$/$2b$)          verified natively here
    • 32-char MD5 hex             legacy
    • plaintext "Password" column legacy / until purged
The CRM never writes to the credentials sheet — the ordering app stays the
single place where passwords are managed. Change a password or set Active = No
there, and the CRM follows (within ~2 minutes, the cache TTL).

Staying signed in
-----------------
After a successful login the server issues a signed token (HMAC-SHA256,
30-day expiry). It is kept by the client in two ways so users are not asked to
log in every time they open the app:
    • the installed app shell (Android APK / iPhone home-screen app) receives it
      by postMessage and passes it back as ``?t=<token>`` on the next launch;
    • a first-party cookie for people using the site directly in a browser.
Every token use re-checks that the user still exists and is active, so
deactivating someone in the sheet signs them out everywhere.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets as _pysecrets
import time

import streamlit as st

# ── Config ───────────────────────────────────────────────────────────────────
CREDS_SHEET = "APP_ORDERING_CREDS"
STAFF_SHEET = "Staff"
# The ordering app's OPS spreadsheet. Used only if the CRM's configured OPS
# spreadsheet does not have the credentials tab.
ORDERING_APP_OPS_ID = "12RtOVqlOicoGlF2oLRBv3wB9eeludiz08AFKbhPcNqs"

TOKEN_TTL_SEC = 30 * 24 * 3600          # stay signed in for 30 days
COOKIE_NAME = "crm_session"
QUERY_KEY = "t"
# Origins of the installed-app shell: GitHub Pages (iPhone / Windows) and the
# shell bundled inside the Android APK. The token is posted ONLY to these, so a
# page that frames the CRM elsewhere can never receive it.
DEFAULT_SHELL_ORIGINS = ("https://pritish-dev.github.io", "https://appassets.androidplatform.net")

_SS_USER = "app_user"
_SS_PENDING_TOKEN = "_crm_pending_token"
_SS_PENDING_LOGOUT = "_crm_pending_logout"
_SS_LOGGED_OUT = "_crm_logged_out"


def _secret_value(section: str, key: str) -> str:
    try:
        return str(st.secrets[section][key]).strip()
    except Exception:
        return ""


def _shell_origins() -> list:
    extra = (_secret_value("app", "SHELL_ORIGIN") or os.getenv("CRM_SHELL_ORIGIN", "")).strip()
    origins = [o.strip().rstrip("/") for o in extra.split(",") if o.strip()]
    return origins + [o for o in DEFAULT_SHELL_ORIGINS if o not in origins]


@st.cache_resource
def _signing_key() -> bytes:
    """Stable per-deployment secret used to sign session tokens.

    Order: explicit [auth] SESSION_SECRET → CRM_SESSION_SECRET env → derived
    from the Google service-account private key (already in secrets, so no new
    setup is needed) → random per-process key (tokens then last until restart).
    """
    raw = (_secret_value("auth", "SESSION_SECRET")
           or os.getenv("CRM_SESSION_SECRET", "").strip()
           or _secret_value("google", "private_key"))
    if not raw:
        try:
            raw = json.loads(os.getenv("GOOGLE_CREDENTIALS", "") or "{}").get("private_key", "")
        except Exception:
            raw = ""
    if not raw:
        raw = _pysecrets.token_hex(32)
    return hashlib.sha256(("4s-crm-session|" + raw).encode()).digest()


# ── Tokens ───────────────────────────────────────────────────────────────────
def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(username: str) -> str:
    payload = _b64u(json.dumps(
        {"u": username, "exp": int(time.time()) + TOKEN_TTL_SEC},
        separators=(",", ":")).encode())
    sig = _b64u(hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest()[:24])
    return f"{payload}.{sig}"


def read_token(token: str) -> str | None:
    """Return the username in a valid, unexpired token, else None."""
    try:
        payload, sig = str(token or "").strip().split(".", 1)
        good = _b64u(hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest()[:24])
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_b64u_dec(payload))
        if int(data.get("exp", 0)) < time.time():
            return None
        return str(data.get("u") or "").strip().lower() or None
    except Exception:
        return None


# ── Password verification (mirrors the ordering app's Code.gs) ───────────────
def _pbkdf2_variants(password: str, salt: str, iters: int):
    """Yield candidate hashes for the ordering app's iterated HMAC-SHA256.

    Apps Script computes HMAC(key=salt, msg=password), then re-HMACs the digest
    ``iters-1`` times. How the Apps Script bridge passes the byte[] digest back
    in (raw bytes vs. its comma-joined string form) is not documented, so both
    interpretations are checked.
    """
    key = salt.encode("utf-8")
    first = hmac.new(key, password.encode("utf-8"), hashlib.sha256).digest()

    mac = first
    for _ in range(1, iters):
        mac = hmac.new(key, mac, hashlib.sha256).digest()
    yield base64.b64encode(mac).decode()

    mac = first
    for _ in range(1, iters):
        joined = ",".join(str(b - 256 if b > 127 else b) for b in mac)
        mac = hmac.new(key, joined.encode("utf-8"), hashlib.sha256).digest()
    yield base64.b64encode(mac).decode()


def _check_password(password: str, stored_hash: str, stored_plain: str) -> bool:
    stored_hash = (stored_hash or "").strip()
    if stored_hash.startswith("pbkdf2$"):
        parts = stored_hash.split("$")
        if len(parts) == 4:
            try:
                iters = int(parts[1]) or 4096
            except ValueError:
                iters = 4096
            iters = max(1, min(iters, 200_000))
            for cand in _pbkdf2_variants(password, parts[2], iters):
                if hmac.compare_digest(cand, parts[3]):
                    return True
    elif stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt
            if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                return True
        except Exception:
            pass
    elif len(stored_hash) == 32:
        if hmac.compare_digest(hashlib.md5(password.encode()).hexdigest(), stored_hash.lower()):
            return True
    plain = (stored_plain or "").strip()
    return bool(plain) and hmac.compare_digest(plain, password)


# ── Credential sheets (read-only) ────────────────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def _sheet_rows(sheet_name: str) -> list | None:
    """All values of an OPS tab, or None if the tab doesn't exist anywhere.

    Deliberately NOT services.sheets.get_df: that helper creates a missing tab,
    and this must never touch the credentials sheet.
    """
    from gspread.exceptions import WorksheetNotFound
    from services.sheets import _get_client, _get_ops_spreadsheet, _api_retry

    books = []
    try:
        books.append(_get_ops_spreadsheet())
    except Exception:
        pass
    try:
        if not books or books[0].id != ORDERING_APP_OPS_ID:
            books.append(_get_client().open_by_key(ORDERING_APP_OPS_ID))
    except Exception:
        pass
    for book in books:
        try:
            ws = _api_retry(book.worksheet, sheet_name)
        except WorksheetNotFound:
            continue
        return _api_retry(ws.get_all_values)
    return None


def _idx(headers: list, names: list, default: int) -> int:
    for n in names:
        if n in headers:
            return headers.index(n)
    return default


def _cell(row: list, i: int) -> str:
    return str(row[i]).strip() if 0 <= i < len(row) else ""


def _norm_role(raw: str) -> str:
    r = (raw or "").strip().lower()
    if r in ("admin", "administrator", "owner"):
        return "admin"
    if r in ("manager", "mgr", "store manager"):
        return "manager"
    if r in ("dummy", "read only", "read-only", "readonly", "view only"):
        return "dummy"
    return "sales"


def _find_user(username: str):
    """Return (record, source) for a username, or (None, None).

    record = {username, name, role, active, hash, plain}
    """
    rows = _sheet_rows(CREDS_SHEET)
    if rows and len(rows) > 1:
        hdr = [str(c).strip().lower() for c in rows[0]]
        c_name = _idx(hdr, ["sales person name", "salesperson name", "name", "sales person"], 0)
        c_user = _idx(hdr, ["username", "user name", "user"], 1)
        c_pass = _idx(hdr, ["password"], 2)
        c_hash = _idx(hdr, ["password_hash", "passwordhash", "hash"], 3)
        c_act = _idx(hdr, ["active", "status", "enabled"], 4)
        c_role = _idx(hdr, ["role", "user role", "access", "access level", "designation"], -1)
        for r in rows[1:]:
            if _cell(r, c_user).lower() != username:
                continue
            active = _cell(r, c_act).lower() if c_act < len(r) else "true"
            return {
                "username": username,
                "name": _cell(r, c_name) or username,
                "role": _norm_role(_cell(r, c_role)),
                "active": (not active) or active in ("true", "yes", "y", "1"),
                "hash": _cell(r, c_hash),
                "plain": _cell(r, c_pass),
            }, CREDS_SHEET

    rows = _sheet_rows(STAFF_SHEET)
    if rows and len(rows) > 1:
        for r in rows[1:]:  # username | password | name | code | role
            if _cell(r, 0).lower() != username:
                continue
            return {
                "username": username,
                "name": _cell(r, 2) or username,
                "role": _norm_role(_cell(r, 4)),
                "active": True,
                "hash": "",
                "plain": _cell(r, 1),
            }, STAFF_SHEET
    return None, None


# ── Session helpers ──────────────────────────────────────────────────────────
_LEGACY_ROLE = {"admin": "Admin", "manager": "Editor", "sales": "Editor", "dummy": "Viewer"}


def _start_session(rec: dict) -> None:
    user = {"username": rec["username"], "name": rec["name"], "role": rec["role"]}
    st.session_state[_SS_USER] = user
    st.session_state.pop(_SS_LOGGED_OUT, None)
    # Existing pages (e.g. Sales Manager Dashboard, RPL Stock) read the older
    # services.auth session key — fill it so they recognise the signed-in user.
    if not st.session_state.get("auth_user"):
        st.session_state["auth_user"] = {
            "username": rec["username"],
            "fullname": rec["name"],
            "role": _LEGACY_ROLE.get(rec["role"], "Viewer"),
        }


def current_app_user() -> dict | None:
    return st.session_state.get(_SS_USER)


def _try_token(token: str) -> bool:
    username = read_token(token)
    if not username:
        return False
    try:
        rec, _ = _find_user(username)
    except Exception:
        # Sheets unreachable: trust the signed token rather than lock everyone out.
        rec = {"username": username, "name": username, "role": "sales", "active": True}
    if not rec or not rec.get("active"):
        return False
    _start_session(rec)
    return True


def _restore_session() -> bool:
    """Sign in silently from ?t=<token> (app shell) or the session cookie."""
    qp = st.query_params.get(QUERY_KEY)
    if qp:
        try:
            del st.query_params[QUERY_KEY]       # keep the token out of the URL
        except Exception:
            pass
        if _try_token(qp):
            return True
    if st.session_state.get(_SS_LOGGED_OUT):
        return False
    try:
        cookie = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        cookie = None
    return bool(cookie) and _try_token(cookie)


def _client_js(token: str | None) -> None:
    """Hand the token to the app shell + cookie (or clear both when None)."""
    import streamlit.components.v1 as components

    max_age = TOKEN_TTL_SEC if token else 0
    msg = {"type": "crm-auth", "token": token} if token else {"type": "crm-logout"}
    components.html(
        f"""<script>
(function(){{
  var msg = {json.dumps(msg)}, shells = {json.dumps(_shell_origins())};
  if (window.top !== window.parent) shells.forEach(function (o) {{
    try {{ window.top.postMessage(msg, o); }} catch (e) {{}}
  }});
  try {{
    var d = window.parent.document, sec = location.protocol === 'https:' ? '; Secure' : '';
    d.cookie = {json.dumps(COOKIE_NAME)} + '=' + encodeURIComponent(msg.token || '') +
               '; path=/; max-age={max_age}; SameSite=Lax' + sec;
  }} catch (e) {{}}
}})();
</script>""",
        height=0,
    )


def logout() -> None:
    st.session_state.pop(_SS_USER, None)
    st.session_state.pop("auth_user", None)
    st.session_state.pop("incentive_user", None)
    st.session_state[_SS_LOGGED_OUT] = True
    st.session_state[_SS_PENDING_LOGOUT] = True
    st.rerun()


# ── Login screen ─────────────────────────────────────────────────────────────
_LOGIN_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"], header[data-testid="stHeader"] { display: none !important; }
.block-container { max-width: 440px !important; padding-top: 6vh !important; }
.crm-brand { text-align: center; margin-bottom: 1.4rem; }
.crm-badge {
  width: 76px; height: 76px; border-radius: 22px; margin: 0 auto .9rem;
  background: linear-gradient(135deg, #F08C1E, #C9700F);
  box-shadow: 0 10px 28px rgba(240,140,30,.35);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font: 800 30px/1 system-ui, -apple-system, Segoe UI, sans-serif; letter-spacing: -1px;
}
.crm-brand h1 { font-size: 1.55rem !important; margin: 0 !important; padding: 0 !important; }
.crm-brand p { color: #888; margin: .25rem 0 0; font-size: .92rem; }
[data-testid="stForm"] {
  border-radius: 18px !important; padding: 1.4rem 1.3rem !important;
  box-shadow: 0 8px 30px rgba(0,0,0,.07);
}
[data-testid="stForm"] button[kind="primaryFormSubmit"],
[data-testid="stForm"] button[data-testid="stBaseButton-primaryFormSubmit"] {
  width: 100%; background: linear-gradient(135deg, #F08C1E, #C9700F) !important;
  color: #fff !important; border: 0 !important; font-weight: 700; padding: .6rem 0;
  border-radius: 12px !important;
}
.crm-foot { text-align: center; color: #999; font-size: .8rem; margin-top: 1rem; }
</style>
"""


def _login_page() -> None:
    if st.session_state.pop(_SS_PENDING_LOGOUT, False):
        _client_js(None)
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="crm-brand"><div class="crm-badge">4S</div>'
        "<h1>4S Interiors CRM</h1>"
        "<p>Sign in with your ordering-app username &amp; password</p></div>",
        unsafe_allow_html=True,
    )
    with st.form("crm_login", clear_on_submit=False):
        username = st.text_input("Username", autocomplete="username").strip().lower()
        password = st.text_input("Password", type="password", autocomplete="current-password").strip()
        try:
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        except TypeError:   # older Streamlit
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    st.markdown('<div class="crm-foot">Interio by Godrej · Patia</div>', unsafe_allow_html=True)

    if not submitted:
        return
    if not username or not password:
        st.error("Enter your username and password.")
        return

    fails = st.session_state.setdefault("_crm_login_fails", {})
    if fails.get(username, 0) >= 8:
        st.error("Too many failed attempts. Please close the app and try again in a few minutes.")
        return

    try:
        with st.spinner("Signing in…"):
            rec, _ = _find_user(username)
    except Exception:
        st.error("Couldn't reach the credentials sheet. Check your internet and try again.")
        return

    if not rec:
        st.error("Username not found. Use the same login as the ordering app, or contact your manager.")
        return
    if not rec["active"]:
        st.error("Your account is inactive. Please contact your manager.")
        return
    if not _check_password(password, rec["hash"], rec["plain"]):
        fails[username] = fails.get(username, 0) + 1
        st.error("Incorrect password. Please try again.")
        return

    fails.pop(username, None)
    _start_session(rec)
    st.session_state[_SS_PENDING_TOKEN] = make_token(username)
    st.rerun()


def require_login() -> dict | None:
    """Gate the app. Returns the signed-in user, or renders the login screen.

    Call right after st.set_page_config(). When it returns None the caller must
    stop (the login page has already been routed via st.navigation).
    """
    user = current_app_user()
    if not user and _restore_session():
        user = current_app_user()
        # Refresh the token on every silent sign-in so active users never expire.
        st.session_state[_SS_PENDING_TOKEN] = make_token(user["username"])

    if user:
        token = st.session_state.pop(_SS_PENDING_TOKEN, None)
        if token:
            _client_js(token)
        return user

    st.navigation([st.Page(_login_page, title="Sign in", icon="🔐")], position="hidden").run()
    return None


def sidebar_account_box() -> None:
    user = current_app_user()
    if not user:
        return
    role = {"admin": "Admin", "manager": "Manager", "dummy": "View only"}.get(user["role"], "Sales")
    st.markdown(f"**👤 {user['name']}**  \n<small>{role} · {user['username']}</small>",
                unsafe_allow_html=True)
    try:
        clicked = st.button("Sign out", key="crm_sign_out", width="stretch")
    except TypeError:   # older Streamlit
        clicked = st.button("Sign out", key="crm_sign_out", use_container_width=True)
    if clicked:
        logout()
