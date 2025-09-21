import streamlit as st
from sheets import get_df
import pandas as pd

st.set_page_config(page_title="Service Requests", layout="wide")
st.title("🛠 Service Requests")

df = get_df("Service Requests")

if df is not None and not df.empty:
    st.dataframe(df, use_container_width=True)

    # Status breakdown
    st.subheader("📊 Request Status")
    status_counts = df["Status"].value_counts()
    st.bar_chart(status_counts)
else:
    st.warning("No service request data available yet.")
