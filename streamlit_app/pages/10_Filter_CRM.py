# pages/40_Filter_CRM.py
import streamlit as st
from services.sheets import get_df
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

st.set_page_config(layout="wide")
st.title("🔎 CRM Filter (Excel-style) — Read-Only")

df = get_df("CRM")
if df is None or df.empty:
    st.info("CRM is empty.")
    st.stop()

# ---- Sidebar display tuning ----
st.sidebar.subheader("🧰 View Options")
page_size = st.sidebar.selectbox("Rows per page", [25, 50, 100, 200], index=0)
min_col_w = st.sidebar.slider("Min column width (px)", 120, 300, 180, 10)
wrap_text = st.sidebar.checkbox("Wrap cell text", value=False)

# Row height depends on wrapping
row_height = 48 if wrap_text else 28

gb = GridOptionsBuilder.from_dataframe(df)

# Default columns: allow horizontal scroll by NOT fitting to viewport
gb.configure_default_column(
    resizable=True,
    filter=True,
    sortable=True,
    floatingFilter=True,
    min_width=min_col_w,
    wrapText=wrap_text,      # requires autoHeight to expand wrapped rows
    autoHeight=wrap_text,
)

# Grid-level options
gb.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=page_size)
gb.configure_selection(selection_mode="single", use_checkbox=True)

# Ensure normal DOM layout (allows horizontal scrollbar)
gb.configure_grid_options(
    domLayout="normal",
    ensureDomOrder=True,
    suppressHorizontalScroll=False,
    headerHeight=36,
    rowHeight=row_height,
)

go = gb.build()

AgGrid(
    df,
    gridOptions=go,
    update_mode=GridUpdateMode.NO_UPDATE,
    enable_enterprise_modules=False,
    height=650,
    fit_columns_on_grid_load=False,   # <-- KEY: allow natural widths + horizontal scroll
    allow_unsafe_jscode=False,
    theme="balham",                   # (optional) clean readable theme
)

st.caption("Tip: Use the header filter icons or the floating filter row below headers. Drag edges to resize columns; a horizontal scrollbar is available when needed.")
