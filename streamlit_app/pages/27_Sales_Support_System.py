"""
pages/27_Sales_Support_System.py

Sales Support System — Sales Handbook directory page.

A single, professional "who to contact and whom to escalate to" reference for
the four sales-support departments:

    • CST  (Customer Support Team)
    • Logistics
    • Spare
    • Service

The reporting hierarchy (contact person → team lead → department head → BCM) is
defined below from the official Sales Support System structure. Email addresses
and contact numbers are pulled live from the OPS sheet tab named
"SALES SUPPORT SYSTEM" and matched to each person by name, so the directory
stays up to date without touching the code.
"""
import sys
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import pandas as pd
import streamlit as st

SUPPORT_SHEET = "SALES SUPPORT SYSTEM"

st.set_page_config(
    layout="wide",
    page_title="Sales Support System",
    page_icon="🤝",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# DEPARTMENT STRUCTURE  (source of truth for the escalation hierarchy)
# ─────────────────────────────────────────────────────────────────────────────
# Each department lists its front-line contact persons and an ordered escalation
# chain. Escalation always flows top-to-bottom: if the person you contacted does
# not respond, move to the next name in the chain.
DEPARTMENTS = [
    {
        "id": "cst",
        "name": "CST",
        "full_name": "Customer Support Team",
        "emoji": "🎧",
        "gradient": "linear-gradient(135deg, #11998e, #38ef7d)",
        "purpose": (
            "First point of contact for customer queries, order status, "
            "post-sales coordination and general support requests."
        ),
        "contacts": ["Manash", "Sushil", "Padmaja"],
        # Escalation order after the front-line contact persons.
        "escalation": ["Dilip Pratihary", "Dawn"],
    },
    {
        "id": "logistics",
        "name": "Logistics",
        "full_name": "Logistics & Dispatch",
        "emoji": "🚚",
        "gradient": "linear-gradient(135deg, #654ea3, #eaafc8)",
        "purpose": (
            "Handles dispatch, transportation and movement of goods from the "
            "warehouse to the customer or outlet."
        ),
        "contacts": ["Ashis", "Sudhir", "Manoj", "Ratha Babu"],
        "escalation": ["Saroj", "Nitin Mohapatra", "Dawn"],
    },
    {
        "id": "spare",
        "name": "Spare",
        "full_name": "Spare Parts",
        "emoji": "🔧",
        "gradient": "linear-gradient(135deg, #f7971e, #ffd200)",
        "purpose": (
            "Manages spare-part requirements, replacement components and "
            "part-related fulfilment."
        ),
        "contacts": ["Swadhin"],
        "escalation": ["Somnath Panda", "Nitin Mohapatra", "Dawn"],
    },
    {
        "id": "service",
        "name": "Service",
        "full_name": "After-Sales Service",
        "emoji": "🛠️",
        "gradient": "linear-gradient(135deg, #2c3e50, #4ca1af)",
        "purpose": (
            "Attends to installation, repair and after-sales service "
            "complaints raised by customers."
        ),
        "contacts": ["Subhrajyoti"],
        # Service escalates to Bikas only — Bikas does NOT report to Dawn, so the
        # chain deliberately stops here (no BCM level).
        "escalation": ["Bikas"],
    },
]

# Role label shown against each name in the hierarchy.
ROLE_LABELS = {
    "Dilip Pratihary": "Department Head — CST",
    "Saroj": "Team Lead — Logistics",
    "Nitin Mohapatra": "Department Head — Logistics & Spare",
    "Somnath Panda": "Team Lead — Spare",
    "Bikas": "Department Head — Service",
    "Dawn": "BCM (Branch / Business Head)",
}

BCM_NAME = "Dawn"

# People who must always be kept in CC on every escalation (across all four
# departments), regardless of which chain is being escalated.
CC_ON_ESCALATION = ["Bibekananda Nayak", "Pradosh Dash"]

# ─────────────────────────────────────────────────────────────────────────────
# CONTACT LOOKUP  (email + phone pulled from the OPS "SALES SUPPORT SYSTEM" tab)
# ─────────────────────────────────────────────────────────────────────────────
def _norm(text: str) -> str:
    """Lowercase, collapse spaces — for fuzzy name matching."""
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


@st.cache_data(ttl=300, show_spinner=False)
def _load_directory() -> pd.DataFrame:
    """Read the SALES SUPPORT SYSTEM tab from the OPS sheet. Returns an empty
    DataFrame (never raises) so the page renders even if the sheet is missing."""
    try:
        from services.sheets import get_df
        df = get_df(SUPPORT_SHEET)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _classify_columns(df: pd.DataFrame):
    """Detect which columns hold the name, email and phone using header keywords.
    Returns (name_cols, email_cols, phone_cols) as lists of original headers."""
    name_cols, email_cols, phone_cols = [], [], []
    for col in df.columns:
        h = _norm(col)
        if "mail" in h:  # matches "email" and "e-mail"
            email_cols.append(col)
        elif any(k in h for k in ("name", "person", "employee")):
            # Checked before phone so a header like "Contact Person" is treated
            # as a name column, not a phone column (both contain "contact").
            name_cols.append(col)
        elif any(k in h for k in ("phone", "mobile", "contact", "number", "cell", "no.")):
            phone_cols.append(col)
    # Fallbacks when headers are unlabelled.
    if not name_cols and len(df.columns):
        name_cols = [df.columns[0]]
    return name_cols, email_cols, phone_cols


def _build_contact_map(df: pd.DataFrame) -> dict:
    """Map normalised person name -> {'email': ..., 'phone': ...} from the sheet.
    Matching is done on the first token of the name so 'Ratha Babu' matches a
    sheet entry of 'Ratha Babu Sahoo', and 'Manash' matches 'Manash Kumar'."""
    if df is None or df.empty:
        return {}

    name_cols, email_cols, phone_cols = _classify_columns(df)
    contact_map: dict[str, dict] = {}

    def _first_nonempty(row, cols):
        for c in cols:
            val = str(row.get(c, "")).strip()
            if val and val.lower() not in ("nan", "none", "-"):
                return val
        return ""

    for _, row in df.iterrows():
        raw_name = _first_nonempty(row, name_cols)
        if not raw_name:
            continue
        key = _norm(raw_name)
        entry = {
            "sheet_name": raw_name,
            "email": _first_nonempty(row, email_cols),
            "phone": _first_nonempty(row, phone_cols),
        }
        contact_map[key] = entry
        # Also index by first token for lenient matching.
        first = key.split(" ")[0]
        contact_map.setdefault(first, entry)
    return contact_map


def _lookup(name: str, contact_map: dict) -> dict:
    """Best-effort contact lookup for a hierarchy name."""
    if not contact_map:
        return {"email": "", "phone": ""}
    n = _norm(name)
    if n in contact_map:
        return contact_map[n]
    first = n.split(" ")[0]
    if first in contact_map:
        return contact_map[first]
    # Substring match either direction (handles middle names / initials).
    for key, entry in contact_map.items():
        if first and (first in key or key.split(" ")[0] == first):
            return entry
    return {"email": "", "phone": ""}


directory_df = _load_directory()
CONTACTS = _build_contact_map(directory_df)


def _contact_bits(name: str) -> str:
    """Return an HTML snippet with email + phone for a person, gracefully blank."""
    info = _lookup(name, CONTACTS)
    parts = []
    if info.get("phone"):
        phone = str(info["phone"]).strip()
        tel = re.sub(r"[^\d+]", "", phone)
        parts.append(f'<a class="sss-contact" href="tel:{tel}">📞 {phone}</a>')
    if info.get("email"):
        email = str(info["email"]).strip()
        parts.append(f'<a class="sss-contact" href="mailto:{email}">✉️ {email}</a>')
    if not parts:
        return '<span class="sss-nodata">Contact details in OPS sheet</span>'
    return " &nbsp;·&nbsp; ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# STYLES
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
.main .block-container { padding-top: 1.2rem; padding-bottom: 3rem; }

.sss-hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 45%, #0f3460 75%, #533483 100%);
    border-radius: 20px; padding: 2.4rem 2.8rem; margin-bottom: 1.6rem;
    position: relative; overflow: hidden;
}
.sss-hero::after {
    content: ''; position: absolute; bottom: -80px; right: -40px;
    width: 300px; height: 300px; background: rgba(255,255,255,0.04); border-radius: 50%;
}
.sss-hero h1 { color: #fff; font-size: 2.3rem; font-weight: 800; margin: 0 0 .5rem; }
.sss-hero p  { color: rgba(255,255,255,0.82); font-size: 1.05rem; max-width: 760px; margin: 0; line-height: 1.6; }

.sss-legend {
    display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 0 0 1.6rem;
    font-size: .9rem; color: #444;
}
.sss-legend b { color: #111; }

.sss-card {
    border-radius: 16px; padding: 1.4rem 1.5rem 1.5rem; margin-bottom: 1.2rem;
    color: #fff; position: relative; overflow: hidden;
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
}
.sss-card h2 { font-size: 1.45rem; font-weight: 800; margin: 0; color: #fff; }
.sss-card .sub { font-size: .95rem; opacity: .9; margin: .1rem 0 .8rem; font-weight: 500; }
.sss-card .purpose {
    background: rgba(255,255,255,0.15); border-radius: 10px; padding: .7rem .9rem;
    font-size: .93rem; line-height: 1.5; margin-bottom: 1rem;
}

.sss-label {
    text-transform: uppercase; letter-spacing: .06em; font-size: .72rem;
    font-weight: 700; opacity: .85; margin: .2rem 0 .5rem;
}
.sss-person {
    background: rgba(255,255,255,0.95); color: #1a1a2e; border-radius: 10px;
    padding: .6rem .85rem; margin-bottom: .5rem;
}
.sss-person .pname { font-weight: 700; font-size: 1rem; }
.sss-person .prole { font-size: .78rem; color: #666; font-weight: 500; }
.sss-contact { color: #0f3460 !important; text-decoration: none; font-weight: 600; font-size: .85rem; }
.sss-contact:hover { text-decoration: underline; }
.sss-nodata { color: #999; font-size: .8rem; font-style: italic; }

.sss-esc {
    display: flex; align-items: stretch; gap: .4rem; flex-wrap: wrap;
    margin-top: .3rem;
}
.sss-step {
    background: rgba(255,255,255,0.92); color: #1a1a2e; border-radius: 10px;
    padding: .5rem .8rem; flex: 1; min-width: 150px;
}
.sss-step .tier { font-size: .68rem; text-transform: uppercase; letter-spacing: .05em;
    color: #888; font-weight: 700; }
.sss-step .sname { font-weight: 700; font-size: .95rem; }
.sss-step .srole { font-size: .74rem; color: #666; }
.sss-arrow { align-self: center; font-size: 1.2rem; opacity: .8; }

.sss-note {
    background: #fff8e1; border-left: 4px solid #f7b500; border-radius: 8px;
    padding: .55rem .8rem; margin-top: .7rem; color: #6b5300; font-size: .85rem;
}

.sss-ccbar {
    background: linear-gradient(135deg, #b71c1c, #e53935); border-radius: 14px;
    padding: 1rem 1.3rem 1.15rem; margin: 0 0 1.6rem;
    box-shadow: 0 8px 24px rgba(183,28,28,0.18);
}
.sss-cc-head { color: #fff; font-weight: 800; font-size: 1.05rem; margin-bottom: .7rem; }
.sss-cc-head span { font-weight: 500; opacity: .85; font-size: .9rem; }
.sss-cc-grid { display: flex; gap: .7rem; flex-wrap: wrap; }
.sss-cc-person {
    background: rgba(255,255,255,0.96); color: #1a1a2e; border-radius: 10px;
    padding: .6rem .9rem; flex: 1; min-width: 220px;
}
.sss-cc-person .pname { font-weight: 700; font-size: 1rem; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HERO
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="sss-hero">
        <h1>🤝 Sales Support System</h1>
        <p>Your single reference for <b>whom to contact</b> for any support need and
        <b>whom to escalate to</b> if you don't get a response. The Sales Support System
        is organised into four departments — reach the front-line contact first, then move
        up the escalation chain in order.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="sss-legend">
        <span>👤 <b>Contact Person</b> — your first point of contact</span>
        <span>🪜 <b>Escalation Chain</b> — follow top to bottom if no response</span>
        <span>👑 <b>BCM = Dawn</b> — final escalation (Branch head)</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Always-CC banner ─────────────────────────────────────────────────────────
# Two people must be kept in CC on every escalation, across all departments.
_cc_cards = ""
for _p in CC_ON_ESCALATION:
    _cc_cards += (
        f'<div class="sss-cc-person">'
        f'<div class="pname">{_p}</div>'
        f'<div>{_contact_bits(_p)}</div>'
        f'</div>'
    )
st.markdown(
    f"""
    <div class="sss-ccbar">
        <div class="sss-cc-head">📋 Always keep in CC on <u>every</u> escalation
            <span>— across CST, Logistics, Spare and Service</span></div>
        <div class="sss-cc-grid">{_cc_cards}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if directory_df is None or directory_df.empty:
    st.info(
        "📇 Contact numbers and email addresses will appear automatically once the "
        f"**'{SUPPORT_SHEET}'** tab in the OPS sheet is reachable. The escalation "
        "structure below is always available."
    )

# ─────────────────────────────────────────────────────────────────────────────
# DEPARTMENT CARDS
# ─────────────────────────────────────────────────────────────────────────────
def _role_of(name: str) -> str:
    return ROLE_LABELS.get(name, "")


cols = st.columns(2)
for idx, dept in enumerate(DEPARTMENTS):
    with cols[idx % 2]:
        # Front-line contact persons.
        contacts_html = ""
        for person in dept["contacts"]:
            contacts_html += (
                f'<div class="sss-person">'
                f'<div class="pname">{person}</div>'
                f'<div>{_contact_bits(person)}</div>'
                f'</div>'
            )

        # Escalation chain.
        steps_html = ""
        chain = dept["escalation"]
        for i, name in enumerate(chain):
            tier = "Final (BCM)" if name == BCM_NAME else f"Escalation {i + 1}"
            role = _role_of(name)
            steps_html += (
                f'<div class="sss-step">'
                f'<div class="tier">{tier}</div>'
                f'<div class="sname">{name}</div>'
                + (f'<div class="srole">{role}</div>' if role else "")
                + f'<div>{_contact_bits(name)}</div>'
                f'</div>'
            )
            if i < len(chain) - 1:
                steps_html += '<div class="sss-arrow">→</div>'

        note_html = ""
        if dept["id"] == "service":
            note_html = (
                '<div class="sss-note">⚠️ <b>Note:</b> Service escalates up to '
                '<b>Bikas</b> only. Bikas does not report to Dawn, so this chain '
                'stops at the Service department head.</div>'
            )

        st.markdown(
            f"""
            <div class="sss-card" style="background:{dept['gradient']};">
                <h2>{dept['emoji']} {dept['name']}</h2>
                <div class="sub">{dept['full_name']}</div>
                <div class="purpose">{dept['purpose']}</div>
                <div class="sss-label">👤 Contact Person(s) — reach first</div>
                {contacts_html}
                <div class="sss-label" style="margin-top:.9rem;">🪜 Escalation Chain — if no response</div>
                <div class="sss-esc">{steps_html}</div>
                {note_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────────────────────────────────────────────
# QUICK ESCALATION MATRIX (flat table)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 🧭 Quick Escalation Matrix")
st.caption(
    "At a glance: whom to contact first for each department and the exact order "
    "to escalate in if you don't hear back."
)

matrix_rows = []
for dept in DEPARTMENTS:
    chain_display = []
    for name in dept["escalation"]:
        role = _role_of(name)
        chain_display.append(f"{name}" + (f" ({role.split('—')[0].strip()})" if role else ""))
    matrix_rows.append({
        "Department": f"{dept['emoji']} {dept['name']} — {dept['full_name']}",
        "When to contact": dept["purpose"],
        "Contact Person(s)": ", ".join(dept["contacts"]),
        "Escalate in this order": "  →  ".join(chain_display),
    })

st.dataframe(
    pd.DataFrame(matrix_rows),
    use_container_width=True,
    hide_index=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# FULL CONTACT DIRECTORY (email + phone for everyone)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 📇 Contact Directory")

# Build one row per unique person in the hierarchy, in department order.
seen = set()
dir_rows = []
for dept in DEPARTMENTS:
    people = [(p, "Contact Person") for p in dept["contacts"]]
    people += [(p, _role_of(p) or "Escalation") for p in dept["escalation"]]
    for name, role in people:
        key = _norm(name)
        if key in seen:
            continue
        seen.add(key)
        info = _lookup(name, CONTACTS)
        dir_rows.append({
            "Name": name,
            "Department": dept["name"],
            "Role": role,
            "Phone": info.get("phone", "") or "—",
            "Email": info.get("email", "") or "—",
        })

# Always-CC contacts (apply to every department's escalation).
for name in CC_ON_ESCALATION:
    key = _norm(name)
    if key in seen:
        continue
    seen.add(key)
    info = _lookup(name, CONTACTS)
    dir_rows.append({
        "Name": name,
        "Department": "All",
        "Role": "CC on every escalation",
        "Phone": info.get("phone", "") or "—",
        "Email": info.get("email", "") or "—",
    })

st.dataframe(
    pd.DataFrame(dir_rows),
    use_container_width=True,
    hide_index=True,
)

with st.expander("ℹ️ How this directory stays up to date"):
    _cc_names = " and ".join(CC_ON_ESCALATION)
    st.markdown(
        f"""
        - The **reporting structure and escalation order** are maintained in this page.
        - **Phone numbers and email addresses** are read live from the OPS spreadsheet
          tab named **`{SUPPORT_SHEET}`** and matched to each person by name.
        - To update a contact number or email, simply edit that person's row in the
          **`{SUPPORT_SHEET}`** tab — the change shows here within 5 minutes
          (or immediately on a hard refresh).
        - **Escalation rule:** always contact the front-line person first. Escalate to
          the next name in the chain only after a reasonable wait with no response.
          For CST, Logistics and Spare the final escalation is **Dawn (BCM)**; the
          **Service** chain stops at **Bikas**.
        - **Always CC on escalations:** keep **{_cc_names}** in CC on *every*
          escalation email, across all four departments.
        """
    )

if not directory_df.empty:
    if st.button("🔄 Refresh contact details", help="Reload phone/email from the OPS sheet"):
        _load_directory.clear()
        st.rerun()
