"""
29_SOP.py
Standard Operating Procedure (SOP) reference page for the Sales Handbook.

Each SOP is grouped under a collapsible category. Categories stay collapsed by
default and expand on click to reveal the step-by-step procedure.
"""

import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="Standard Operating Procedures",
    page_icon="📋",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# STYLES
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

.main .block-container { padding-top: 1rem; padding-bottom: 3rem; }
html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }

/* ── Hero Banner ─────────────────────────────────────────────────────────── */
.sop-hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 40%, #0f3460 70%, #533483 100%);
    border-radius: 20px;
    padding: 2.6rem 3rem;
    margin-bottom: 1.8rem;
    position: relative;
    overflow: hidden;
}
.sop-hero::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 240px; height: 240px;
    background: rgba(255,255,255,0.04);
    border-radius: 50%;
}
.sop-hero-title {
    font-size: 2.4rem; font-weight: 800; color: #ffffff;
    line-height: 1.2; margin-bottom: 0.6rem;
}
.sop-hero-subtitle {
    font-size: 1.08rem; color: rgba(255,255,255,0.80);
    font-weight: 400; line-height: 1.6; max-width: 720px;
}

/* ── Step cards inside an SOP ────────────────────────────────────────────── */
.sop-step {
    display: flex;
    gap: 1rem;
    padding: 1rem 1.1rem;
    margin-bottom: 0.85rem;
    background: rgba(15, 52, 96, 0.05);
    border: 1px solid rgba(15, 52, 96, 0.12);
    border-left: 4px solid #0f3460;
    border-radius: 12px;
}
.sop-step-num {
    flex: 0 0 34px;
    height: 34px; width: 34px;
    border-radius: 50%;
    background: #0f3460;
    color: #ffffff;
    font-weight: 700;
    font-size: 1rem;
    display: flex; align-items: center; justify-content: center;
}
.sop-step-body { flex: 1; }
.sop-step-body p { margin: 0; font-size: 1rem; line-height: 1.55; color: #1f2937; }

.sop-note {
    background: #fff7ed;
    border: 1px solid #fdba74;
    border-left: 4px solid #ea580c;
    border-radius: 12px;
    padding: 1rem 1.2rem;
    margin-top: 0.4rem;
}
.sop-note b { color: #c2410c; }
.sop-note p { margin: 0.3rem 0 0 0; color: #431407; line-height: 1.55; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HERO
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="sop-hero">
    <div class="sop-hero-title">📋 Standard Operating Procedures</div>
    <div class="sop-hero-subtitle">
        Step-by-step SOPs for the sales &amp; service team. Click a category below to
        expand it and read the full procedure. Follow every step in order.
    </div>
</div>
""", unsafe_allow_html=True)


def render_step(number: str, text: str) -> str:
    """Return HTML for a single numbered SOP step."""
    return (
        f'<div class="sop-step">'
        f'<div class="sop-step-num">{number}</div>'
        f'<div class="sop-step-body"><p>{text}</p></div>'
        f'</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY: SERVICE REQUEST  (collapsed by default — expanded=False)
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("🛠️  Service Request", expanded=False):
    steps = [
        (
            "1",
            "When there is a customer complaint, ask the customer to lodge a "
            "service request — or lodge it on their behalf.",
        ),
        (
            "2",
            "Add that service request against the customer order in the App, and "
            "also record it in the Service Request register. It is "
            "<b>MANDATORY to enter the Service Request Number</b> whenever a new "
            "service request is raised — a request cannot be logged without it.",
        ),
        (
            "3",
            "Follow up with the service team on the service request number for a "
            "maximum of 7 days over phone. Register every communication in both the "
            "App and the register.",
        ),
        (
            "4",
            "After 7 days, initiate an email communication for the service request "
            "with full order details (SO number, customer details and order "
            "details) and follow up via email. Share the details with the customer "
            "by calling them, and if necessary set up a conference call between the "
            "customer and the service team.",
        ),
        (
            "5",
            "Collect the HAPPY CODE from the customer only after the issue is "
            "resolved — the service request can be closed from our end only once "
            "the Happy Code is received. It is <b>MANDATORY to enter the Happy "
            "Code</b> while resolving a service request; the request cannot be "
            "marked resolved / closed without it.",
        ),
    ]
    st.markdown(
        "".join(render_step(num, text) for num, text in steps),
        unsafe_allow_html=True,
    )
    st.markdown("""
<div class="sop-note">
    <b>⚠️ Educate the customer on the HAPPY CODE</b>
    <p>
        Make sure customers understand the Happy Code and know <b>not to share it</b>
        with the installation / service team if they are not satisfied with the
        installation or the resolution of the service request.
    </p>
</div>
""", unsafe_allow_html=True)
