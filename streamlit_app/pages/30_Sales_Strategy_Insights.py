import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.sheets import get_df

st.set_page_config(page_title="Sales Strategy & Insights", layout="wide")

# ---------- 1. MORALE BOOSTER (DAILY QUOTE) ----------
quotes = [
    "“90 percent of selling is conviction and 10 percent is persuasion.” – Shiv Khera",
    "“Keep your face always toward the sunshine – and shadows will fall behind you.” – Walt Whitman",
    "“Opportunities are usually disguised as hard work, so most people don't recognize them.” – Ann Landers",
    "“Your attitude, not your aptitude, will determine your altitude.” – Zig Ziglar",
    "“Great salespeople are relationship builders who provide value and help their customers win.” – Jeffrey Gitomer",
    "“Don't watch the clock; do what it does. Keep going.” – Sam Levenson"
]
quote_of_the_day = quotes[datetime.now().day % len(quotes)]

st.markdown(f"""
    <div style="background-color: #f0f2f6; padding: 20px; border-radius: 10px; border-left: 5px solid #2e7d32; margin-bottom: 25px;">
        <h3 style="margin-top: 0; color: #2e7d32;">🌟 Team Morale Booster</h3>
        <p style="font-size: 18px; font-style: italic; color: #333;">{quote_of_the_day}</p>
    </div>
""", unsafe_allow_html=True)

st.title("📈 Sales Strategy & Festival Insights")

# ---------- 2. MONTHLY TARGET TRACKER ----------
st.subheader("🎯 Monthly Target Tracker")

crm_raw = get_df("CRM")
current_month_sales = 0

if crm_raw is not None and not crm_raw.empty:
    crm = crm_raw.copy()
    crm.columns = [str(c).strip().upper() for c in crm.columns]
    
    # Clean Sales Data
    sales_col = next((c for c in crm.columns if "ORDER" in c and "AMOUNT" in c), "ORDER AMOUNT")
    if sales_col in crm.columns:
        crm[sales_col] = pd.to_numeric(crm[sales_col].astype(str).str.replace("[₹,]", "", regex=True), errors='coerce').fillna(0)
    
    crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
    
    # Filter for Current Month Sales
    now = datetime.now()
    month_mask = (crm["DATE_DT"].dt.month == now.month) & (crm["DATE_DT"].dt.year == now.year)
    current_month_sales = crm.loc[month_mask, sales_col].sum()

# Layout for Tracker
col_t1, col_t2 = st.columns([1, 2])
with col_t1:
    monthly_goal = st.number_input("Set Monthly Target (₹)", min_value=100000, value=3000000, step=100000)

achievement_pct = (current_month_sales / monthly_goal) * 100 if monthly_goal > 0 else 0
remaining = monthly_goal - current_month_sales if monthly_goal > current_month_sales else 0

with col_t2:
    st.write(f"### Current Achievement: ₹{current_month_sales:,.2f}")
    # Visual Progress Bar
    st.progress(min(achievement_pct / 100, 1.0))
    st.write(f"**{achievement_pct:.1f}%** of goal reached.")

# Daily Run-Rate Calculation
if remaining > 0:
    # Calculate days left in current month
    last_day = (now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    days_left = (last_day.date() - now.date()).days + 1
    daily_needed = remaining / max(days_left, 1)
    st.warning(f"🚩 Target Gap: **₹{remaining:,.2f}**. You need **₹{daily_needed:,.2f}/day** for the next {days_left} days.")
else:
    st.balloons()
    st.success("🏆 **Goal Achieved!** The team has hit the monthly target.")

st.markdown("---")

# ---------- 3. ANALYSIS LOGIC ----------
if crm_raw is not None and not crm_raw.empty:
    crm["DAY_NAME"] = crm["DATE_DT"].dt.day_name()
    day_performance = crm.groupby("DAY_NAME")[sales_col].mean().sort_values(ascending=False)
    top_day = day_performance.index[0]
    
    product_col = next((c for c in crm.columns if "ITEM" in c or "PRODUCT" in c), "PRODUCT")
    top_products = crm.groupby(product_col)[sales_col].sum().nlargest(3).index.tolist()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📊 Performance Trends")
        st.write(f"✅ **Peak Sales Day:** {top_day}s")
        st.write(f"🔥 **Trending Products:** {', '.join(top_products)}")
    with col2:
        st.info("💡 **Insight:** Schedule your showroom cleaning and restocking for your lowest sales day to ensure the team is 100% available for customers on peak days.")

st.markdown("---")

# ---------- 4. BHUBANESWAR FESTIVAL CALENDAR 2026 ----------
st.subheader("🗓️ Upcoming Boost Opportunities (Bhubaneswar, Odisha)")

festivals = [
    {"Date": "01-Apr-2026", "Festival": "Odisha Day (Utkala Dibasa)", "Type": "Regional Pride", "Decoration": "Odishi Theme, Pattachitra Hangings"},
    {"Date": "14-Apr-2026", "Festival": "Maha Vishuba Sankranti (Odia New Year)", "Type": "Major Festival", "Decoration": "Traditional Alpona/Jhoti, Marigold Flowers"},
    {"Date": "01-May-2026", "Festival": "Buddha Purnima", "Type": "Holiday", "Decoration": "Zen/Minimalist Furniture Layout"},
    {"Date": "14-Jun-2026", "Festival": "Raja Parba (Starts)", "Type": "Regional Celebration", "Decoration": "Floral Swings, Ethnic Fabric Drapes"},
    {"Date": "16-Jul-2026", "Festival": "Ratha Yatra", "Type": "Massive Peak", "Decoration": "Chariot Motifs, Bright Yellow/Red Fabrics"},
]

fest_df = pd.DataFrame(festivals)
st.table(fest_df)

# ---------- 5. ACTIONABLE METHODS ----------
st.markdown("---")
st.subheader("🛠️ Strategy & Decoration Guide")

tab1, tab2 = st.tabs(["🎨 Decoration Strategy", "💰 Sales Growth Methods"])

with tab1:
    st.markdown("""
    **When to Decorate:** * Always decorate **3-4 days before** the festival date.
    **Decoration Ideas:**
    * **Themed Room Sets:** Create a 'Festival Living Room' with local textiles.
    * **Sensory Marketing:** Use Sandalwood incense and Odissi music.
    * **Photo Corner:** A 'Selfie Spot' with festival props gets you free social media tags!
    """)

with tab2:
    st.markdown("""
    * **Festival Combo Offers:** Pair Sofas with Coffee Tables for a 'New Year Bundle'.
    * **Exchange Melas:** April is perfect for 'Old to New' exchange offers.
    * **The 'Raja' Special:** Discounts for women shoppers during Raja Parba.
    * **Early Bird:** Extra 5% off for invoices generated before 1:00 PM.
    """)

# Find the next festival from today's date
upcoming = [f for f in festivals if datetime.strptime(f['Date'], '%d-%b-%Y').date() >= datetime.now().date()]
next_fest = upcoming[0]['Festival'] if upcoming else "the next season"

st.success(f"🚀 **Action Point:** Start planning your showroom layout for **{next_fest}** today!")