"""
app.py — Navigation controller for Interio by Godrej Patia CRM
All page names in the sidebar are defined here via st.navigation().
The first page listed is shown by default when the app loads.
"""
import streamlit as st

st.set_page_config(
    layout="wide",
    page_title="4sInteriors B2C Sales Dashboard",
    page_icon="🛋️",
    initial_sidebar_state="expanded",
)

# ── Sidebar toggle: show / hide Old Data Dashboard ───────────────────────────
# Persists across page changes via st.session_state so the user does not have
# to re-enable it each time they navigate.
if "show_old_data_dashboard" not in st.session_state:
    st.session_state.show_old_data_dashboard = False  # hidden by default

with st.sidebar:
    st.markdown("### ⚙️ Page Settings")
    st.toggle(
        "Show Old Data Dashboard (Pre FY 26-27)",
        key="show_old_data_dashboard",
        help=(
            "Turn this on to view the historical (pre FY 26-27) data dashboard. "
            "When off, the page is hidden from the sidebar."
        ),
    )
    st.markdown("---")

# ── Build the navigation list dynamically ────────────────────────────────────
pages = [
    st.Page("pages/b2c_dashboard.py",                   title="4sInteriors B2C Sales Dashboard",  icon="🛋️"),
    st.Page("pages/daily_b2c_sales.py",                 title="Daily B2C Sales",                  icon="📅"),
    st.Page("pages/17_Customer_Intelligence_Engine.py", title="Customer Intelligence Engine",     icon="🧠"),
    st.Page("pages/20_Product_Sales_Analysis.py",       title="Product Sales Analysis",           icon="📊"),
    st.Page("pages/30_Sales_Reports_and_Strategy.py",   title="Sales Reports and Strategy",       icon="💡"),
    st.Page("pages/40_Products_catalog.py",             title="Products Catalog",                 icon="🪑"),
    st.Page("pages/70_Leads.py",                        title="Leads",                            icon="🎯"),
    st.Page("pages/80_Sales_Targets.py",                title="Sales Targets & Achievement",      icon="📈"),
    st.Page("pages/90_Sales_Team_Tasks.py",             title="Sales Team Tasks",                 icon="✅"),
]

# Old Data Dashboard is appended at the BOTTOM and only when the toggle is on.
if st.session_state.show_old_data_dashboard:
    pages.append(
        st.Page("pages/old_data_dashboard.py", title="Old Data Dashboard", icon="📂")
    )

pg = st.navigation(pages)
pg.run()
