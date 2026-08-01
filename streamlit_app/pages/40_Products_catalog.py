import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ==============================
# CONFIGURATION
# ==============================
st.set_page_config(page_title="Product Catalog", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.sheet_config import OPS_SPREADSHEET_ID as SPREADSHEET_ID
from services.discontinued_email_import import (
    fetch_and_save_discontinued,
    DISCONTINUED_SUBJECT,
)
from services.catalog_pdf_service import fetch_and_sync_catalog_from_drive
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
        
    # Build a list of (normalized_name, discontinued_date) entries.
    # Supports both the legacy schema (Product Name / Discontinued Date) and the
    # new automated import schema (Item Description / DATE OF DISCONTINUATION).
    disc_entries = []
    if not df_disc.empty:
        name_col = next(
            (c for c in ("Product Name", "Item Description") if c in df_disc.columns),
            None,
        )
        date_col = next(
            (c for c in ("Discontinued Date", "DATE OF DISCONTINUATION") if c in df_disc.columns),
            None,
        )
        if name_col:
            for _, row in df_disc.iterrows():
                key = " ".join(str(row[name_col]).strip().lower().split())
                if not key:
                    continue
                date = str(row.get(date_col, "Unknown Date")) if date_col else "Unknown Date"
                disc_entries.append((key, date))

    return df_catalog, disc_entries


def match_discontinued(product_name, disc_entries):
    """Return the discontinuation date if `product_name` is discontinued, else None.

    Catalogue product names are marketing names (e.g. "Nebula V3") while the
    Discontinued Products sheet lists Godrej item descriptions, so an exact
    match is rare. We fall back to a word-safe substring match in either
    direction so a product whose name appears inside a discontinued item's
    description is still flagged.
    """
    key = " ".join(str(product_name or "").strip().lower().split())
    if not key:
        return None
    for name, date in disc_entries:            # exact match first
        if name == key:
            return date
    if len(key) >= 4:                          # substring match (guard tiny names)
        for name, date in disc_entries:
            if name and (key in name or name in key):
                return date
    return None

# ==============================
# MAIN APP
# ==============================
st.title("🛋️ Godrej Interio Catalog")

# --- DISCONTINUED PRODUCTS: manual email check ---
# The 'Discontinued Products' sheet is refreshed automatically every day at
# 11 AM IST from the "Product Discontinuation Circular" email. This button lets
# staff pull the latest circular on demand (looks back over the last 30 days).
_dcol1, _dcol2, _dcol3 = st.columns([3, 3, 4])
with _dcol1:
    check_disc = st.button(
        "🔄 check for Discontinued Products",
        use_container_width=True,
        help=f'Reads the latest "{DISCONTINUED_SUBJECT}" email and updates the '
             f'Discontinued Products sheet.',
    )
with _dcol2:
    run_catalog = st.button(
        "🛠️ Extract products from Catalogue PDFs",
        use_container_width=True,
        help="Reads the catalogue PDFs from the B2C_CATALOGUE Google Drive "
             "folder, extracts each product with AI, and adds new/changed "
             "products to this sheet. Existing rows are preserved.",
    )
with _dcol3:
    _cat_test_pages = st.number_input(
        "Test: pages/catalogue (0 = all)",
        min_value=0, max_value=500, value=0, step=1,
        help="Cap how many pages per catalogue are sent to the AI. Use a small "
             "value (e.g. 2) for a cheap diagnostic run before scanning everything.",
    )

if run_catalog:
    _ph = st.empty()
    _log_lines = []

    def _catalog_progress(msg):
        _log_lines.append(msg)
        _ph.text("\n".join(_log_lines[-14:]))

    with st.spinner(
        "Reading catalogue PDFs and extracting products with AI… "
        "this can take several minutes for large catalogues."
    ):
        try:
            _added, _updated, _cat_status = fetch_and_sync_catalog_from_drive(
                progress=_catalog_progress,
                max_pages=(int(_cat_test_pages) or None),
            )
        except Exception as e:
            import traceback
            _added, _updated, _cat_status = 0, 0, (
                f"❌ Extraction failed: {e}\n\n{traceback.format_exc()}"
            )
    _ph.empty()

    load_all_data.clear()  # bust the 5-min cache so new products show immediately
    _headline = _cat_status.split("\n", 1)[0]
    (st.success if _cat_status.startswith("✅") else st.warning)(_headline)

    # Always surface the full per-page log so a billed-but-empty run is debuggable
    # instead of silently reporting "nothing happened".
    with st.expander(
        "🔎 Extraction log / diagnostics",
        expanded=not _cat_status.startswith("✅"),
    ):
        st.code(_cat_status or "(no output)")
    with st.expander("Extraction details"):
        st.text(_cat_status)

if check_disc:
    with st.spinner("Checking Gmail for the latest Product Discontinuation Circular…"):
        try:
            _df, _status = fetch_and_save_discontinued(today_only=False)
        except Exception as e:
            _df, _status = None, f"❌ Check failed: {e}"
    if _df is not None and not _df.empty:
        load_all_data.clear()   # bust the 5-min cache so the update shows immediately
        st.success(_status)
    else:
        st.warning(_status)

df_catalog, disc_entries = load_all_data()

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

# Slice the dataframe for the current page.
start_idx = st.session_state.page_num * ITEMS_PER_PAGE
end_idx = start_idx + ITEMS_PER_PAGE
page_df = filtered_df.iloc[start_idx:end_idx]

# --- RENDER PRODUCTS ---
for _, product in page_df.iterrows():
    p_name = product.get('Product Name', 'Unknown Product')
    disc_date = match_discontinued(p_name, disc_entries)
    is_discontinued = disc_date is not None

    with st.container():
        # Discontinued Marquee Alert
        if is_discontinued:
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
                
            # Tab 2: Measurements (Enhanced Consistency Fix)
            with tab2:
                measurements_raw = str(product.get('Measurements', '')).strip()
                
                if measurements_raw:
                    # 1. Standard Table Logic (If multiple pipes exist)
                    if "|" in measurements_raw:
                        lines = [line.strip() for line in measurements_raw.split('\n') if line.strip()]
                        
                        # Check if this is a complex string (like Broadway V2) or a proper table
                        # If there's only one line of text but many pipes, it's a "Linear Pipe Line"
                        if len(lines) == 1:
                            # Split the single line into segments and display as a vertical list
                            segments = [s.strip() for s in measurements_raw.split('|') if s.strip()]
                            for seg in segments:
                                st.markdown(f"🔹 {seg}")
                        else:
                            # Proper Table Logic
                            try:
                                headers = [h.strip() for h in lines[0].split('|')]
                                rows = [[cell.strip() for cell in line.split('|')] for line in lines[1:]]
                                max_cols = len(headers)
                                padded_rows = [r + ['']*(max_cols - len(r)) for r in rows]
                                
                                df_meas = pd.DataFrame(padded_rows, columns=headers)
                                st.dataframe(df_meas, hide_index=True, use_container_width=True)
                            except:
                                st.write(measurements_raw) # Safety fallback
                    
                    # 2. Linear Sentence Logic (No pipes)
                    else:
                        # Split by common keywords to force verticality
                        for label in ["Width:", "Depth:", "Height:", "Seat Height:", "1 Seater:", "2 Seater:", "3 Seater:"]:
                            measurements_raw = measurements_raw.replace(label, f"\n\n**{label}**")
                        st.markdown(measurements_raw)
                else:
                    st.info("No detailed measurements available.")

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