# pages/90_History_Log.py
import streamlit as st
from services.sheets import get_df

st.set_page_config(layout="wide")
st.title("📝 Change History (read-only)")

log_df = get_df("History Log")
if log_df is None or log_df.empty:
    st.info("No history recorded yet.")
else:
    st.dataframe(log_df, use_container_width=True)
