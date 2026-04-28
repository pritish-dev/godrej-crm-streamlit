import streamlit as st
from datetime import date
from services.attendance import fetch_attendance
from utils.admin_auth import admin_login, admin_logout_button


def show_attendance_page():
    # 🔐 Protect page
    admin_login()

    st.title("📊 Employee Attendance")

    admin_logout_button()

    col1, col2 = st.columns(2)

    with col1:
        from_date = st.date_input("From Date", date.today())

    with col2:
        to_date = st.date_input("To Date", date.today())

    if st.button("Fetch Attendance"):
        df = fetch_attendance(str(from_date), str(to_date))

        if df.empty:
            st.warning("No data found")
        else:
            st.success(f"{len(df)} records found")
            st.dataframe(df, use_container_width=True)

            # Metrics
            st.subheader("Summary")
            st.metric("Total Logs", len(df))
            st.metric("Employees", df["Employee ID"].nunique())

            # Download
            st.download_button(
                "Download CSV",
                df.to_csv(index=False),
                "attendance.csv",
                "text/csv"
            )