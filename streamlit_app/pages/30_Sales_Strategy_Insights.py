import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.sheets import get_df
import altair as alt

st.set_page_config(page_title="Sales Strategy & Insights", layout="wide")

# ---------- 1. MORALE BOOSTER (DAILY QUOTE) ----------
quotes = [
    "“90 percent of selling is conviction and 10 percent is persuasion.” – Shiv Khera",
    "“The successful warrior is the average man, with laser-like focus.” – Bruce Lee",
    "“Opportunities are usually disguised as hard work, so most people don't recognize them.” – Ann Landers",
    "“Your attitude, not your aptitude, will determine your altitude.” – Zig Ziglar",
    "“Great salespeople are relationship builders who provide value and help their customers win.” – Jeffrey Gitomer",
    "“Don't watch the clock; do what it does. Keep going.” – Sam Levenson"
]
quote_of_the_day = quotes[datetime.now().day % len(quotes)]

st.markdown(f"""
    <div style="background-color: #f0f2f6; padding: 20px; border-radius: 10px; border-left: 5px solid #1b5e20; margin-bottom: 25px;">
        <h3 style="margin-top: 0; color: #1b5e20;">🌟 Team Morale Booster</h3>
        <p style="font-size: 18px; font-weight: bold; color: #333;">{quote_of_the_day}</p>
    </div>
""", unsafe_allow_html=True)

st.title("📈 Sales Strategy & Festival Insights")

# ---------- 2. MONTHLY TARGET TRACKER ----------
st.markdown("---")
st.subheader("🎯 Monthly Target Tracker")

# Load CRM data to calculate current achievement
crm_raw = get_df("CRM")
current_month_sales = 0

if crm_raw is not None and not crm_raw.empty:
    crm = crm_raw.copy()
    crm.columns = [str(c).strip().upper() for c in crm.columns]
    
    # Cleaning Numeric Data
    sales_col = next((c for c in crm.columns if "ORDER" in c and "AMOUNT" in c), "ORDER AMOUNT")
    if sales_col in crm.columns:
        crm[sales_col] = pd.to_numeric(crm[sales_col].astype(str).str.replace("[₹,]", "", regex=True), errors='coerce').fillna(0)
    
    crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
    
    # Filter for current month and year
    now = datetime.now()
    month_mask = (crm["DATE_DT"].dt.month == now.month) & (crm["DATE_DT"].dt.year == now.year)
    current_month_sales = crm.loc[month_mask, sales_col].sum()

# User Input for Target
col_t1, col_t2 = st.columns([1, 2])
with col_t1:
    monthly_goal = st.number_input("Set Monthly Sales Goal (₹)", min_value=100000, value=5000000, step=100000)

achievement_pct = (current_month_sales / monthly_goal) * 100 if monthly_goal > 0 else 0
remaining = monthly_goal - current_month_sales if monthly_goal > current_month_sales else 0

with col_t2:
    st.write(f"### Current Achievement: ₹{current_month_sales:,.2f}")
    # Progress Bar
    bar_color = "green" if achievement_pct >= 80 else "orange" if achievement_pct >= 40 else "red"
    st.progress(min(achievement_pct / 100, 1.0))
    st.write(f"**{achievement_pct:.1f}%** of the monthly goal achieved.")

if remaining > 0:
    days_left = (datetime(now.year, now.month + 1, 1) - timedelta(days=1)).day - now.day
    daily_needed = remaining / max(days_left, 1)
    st.warning(f"🚩 Need **₹{daily_needed:,.2f}/day** for the next {days_left} days to hit the target!")
else:
    st.balloons()
    st.success("🏆 Target Smashed! Everything from here is a bonus for the team.")

# ---------- 3. BHUBANESWAR FESTIVAL CALENDAR ----------
st.markdown("---")
st.subheader("🗓️ Upcoming Boost Opportunities (Bhubaneswar, Odisha)")

festivals = [
    {"Date": "01-Apr-2026", "Festival": "Odisha Day (Utkala Dibasa)", "Type": "Regional Pride", "Decoration": "Odishi Theme, Pattachitra Hangings"},
    {"Date": "14-Apr-2026", "Festival": "Maha Vishuba Sankranti (New Year)", "Type": "Major Festival", "Decoration": "Traditional Alpona/Jhoti"},
    {"Date": "14-Jun-2026", "Festival": "Raja Parba", "Type": "Regional Peak", "Decoration": "Floral Swings, Ethnic Drapes"},
    {"Date": "16-Jul-2026", "Festival": "Ratha Yatra", "Type": "Massive Peak", "Decoration": "Chariot Motifs & Bright Fabrics"},
]
st.table(pd.DataFrame(festivals))

# ---------- 4. STRATEGY & DECORATION ----------
st.markdown("---")
st.subheader("🛠️ Showroom Strategy & Methods")

tab1, tab2 = st.tabs(["🎨 Decoration Strategy", "💰 Sales Growth Methods"])

with tab1:
    st.markdown("""
    **When to Decorate:** * Start decorations **3-5 days before** the festival to catch early shoppers.
    
    **Decoration Ideas:**
    * **Themed Room Sets:** Create a 'Festival Living Room' corner with local cushions.
    * **Photo Corner:** A decorated 'Selfie Spot' encourages customers to share photos of your showroom online.
    * **Local Aesthetics:** Use marigold flowers and traditional brass lamps (Diyas) to create a warm, inviting Odia home feel.
    """)

with tab2:
    st.markdown("""
    * **Festival Combo Offers:** Package a Sofa with a Coffee Table as a 'New Year Bundle'.
    * **Exchange Melas:** Run 'Old Furniture Exchange' campaigns during April.
    * **The 'Raja' Special:** Since Raja Parba celebrates women, offer a special discount or a small gift for women customers during those days.
    * **Early Bird Bonus:** Extra 5% discount for bookings made before 1:00 PM to increase morning walk-ins.
    """)

st.info(f"🚀 **Action Point:** Start prepping for **{festivals[0]['Festival']}** on **{festivals[0]['Date']}**!")