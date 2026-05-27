"""
app.py - Navigation controller for Interio by Godrej Patia CRM
All page names in the sidebar are defined here via st.navigation().
The first page listed is shown by default when the app loads.
"""
import streamlit as st

st.set_page_config(
    layout="wide",
    page_title="4sInteriors B2C Sales Dashboard",
    page_icon="🛋",
    initial_sidebar_state="expanded",
)

if "show_old_data_dashboard" not in st.session_state:
    st.session_state.show_old_data_dashboard = False

with st.sidebar:
    st.markdown("### Page Settings")
    st.toggle(
        "Show Old Data Dashboard (Pre FY 26-27)",
        key="show_old_data_dashboard",
        help=(
            "Turn this on to view the historical (pre FY 26-27) data dashboard. "
            "When off, the page is hidden from the sidebar."
        ),
    )
    st.markdown("---")

sales_handbook_pages = [
    st.Page("pages/55_Monthend_Sales_Forecast.py",    title="Monthly Sales Target vs Achievement", icon="📅"),
    st.Page("pages/90_Sales_Team_Tasks.py",            title="Sales Team Tasks",                    icon="✅"),
    st.Page("pages/95_Happy_Calling.py",               title="Happy Calling",                       icon="📞"),
    st.Page("pages/70_Leads.py",                       title="Leads",                               icon="🎯"),
]

inventory_pages = [
    st.Page("pages/50_MIS_Update.py",          title="MIS UPDATE",         icon="📦"),
    st.Page("pages/60_Stock.py",               title="STOCK",              icon="🏭"),
    st.Page("pages/62_34s_Stock.py",           title="34s Stock Details",  icon="📦"),
    st.Page("pages/65_Price_List.py",          title="Price List",         icon="💰"),
    st.Page("pages/40_Products_catalog.py",    title="Product Catalogue",  icon="🪑"),
]

nav_pages = {
    "": [                   # Streamlit renders "" sections first — keeps pages 1-2 at top with no header
        st.Page("pages/b2c_dashboard.py",                   title="4sInteriors B2C Sales Dashboard", icon="🛋"),
        st.Page("pages/daily_b2c_sales.py",                 title="Daily B2C Sales",                 icon="📅"),
    ],
    "SALES HANDBOOK": sales_handbook_pages,
    "Inventory and Stocks": inventory_pages,
    "​": [             # Zero-width space — unique key, renders as no visible header, stays at bottom
        st.Page("pages/17_Customer_Intelligence_Engine.py", title="Customer Intelligence Engine",    icon="🧠"),
        st.Page("pages/20_Product_Sales_Analysis.py",       title="Product Sales Analysis",          icon="📊"),
        st.Page("pages/100_Sales_Manager_Dashboard.py",     title="Sales Manager Dashboard",         icon="🏆"),
        st.Page("pages/01_CRM_Feature_Guide.py",            title="CRM FEATURE GUIDE",               icon="🗺️"),
    ],
}

if st.session_state.show_old_data_dashboard:
    nav_pages[""].append(
        st.Page("pages/old_data_dashboard.py", title="Old Data Dashboard", icon="📂")
    )

pg = st.navigation(nav_pages)
pg.run()
