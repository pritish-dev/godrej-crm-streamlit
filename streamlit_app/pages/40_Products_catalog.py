import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ==============================
# CONFIGURATION & CONSTANTS
# ==============================
st.set_page_config(page_title="Product Catalog", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
CATALOG_SHEET_NAME = "Product Catalog"
DISCONTINUED_SHEET_NAME = "Discontinued Products"

# ==============================
# GOOGLE CLIENT (From sheets.py)
# ==============================
@st.cache_resource
def _get_client():
    try:
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
    except Exception:
        creds = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_resource
def _get_spreadsheet():
    return _get_client().open_by_key(SPREADSHEET_ID)

# ==============================
# GET DATA LOGIC
# ==============================
@st.cache_data(ttl=60)
def get_df(sheet_name):
    """Fetches data from a specific sheet and returns a Pandas DataFrame."""
    sh = _get_spreadsheet()
    try:
        ws = sh.worksheet(sheet_name)
    except Exception:
        st.error(f"Sheet '{sheet_name}' not found in Google Sheets.")
        return pd.DataFrame()
        
    data = ws.get_all_values()
    if not data or len(data) < 2:
        return pd.DataFrame()
    return pd.DataFrame(data[1:], columns=data[0])

def load_catalog_data():
    """Formats the raw dataframe into a structured list of dictionaries."""
    df_catalog = get_df(CATALOG_SHEET_NAME)
    df_disc = get_df(DISCONTINUED_SHEET_NAME)
    
    # Create a quick lookup dictionary for discontinued products: {'product name': 'date'}
    discontinued_dict = {}
    if not df_disc.empty and "Product Name" in df_disc.columns and "Discontinued Date" in df_disc.columns:
        for _, row in df_disc.iterrows():
            name = str(row["Product Name"]).strip().lower()
            discontinued_dict[name] = str(row["Discontinued Date"]).strip()

    products = []
    if not df_catalog.empty:
        for _, row in df_catalog.iterrows():
            name = str(row.get("Product Name", "")).strip()
            
            # Assuming specs are separated by a pipe character "|" in the sheet
            raw_specs = str(row.get("Specifications", ""))
            specs = [s.strip() for s in raw_specs.split("|") if s.strip()]
            
            # Assuming image URLs are separated by commas
            raw_images = str(row.get("Image URLs", ""))
            images = [url.strip() for url in raw_images.split(",") if url.strip()]
            
            if name:
                products.append({
                    "name": name,
                    "specs": specs,
                    "images": images,
                    "is_discontinued": name.lower() in discontinued_dict,
                    "discontinued_date": discontinued_dict.get(name.lower(), "")
                })
    return products

# ==============================
# UI RENDERING
# ==============================
st.title("🛋️ Product Catalog")

# Fetch all compiled data
catalog_data = load_catalog_data()

if not catalog_data:
    st.info(f"No products found. Please ensure the '{CATALOG_SHEET_NAME}' tab exists in your Google Sheet and has data.")
else:
    # Search Filter
    search_query = st.text_input("Search products (e.g., 'Sofa', 'Recliner', 'Wardrobe')...", "").lower()
    
    # Filter products based on search
    filtered_products = [p for p in catalog_data if search_query in p['name'].lower()] if search_query else catalog_data
    
    if not filtered_products:
        st.warning("No products found matching your search.")
    
    # Render Products
    for product in filtered_products:
        product_name = product['name']
        
        with st.container():
            st.markdown("---")
            
            # Discontinued Banner
            if product['is_discontinued']:
                st.error(f"🚨 **DISCONTINUED SINCE: {product['discontinued_date']}**")
                
            st.subheader(product_name)
            
            col1, col2 = st.columns([2, 1])
            
            # Column 1: Image Pagination
            with col1:
                images = product['images']
                if images:
                    # Session state to track the current image index for this specific product
                    state_key = f"img_idx_{product_name}"
                    if state_key not in st.session_state:
                        st.session_state[state_key] = 0
    
                    # Navigation Buttons
                    nav_col1, nav_col2, nav_col3 = st.columns([1, 4, 1])
                    
                    with nav_col1:
                        if st.button("◀ Prev", key=f"prev_{product_name}"):
                            st.session_state[state_key] = (st.session_state[state_key] - 1) % len(images)
                            
                    with nav_col3:
                        if st.button("Next ▶", key=f"next_{product_name}"):
                            st.session_state[state_key] = (st.session_state[state_key] + 1) % len(images)
                    
                    # Display current image
                    current_image_idx = st.session_state[state_key]
                    try:
                        st.image(images[current_image_idx], use_container_width=True, caption=f"Image {current_image_idx + 1} of {len(images)}")
                    except Exception as e:
                        st.warning(f"Could not load image. Ensure the URL is publicly accessible. Error: {e}")
                else:
                    st.info("No images available for this product.")
    
            # Column 2: Specifications
            with col2:
                st.markdown("**Specifications:**")
                if product['specs']:
                    for spec in product['specs']:
                        st.markdown(f"- {spec}")
                else:
                    st.write("No specifications listed.")