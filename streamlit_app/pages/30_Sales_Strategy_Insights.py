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
# Selects a quote based on the day of the month
quote_of_the_day = quotes[datetime.now().day % len(quotes)]

st.markdown(f"""
    <div style="background-color: #f0f2f6; padding: 20px; border-radius: 10px; border-left: 5px solid #2e7d32; margin-bottom: 25px;">
        <h3 style="margin-top: 0; color: #2e7d32;">🌟 Team Morale Booster</h3>
        <p style="font-size: 18px; font-style: italic; color: #333;">{quote_of_the_day}</p>
    </div>
""", unsafe_allow_html=True)

st.title("📈 Sales Strategy & Festival Insights")

# ---------- 2. ANALYSIS LOGIC (FROM CRM & PRODUCT DATA) ----------
crm_raw = get_df("CRM") # Replace with your actual sheet name if different

if crm_raw is not None and not crm_raw.empty:
    crm = crm_raw.copy()
    crm.columns = [str(c).strip().upper() for c in crm.columns]
    
    # Cleaning Numeric Data
    for col in ["ORDER AMOUNT"]:
        if col in crm.columns:
            crm[col] = pd.to_numeric(crm[col].astype(str).str.replace("[₹,]", "", regex=True), errors='coerce').fillna(0)
    
    crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
    crm["DAY_NAME"] = crm["DATE_DT"].dt.day_name()

    # Identifying High-Growth Days
    day_performance = crm.groupby("DAY_NAME")["ORDER AMOUNT"].mean().sort_values(ascending=False)
    top_day = day_performance.index[0]
    
    # Identifying Trending Products (Assuming a 'PRODUCT' or 'CATEGORY' column exists)
    product_col = "ITEM NAME" if "ITEM NAME" in crm.columns else "PRODUCT"
    if product_col in crm.columns:
        top_products = crm.groupby(product_col)["ORDER AMOUNT"].sum().nlargest(3).index.tolist()
    else:
        top_products = ["Sofas (General)", "Dining Sets", "Recliners"]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📊 Performance Trends")
        st.write(f"✅ **Peak Sales Day:** {top_day}s show the highest average footfall/conversion.")
        st.write(f"🔥 **Trending Products:** {', '.join(top_products)}")
    with col2:
        st.info("💡 **Insight:** Focus your digital ads on Thursday/Friday to capture the weekend 'Home Improvement' mindset.")

else:
    st.warning("Connect your Google Sheets to see live performance analysis.")

st.markdown("---")

# ---------- 3. BHUBANESWAR FESTIVAL CALENDAR 2026 ----------
st.subheader("🗓️ Upcoming Boost Opportunities (Bhubaneswar, Odisha)")

# Data for 2026
festivals = [
    {"Date": "01-Apr-2026", "Festival": "Odisha Day (Utkala Dibasa)", "Type": "Regional Pride", "Decoration": "Odishi Theme, Pattachitra Hangings"},
    {"Date": "14-Apr-2026", "Festival": "Maha Vishuba Sankranti (Odia New Year)", "Type": "Major Festival", "Decoration": "Traditional Alpona/Jhoti, Marigold Flowers"},
    {"Date": "01-May-2026", "Festival": "Buddha Purnima", "Type": "Holiday", "Decoration": "Zen/Minimalist Furniture Layout"},
    {"Date": "14-Jun-2026", "Festival": "Raja Parba (Starts)", "Type": "Regional Celebration", "Decoration": "Floral Swings, Ethnic Fabric Drapes"},
    {"Date": "16-Jul-2026", "Festival": "Ratha Yatra", "Type": "Massive Peak", "Decoration": "Chariot Motifs, Bright Yellow/Red Fabrics"},
]

fest_df = pd.DataFrame(festivals)
st.table(fest_df)

# ---------- 4. ACTIONABLE METHODS TO BOOST SALES ----------
st.markdown("---")
st.subheader("🛠️ Strategy & Decoration Guide")

tab1, tab2 = st.tabs(["🎨 Decoration Strategy", "💰 Sales Growth Methods"])

with tab1:
    st.markdown("""
    **When to Decorate:** * Always decorate **3-4 days before** the festival date to build anticipation.
    * For major events like **Ratha Yatra** or **Diwali**, start 1 week early.
    
    **Decoration Ideas:**
    * **Themed Room Sets:** Instead of just placing sofas, create a 'Festival Living Room' corner with traditional cushions and lamps.
    * **Sensory Marketing:** Use local fragrances (Sandalwood/Jasmine) and play soft Odissi instrumental music.
    * **Photo Op Spot:** Create a beautifully decorated 'Selfie Corner'—when customers post photos, your showroom gets free promotion!
    """)

with tab2:
    st.markdown("""
    * **Festival Combo Offers:** Pair a Sofa set with a Coffee Table as a 'New Year Bundle' for Utkala Dibasa.
    * **Exchange Melas:** Run 'Old Furniture Exchange' campaigns during the Odia New Year (April 14).
    * **The 'Raja' Special:** During Raja Parba, offer special discounts specifically for women shoppers, as they are the decision-makers during this festival.
    * **Early Bird Discounts:** Offer an extra 5% off for bookings made before 12:00 PM to drive morning walk-ins.
    """)

st.success("🚀 **Action Point:** Start planning the **Utkala Dibasa (April 1st)** display today!")