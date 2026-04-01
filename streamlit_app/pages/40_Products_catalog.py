import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ==============================
# CONFIGURATION
# ==============================
st.set_page_config(page_title="Product Catalog", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
CATALOG_SHEET_NAME = "Product Catalog"
DISCONTINUED_SHEET_NAME = "Discontinued Products"
ITEMS_PER_PAGE = 10

# ==============================
# DATA FETCHING
# ==============================
@st.cache_resource
def _get_client():
    try:
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
    except Exception:
        creds = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_data(ttl=300) # Cache for 5 minutes
def load_all_data():
    sh = _get_client().open_by_key(SPREADSHEET_ID)
    
    # 1. Fetch Catalog
    try:
        ws_catalog = sh.worksheet(CATALOG_SHEET_NAME)
        cat_data = ws_catalog.get_all_values()
        df_catalog = pd.DataFrame(cat_data[1:], columns=cat_data[0]) if len(cat_data) > 1 else pd.DataFrame()
    except Exception:
        df_catalog = pd.DataFrame()

    # 2. Fetch Discontinued
    try:
        ws_disc = sh.worksheet(DISCONTINUED_SHEET_NAME)
        disc_data = ws_disc.get_all_values()
        df_disc = pd.DataFrame(disc_data[1:], columns=disc_data[0]) if len(disc_data) > 1 else pd.DataFrame()
    except Exception:
        df_disc = pd.DataFrame()
        
    # Build a fast lookup dictionary for discontinued items
    disc_dict = {}
    if not df_disc.empty and "Product Name" in df_disc.columns:
        for _, row in df_disc.iterrows():
            disc_dict[str(row["Product Name"]).strip().lower()] = str(row.get("Discontinued Date", "Unknown Date"))

    return df_catalog, disc_dict

# ==============================
# MAIN APP
# ==============================
st.title("🛋️ Godrej Interio Catalog")

df_catalog, disc_dict = load_all_data()

if df_catalog.empty:
    st.warning("Catalog is empty or could not be loaded.")
    st.stop()

# --- SEARCH BAR ---
search_query = st.text_input("🔍 Search by Product Name, Main Category, or Sub Category...", "").lower()

# Reset pagination to page 0 if the user types a new search query
if "last_search" not in st.session_state or st.session_state.last_search != search_query:
    st.session_state.page_num = 0
    st.session_state.last_search = search_query

# Filter Data
if search_query:
    mask = (
        df_catalog['Product Name'].str.lower().str.contains(search_query, na=False) |
        df_catalog['Main Category'].str.lower().str.contains(search_query, na=False) |
        df_catalog['Sub Category'].str.lower().str.contains(search_query, na=False)
    )
    filtered_df = df_catalog[mask]
else:
    filtered_df = df_catalog

# --- NO RESULTS FALLBACK (Instant Text) ---
if filtered_df.empty:
    st.error(f"No exact matches found for '{search_query}'.")
    st.info("💡 Tip: Try checking your spelling or using a broader search term (e.g., 'Sofa' instead of 'Nebula Sofa').")
    st.stop()

# --- PAGINATION LOGIC ---
total_items = len(filtered_df)
total_pages = (total_items - 1) // ITEMS_PER_PAGE + 1

if "page_num" not in st.session_state:
    st.session_state.page_num = 0

# Pagination Controls (Top)
col1, col2, col3 = st.columns([1, 8, 1])
with col1:
    if st.button("◀ Prev", disabled=(st.session_state.page_num == 0)):
        st.session_state.page_num -= 1
        st.rerun()
with col2:
    st.markdown(f"<div style='text-align: center; padding-top: 5px;'>Showing Page <b>{st.session_state.page_num + 1}</b> of {total_pages} ({total_items} total products)</div>", unsafe_allow_html=True)
with col3:
    if st.button("Next ▶", disabled=(st.session_state.page_num >= total_pages - 1)):
        st.session_state.page_num += 1
        st.rerun()

st.markdown("---")

# Slice the dataframe for the current page
start_idx = st.session_state.page_num * ITEMS_PER_PAGE
end_idx = start_idx + ITEMS_PER_PAGE
page_df = filtered_df.iloc[start_idx:end_idx]

# --- RENDER PRODUCTS ---
for _, product in page_df.iterrows():
    p_name = product.get('Product Name', 'Unknown Product')
    is_discontinued = p_name.lower() in disc_dict
    
    with st.container():
        # Discontinued Marquee Alert
        if is_discontinued:
            disc_date = disc_dict[p_name.lower()]
            st.markdown(
                f"""
                <marquee style="color: white; background-color: #d9534f; padding: 5px; font-weight: bold; border-radius: 4px;">
                🚨 THIS PRODUCT HAS BEEN DISCONTINUED SINCE {disc_date.upper()} 🚨
                </marquee>
                """, 
                unsafe_allow_html=True
            )
            
        # Breadcrumbs & Title
        st.caption(f"{product.get('Main Category', '')} > {product.get('Sub Category', '')}")
        st.subheader(p_name)
        
        # Discontinued Sub-label
        if is_discontinued:
            st.markdown("<h5 style='color: #d9534f; margin-top: -10px;'><b>DISCONTINUED</b></h5>", unsafe_allow_html=True)
        
        layout_col1, layout_col2 = st.columns([1.2, 2])
        
        # LEFT COLUMN: Large Images
        with layout_col1:
            raw_images = product.get('Product Image URLs', "")
            images = [url.strip() for url in raw_images.split(",") if url.strip()]
            
            if images:
                state_key = f"img_{p_name}"
                if state_key not in st.session_state:
                    st.session_state[state_key] = 0
                    
                nav1, nav2, nav3 = st.columns([1, 3, 1])
                with nav1:
                    if st.button("<", key=f"p_{p_name}"): st.session_state[state_key] = (st.session_state[state_key] - 1) % len(images)
                with nav3:
                    if st.button(">", key=f"n_{p_name}"): st.session_state[state_key] = (st.session_state[state_key] + 1) % len(images)
                
                st.image(images[st.session_state[state_key]], use_container_width=True)
            else:
                st.info("No product image available.")
                
        # RIGHT COLUMN: Details
        with layout_col2:
            tab1, tab2, tab3 = st.tabs(["Features", "Measurements", "Colour & Material"])
            
            # Tab 1: Specs
            #with tab1:
                #st.write(product.get('Features', 'No specific Features listed.'))
                
            with tab1:
                raw_features = product.get('Features', 'No specific Features listed.')
                # This ensures any '|' separators or single newlines become 
                # double newlines, which Markdown requires for a clean visual break.
                clean_features = str(raw_features).replace("\n", "\n\n")
                st.markdown(clean_features)
            # Tab 2: Measurements Table
            '''with tab2:
                measurements_raw = str(product.get('Measurements', ''))
                if "|" in measurements_raw:
                    lines = [line.strip() for line in measurements_raw.split('\n') if line.strip()]
                    try:
                        headers = [h.strip() for h in lines[0].split('|')]
                        rows = [[cell.strip() for cell in line.split('|')] for line in lines[1:]]
                        # Pad rows that might be missing columns to prevent pandas errors
                        max_cols = len(headers)
                        padded_rows = [r + ['']*(max_cols - len(r)) for r in rows]
                        
                        df_meas = pd.DataFrame(padded_rows, columns=headers)
                        st.dataframe(df_meas, hide_index=True, use_container_width=True)
                    except Exception as e:
                        st.write(measurements_raw) # Fallback to raw text if table parsing fails
                else:
                    st.write("No detailed measurements available.")'''
                    
            # Tab 2: Measurements (Smart Tabular Form)
            with tab2:
                measurements_raw = str(product.get('Measurements', ''))
                
                if measurements_raw.strip():
                    # Check if it's a "Pipe Table" (extracted correctly) 
                    # or a "Linear Line" (extracted as a sentence)
                    if "|" in measurements_raw:
                        lines = [line.strip() for line in measurements_raw.split('\n') if line.strip()]
                        try:
                            # Split by pipe and clean headers/rows
                            headers = [h.strip() for h in lines[0].split('|')]
                            rows = [[cell.strip() for cell in line.split('|')] for line in lines[1:]]
                            
                            # Standardize column counts
                            max_cols = len(headers)
                            padded_rows = [r + ['']*(max_cols - len(r)) for r in rows]
                            
                            df_meas = pd.DataFrame(padded_rows, columns=headers)
                            st.dataframe(df_meas, hide_index=True, use_container_width=True)
                        except:
                            st.info(measurements_raw) # Fallback
                            
                    else:
                        # FIX FOR LINEAR LINES: 
                        # If it's a long sentence, we split by common labels to create a vertical table
                        labels = ["Width:", "Depth:", "Height:", "Seat Height:", "1 Seater:", "2 Seater:", "3 Seater:"]
                        processed_text = measurements_raw
                        for label in labels:
                            processed_text = processed_text.replace(label, f"\n**{label}**")
                        
                        st.markdown(processed_text)
                else:
                    st.write("No detailed measurements available.")

            # Tab 3: Swatches and Colors
            with tab3:
                st.write(product.get('Colour & Material', 'No details available.'))
                
                raw_swatches = product.get('Swatch Image URLs', "")
                swatches = [url.strip() for url in raw_swatches.split(",") if url.strip()]
                
                if swatches:
                    st.write("**Available Options:**")
                    # Display swatches side-by-side cleanly
                    swatch_cols = st.columns(min(len(swatches), 8)) 
                    for idx, swatch_url in enumerate(swatches):
                        if idx < 8: # Limit to 8 swatches per row to avoid UI clutter
                            with swatch_cols[idx]:
                                st.image(swatch_url, width=50)

        st.markdown("<br><hr><br>", unsafe_allow_html=True) # Divider