# ---------- 5. TOTALS & ADVANCED STYLING ----------
if not df_display.empty and len(all_execs) > 0:
    # Append Total Row
    totals_val = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date":
            totals_val[col] = df_display[col].sum()
    df_display = pd.concat([df_display, pd.DataFrame([totals_val])], ignore_index=True)

    # Injecting CSS for Sticky Header, Scrollbar, and Styling
    st.markdown("""
        <style>
            /* The Container that holds the table */
            .table-scroll-container {
                max-height: 450px; /* Approximately 15 days of data height */
                overflow-y: auto;
                border: 1px solid #ccc;
                width: fit-content;
                margin-bottom: 20px;
            }
            
            .squeezed-table {
                width: auto !important;
                border-collapse: separate; /* Required for sticky border integrity */
                border-spacing: 0;
                font-family: Arial, sans-serif;
            }

            /* STICKY HEADER LOGIC */
            .squeezed-table thead th {
                position: sticky;
                top: 0;
                z-index: 10;
                background-color: #f0f2f6;
                color: #000000 !important;
                font-weight: 900 !important;
                padding: 6px 10px !important;
                border: 1px solid #ccc;
                text-align: center;
                white-space: nowrap;
            }

            .squeezed-table td {
                padding: 4px 8px !important;
                border: 1px solid #ccc;
                text-align: right;
                white-space: nowrap;
                color: #333;
            }

            /* Custom Scrollbar Styling */
            .table-scroll-container::-webkit-scrollbar {
                width: 8px;
            }
            .table-scroll-container::-webkit-scrollbar-track {
                background: #f1f1f1;
            }
            .table-scroll-container::-webkit-scrollbar-thumb {
                background: #888;
                border-radius: 4px;
            }
            .table-scroll-container::-webkit-scrollbar-thumb:hover {
                background: #555;
            }
        </style>
    """, unsafe_allow_html=True)

    def style_dataframe(row):
        row_styles = [''] * len(row)
        is_total_row = (row["Date"] == "TOTAL")
        
        # Determine background color
        bg_color = ""
        if not is_total_row:
            if row["Store Total"] > 500000:
                bg_color = "background-color: #2e7d32; color: white;" 
            elif row["Store Total"] <= 0:
                bg_color = "background-color: #f8d7da;" 
        else:
            bg_color = "background-color: #eeeeee; font-weight: 900; color: #000000;"

        # Apply styles cell by cell
        for i, col in enumerate(df_display.columns):
            cell_style = bg_color
            
            if col == "Store Total" or is_total_row:
                cell_style += " font-weight: 900; color: #000000 !important;"
            
            if not is_total_row and col not in ["Date", "Store Total"] and row[col] <= 0:
                cell_style += " color: #721c24;"
            
            row_styles[i] = cell_style
            
        return row_styles

    # Format numeric values
    format_cols = {col: "{:.2f}" for col in df_display.columns if col != "Date"}
    
    # Generate Styled HTML
    styled_html = (
        df_display.style
        .apply(style_dataframe, axis=1)
        .format(format_cols)
        .set_table_attributes('class="squeezed-table"')
        .hide(axis='index') # Hide the default pandas index
        .to_html()
    )

    # WRAP THE TABLE IN THE SCROLL CONTAINER
    st.write(f'<div class="table-scroll-container">{styled_html}</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.success(f"### 💰 Grand Total Sales: ₹{df_display.iloc[-1]['Store Total']:,.2f}")
else:
    st.info("No active sales data found for this period.")