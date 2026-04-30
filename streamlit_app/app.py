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

pg = st.navigation([
    st.Page("pages/b2c_dashboard.py",      title="4sInteriors B2C Sales Dashboard", icon="🛋️"),
    st.Page("pages/daily_b2c_sales.py",    title="Daily B2C Sales",                 icon="📅"),
    st.Page("pages/old_data_dashboard.py", title="Old Data Dashboard",               icon="📂"),
    st.Page("pages/17_Customer_Intelligence_Engine.py", title="Customer Intelligence Engine", icon="🧠"),
    st.Page("pages/20_Product_Sales_Analysis.py",       title="Product Sales Analysis",       icon="📊"),
    st.Page("pages/30_Sales_Strategy_Insights.py",      title="Sales Strategy Insights",      icon="💡"),
    st.Page("pages/40_Products_catalog.py",             title="Products Catalog",              icon="🪑"),
    st.Page("pages/70_Leads.py",                        title="Leads",                         icon="🎯"),
    st.Page("pages/90_Sales_Team_Tasks.py",             title="Sales Team Tasks",              icon="✅"),
])

pg.run()
