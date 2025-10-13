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

gb = GridOptionsBuilder.from_dataframe(df)
gb.configure_default_column(resizable=True, filter=True, sortable=True, floatingFilter=True)
gb.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=25)
gb.configure_selection(selection_mode="single", use_checkbox=True)
go = gb.build()

AgGrid(
    df,
    gridOptions=go,
    update_mode=GridUpdateMode.NO_UPDATE,
    enable_enterprise_modules=False,
    height=600,
    fit_columns_on_grid_load=True
)

st.caption("Tip: Use the column headers’ filter icon or the floating filter row just below the headers.")
