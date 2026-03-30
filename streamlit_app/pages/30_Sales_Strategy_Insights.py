import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.sheets import get_df

# 1. PAGE CONFIG
st.set_page_config(page_title="Sales Strategy & Insights", layout="wide")

# ---------------------------------------------------------
# 2. PERSISTENT STATE INITIALIZATION
# ---------------------------------------------------------
# This ensures the target value stays fixed during page changes
if "monthly_goal_persistent" not in st.session_state:
    st.session_state.monthly_goal_persistent = 10000000.0  # Default: 1 Crore

# ---------------------------------------------------------
# 3. DYNAMIC DAILY QUOTE
# ---------------------------------------------------------
quotes = [
    "“90% of selling is conviction and 10% is persuasion.” – Shiv Khera",
    "“Your attitude, not your aptitude, will determine your altitude.” – Zig Ziglar",
    "“Great salespeople are relationship builders who help customers win.” – Jeffrey Gitomer",
    "“Don't watch the clock; do what it does. Keep going.” – Sam Levenson",
    "“Action is the foundational key to all success.” – Pablo Picasso",
    "“Quality is not an act, it is a habit.” – Aristotle"
]
# Changes based on the day of the year
quote_of_the_day = quotes[datetime.now().timetuple().tm_yday % len(quotes)]

st.markdown(f"""
    <div style="background-color: #f0f2f6; padding: 20px; border-radius: 10px; border-left: 5px solid #2e7d32; margin-bottom: 25px;">
        <h3 style="margin-top: 0; color: #2e7d32;">🌟 Team Morale Booster</h3>
        <p style="font-size: 18px; font-style: italic; color: #333;">{quote_of_the_day}</p>
    </div>
""", unsafe_allow_html=True)

st.title("📈 Sales Strategy & Festival Insights")

# ---------------------------------------------------------
# 4. DATA LOADING & CLEANING
# ---------------------------------------------------------
crm_raw = get_df("CRM")
current_month_sales = 0

if crm_raw is not None and not crm_raw.empty:
    crm = crm_raw.copy()
    crm.columns = [str(c).strip().upper() for c in crm.columns]
    
    # Identify key columns
    sales_col = next((c for c in crm.columns if "ORDER" in c and "AMOUNT" in c), "ORDER AMOUNT")
    product_col = next((c for c in crm.columns if "PRODUCT" in c or "ITEM" in c), "PRODUCT NAME")
    
    # Numeric Clean
    crm[sales_col] = pd.to_numeric(crm[sales_col].astype(str).str.replace("[₹,]", "", regex=True), errors='coerce').fillna(0)
    
    # Date Handling
    crm["DATE_DT"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")
    crm = crm.dropna(subset=["DATE_DT"])
    
    # Filter Current Month
    now = datetime.now()
    month_mask = (crm["DATE_DT"].dt.month == now.month) & (crm["DATE_DT"].dt.year == now.year)
    current_month_sales = crm.loc[month_mask, sales_col].sum()

    # ---------------------------------------------------------
    # 5. PERSISTENT MONTHLY TARGET TRACKER
    # ---------------------------------------------------------
    st.subheader("🎯 Monthly Target Tracker")
    col_t1, col_t2 = st.columns([1, 2])

    with col_t1:
        # 'key' links this input directly to the persistent session state
        monthly_goal = st.number_input(
            "Set Monthly Target (₹)", 
            min_value=100000.0, 
            step=100000.0,
            key="monthly_goal_persistent"
        )

    achievement_pct = (current_month_sales / monthly_goal) * 100 if monthly_goal > 0 else 0
    remaining = monthly_goal - current_month_sales

    with col_t2:
        st.write(f"### Achievement: ₹{current_month_sales:,.2f}")
        st.progress(min(achievement_pct / 100, 1.0))
        st.write(f"**{achievement_pct:.1f}%** reached.")

    # Run-rate logic
    if remaining > 0:
        last_day = (now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        days_left = (last_day.date() - now.date()).days + 1
        daily_needed = remaining / max(days_left, 1)
        st.warning(f"🚩 Gap: **₹{remaining:,.2f}**. Need **₹{daily_needed:,.2f}/day** for the next {days_left} days.")
    else:
        st.balloons()
        st.success("🏆 **Goal Achieved!**")

    st.markdown("---")

    # ---------------------------------------------------------
    # 6. DYNAMIC SALES TRENDS (PRODUCT & FOOTFALL)
    # ---------------------------------------------------------
    st.subheader("📊 Intelligent Sales Trends")
    
    crm["DAY_NAME"] = crm["DATE_DT"].dt.day_name()
    
    # Performance by Day
    day_perf = crm.groupby("DAY_NAME").agg({sales_col: ["sum", "count"]})
    day_perf.columns = ["Revenue", "Orders"]
    
    top_revenue_day = day_perf["Revenue"].idxmax()
    top_footfall_day = day_perf["Orders"].idxmax()
    
    # Performance by Product
    prod_perf = crm.groupby(product_col)[sales_col].sum().sort_values(ascending=False)
    best_seller = prod_perf.index[0]

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("🔥 Best Seller", best_seller)
    with c2:
        st.metric("🚶 Peak Footfall", f"Every {top_footfall_day}")
    with col3 if 'col3' in locals() else c3: # Safety check for column names
        st.metric("💰 High Revenue Day", f"Every {top_revenue_day}")

    st.info(f"💡 **Insight:** Your highest volume of customers arrive on **{top_footfall_day}s**. Ensure all Godrej sofa displays are vacuumed and price tags are visible before the showroom opens on these days.")

# ---------------------------------------------------------
# 7. DYNAMIC BHUBANESWAR FESTIVAL CALENDAR
# ---------------------------------------------------------
st.markdown("---")
st.subheader("🗓️ Upcoming Boost Opportunities (Bhubaneswar)")

festivals = [
    {"Date": "01-Apr-2026", "Festival": "Odisha Day (Utkala Dibasa)", "Type": "Regional Pride", "Decoration": "Pattachitra Hangings"},
    {"Date": "14-Apr-2026", "Festival": "Odia New Year", "Type": "Major Festival", "Decoration": "Marigold Flowers & Jhoti"},
    {"Date": "14-Jun-2026", "Festival": "Raja Parba", "Type": "Regional Celebration", "Decoration": "Floral Swings & Ethnic Drapes"},
    {"Date": "16-Jul-2026", "Festival": "Ratha Yatra", "Type": "Massive Peak", "Decoration": "Chariot Motifs & Red/Yellow Fabrics"},
    {"Date": "20-Oct-2026", "Festival": "Durga Puja / Dussehra", "Type": "Shopping Peak", "Decoration": "Traditional Pandal Theme"},
    {"Date": "08-Nov-2026", "Festival": "Diwali", "Type": "Mega Sale", "Decoration": "Diyas, Rangoli & LED Lights"}
]

fest_df = pd.DataFrame(festivals)
fest_df["DATE_OBJ"] = pd.to_datetime(fest_df["Date"], format="%d-%b-%Y")

# DYNAMIC FILTER: Only show today and future dates
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
upcoming_df = fest_df[fest_df["DATE_OBJ"] >= today].sort_values("DATE_OBJ")

if not upcoming_df.empty:
    st.table(upcoming_df[["Date", "Festival", "Type", "Decoration"]])
    next_fest = upcoming_df.iloc[0]
    st.success(f"🚀 **Action Point:** Start {next_fest['Festival']} preparations by **{(next_event['DATE_OBJ'] - timedelta(days=4)).strftime('%d-%b') if 'next_event' in locals() else 'next week'}**.")
else:
    st.info("No more festivals listed for this period.")

# ---------------------------------------------------------
# 8. STRATEGY GUIDE
# ---------------------------------------------------------
st.markdown("---")
tab1, tab2 = st.tabs(["🎨 Decoration Strategy", "💰 Sales Growth"])

with tab1:
    st.markdown("""
    * **The Golden Triangle:** Place your best-selling product near the center of the showroom.
    * **Sensory Branding:** Use subtle Sandalwood fragrance to create a premium Godrej experience.
    * **Lighting:** Use warm spotlights on leatherette sofas to highlight textures.
    """)

with tab2:
    st.markdown("""
    * **Combo Offers:** Bundle slow-moving accessories with top-selling recliners.
    * **Early Bird:** Offer a 'Morning Coffee' discount for bookings made before 12:00 PM.
    * **WhatsApp Retargeting:** Send festival-themed greetings 2 days before the event.
    """)