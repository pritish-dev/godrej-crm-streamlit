"""
pages/20_Product_Sales_Analysis.py
Product Sales Analysis — supports BOTH the legacy and the new FY 26-27
column formats.

Categories  : HOME STORAGE  |  HOME FURNITURE  |  OTHERS
Sub-categories are auto-detected from the product name (Bed, Sofa, Coffee
Table, Dining, Mattress, Wardrobe, …).

Special handling — Kreation X3 (modular Home Storage)
─────────────────────────────────────────────────────
A Kreation X3 unit is built from multiple modular items.  We compute the
number of complete Kreation X3 units sold per ORDER NO using these rules:

    • If the order contains Kreation X3 items but NO dresser unit  →
        units sold == count of items containing the word "Main".
    • If the order contains a "Dresser 1" item                     →
        units sold == count of items containing "Main".
    • If the order contains a "Dresser 2" item                     →
        units sold == count of items containing "Main"  ÷ 2.

The aggregated Kreation-X3 unit count is added to the Home Storage table.
"""
from __future__ import annotations

import math
import re
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from services.sheets import get_df

st.set_page_config(page_title="Product Sales Analysis", layout="wide")
st.title("📦 Product Sales Performance")

# =========================================================
# HELPERS
# =========================================================
def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def fix_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols, count = [], {}
    for col in df.columns:
        if col in count:
            count[col] += 1
            cols.append(f"{col}_{count[col]}")
        else:
            count[col] = 0
            cols.append(col)
    df.columns = cols
    return df


def parse_mixed_date(x):
    try:
        s = str(x).strip()
        if s.isdigit():
            return pd.to_datetime("1899-12-30") + pd.to_timedelta(int(s), unit="D")
        return pd.to_datetime(s, errors="coerce", dayfirst=True)
    except Exception:
        return pd.NaT


def clean_product_names(series: pd.Series) -> pd.Series:
    garbage = {"", "0", "NAN", "NONE", "NULL", "-", "--"}
    return series.apply(lambda x: x if str(x).strip().upper() not in garbage else None)


# =========================================================
# CATEGORY + SUB-CATEGORY MAPPING
# =========================================================
CATEGORY_MAP = {
    "HOME FURNITURE": "HOME FURNITURE",
    "FURNITURE":      "HOME FURNITURE",
    "HOME STORAGE":   "HOME STORAGE",
    "STORAGE":        "HOME STORAGE",
}

# Order matters — first match wins.  All keys are upper-case substrings.
SUBCATEGORY_RULES: list[tuple[str, str]] = [
    ("KREATION X3",                                 "Kreation X3"),
    ("DINING",                                      "Dining Table"),
    ("COFFEE TABLE",                                "Coffee Table"),
    ("CENTER TABLE",                                "Centre Table"),
    ("STUDY TABLE",                                 "Study Table"),
    ("SIDE TABLE",                                  "Side Table"),
    ("CONSOLE",                                     "Console Table"),
    ("DRESSER",                                     "Dresser"),
    ("WARDROBE",                                    "Wardrobe"),
    ("ALMIRAH",                                     "Wardrobe"),
    ("CHEST",                                       "Chest of Drawers"),
    ("BOOK",                                        "Bookshelf"),
    ("SHOE",                                        "Shoe Rack"),
    ("TV UNIT",                                     "TV Unit"),
    ("TV CABINET",                                  "TV Unit"),
    ("ENTERTAINMENT",                               "TV Unit"),
    ("SOFA CUM BED",                                "Sofa Cum Bed"),
    ("RECLINER",                                    "Recliner"),
    ("SOFA",                                        "Sofa"),
    ("MATTRESS",                                    "Mattress"),
    ("BED",                                         "Bed"),
    ("CHAIR",                                       "Chair"),
    ("STOOL",                                       "Stool"),
    ("BENCH",                                       "Bench"),
    ("OFFICE",                                      "Office Furniture"),
    ("DESK",                                        "Desk"),
    ("TABLE",                                       "Table (Other)"),
]


def map_category(raw: str) -> str:
    s = str(raw).upper()
    for k, v in CATEGORY_MAP.items():
        if k in s:
            return v
    return "OTHERS"


def map_subcategory(prod: str) -> str:
    s = str(prod).upper()
    for needle, label in SUBCATEGORY_RULES:
        if needle in s:
            return label
    return "Other"


# =========================================================
# DATA LOADING
# =========================================================
@st.cache_data(ttl=120)
def load_all_franchise_data() -> pd.DataFrame:
    """Pulls every sheet referenced by SHEET_DETAILS (Franchise + 4S)."""
    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
        return pd.DataFrame()
    config_df = standardize_columns(config_df)

    sheet_list: list[str] = []
    for col in ("FRANCHISE_SHEETS", "FOUR_S_SHEETS"):
        if col in config_df.columns:
            sheet_list += config_df[col].dropna().tolist()
    sheet_list = list({str(s).strip() for s in sheet_list if str(s).strip()})

    frames = []
    for sheet in sheet_list:
        df = get_df(sheet)
        if df is None or df.empty:
            continue
        df = standardize_columns(df)
        df = fix_duplicate_columns(df)
        df["SOURCE_SHEET"] = sheet
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    cleaned = []
    for df in frames:
        df = df.loc[:, ~df.columns.duplicated()]
        cleaned.append(df)

    return pd.concat(cleaned, ignore_index=True, sort=False)


# ─── load + unify columns across legacy and new format ──────────────────────
crm_raw = load_all_franchise_data()
if crm_raw.empty:
    st.warning("No data found.")
    st.stop()

crm = standardize_columns(crm_raw.copy())

# Old-and-new column normalisation
RENAME = {
    "ORDER UNIT PRICE=(AFTER DISC + TAX)": "ORDER VALUE",
    "ORDER AMOUNT":                        "ORDER VALUE",      # legacy
    "DATE":                                "ORDER DATE",       # legacy
    "DELIVERY REMARKS(DELIVERED/PENDING)": "DELIVERY STATUS",
    "DELIVERY REMARKS":                    "DELIVERY STATUS",  # legacy
    "CUSTOMER DELIVERY DATE (TO BE)":      "DELIVERY DATE",
    "SALES REP":                           "SALES PERSON",
}
for src, dst in RENAME.items():
    if src in crm.columns and dst not in crm.columns:
        crm.rename(columns={src: dst}, inplace=True)

# Detect product / category / qty / order columns
prod_col  = next((c for c in crm.columns if "PRODUCT" in c and "NAME" in c), None) \
            or next((c for c in crm.columns if "PRODUCT" in c), None)
cat_col   = next((c for c in crm.columns if "CATEGORY" in c), None)
qty_col   = next((c for c in crm.columns if c == "QTY" or c.startswith("QTY")), None)
order_col = next((c for c in crm.columns if c == "ORDER NO"), None)
date_col  = "ORDER DATE" if "ORDER DATE" in crm.columns else None

if prod_col is None:
    st.error("No product column found in any of the sheets.")
    st.stop()

crm["WORK_PROD"] = crm[prod_col].fillna("UNKNOWN").astype(str).str.strip()
crm["WORK_PROD"] = clean_product_names(crm["WORK_PROD"])
crm = crm.dropna(subset=["WORK_PROD"]).copy()

if cat_col:
    crm["WORK_CAT_RAW"] = crm[cat_col].fillna("OTHERS").astype(str).str.strip()
else:
    crm["WORK_CAT_RAW"] = "OTHERS"
crm["WORK_CAT"] = crm["WORK_CAT_RAW"].apply(map_category)

# ── If category is OTHERS but the product name itself maps to a known
#    category through sub-category → re-classify so the bucketing is honest.
def reclassify_other(row):
    if row["WORK_CAT"] != "OTHERS":
        return row["WORK_CAT"]
    sub = map_subcategory(row["WORK_PROD"])
    if sub in {"Bed", "Sofa", "Sofa Cum Bed", "Recliner", "Mattress",
               "Coffee Table", "Centre Table", "Side Table", "Console Table",
               "Dining Table", "Chair", "Stool", "Bench", "Study Table",
               "Office Furniture", "Desk", "Table (Other)"}:
        return "HOME FURNITURE"
    if sub in {"Wardrobe", "Chest of Drawers", "Bookshelf", "Shoe Rack",
               "TV Unit", "Dresser", "Kreation X3"}:
        return "HOME STORAGE"
    return "OTHERS"


crm["WORK_CAT"] = crm.apply(reclassify_other, axis=1)
crm["SUB_CAT"]  = crm["WORK_PROD"].apply(map_subcategory)

# QTY
if qty_col:
    crm["WORK_QTY"] = pd.to_numeric(crm[qty_col], errors="coerce").fillna(0)
else:
    crm["WORK_QTY"] = 1

# Order date / Year / Month
if date_col:
    crm["WORK_DATE"] = crm[date_col].apply(parse_mixed_date)
else:
    crm["WORK_DATE"] = pd.NaT

crm["YEAR"]  = crm["WORK_DATE"].dt.year.fillna(0).astype(int)
crm["MONTH"] = crm["WORK_DATE"].dt.strftime("%b %Y").fillna("Unknown")

# Order Value (revenue) — optional
if "ORDER VALUE" in crm.columns:
    crm["WORK_VALUE"] = pd.to_numeric(
        crm["ORDER VALUE"].astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0)
else:
    crm["WORK_VALUE"] = 0


# =========================================================
# KREATION X3 — modular unit calculation per ORDER NO
# =========================================================
def kreation_x3_units(order_df: pd.DataFrame) -> int:
    """Compute completed Kreation X3 units within a single ORDER NO."""
    items = order_df["WORK_PROD"].astype(str).str.upper()
    if not items.str.contains("KREATION X3").any():
        return 0

    has_dresser_2 = items.str.contains(r"DRESSER\s*2").any()
    has_dresser_1 = items.str.contains(r"DRESSER\s*1").any()

    # qty-aware "Main" count: sum the QTY of every row whose product name
    # contains the word "MAIN" (handles items like "Kreation X3 Main Unit").
    main_mask  = items.str.contains(r"\bMAIN\b", regex=True)
    main_count = float(order_df.loc[main_mask, "WORK_QTY"].sum())

    # Fallback when there is no 'Main' explicitly named: each Kreation X3
    # row counts itself once.
    if main_count == 0:
        krx3_rows = order_df[items.str.contains("KREATION X3")]
        main_count = float(krx3_rows["WORK_QTY"].sum())

    if has_dresser_2:
        return int(math.floor(main_count / 2))
    # Dresser 1 OR no dresser at all → 1 Main = 1 Kreation X3
    return int(main_count)


def compute_kreation_x3_total(df: pd.DataFrame) -> int:
    if order_col and order_col in df.columns:
        groups = df.groupby(order_col)
    else:
        # Fallback: group by (customer, date) when ORDER NO is absent
        df["_KX3_KEY"] = (
            df.get("CUSTOMER NAME", pd.Series("")).astype(str).str.strip() +
            "|" + df["WORK_DATE"].astype(str)
        )
        groups = df.groupby("_KX3_KEY")
    return int(sum(kreation_x3_units(g) for _, g in groups))


# =========================================================
# FILTERS
# =========================================================
st.subheader("Analysis Filters")
c1, c2, c3, c4 = st.columns(4)

with c1:
    years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    selected_year = st.selectbox("Year", options=["ALL"] + years)

with c2:
    cat_options = ["HOME STORAGE", "HOME FURNITURE", "OTHERS"]
    selected_cat = st.selectbox("Category", options=cat_options)

with c3:
    cat_mask = crm["WORK_CAT"] == selected_cat
    if selected_year != "ALL":
        cat_mask &= crm["YEAR"] == selected_year
    sub_options = ["ALL SUB-CATEGORIES"] + sorted(crm.loc[cat_mask, "SUB_CAT"].dropna().unique().tolist())
    selected_sub = st.selectbox("Sub-Category", options=sub_options)

with c4:
    sub_mask = cat_mask
    if selected_sub != "ALL SUB-CATEGORIES":
        sub_mask &= crm["SUB_CAT"] == selected_sub
    prods = ["ALL PRODUCTS"] + sorted(crm.loc[sub_mask, "WORK_PROD"].dropna().unique().tolist())
    selected_prod = st.selectbox("Product", options=prods)

search_query = st.text_input("🔍 Search Product").strip().upper()

# Build final mask
final_mask = crm["WORK_CAT"] == selected_cat
if selected_year != "ALL":
    final_mask &= crm["YEAR"] == selected_year
if selected_sub != "ALL SUB-CATEGORIES":
    final_mask &= crm["SUB_CAT"] == selected_sub
if selected_prod != "ALL PRODUCTS":
    final_mask &= crm["WORK_PROD"] == selected_prod
if search_query:
    final_mask &= crm["WORK_PROD"].str.upper().str.contains(search_query, na=False)

analysis_df = crm[final_mask].copy()


# =========================================================
# OUTPUT
# =========================================================
total_units    = int(analysis_df["WORK_QTY"].sum())
total_revenue  = float(analysis_df["WORK_VALUE"].sum())
unique_orders  = analysis_df[order_col].nunique() if order_col else len(analysis_df)
unique_skus    = analysis_df["WORK_PROD"].nunique()

m1, m2, m3, m4 = st.columns(4)
m1.metric("📦 Total Units",     total_units)
m2.metric("💰 Total Revenue",   f"₹{total_revenue:,.0f}")
m3.metric("🧾 Unique Orders",   unique_orders)
m4.metric("🛋️ Distinct SKUs",   unique_skus)

# ── Special card: Kreation X3 modular unit count (Home Storage only) ────────
if selected_cat == "HOME STORAGE":
    krx3_total = compute_kreation_x3_total(crm[final_mask])
    st.success(f"🛏️ **Kreation X3 — Completed Modular Units Sold: `{krx3_total}`**")

st.divider()

# ── Sub-category breakdown ──────────────────────────────────────────────────
st.subheader(f"📊 Sub-Category Breakdown — {selected_cat}")
sub_summary = (
    analysis_df.groupby("SUB_CAT")
    .agg(UNITS=("WORK_QTY", "sum"), REVENUE=("WORK_VALUE", "sum"))
    .reset_index()
    .sort_values("UNITS", ascending=False)
)
if not sub_summary.empty:
    chart_sub = alt.Chart(sub_summary).mark_bar().encode(
        x=alt.X("SUB_CAT:N", sort="-y", title="Sub-category"),
        y=alt.Y("UNITS:Q",  title="Units sold"),
        tooltip=["SUB_CAT", "UNITS", alt.Tooltip("REVENUE:Q", format=",.0f")],
    )
    st.altair_chart(chart_sub, use_container_width=True)
    st.dataframe(
        sub_summary.rename(columns={"SUB_CAT": "Sub-Category", "UNITS": "Units", "REVENUE": "Revenue (₹)"}),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("No sub-category data for the current filter set.")

st.divider()

# ── Top products ────────────────────────────────────────────────────────────
st.subheader("🏆 Top Products")
prod_summary = (
    analysis_df.groupby(["SUB_CAT", "WORK_PROD"])
    .agg(UNITS=("WORK_QTY", "sum"), REVENUE=("WORK_VALUE", "sum"))
    .reset_index()
    .sort_values("UNITS", ascending=False)
)
prod_summary.columns = ["Sub-Category", "Product Name", "Units Sold", "Revenue (₹)"]

if not prod_summary.empty:
    top_row = prod_summary.iloc[0]
    st.success(
        f"🏅 Highest sold: **{top_row['Product Name']}** "
        f"({int(top_row['Units Sold'])} units, ₹{top_row['Revenue (₹)']:,.0f})"
    )

    st.download_button(
        "📥 Download CSV", prod_summary.to_csv(index=False).encode("utf-8"),
        "product_sales.csv",
    )
    st.dataframe(prod_summary, use_container_width=True, hide_index=True)

    st.subheader("Top 5 Products (by units)")
    top5 = prod_summary.head(5)
    chart_top5 = alt.Chart(top5).mark_bar().encode(
        x=alt.X("Product Name:N", sort="-y"),
        y="Units Sold:Q",
        tooltip=["Product Name", "Sub-Category", "Units Sold", "Revenue (₹)"],
    )
    st.altair_chart(chart_top5, use_container_width=True)
else:
    st.warning("No product data found for the selected filters.")
