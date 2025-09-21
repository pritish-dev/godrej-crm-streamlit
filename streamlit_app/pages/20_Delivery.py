import streamlit as st
from sheets import get_df
import pandas as pd

st.set_page_config(page_title="Delivery", layout="wide")
st.title("🚚 Deliveries")

df = get_df("Delivery")

if df is not None and not df.empty:
    st.dataframe(df, use_container_width=True)

    # Delivery status summary
    st.subheader("📊 Delivery Status")
    status_counts = df["Delivery Status"].value_counts()
    st.bar_chart(status_counts)
else:
    st.warning("No delivery data available yet.")
        1 file(s) copied.
