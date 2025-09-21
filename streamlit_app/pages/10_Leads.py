import streamlit as st
from sheets import get_df
import pandas as pd

st.set_page_config(page_title="Leads", layout="wide")
st.title("📋 Leads")

# Load data
df = get_df("Leads")

if df is not None and not df.empty:
    st.dataframe(df, use_container_width=True)

    # Summary
    st.subheader("📊 Leads Summary")
    weekly = df.groupby(pd.to_datetime(df["Next Follow-up Date"]).dt.isocalendar().week).size()
    st.bar_chart(weekly)
else:
    st.warning("No leads data available yet.")
