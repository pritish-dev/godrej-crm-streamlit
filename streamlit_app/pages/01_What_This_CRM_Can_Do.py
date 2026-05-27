"""
01_What_This_CRM_Can_Do.py
Interactive CRM Feature Discovery & Navigation Guide
"""

import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="What This CRM Can Do",
    page_icon="🗺️",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# STYLES
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Global ─────────────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

.main .block-container { padding-top: 1rem; padding-bottom: 3rem; }
html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }

/* ── Hero Banner ─────────────────────────────────────────────────────────── */
.crm-hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 40%, #0f3460 70%, #533483 100%);
    border-radius: 20px;
    padding: 3rem 3.5rem;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
}
.crm-hero::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 250px; height: 250px;
    background: rgba(255,255,255,0.04);
    border-radius: 50%;
}
.crm-hero::after {
    content: '';
    position: absolute;
    bottom: -80px; left: 20%;
    width: 350px; height: 350px;
    background: rgba(255,255,255,0.03);
    border-radius: 50%;
}
.hero-title {
    font-size: 2.8rem; font-weight: 800; color: #ffffff;
    line-height: 1.2; margin-bottom: 0.75rem;
}
.hero-subtitle {
    font-size: 1.15rem; color: rgba(255,255,255,0.78);
    font-weight: 400; line-height: 1.6; max-width: 640px;
}
.hero-badge {
    display: inline-block;
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.25);
    color: #fff; font-size: 0.78rem; font-weight: 600;
    padding: 5px 14px; border-radius: 20px;
    letter-spacing: 0.5px; margin-bottom: 1.2rem;
}
.hero-stats {
    display: flex; gap: 2.5rem; margin-top: 2rem; flex-wrap: wrap;
}
.hero-stat { text-align: center; }
.hero-stat-number {
    font-size: 2rem; font-weight: 800; color: #fff; display: block;
}
.hero-stat-label {
    font-size: 0.78rem; color: rgba(255,255,255,0.6);
    text-transform: uppercase; letter-spacing: 0.8px;
}

/* ── Search Bar ──────────────────────────────────────────────────────────── */
.search-wrapper {
    background: #f8faff;
    border: 2px solid #e2e8f7;
    border-radius: 14px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.5rem;
}
.search-label {
    font-size: 0.82rem; font-weight: 600; color: #64748b;
    text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 0.5rem;
}

/* ── Category Pills ──────────────────────────────────────────────────────── */
.cat-row { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 1.8rem; }
.cat-pill {
    padding: 6px 18px; border-radius: 20px; font-size: 0.82rem; font-weight: 600;
    cursor: pointer; border: 2px solid transparent; transition: all 0.2s;
}

/* ── Section Header ──────────────────────────────────────────────────────── */
.section-header {
    display: flex; align-items: center; gap: 0.8rem;
    padding: 0.9rem 1.4rem;
    border-radius: 12px 12px 0 0;
    margin-bottom: 0;
    margin-top: 1.5rem;
}
.section-icon { font-size: 1.6rem; }
.section-title { font-size: 1.15rem; font-weight: 700; color: #fff; }
.section-desc { font-size: 0.82rem; color: rgba(255,255,255,0.8); margin-top: 2px; }

/* ── Module Card ─────────────────────────────────────────────────────────── */
.module-card {
    background: #fff;
    border-radius: 0 0 14px 14px;
    border: 1px solid #e8edf5;
    border-top: none;
    padding: 1.4rem 1.6rem 1.2rem;
    margin-bottom: 0.3rem;
}

/* ── Feature Card ────────────────────────────────────────────────────────── */
.feature-grid { display: flex; flex-wrap: wrap; gap: 0.85rem; margin-top: 0.9rem; }
.feature-card {
    flex: 1 1 260px;
    background: linear-gradient(145deg, #fafbff 0%, #f0f4ff 100%);
    border: 1.5px solid #e2e8f7;
    border-radius: 12px;
    padding: 1rem 1.1rem;
    transition: all 0.2s ease;
    min-width: 240px;
}
.feature-card:hover {
    border-color: #6366f1;
    box-shadow: 0 4px 16px rgba(99,102,241,0.12);
    transform: translateY(-2px);
}
.feature-icon { font-size: 1.4rem; margin-bottom: 0.4rem; }
.feature-name {
    font-size: 0.88rem; font-weight: 700; color: #1e293b; margin-bottom: 0.3rem;
}
.feature-desc {
    font-size: 0.78rem; color: #64748b; line-height: 1.5;
}
.feature-benefit {
    display: inline-block;
    background: #eff6ff; color: #3b82f6;
    font-size: 0.7rem; font-weight: 600;
    padding: 2px 8px; border-radius: 6px;
    margin-top: 0.5rem;
}

/* ── Highlight Cards ─────────────────────────────────────────────────────── */
.highlight-row { display: flex; gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap; }
.highlight-card {
    flex: 1 1 200px;
    border-radius: 14px;
    padding: 1.2rem 1.4rem;
    min-width: 180px;
    position: relative; overflow: hidden;
}
.highlight-card::after {
    content: '';
    position: absolute; top: -20px; right: -20px;
    width: 80px; height: 80px;
    background: rgba(255,255,255,0.12); border-radius: 50%;
}
.highlight-label {
    font-size: 0.72rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.8px;
    opacity: 0.85; margin-bottom: 0.3rem;
}
.highlight-value {
    font-size: 1.4rem; font-weight: 800;
    color: #fff;
}
.highlight-sub {
    font-size: 0.76rem; opacity: 0.8; margin-top: 0.15rem;
}

/* ── Navigation Button ───────────────────────────────────────────────────── */
.nav-tip {
    background: linear-gradient(135deg, #ecfdf5, #d1fae5);
    border: 1.5px solid #6ee7b7;
    border-radius: 12px;
    padding: 1rem 1.4rem;
    margin-top: 0.8rem;
    font-size: 0.82rem; color: #065f46;
    font-weight: 500;
}

/* ── Tag Badges ──────────────────────────────────────────────────────────── */
.tag {
    display: inline-block;
    font-size: 0.68rem; font-weight: 700;
    padding: 2px 9px; border-radius: 20px;
    margin-right: 4px; margin-bottom: 4px;
    letter-spacing: 0.3px;
}
.tag-daily { background: #fef3c7; color: #92400e; }
.tag-manager { background: #ede9fe; color: #5b21b6; }
.tag-sales { background: #dbeafe; color: #1e40af; }
.tag-auto { background: #dcfce7; color: #166534; }
.tag-new { background: #fee2e2; color: #991b1b; }

/* ── Divider ─────────────────────────────────────────────────────────────── */
.fancy-divider {
    height: 3px;
    background: linear-gradient(90deg, #6366f1, #8b5cf6, #ec4899, transparent);
    border-radius: 2px; margin: 2.5rem 0;
}

/* ── Quick Ref Table ─────────────────────────────────────────────────────── */
.ref-table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
.ref-table th {
    background: #1e293b; color: #fff;
    padding: 10px 14px; text-align: left;
    font-weight: 600; font-size: 0.78rem;
    text-transform: uppercase; letter-spacing: 0.5px;
}
.ref-table tr:nth-child(even) td { background: #f8faff; }
.ref-table td { padding: 9px 14px; border-bottom: 1px solid #e8edf5; color: #334155; }
.ref-table tr:hover td { background: #eff6ff; }

/* ── Footer ──────────────────────────────────────────────────────────────── */
.guide-footer {
    background: linear-gradient(135deg, #1e293b, #0f172a);
    border-radius: 14px;
    padding: 1.8rem 2rem;
    text-align: center; margin-top: 2.5rem;
    color: rgba(255,255,255,0.7); font-size: 0.85rem;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# DATA — MODULE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
MODULES = [
    # ── SALES DASHBOARD ──────────────────────────────────────────────────────
    {
        "id": "b2c_dashboard",
        "emoji": "🛋️",
        "title": "4sInteriors B2C Sales Dashboard",
        "route": "pages/b2c_dashboard.py",
        "category": "Sales",
        "section": "Main",
        "gradient": "linear-gradient(135deg, #1a1a2e, #16213e)",
        "tags": ["daily", "sales"],
        "tagline": "Your complete view of every sale, delivery, and payment — all in one place.",
        "what_it_does": "This is your main dashboard. It shows every order taken at the showroom — from the moment a customer places an order to delivery and final payment. You can see exactly what is pending, what is paid, and what needs follow-up.",
        "features": [
            {
                "icon": "📋",
                "name": "Live Order Table",
                "desc": "See all current orders with customer name, product, quantity, value, and sales executive — updated in real time.",
                "benefit": "Never miss an order",
            },
            {
                "icon": "🚚",
                "name": "Pending Delivery Tracker",
                "desc": "Quickly see which customer orders are still waiting for delivery. Green highlights mean the item is ready to deliver now.",
                "benefit": "Faster delivery coordination",
            },
            {
                "icon": "💰",
                "name": "Payment Due Summary",
                "desc": "See how much payment is pending from each customer. One glance tells you who still owes money.",
                "benefit": "Better cash flow tracking",
            },
            {
                "icon": "📊",
                "name": "Key Metrics Cards",
                "desc": "Shows total orders count, total order value in ₹, total pending dues, and total delivered orders at the top of the page.",
                "benefit": "Instant business snapshot",
            },
            {
                "icon": "🔔",
                "name": "Smart Alerts Ticker",
                "desc": "A scrolling alert banner at the top shows important reminders — pending deliveries, overdue payments, or follow-up tasks that need attention today.",
                "benefit": "Stay on top of priorities",
            },
            {
                "icon": "📧",
                "name": "Delivery Readiness Updates",
                "desc": "Automatically checks which items are committed and ready in the warehouse, so you know when to schedule customer delivery.",
                "benefit": "No more guessing delivery dates",
            },
        ],
    },
    # ── DAILY B2C SALES ───────────────────────────────────────────────────────
    {
        "id": "daily_b2c_sales",
        "emoji": "📅",
        "title": "Daily B2C Sales",
        "route": "pages/daily_b2c_sales.py",
        "category": "Sales",
        "section": "Main",
        "gradient": "linear-gradient(135deg, #134e5e, #71b280)",
        "tags": ["daily", "sales"],
        "tagline": "Track each sales executive's daily performance and stay motivated.",
        "what_it_does": "This page breaks down sales by each team member — showing who sold what, how much, and how they compare against their monthly target. It's the daily scoreboard for the sales team.",
        "features": [
            {
                "icon": "🏆",
                "name": "Sales Executive Leaderboard",
                "desc": "Shows each team member's total sales value for the current financial year. Easy to see who is leading.",
                "benefit": "Healthy team competition",
            },
            {
                "icon": "🎯",
                "name": "Target vs Achievement",
                "desc": "Compares each executive's actual sales against their monthly target. Shows exactly how far they are from the goal.",
                "benefit": "Clear progress visibility",
            },
            {
                "icon": "⭐",
                "name": "Google Reviews Tracker",
                "desc": "Shows how many 5-star Google reviews each executive has collected. Reviews are tied to their customer service.",
                "benefit": "Reward great service",
            },
            {
                "icon": "💬",
                "name": "Daily Motivational Quotes",
                "desc": "A fresh motivational quote appears every day for the sales team to stay energized and focused.",
                "benefit": "Team morale boost",
            },
        ],
    },
    # ── CUSTOMER INTELLIGENCE ─────────────────────────────────────────────────
    {
        "id": "customer_intelligence",
        "emoji": "🧠",
        "title": "Customer Intelligence Engine",
        "route": "pages/17_Customer_Intelligence_Engine.py",
        "category": "Sales",
        "section": "Main",
        "gradient": "linear-gradient(135deg, #7c4dff, #1565c0)",
        "tags": ["sales", "manager"],
        "tagline": "Know your best customers, spot at-risk ones, and never lose a loyal buyer.",
        "what_it_does": "This powerful page categorizes every customer based on their buying history. You can instantly see who are your best spenders, who buys repeatedly, who hasn't visited in a long time, and who is a brand new customer.",
        "features": [
            {
                "icon": "💎",
                "name": "High Value Customers",
                "desc": "Automatically identifies customers who have spent ₹5 lakh or more. These are your VIP customers who deserve extra attention.",
                "benefit": "Protect your biggest revenue source",
            },
            {
                "icon": "🔁",
                "name": "Loyal Customers",
                "desc": "Finds customers who have bought from you more than once. These repeat buyers are your most reliable sales.",
                "benefit": "Identify brand advocates",
            },
            {
                "icon": "⚠️",
                "name": "At-Risk Customers",
                "desc": "Spots customers who haven't visited in 90 to 180 days. These people need a call or message before they forget you.",
                "benefit": "Win back customers before it's too late",
            },
            {
                "icon": "💤",
                "name": "Dormant Customers",
                "desc": "Shows customers who have not purchased in over 6 months. A special offer or personal call could re-activate them.",
                "benefit": "Recover lost revenue",
            },
            {
                "icon": "✨",
                "name": "New Customers",
                "desc": "Highlights customers who made their first purchase within the last 60 days. These need a warm follow-up to build loyalty.",
                "benefit": "Convert new buyers into repeat customers",
            },
            {
                "icon": "📱",
                "name": "WhatsApp Direct Messaging",
                "desc": "Click a button next to any customer and open a pre-filled WhatsApp message to them instantly.",
                "benefit": "Faster, personal communication",
            },
            {
                "icon": "🔍",
                "name": "Customer Search",
                "desc": "Search for any customer by name or phone number to see their complete purchase history and category.",
                "benefit": "Instant customer lookup",
            },
        ],
    },
    # ── PRODUCT SALES ANALYSIS ────────────────────────────────────────────────
    {
        "id": "product_sales",
        "emoji": "📊",
        "title": "Product Sales Analysis",
        "route": "pages/20_Product_Sales_Analysis.py",
        "category": "Reporting",
        "section": "Main",
        "gradient": "linear-gradient(135deg, #f093fb, #f5576c)",
        "tags": ["manager", "sales"],
        "tagline": "See which products are selling most and which categories drive revenue.",
        "what_it_does": "This page shows a detailed breakdown of all product sales by category and sub-category. You can see whether furniture, storage, or mattresses are selling more, and which specific products are most popular.",
        "features": [
            {
                "icon": "🪑",
                "name": "Category Sales Breakdown",
                "desc": "Shows sales split between Home Furniture, Home Storage, and Other products — so you know where most revenue comes from.",
                "benefit": "Focus on what sells",
            },
            {
                "icon": "🛏️",
                "name": "Sub-Category Analysis",
                "desc": "Drills down to specific product types like Beds, Sofas, Wardrobes, Mattresses, Dining sets, and more.",
                "benefit": "Stock the right products",
            },
            {
                "icon": "📈",
                "name": "Sales Trends Over Time",
                "desc": "Shows how product sales have changed month over month. Identify seasonal patterns easily.",
                "benefit": "Plan inventory smartly",
            },
            {
                "icon": "🔢",
                "name": "Kreation X3 Unit Tracking",
                "desc": "Specially tracks modular furniture units with accurate counting logic for complex products.",
                "benefit": "Accurate modular furniture reporting",
            },
        ],
    },
    # ── LEADS ─────────────────────────────────────────────────────────────────
    {
        "id": "leads",
        "emoji": "🎯",
        "title": "Leads",
        "route": "pages/70_Leads.py",
        "category": "Sales",
        "section": "Main",
        "gradient": "linear-gradient(135deg, #11998e, #38ef7d)",
        "tags": ["daily", "sales"],
        "tagline": "Track every potential customer from first contact to final sale.",
        "what_it_does": "The Leads page is where you manage all potential customers who have shown interest but haven't purchased yet. Track leads from Instagram, Facebook, phone calls, walk-ins, and more — all in one organized list.",
        "features": [
            {
                "icon": "➕",
                "name": "Add New Lead",
                "desc": "Manually add a new potential customer with their name, phone, email, source of enquiry, and any notes.",
                "benefit": "Never lose a prospect",
            },
            {
                "icon": "📧",
                "name": "Auto-Import from Email",
                "desc": "Leads coming from OneCRM via email are automatically imported and added to the list — no manual entry needed.",
                "benefit": "Zero data entry for online leads",
            },
            {
                "icon": "🔄",
                "name": "Lead Status Tracking",
                "desc": "Mark each lead as: New → Contacted → Qualified → Proposal Sent → Converted or Lost. Color-coded for easy scanning.",
                "benefit": "Know where every lead stands",
            },
            {
                "icon": "👤",
                "name": "Assign to Sales Executive",
                "desc": "Assign any lead to a specific team member so there is clear ownership and accountability.",
                "benefit": "No leads fall through the cracks",
            },
            {
                "icon": "📅",
                "name": "Follow-Up Date Reminder",
                "desc": "Set a follow-up date for each lead. You'll know exactly when to call or message each prospect.",
                "benefit": "Never miss a follow-up",
            },
            {
                "icon": "📍",
                "name": "Lead Source Tracking",
                "desc": "Records where each lead came from — Instagram, Facebook, Website, Phone, Walk-in, Referral, Event, or LinkedIn.",
                "benefit": "Know which channels bring best leads",
            },
            {
                "icon": "💰",
                "name": "Deal Value Tracking",
                "desc": "Note the estimated deal value for each lead so you can prioritize high-value prospects.",
                "benefit": "Focus on the biggest opportunities",
            },
        ],
    },
    # ── SALES TEAM TASKS ──────────────────────────────────────────────────────
    {
        "id": "sales_tasks",
        "emoji": "✅",
        "title": "Sales Team Tasks",
        "route": "pages/90_Sales_Team_Tasks.py",
        "category": "Productivity",
        "section": "Main",
        "gradient": "linear-gradient(135deg, #4facfe, #00f2fe)",
        "tags": ["daily", "manager"],
        "tagline": "Keep the entire team on track with daily, weekly, and monthly tasks.",
        "what_it_does": "This page manages all tasks assigned to sales team members — daily checklists, weekly reviews, monthly reports, and special tasks. Managers can see what is done, pending, or missed at a glance.",
        "features": [
            {
                "icon": "📋",
                "name": "Daily Task Checklist",
                "desc": "Each team member sees their tasks for today — from floor duties to customer follow-ups. Mark them done when complete.",
                "benefit": "Structured daily routine",
            },
            {
                "icon": "📆",
                "name": "Weekly & Monthly Tasks",
                "desc": "Tracks recurring tasks that happen every week or month — like updating reports, stock checks, or review collections.",
                "benefit": "Never miss periodic tasks",
            },
            {
                "icon": "🚨",
                "name": "Missed Task Alerts",
                "desc": "Daily tasks not completed by end of day are automatically marked as 'Missed' so managers can follow up.",
                "benefit": "Accountability for the whole team",
            },
            {
                "icon": "📊",
                "name": "Task Completion Dashboard",
                "desc": "Managers see a summary of how many tasks were done vs pending vs missed across the entire team.",
                "benefit": "Team performance at a glance",
            },
            {
                "icon": "📤",
                "name": "Email Notifications",
                "desc": "Team members get email reminders for upcoming tasks, and managers get daily completion reports.",
                "benefit": "Everyone stays informed",
            },
            {
                "icon": "🏖️",
                "name": "Week-off Integration",
                "desc": "If an employee is on their weekly off, tasks are automatically skipped for that day — no manual adjustments needed.",
                "benefit": "Smart task scheduling",
            },
        ],
    },
    # ── HAPPY CALLING ─────────────────────────────────────────────────────────
    {
        "id": "happy_calling",
        "emoji": "📞",
        "title": "Happy Calling",
        "route": "pages/95_Happy_Calling.py",
        "category": "Sales",
        "section": "Main",
        "gradient": "linear-gradient(135deg, #f7971e, #ffd200)",
        "tags": ["daily", "sales"],
        "tagline": "Call delivered customers to ensure satisfaction and collect Google reviews.",
        "what_it_does": "After a customer receives their furniture, this page helps you call them to check if they are happy. It also makes it easy to ask for a Google review — which builds your showroom's online reputation.",
        "features": [
            {
                "icon": "📱",
                "name": "Delivered Customer List",
                "desc": "Shows all customers whose furniture has been delivered, making it easy to know who to call next.",
                "benefit": "Systematic post-sale follow-up",
            },
            {
                "icon": "💬",
                "name": "WhatsApp Message Generator",
                "desc": "One-click button generates a personalized WhatsApp message with the customer's name, product, Google review link, and your WhatsApp channel.",
                "benefit": "Professional messages in seconds",
            },
            {
                "icon": "📅",
                "name": "Happy Call Date Logging",
                "desc": "Record the date when you called the customer. Edit directly in the table — no extra forms needed.",
                "benefit": "Complete post-sale history",
            },
            {
                "icon": "📊",
                "name": "Calling Progress Metrics",
                "desc": "Shows total delivered customers, how many have been called, and how many are still awaiting a call.",
                "benefit": "Track team's calling progress",
            },
            {
                "icon": "⏰",
                "name": "Daily Call Reminders",
                "desc": "Automated email reminder at 7 AM every day reminding the team who needs a happy call today.",
                "benefit": "Never forget post-delivery calls",
            },
        ],
    },
    # ── SALES MANAGER DASHBOARD ───────────────────────────────────────────────
    {
        "id": "sales_manager",
        "emoji": "🏆",
        "title": "Sales Manager Dashboard",
        "route": "pages/100_Sales_Manager_Dashboard.py",
        "category": "HR & Incentives",
        "section": "Main",
        "gradient": "linear-gradient(135deg, #f7971e, #f953c6)",
        "tags": ["manager"],
        "tagline": "Calculate incentives, track quarterly targets, and reward top performers.",
        "what_it_does": "This is the manager's private dashboard for calculating and reviewing sales incentives. It shows exactly how much incentive each team member has earned based on their sales, reviews, attendance, and special achievements.",
        "features": [
            {
                "icon": "💵",
                "name": "Incentive Calculator",
                "desc": "Automatically calculates each executive's total incentive — based on sales value, B2B orders, review count, and attendance.",
                "benefit": "Zero manual calculation errors",
            },
            {
                "icon": "📈",
                "name": "Quarterly Target Tracker",
                "desc": "Shows quarterly sales targets vs actual achievement with tier breakdowns (0.5% / 1% / 1.25% payouts).",
                "benefit": "Transparent performance milestones",
            },
            {
                "icon": "⭐",
                "name": "Star Ledger System",
                "desc": "Tracks 'stars' earned through activities like upselling, getting reviews, bringing new leads, and NPI (new product introductions).",
                "benefit": "Reward all-round performance",
            },
            {
                "icon": "🔒",
                "name": "Locker Incentive Tracking",
                "desc": "Special incentive for selling lockers — ₹100/unit for premium lockers and ₹50/unit for standard ones.",
                "benefit": "Drive accessory sales",
            },
            {
                "icon": "🔐",
                "name": "Manager-Only Access",
                "desc": "This page is restricted to Managers, Admins, Owners, and Proprietors only. Regular staff cannot view this data.",
                "benefit": "Secure and confidential payroll data",
            },
            {
                "icon": "📋",
                "name": "Incentive Audit Log",
                "desc": "Every incentive calculation is automatically logged with timestamps so there is a clear record of all payouts.",
                "benefit": "Complete accountability trail",
            },
        ],
    },
    # ── SALES REPORTS ─────────────────────────────────────────────────────────
    {
        "id": "sales_reports",
        "emoji": "💡",
        "title": "Sales Reports and Strategy",
        "route": "pages/30_Sales_Reports_and_Strategy.py",
        "category": "Reporting",
        "section": "Sales Handbook",
        "gradient": "linear-gradient(135deg, #667eea, #764ba2)",
        "tags": ["manager", "sales"],
        "tagline": "Deep analysis of revenue trends, product mix, and team performance.",
        "what_it_does": "The most comprehensive reporting page in the CRM. It gives managers a complete strategic view of sales performance — from monthly trends to the best selling products to festival-based sales strategies.",
        "features": [
            {
                "icon": "📊",
                "name": "Headline KPIs",
                "desc": "Shows lifetime revenue, current month revenue, and a projected run-rate for the month — all at a glance.",
                "benefit": "Instant business health check",
            },
            {
                "icon": "📅",
                "name": "Monthly Target Tracker",
                "desc": "Visual progress bar showing how close the showroom is to hitting the monthly sales target.",
                "benefit": "Real-time goal tracking",
            },
            {
                "icon": "📈",
                "name": "Revenue Trend Charts",
                "desc": "Charts showing sales by month, day of week, and hour of day — revealing the busiest selling times.",
                "benefit": "Schedule staff during peak hours",
            },
            {
                "icon": "🏅",
                "name": "Sales Person Leaderboard",
                "desc": "Ranked list of all executives by sales value, with their Google review count included.",
                "benefit": "Fair, data-driven recognition",
            },
            {
                "icon": "🛋️",
                "name": "Product Mix Analysis",
                "desc": "Shows which product categories contribute most to revenue — furniture, storage, mattresses.",
                "benefit": "Stock decisions based on real data",
            },
            {
                "icon": "🏮",
                "name": "Festival Sales Strategy",
                "desc": "Shows upcoming Odia festivals with specific sales-event recommendations — décor themes, floor activations, product promotions.",
                "benefit": "Never miss a festive sales opportunity",
            },
            {
                "icon": "👥",
                "name": "Customer Cohort Summary",
                "desc": "Quick summary of how many High Value, Loyal, At-Risk, and New customers you have currently.",
                "benefit": "Strategic customer relationship overview",
            },
        ],
    },
    # ── MIS UPDATE ────────────────────────────────────────────────────────────
    {
        "id": "mis_update",
        "emoji": "📦",
        "title": "MIS Update",
        "route": "pages/50_MIS_Update.py",
        "category": "Operations",
        "section": "Sales Handbook",
        "gradient": "linear-gradient(135deg, #2c3e50, #4ca1af)",
        "tags": ["daily", "manager"],
        "tagline": "Live stock and order commitment data directly from Godrej warehouse systems.",
        "what_it_does": "MIS (Management Information System) shows the latest order and stock status from Godrej's internal system. It tells you which orders have been committed by Godrej and which products are confirmed for dispatch.",
        "features": [
            {
                "icon": "📋",
                "name": "Live MIS Data Table",
                "desc": "Shows all current orders with their Godrej system status — including order quantities, committed quantities, and dates.",
                "benefit": "Real-time order visibility",
            },
            {
                "icon": "🟢",
                "name": "Delivery-Ready Highlighting",
                "desc": "Rows highlighted in green = items that are committed by Godrej AND belong to your pending delivery customers. These are ready to deliver!",
                "benefit": "Instantly spot what can be delivered today",
            },
            {
                "icon": "🔄",
                "name": "Auto-Refresh at 11 AM",
                "desc": "MIS data is automatically pulled from Godrej's email system every morning at 11 AM without any manual work.",
                "benefit": "Always up-to-date without effort",
            },
            {
                "icon": "🔃",
                "name": "Manual Force Refresh",
                "desc": "Need the latest data right now? Click 'Force Fetch Now' to immediately pull the newest MIS update.",
                "benefit": "Get data when you need it",
            },
            {
                "icon": "📊",
                "name": "Summary Metrics",
                "desc": "Shows total orders, total line items, total order quantity, and how many items are ready for delivery.",
                "benefit": "Quick operations summary",
            },
        ],
    },
    # ── MONTHEND FORECAST ─────────────────────────────────────────────────────
    {
        "id": "monthend_forecast",
        "emoji": "📅",
        "title": "Monthend Sales Forecast",
        "route": "pages/55_Monthend_Sales_Forecast.py",
        "category": "Reporting",
        "section": "Sales Handbook",
        "gradient": "linear-gradient(135deg, #0f2027, #2c5364)",
        "tags": ["manager"],
        "tagline": "Predict month-end sales and plan final pushes to hit targets.",
        "what_it_does": "During the last 5 days of the month, this page shows which orders are committed and likely to be billed. It calculates the forecasted sales value so managers know if the team will hit the monthly target.",
        "features": [
            {
                "icon": "🎯",
                "name": "Month-End Forecast Value",
                "desc": "Calculates the total expected sales value from all confirmed and committed orders in the closing period.",
                "benefit": "Know your target gap in advance",
            },
            {
                "icon": "✅",
                "name": "Committed Order Tracking",
                "desc": "Shows orders that are both MIS-committed (Godrej system) and manually confirmed by managers.",
                "benefit": "Accurate forecast, not guesswork",
            },
            {
                "icon": "🏭",
                "name": "34s Stock Cross-Check",
                "desc": "Automatically checks whether uncommitted items are physically available in your store stock.",
                "benefit": "Avoid promises you can't keep",
            },
            {
                "icon": "💾",
                "name": "Forecast Persistence",
                "desc": "Each month's forecast is saved to a dedicated Google Sheet for future reference and accountability.",
                "benefit": "Compare forecast vs actual month-end",
            },
        ],
    },
    # ── STOCK ─────────────────────────────────────────────────────────────────
    {
        "id": "stock",
        "emoji": "🏭",
        "title": "Stock",
        "route": "pages/60_Stock.py",
        "category": "Operations",
        "section": "Sales Handbook",
        "gradient": "linear-gradient(135deg, #373b44, #4286f4)",
        "tags": ["daily", "manager"],
        "tagline": "Check live stock levels across all product categories at a glance.",
        "what_it_does": "The Stock page shows the current inventory levels for all products in the system. You can instantly see how many units of each product are available, helping you avoid over-promising customers.",
        "features": [
            {
                "icon": "📦",
                "name": "Live Stock Levels",
                "desc": "Shows current stock quantity for every product SKU in the system — updated daily from Godrej's system.",
                "benefit": "Accurate inventory at all times",
            },
            {
                "icon": "🔴",
                "name": "Zero Stock Alerts",
                "desc": "Products with zero stock are highlighted so you can immediately see what needs to be restocked.",
                "benefit": "Never accidentally sell out-of-stock items",
            },
            {
                "icon": "🔍",
                "name": "Search & Filter",
                "desc": "Search for any product by name or category to find stock levels instantly.",
                "benefit": "Fast product lookup for customers",
            },
            {
                "icon": "🔄",
                "name": "Daily Auto-Update",
                "desc": "Stock data is automatically refreshed every day at 11 AM from Godrej's email system.",
                "benefit": "Always current without manual work",
            },
            {
                "icon": "📊",
                "name": "Stock Summary Metrics",
                "desc": "Shows total SKUs tracked, total units in stock, number of categories, and count of zero-stock items.",
                "benefit": "Overall inventory health in seconds",
            },
        ],
    },
    # ── 34S STOCK ─────────────────────────────────────────────────────────────
    {
        "id": "34s_stock",
        "emoji": "📦",
        "title": "34S Physical Stock Register",
        "route": "pages/62_34s_Stock.py",
        "category": "Operations",
        "section": "Sales Handbook",
        "gradient": "linear-gradient(135deg, #093028, #237a57)",
        "tags": ["daily"],
        "tagline": "Physical stock register for your 34S store — daily inward, outward, and closing stock.",
        "what_it_does": "This is the daily physical stock register for the 34S store location. It records stock received (In Ward), stock dispatched (Out Ward), and the closing stock for each day — just like a manual stock register, but digital.",
        "features": [
            {
                "icon": "📅",
                "name": "Daily Stock Columns",
                "desc": "Each day's inward, outward, opening, and closing stock is recorded separately — easy to trace any day's movement.",
                "benefit": "Complete daily stock trail",
            },
            {
                "icon": "🟥",
                "name": "Zero Stock Highlighting",
                "desc": "Products with zero closing stock are highlighted in red — immediate visual warning.",
                "benefit": "Spot gaps before customers ask",
            },
            {
                "icon": "📤",
                "name": "Setup Monthly Sheet",
                "desc": "One-click setup creates the current month's stock register sheet with all date columns pre-filled.",
                "benefit": "Zero manual spreadsheet setup",
            },
            {
                "icon": "🔄",
                "name": "Auto-Update from Emails",
                "desc": "Daily stock reports received via email are automatically parsed and filled into the register.",
                "benefit": "Fully automated record keeping",
            },
            {
                "icon": "📧",
                "name": "Email Monthly Report",
                "desc": "Send the complete monthly stock register as an Excel file to management with one click.",
                "benefit": "Easy reporting to HO",
            },
            {
                "icon": "⬇️",
                "name": "CSV Download",
                "desc": "Download the current month's stock register as a CSV file for offline use or sharing.",
                "benefit": "Portable data when needed",
            },
        ],
    },
    # ── PRICE LIST ────────────────────────────────────────────────────────────
    {
        "id": "price_list",
        "emoji": "💰",
        "title": "Price List",
        "route": "pages/65_Price_List.py",
        "category": "Operations",
        "section": "Sales Handbook",
        "gradient": "linear-gradient(135deg, #f7971e, #ffd200)",
        "tags": ["daily", "sales"],
        "tagline": "Always have the latest Godrej product prices at your fingertips.",
        "what_it_does": "The Price List page shows the current selling prices for all Godrej furniture, storage, and mattress products — including category, item code, CPL (cost price), GST, and final selling price. No more paper price lists!",
        "features": [
            {
                "icon": "🪑",
                "name": "Furniture & Storage Prices",
                "desc": "Browse all furniture and storage product prices organized by category with item codes and GST details.",
                "benefit": "Instant price answers for customers",
            },
            {
                "icon": "🛏️",
                "name": "Mattress Prices",
                "desc": "Separate tab with mattress prices including thickness in inches and centimeters for easy comparison.",
                "benefit": "Avoid wrong pricing mistakes",
            },
            {
                "icon": "🔍",
                "name": "Search Products",
                "desc": "Type any product name or code to find its price instantly without scrolling.",
                "benefit": "Faster customer queries",
            },
            {
                "icon": "🔄",
                "name": "Auto-Updated Prices",
                "desc": "Prices are updated from official Godrej price list PDFs. No manual updates by staff needed.",
                "benefit": "Always using current official prices",
            },
        ],
    },
    # ── PRODUCTS CATALOG ──────────────────────────────────────────────────────
    {
        "id": "products_catalog",
        "emoji": "🪑",
        "title": "Product Catalogue",
        "route": "pages/40_Products_catalog.py",
        "category": "Sales",
        "section": "Sales Handbook",
        "gradient": "linear-gradient(135deg, #8360c3, #2ebf91)",
        "tags": ["sales"],
        "tagline": "Browse the complete Godrej Interio product range with photos and specs.",
        "what_it_does": "This is your digital product catalogue. Browse all available Godrej Interio products with multiple photos, features, dimensions, and colour options — exactly like a digital brochure.",
        "features": [
            {
                "icon": "📸",
                "name": "Product Photo Gallery",
                "desc": "Each product has multiple photos you can scroll through — left and right navigation buttons for each product.",
                "benefit": "Show customers accurate visuals",
            },
            {
                "icon": "📐",
                "name": "Product Measurements",
                "desc": "Detailed dimensions like Width, Depth, Height, and Seat Height displayed in a clean table format.",
                "benefit": "Answer space-fit questions instantly",
            },
            {
                "icon": "🎨",
                "name": "Colour & Material Options",
                "desc": "Shows all available colour options with swatch images. Customers can easily visualize what fits their home.",
                "benefit": "Reduce returns and dissatisfaction",
            },
            {
                "icon": "⭐",
                "name": "Product Features",
                "desc": "Detailed feature descriptions for each product — materials, mechanisms, finishes, and selling points.",
                "benefit": "Better sales pitches",
            },
            {
                "icon": "🚫",
                "name": "Discontinued Product Alert",
                "desc": "A red banner appears at the top if any displayed product has been discontinued, with the exact date.",
                "benefit": "Avoid selling discontinued items",
            },
            {
                "icon": "🔍",
                "name": "Search & Browse by Category",
                "desc": "Search by name or browse by Main Category → Sub Category using breadcrumb navigation.",
                "benefit": "Find any product in seconds",
            },
        ],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# HELPER: render section header
# ─────────────────────────────────────────────────────────────────────────────
CATEGORY_COLORS = {
    "Sales":           "#16213e",
    "Reporting":       "#1a0533",
    "Operations":      "#0d2137",
    "Productivity":    "#062012",
    "HR & Incentives": "#1a0a00",
}
CATEGORY_ACCENTS = {
    "Sales":           "#6366f1",
    "Reporting":       "#a855f7",
    "Operations":      "#0ea5e9",
    "Productivity":    "#10b981",
    "HR & Incentives": "#f59e0b",
}
ALL_CATEGORIES = ["All"] + list(CATEGORY_COLORS.keys())

# ─────────────────────────────────────────────────────────────────────────────
# ROUTE MAP for st.switch_page()
# ─────────────────────────────────────────────────────────────────────────────
ROUTE_MAP = {m["id"]: m["route"] for m in MODULES}

# ─────────────────────────────────────────────────────────────────────────────
# HERO SECTION
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="crm-hero">
  <div class="hero-badge">✦ GODREJ INTERIO PATIA · CRM FEATURE GUIDE</div>
  <div class="hero-title">What This CRM Can Do</div>
  <div class="hero-subtitle">
    Your complete guide to every tool in the system. Click on any module to go there directly,
    or explore what each feature does and how it helps your daily work.
  </div>
  <div class="hero-stats">
    <div class="hero-stat">
      <span class="hero-stat-number">15+</span>
      <span class="hero-stat-label">Modules</span>
    </div>
    <div class="hero-stat">
      <span class="hero-stat-number">60+</span>
      <span class="hero-stat-label">Features</span>
    </div>
    <div class="hero-stat">
      <span class="hero-stat-number">5</span>
      <span class="hero-stat-label">Categories</span>
    </div>
    <div class="hero-stat">
      <span class="hero-stat-number">24/7</span>
      <span class="hero-stat-label">Automation</span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# QUICK HIGHLIGHTS ROW
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="highlight-row">
  <div class="highlight-card" style="background: linear-gradient(135deg,#6366f1,#8b5cf6); color:#fff;">
    <div class="highlight-label">⚡ Most Used Daily</div>
    <div class="highlight-value">B2C Dashboard</div>
    <div class="highlight-sub">Your starting point every morning</div>
  </div>
  <div class="highlight-card" style="background: linear-gradient(135deg,#10b981,#059669); color:#fff;">
    <div class="highlight-label">🕒 Saves Most Time</div>
    <div class="highlight-value">Auto-Imports</div>
    <div class="highlight-sub">Leads, MIS & Stock — zero manual entry</div>
  </div>
  <div class="highlight-card" style="background: linear-gradient(135deg,#f59e0b,#d97706); color:#fff;">
    <div class="highlight-label">💡 Manager's Must-Have</div>
    <div class="highlight-value">Sales Reports</div>
    <div class="highlight-sub">Strategy & performance in one place</div>
  </div>
  <div class="highlight-card" style="background: linear-gradient(135deg,#ec4899,#be185d); color:#fff;">
    <div class="highlight-label">🏆 Revenue Builder</div>
    <div class="highlight-value">Customer Intel</div>
    <div class="highlight-sub">Re-engage at-risk & dormant buyers</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH + FILTER ROW
# ─────────────────────────────────────────────────────────────────────────────
col_search, col_cat = st.columns([3, 2])

with col_search:
    search_query = st.text_input(
        "🔍 Search features, modules, or topics…",
        placeholder="e.g. 'leads', 'stock', 'incentive', 'WhatsApp'…",
        label_visibility="collapsed",
    )

with col_cat:
    selected_cat = st.selectbox(
        "Category",
        ALL_CATEGORIES,
        label_visibility="collapsed",
    )

# ─────────────────────────────────────────────────────────────────────────────
# FILTER LOGIC
# ─────────────────────────────────────────────────────────────────────────────
def matches(mod: dict, query: str, cat: str) -> bool:
    if cat != "All" and mod["category"] != cat:
        return False
    if not query:
        return True
    q = query.lower()
    searchable = (
        mod["title"] + " " +
        mod["tagline"] + " " +
        mod["what_it_does"] + " " +
        " ".join(f["name"] + " " + f["desc"] for f in mod["features"])
    ).lower()
    return q in searchable

filtered = [m for m in MODULES if matches(m, search_query, selected_cat)]

if not filtered:
    st.markdown("""
    <div style="text-align:center; padding:4rem 2rem; color:#94a3b8;">
        <div style="font-size:3rem; margin-bottom:1rem;">🔎</div>
        <div style="font-size:1.2rem; font-weight:600; color:#64748b;">No modules found</div>
        <div style="margin-top:0.5rem;">Try a different search term or select a different category.</div>
    </div>
    """, unsafe_allow_html=True)
else:
    # ── SECTION: MAIN ────────────────────────────────────────────────────────
    main_mods = [m for m in filtered if m["section"] == "Main"]
    handbook_mods = [m for m in filtered if m["section"] == "Sales Handbook"]

    def render_tag(t: str) -> str:
        cls_map = {"daily": "tag-daily", "manager": "tag-manager", "sales": "tag-sales", "auto": "tag-auto", "new": "tag-new"}
        label_map = {"daily": "📅 Daily Use", "manager": "🔐 Manager", "sales": "💼 Sales", "auto": "⚡ Auto", "new": "✨ New"}
        cls = cls_map.get(t, "tag-sales")
        lbl = label_map.get(t, t)
        return f'<span class="tag {cls}">{lbl}</span>'

    def render_section(mods, section_label, section_icon):
        if not mods:
            return

        st.markdown(f"""
        <div class="fancy-divider"></div>
        <h2 style="font-size:1.4rem; font-weight:800; color:#1e293b; margin-bottom:1.2rem;">
            {section_icon} {section_label}
        </h2>
        """, unsafe_allow_html=True)

        for mod in mods:
            accent = CATEGORY_ACCENTS.get(mod["category"], "#6366f1")
            bg = CATEGORY_COLORS.get(mod["category"], "#1e293b")
            tags_html = "".join(render_tag(t) for t in mod["tags"])

            # ── Section header ──
            st.markdown(f"""
            <div class="section-header" style="background: {mod['gradient']};">
                <span class="section-icon">{mod['emoji']}</span>
                <div>
                    <div class="section-title">{mod['title']}</div>
                    <div class="section-desc">{mod['tagline']}</div>
                </div>
                <div style="margin-left:auto;">{tags_html}</div>
            </div>
            """, unsafe_allow_html=True)

            # ── Module card ──
            feature_cards_html = ""
            for f in mod["features"]:
                feature_cards_html += f"""
                <div class="feature-card">
                    <div class="feature-icon">{f['icon']}</div>
                    <div class="feature-name">{f['name']}</div>
                    <div class="feature-desc">{f['desc']}</div>
                    <span class="feature-benefit">✓ {f['benefit']}</span>
                </div>
                """

            st.markdown(f"""
            <div class="module-card">
                <p style="font-size:0.88rem; color:#475569; margin:0 0 0.7rem 0; line-height:1.6;">
                    {mod['what_it_does']}
                </p>
                <div style="font-size:0.78rem; font-weight:700; color:{accent}; text-transform:uppercase;
                     letter-spacing:0.6px; margin-bottom:0.5rem;">
                    FEATURES ON THIS PAGE
                </div>
                <div class="feature-grid">
                    {feature_cards_html}
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ── Navigate button ──
            btn_col, _ = st.columns([2, 5])
            with btn_col:
                if st.button(f"Open {mod['emoji']} {mod['title']}", key=f"nav_{mod['id']}",
                             use_container_width=True):
                    st.switch_page(mod["route"])

    render_section(main_mods, "Main Dashboard & Tools", "🛋️")
    render_section(handbook_mods, "Sales Handbook", "📚")


# ─────────────────────────────────────────────────────────────────────────────
# QUICK REFERENCE TABLE
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="fancy-divider"></div>', unsafe_allow_html=True)
st.markdown("### 📋 Quick Reference — All Modules at a Glance")

table_rows = ""
for m in MODULES:
    tags_text = " · ".join(t.upper() for t in m["tags"])
    feat_count = len(m["features"])
    table_rows += f"""
    <tr>
        <td><strong>{m['emoji']} {m['title']}</strong></td>
        <td>{m['category']}</td>
        <td>{feat_count} features</td>
        <td><span style="font-size:0.75rem; color:#64748b;">{tags_text}</span></td>
    </tr>
    """

st.markdown(f"""
<table class="ref-table">
  <thead>
    <tr>
      <th>Module</th>
      <th>Category</th>
      <th>Features</th>
      <th>Tags</th>
    </tr>
  </thead>
  <tbody>
    {table_rows}
  </tbody>
</table>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# DAILY WORKFLOW GUIDE
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="fancy-divider"></div>', unsafe_allow_html=True)
st.markdown("### 🌅 Recommended Daily Workflow for Sales Executives")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#eff6ff,#dbeafe); border-radius:14px; padding:1.4rem; border:1.5px solid #bfdbfe;">
        <div style="font-size:1.5rem; margin-bottom:0.5rem;">☀️ Morning (9–10 AM)</div>
        <ul style="font-size:0.85rem; color:#1e40af; line-height:1.9; padding-left:1.2rem; margin:0;">
            <li>Check <strong>B2C Dashboard</strong> for new orders</li>
            <li>Review <strong>Smart Alerts</strong> ticker</li>
            <li>Check <strong>Sales Team Tasks</strong> for today</li>
            <li>Open <strong>MIS Update</strong> for delivery-ready items</li>
            <li>Call pending <strong>Happy Calling</strong> customers</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#f0fdf4,#dcfce7); border-radius:14px; padding:1.4rem; border:1.5px solid #86efac;">
        <div style="font-size:1.5rem; margin-bottom:0.5rem;">🏪 Showroom Hours (10–6 PM)</div>
        <ul style="font-size:0.85rem; color:#166534; line-height:1.9; padding-left:1.2rem; margin:0;">
            <li>Check <strong>Price List</strong> for customer queries</li>
            <li>Browse <strong>Product Catalogue</strong> with customers</li>
            <li>Add new walk-in enquiries to <strong>Leads</strong></li>
            <li>Update lead status after each contact</li>
            <li>Check <strong>Stock</strong> before confirming availability</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#fdf4ff,#fae8ff); border-radius:14px; padding:1.4rem; border:1.5px solid #e9d5ff;">
        <div style="font-size:1.5rem; margin-bottom:0.5rem;">🌙 End of Day (6–7 PM)</div>
        <ul style="font-size:0.85rem; color:#6b21a8; line-height:1.9; padding-left:1.2rem; margin:0;">
            <li>Mark tasks complete in <strong>Sales Team Tasks</strong></li>
            <li>Update follow-up dates on all <strong>Leads</strong></li>
            <li>Check <strong>Daily B2C Sales</strong> score vs target</li>
            <li>Send pending <strong>Happy Calling</strong> WhatsApps</li>
            <li>Note any customer feedback in lead remarks</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# FAQ SECTION
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="fancy-divider"></div>', unsafe_allow_html=True)
st.markdown("### ❓ Frequently Asked Questions")

faqs = [
    ("How does my data get saved?",
     "Everything you enter in this CRM is saved directly to Google Sheets in real time. You don't need to click any save button — it's automatic."),
    ("Who can see the Sales Manager Dashboard?",
     "Only users with Manager, Admin, Owner, or Proprietor roles can access the Sales Manager Dashboard. Regular sales executives cannot see incentive calculations."),
    ("How often is MIS and Stock data updated?",
     "Both MIS and Stock data are automatically refreshed every day at 11 AM. You can also manually trigger a fresh pull anytime using the 'Force Fetch Now' button."),
    ("Where do email leads come from?",
     "Leads sent via OneCRM or other configured sources are automatically pulled from a dedicated Gmail inbox and added to the Leads page every few hours."),
    ("Can I use this CRM on my phone?",
     "Yes — the CRM works in any mobile web browser. Open the same URL on your phone and it will adapt to the smaller screen."),
    ("What happens if I accidentally enter wrong data?",
     "Most data can be corrected by editing the record. For critical changes, please contact your manager or system admin."),
    ("How do I check my personal sales performance?",
     "Open the 'Daily B2C Sales' page to see your sales value vs your monthly target. The 'Sales Reports' page shows a longer-term leaderboard."),
    ("What is the difference between B2C Dashboard and Daily B2C Sales?",
     "B2C Dashboard shows all orders and operational details (deliveries, payments). Daily B2C Sales focuses on performance — who sold what and how close each person is to their target."),
]

for i, (q, a) in enumerate(faqs):
    with st.expander(f"Q{i+1}: {q}"):
        st.markdown(f"""
        <div style="background:#f8faff; border-left:4px solid #6366f1; border-radius:6px;
             padding:1rem 1.2rem; font-size:0.88rem; color:#334155; line-height:1.65;">
            {a}
        </div>
        """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="guide-footer">
    <div style="font-size:1.6rem; margin-bottom:0.5rem;">🛋️</div>
    <div style="font-size:1rem; font-weight:700; color:#fff; margin-bottom:0.3rem;">
        Godrej Interio Patia · CRM System
    </div>
    <div>
        For support or to report an issue, contact your system administrator.<br>
        <span style="color:rgba(255,255,255,0.4); font-size:0.75rem;">
            This guide is automatically generated from the live CRM module registry.
        </span>
    </div>
</div>
""", unsafe_allow_html=True)
