import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.sheets import get_df

st.set_page_config(page_title="Sales Strategy & Insights", layout="wide")

# ---------- 1. DYNAMIC DAILY QUOTES ----------
# Dictionary keyed by day of the month (1-31)
daily_quotes = {
    1: "“The secret of getting ahead is getting started.” – Mark Twain",
    2: "“Don’t find fault, find a remedy.” – Henry Ford",
    3: "“90% of selling is conviction and 10% is persuasion.” – Shiv Khera",
    4: "“Your attitude, not your aptitude, will determine your altitude.” – Zig Ziglar",
    5: "“Change your thoughts and you change your world.” – Norman Vincent Peale",
    # ... add up to 31 or use modulo as below for safety
}

# Fallback quotes list if day not in dict
quotes_list = [
    "“Quality is not an act, it is a habit.” – Aristotle",
    "“Great salespeople help their customers win.” – Jeffrey Gitomer",
    "“High expectations are the key to everything.” – Sam Walton",
    "“Everything you’ve ever wanted is on the other side of fear.” – George Addair",
    "“Action is the foundational key to all success.” – Pablo Picasso"
]

day_of_month = datetime.now().day
quote_of_the_day = daily_quotes.get(day_of_month, quotes_list[day_of_month % len(quotes_list)])

st.markdown(f"""
    <div style="background-color: #f0f2f6; padding: 20px; border-radius: 10px; border-left: 5px solid #2e7d32; margin-bottom: 25px;">
        <h3 style="margin-top: 0; color: #2e7d32;">🌟 Team Morale Booster</h3>
        <p style="font-size: 18px; font-style: italic; color: #333;">{quote_of_the_day}</p>
    </div>
""", unsafe_allow_html=True)

st.title("📈 Dynamic Sales Strategy & Insights")

# ---------- 2. DATA PREPARATION ----------
crm_raw = get_df("CRM")
if crm_raw is not None and not crm_raw.empty:
    crm = crm_raw.copy()
    crm.columns = [str(c).strip().upper() for c in crm.columns]
    
    # Identify key columns dynamically
    sales_col = next((c for c in crm.columns if "ORDER" in c and "AMOUNT" in c), "ORDER AMOUNT")
    product_col = next((c for c in crm.columns if "PRODUCT" in c or "ITEM" in c), "PRODUCT NAME")
    
    # Clean Numeric Data
    crm[sales_col] = pd.to_numeric(crm[sales_col].astype(str).str.replace("[₹,]", "", regex=True), errors='coerce').fillna(0)
    
    # Fix Dates
    crm["DATE_DT"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")
    crm = crm.dropna(subset=["DATE_DT"]) # Remove rows with invalid dates
    crm["DAY_NAME"] = crm["DATE_DT"].dt.day_name()
    crm["MONTH_VAL"] = crm["DATE_DT"].dt.month
    crm["YEAR_VAL"] = crm["DATE_DT"].dt.year

    # ---------- 3. MONTHLY TARGET TRACKER ----------
    st.subheader("🎯 Monthly Target Tracker")
    now = datetime.now()
    month_mask = (crm["MONTH_VAL"] == now.month) & (crm["YEAR_VAL"] == now.year)
    current_month_sales = crm.loc[month_mask, sales_col].sum()

    col_t1, col_t2 = st.columns([1, 2])
    with col_t1:
        monthly_goal = st.number_input("Set Monthly Target (₹)", min_value=100000, value=2000000, step=50000)

    achievement_pct = (current_month_sales / monthly_goal) * 100 if monthly_goal > 0 else 0
    remaining = monthly_goal - current_month_sales

    with col_t2:
        st.write(f"### Achievement: ₹{current_month_sales:,.2f}")
        st.progress(min(achievement_pct / 100, 1.0))
        st.write(f"**{achievement_pct:.1f}%** reached.")

    if remaining > 0:
        last_day = (now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        days_left = (last_day.date() - now.date()).days + 1
        daily_needed = remaining / max(days_left, 1)
        st.warning(f"🚩 Need **₹{daily_needed:,.2f}/day** for the next {days_left} days to hit goal.")
    else:
        st.balloons()
        st.success("🏆 Goal Achieved!")

    st.markdown("---")

    # ---------- 4. DYNAMIC TREND ANALYSIS ----------
    st.subheader("📊 Intelligent Sales Trends")
    
    # A. Day of Week Analysis (Footfall vs Value)
    day_stats = crm.groupby("DAY_NAME").agg({
        sales_col: ["mean", "sum", "count"]
    })
    day_stats.columns = ['Avg_Sale', 'Total_Revenue', 'Order_Count']
    
    # Best Day for Volume (Footfall Proxy)
    peak_volume_day = day_stats['Order_Count'].idxmax()
    # Best Day for High-Value Sales
    peak_value_day = day_stats['Avg_Sale'].idxmax()

    # B. Product Analysis
    product_performance = crm.groupby(product_col)[sales_col].sum().sort_values(ascending=False)
    best_seller = product_performance.index[0]
    top_3 = product_performance.head(3).index.tolist()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("🔥 Best Selling Product", best_seller)
    with col2:
        st.metric("🚶 Highest Footfall Day", f"Every {peak_volume_day}")
    with col3:
        st.metric("💰 High-Value Day", f"Every {peak_value_day}")

    st.info(f"💡 **Strategy:** Most customers visit on **{peak_volume_day}s**, but the highest average invoices are closed on **{peak_value_day}s**. Ensure your most senior sales executives are on the floor during these times.")

    # Charts for visualization
    c1, c2 = st.columns(2)
    with c1:
        st.write("**Top 5 Products by Revenue**")
        st.bar_chart(product_performance.head(5))
    with c2:
        st.write("**Sales Volume (Order Count) by Day**")
        st.line_chart(day_stats['Order_Count'])

# ---------- 5. DYNAMIC BHUBANESWAR FESTIVAL CALENDAR ----------
st.markdown("---")
st.subheader("🗓️ Upcoming Boost Opportunities (Future Only)")

# Full 2026 List
all_festivals = [
    {"Date": "01-Jan-2026", "Festival": "New Year Day", "Type": "Global", "Decoration": "Balloons & LED Lights"},
    {"Date": "14-Jan-2026", "Festival": "Makar Sankranti", "Type": "Major", "Decoration": "Kite Theme & Traditional Alpona"},
    {"Date": "26-Jan-2026", "Festival": "Republic Day", "Type": "National", "Decoration": "Tricolor Drapes"},
    {"Date": "01-Apr-2026", "Festival": "Odisha Day (Utkala Dibasa)", "Type": "Regional Pride", "Decoration": "Pattachitra Hangings"},
    {"Date": "14-Apr-2026", "Festival": "Odia New Year", "Type": "Major Festival", "Decoration": "Marigold Flowers & Jhoti"},
    {"Date": "14-Jun-2026", "Festival": "Raja Parba", "Type": "Regional", "Decoration": "Floral Swings"},
    {"Date": "16-Jul-2026", "Festival": "Ratha Yatra", "Type": "Massive Peak", "Decoration": "Chariot Motifs"},
    {"Date": "20-Oct-2026", "Festival": "Durga Puja / Dussehra", "Type": "Shopping Peak", "Decoration": "Traditional Pandal Theme"},
    {"Date": "08-Nov-2026", "Festival": "Diwali", "Type": "Furniture Peak", "Decoration": "Diyas & Rangoli"},
]

# Convert to DataFrame and Filter
fest_df = pd.DataFrame(all_festivals)
fest_df['Date_DT'] = pd.to_datetime(fest_df['Date'], format='%d-%b-%Y')

# Filter for today or future only
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
upcoming_fest_df = fest_df[fest_df['Date_DT'] >= today].sort_values('Date_DT')

if not upcoming_fest_df.empty:
    st.table(upcoming_fest_df[['Date', 'Festival', 'Type', 'Decoration']])
    
    # Action Point based on the very next festival
    next_event = upcoming_fest_df.iloc[0]
    st.success(f"🚀 **Upcoming Deadline:** {next_event['Festival']} is on {next_event['Date']}. Update showroom decor by **{(next_event['Date_DT'] - timedelta(days=3)).strftime('%d-%b')}**!")
else:
    st.info("No more scheduled festivals for the year. Time to focus on End-of-Season sales!")

# ---------- 6. DYNAMIC STRATEGY TABS ----------
st.markdown("---")
st.subheader("🛠️ Strategy & Decoration Guide")

t1, t2 = st.tabs(["🎨 Showroom Presentation", "💰 Dynamic Growth"])

with t1:
    st.markdown(f"""
    **Current Strategy:**
    * **The {best_seller} Focus:** Since this is your best seller, place it in the 'Golden Triangle' (visible from the entrance).
    * **{peak_volume_day} Preparation:** Showroom deep cleaning must happen the day before.
    * **Visual:** Use {upcoming_fest_df.iloc[0]['Decoration'] if not upcoming_fest_df.empty else 'Clean/Minimalist'} themes.
    """)

with t2:
    st.markdown("""
    * **Bundle Deals:** Pair top-sellers with slow-moving inventory.
    * **Flash Sales:** Run 1-hour flash discounts on low-footfall days.
    * **Referral:** Offer Godrej cleaning kits for every successful referral.
    """)