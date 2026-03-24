# pages/40_Filter_CRM.py
import streamlit as st
import pandas as pd
from services.sheets import get_df
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

st.set_page_config(layout="wide")
st.title("🔎 CRM Filter (Orders View) — Read-Only")

# ---------- Load Data ----------
df = get_df("CRM")

if df is None or df.empty:
    st.info("CRM is empty.")
    st.stop()

df = df.copy()
df.columns = [c.strip() for c in df.columns]

# ---------- Preprocessing ----------
# Convert DATE column
if "DATE" in df.columns:
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")

# Clean currency columns
money_cols = [
    "ORDER AMOUNT", "GROSS ORDER VALUE", "MRP",
    "UNIT PRICE=(AFTER DISC + TAX)", "ADV RECEIVED",
    "INV AMT(BEFORE TAX)"
]

for col in money_cols:
    if col in df.columns:
        df[col] = (
            df[col].astype(str)
            .str.replace("[₹,]", "", regex=True)
            .str.strip()
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")

# ---------- Sidebar Filters ----------
st.sidebar.subheader("🔍 Quick Filters")

# B2B/B2C Filter
if "B2B/B2C" in df.columns:
    b2c_filter = st.sidebar.multiselect(
        "B2B / B2C",
        options=sorted(df["B2B/B2C"].dropna().unique()),
        default=sorted(df["B2B/B2C"].dropna().unique())
    )
    df = df[df["B2B/B2C"].isin(b2c_filter)]

# Sales Person Filter
if "SALES PERSON" in df.columns:
    exec_filter = st.sidebar.multiselect(
        "Sales Person",
        options=sorted(df["SALES PERSON"].dropna().unique()),
        default=sorted(df["SALES PERSON"].dropna().unique())
    )
    df = df[df["SALES PERSON"].isin(exec_filter)]

# Date Filter
if "DATE" in df.columns:
    min_date = df["DATE"].min()
    max_date = df["DATE"].max()

    start_date = st.sidebar.date_input("Start Date", value=min_date)
    end_date = st.sidebar.date_input("End Date", value=max_date)

    df = df[
        (df["DATE"] >= pd.to_datetime(start_date)) &
        (df["DATE"] <= pd.to_datetime(end_date))
    ]

# ---------- View Settings ----------
st.sidebar.subheader("🧰 View Options")

page_size = st.sidebar.selectbox("Rows per page", [25, 50, 100, 200], index=0)
min_col_w = st.sidebar.slider("Min column width (px)", 120, 300, 180, 10)
wrap_text = st.sidebar.checkbox("Wrap cell text", value=False)

row_height = 48 if wrap_text else 28

# ---------- Grid Setup ----------
gb = GridOptionsBuilder.from_dataframe(df)

gb.configure_default_column(
    resizable=True,
    filter=True,
    sortable=True,
    floatingFilter=True,
    min_width=min_col_w,
    wrapText=wrap_text,
    autoHeight=wrap_text,
)

# Highlight important columns
highlight_cols = ["ORDER AMOUNT", "GROSS ORDER VALUE"]

for col in highlight_cols:
    if col in df.columns:
        gb.configure_column(
            col,
            type=["numericColumn"],
            valueFormatter="x.toLocaleString('en-IN')",
        )

# Pagination
gb.configure_pagination(
    enabled=True,
    paginationAutoPageSize=False,
    paginationPageSize=page_size
)

gb.configure_selection(selection_mode="single", use_checkbox=True)

# Default sort by DATE (latest first)
if "DATE" in df.columns:
    gb.configure_column("DATE", sort="desc")

# Grid behavior
gb.configure_grid_options(
    domLayout="normal",
    ensureDomOrder=True,
    suppressHorizontalScroll=False,
    headerHeight=36,
    rowHeight=row_height,
)

go = gb.build()

# ---------- Render Grid ----------
AgGrid(
    df,
    gridOptions=go,
    update_mode=GridUpdateMode.NO_UPDATE,
    enable_enterprise_modules=False,
    height=650,
    fit_columns_on_grid_load=False,
    allow_unsafe_jscode=False,
    theme="balham",
)

# ---------- Summary ----------
st.caption(
    "💡 Tips:\n"
    "- Use filters in column headers\n"
    "- Scroll horizontally for full CRM view\n"
    "- Use sidebar filters for quick slicing (B2C, Sales Person, Date)"
)