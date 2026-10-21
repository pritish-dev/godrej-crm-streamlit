import json
import os
import sys

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ==============================
# CONFIGURATION
# ==============================
st.set_page_config(page_title="Product Catalog", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.sheet_config import OPS_SPREADSHEET_ID as SPREADSHEET_ID
from services.discontinued_email_import import (
    fetch_and_save_discontinued,
    DISCONTINUED_SUBJECT,
)
DISCONTINUED_SHEET_NAME = "Discontinued Products"
ITEMS_PER_PAGE = 12
GRID_COLUMNS = 3

# The catalogue comes from the "Visualise" section of the InterioFinder HTML
# export, converted to local files by tools/import_visualise_catalog.py.
CATALOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "visualise_catalog",
)
CATALOG_FILE = os.path.join(CATALOG_DIR, "catalog.json")
IMAGE_DIR = os.path.join(CATALOG_DIR, "images")

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

@st.cache_data
def load_catalog():
    """Return (products, source file name) from the local Visualise catalogue."""
    try:
        with open(CATALOG_FILE, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return [], ""
    return payload.get("products", []), payload.get("source", "")

@st.cache_data(ttl=300) # Cache for 5 minutes
def load_discontinued():
    try:
        ws_disc = _get_client().open_by_key(SPREADSHEET_ID).worksheet(DISCONTINUED_SHEET_NAME)
        disc_data = ws_disc.get_all_values()
        df_disc = pd.DataFrame(disc_data[1:], columns=disc_data[0]) if len(disc_data) > 1 else pd.DataFrame()
    except Exception:
        df_disc = pd.DataFrame()

    # Build a list of (normalized_name, discontinued_date) entries plus an
    # {item_code: discontinued_date} map.
    # Supports both the legacy schema (Product Name / Discontinued Date) and the
    # new automated import schema (Item Code / Item Description / DATE OF DISCONTINUATION).
    disc_entries = []
    disc_codes = {}
    if not df_disc.empty:
        name_col = next(
            (c for c in ("Product Name", "Item Description") if c in df_disc.columns),
            None,
        )
        date_col = next(
            (c for c in ("Discontinued Date", "DATE OF DISCONTINUATION") if c in df_disc.columns),
            None,
        )
        code_col = "Item Code" if "Item Code" in df_disc.columns else None
        for _, row in df_disc.iterrows():
            date = str(row.get(date_col, "Unknown Date")) if date_col else "Unknown Date"
            date = date.strip() or "Unknown Date"
            if code_col:
                code = _norm_code(row[code_col])
                if code:
                    disc_codes[code] = date
            if name_col:
                key = " ".join(str(row[name_col]).strip().lower().split())
                if key:
                    disc_entries.append((key, date))

    return disc_entries, disc_codes


def _norm_code(code):
    return "".join(str(code or "").split()).upper()


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


def item_discontinued(item, disc_codes):
    """Discontinuation date for one price-list item (matched on item code)."""
    for code in (item.get("code"), item.get("ln_code")):
        date = disc_codes.get(_norm_code(code))
        if date:
            return date
    return None


def discontinued_status(product, disc_entries, disc_codes):
    """Return (product_disc_date, {item_code: date}) for a catalogue product.

    The whole product is discontinued when its name matches the Discontinued
    Products sheet, or when every item code linked to it is discontinued.
    Individual discontinued item codes are reported either way.
    """
    items = [it for g in product.get("prices", []) for it in g["items"]]
    disc_items = {}
    for it in items:
        date = item_discontinued(it, disc_codes)
        if date:
            disc_items[it["code"]] = date
    date = match_discontinued(product["name"], disc_entries)
    if date is None and items and len(disc_items) == len(items):
        date = next(iter(disc_items.values()))
    return date, disc_items

# ==============================
# FORMATTING HELPERS
# ==============================
def _num(v):
    return f"{v:g}"

def _cm(a):
    return "–".join(_num(v) for v in a[:2])

def _ft(a, add):
    return "–".join(_num(round(v / 30.48 + add + 1e-9, 1)) for v in a[:2])

def size_lines(product):
    """Size rows as 'Name: W × D × H cm · ft', matching the InterioFinder view."""
    sofa = any(w in product.get("subcategory", "").lower() for w in ("sofa", "recliner"))
    ft_add = 0.2 if sofa else 0.0           # field measurement correction for sofas
    w_add = 0.0 if sofa else 0.1            # +0.1 ft on widths only (non-sofa)
    out = []
    for g in product.get("sizes", []):
        if g.get("r"):
            h, o = g["r"].get("h") or [], g["r"].get("o") or []
            cm = " · ".join(filter(None, [
                ("W/D " + " / ".join(_cm(a) for a in o)) if o else "",
                ("H " + " / ".join(_cm(a) for a in h)) if h else "",
            ]))
            ft = " · ".join(filter(None, [
                ("W/D " + " / ".join(_ft(a, ft_add + w_add) for a in o)) if o else "",
                ("H " + " / ".join(_ft(a, ft_add) for a in h)) if h else "",
            ]))
        else:
            dims = [("W", "w", w_add), ("D", "d", 0.0), ("H", "h", 0.0)]
            cm = " × ".join(f"{lbl} {_cm(g[k])}" for lbl, k, _ in dims if g.get(k))
            ft = " × ".join(f"{lbl} {_ft(g[k], ft_add + extra)}" for lbl, k, extra in dims if g.get(k))
        if not cm:
            continue
        label = f"**{g['n']}:** " if g.get("n") else ""
        out.append(f"{label}{cm} cm · {ft} ft")
    return out

def fmt_price(v):
    if v is None or v == "":
        return "—"
    v = int(round(float(v)))
    s = str(v)
    if len(s) > 3:                            # Indian digit grouping
        head, tail = s[:-3], s[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = f"{head},{tail}"
    return f"₹{s}"

def price_range(items):
    p = [it["price"] for it in items if it.get("price") is not None]
    if not p:
        return ""
    lo, hi = min(p), max(p)
    return fmt_price(lo) if lo == hi else f"{fmt_price(lo)} – {fmt_price(hi)}"

# ==============================
# MAIN APP
# ==============================
st.title("🛋️ Godrej Interio Catalog")

# --- DISCONTINUED PRODUCTS: manual email check ---
# The 'Discontinued Products' sheet is refreshed automatically every day at
# 11 AM IST from the "Product Discontinuation Circular" email. This button lets
# staff pull the latest circular on demand (looks back over the last 30 days).
_dcol1, _dcol2 = st.columns([3, 7])
with _dcol1:
    check_disc = st.button(
        "🔄 check for Discontinued Products",
        use_container_width=True,
        help=f'Reads the latest "{DISCONTINUED_SUBJECT}" email and updates the '
             f'Discontinued Products sheet.',
    )

if check_disc:
    with st.spinner("Checking Gmail for the latest Product Discontinuation Circular…"):
        try:
            _df, _status = fetch_and_save_discontinued(today_only=False)
        except Exception as e:
            _df, _status = None, f"❌ Check failed: {e}"
    if _df is not None and not _df.empty:
        load_discontinued.clear()   # bust the 5-min cache so the update shows immediately
        st.success(_status)
    else:
        st.warning(_status)

products, catalog_source = load_catalog()
disc_entries, disc_codes = load_discontinued()

if not products:
    st.warning(
        "Catalog is empty or could not be loaded. Run "
        "`python streamlit_app/tools/import_visualise_catalog.py <InterioFinder.html>`."
    )
    st.stop()

if catalog_source:
    st.caption(f"Source: {catalog_source} · Visualise section · {len(products)} products")

# --- FILTERS ---
rooms = sorted({p["room"] for p in products if p["room"]})
f1, f2, f3 = st.columns([2, 2, 4])
with f1:
    room = st.selectbox("Room", ["All"] + rooms)
with f2:
    subs = sorted({p["subcategory"] for p in products
                   if p["subcategory"] and (room == "All" or p["room"] == room)})
    sub = st.selectbox("Sub Category", ["All"] + subs)
with f3:
    search_query = st.text_input("🔍 Search by Product Name, Room, Sub Category or Item Code", "").strip().lower()
only_disc = st.checkbox("Show only discontinued products", value=False)

# Reset pagination to page 0 whenever a filter changes
_filter_key = (room, sub, search_query, only_disc)
if st.session_state.get("last_catalog_filter") != _filter_key:
    st.session_state.page_num = 0
    st.session_state.last_catalog_filter = _filter_key

def _matches(p):
    if room != "All" and p["room"] != room:
        return False
    if sub != "All" and p["subcategory"] != sub:
        return False
    if not search_query:
        return True
    hay = " ".join([p["name"], p["room"], p["subcategory"]] +
                   [f"{it['code']} {it['ln_code']} {it['name']}"
                    for g in p["prices"] for it in g["items"]]).lower()
    return search_query in hay

filtered = []
for p in products:
    if not _matches(p):
        continue
    disc_date, disc_items = discontinued_status(p, disc_entries, disc_codes)
    if only_disc and not (disc_date or disc_items):
        continue
    filtered.append((p, disc_date, disc_items))

# --- NO RESULTS FALLBACK (Instant Text) ---
if not filtered:
    st.error(f"No matches found for '{search_query}'." if search_query else "No products match these filters.")
    st.info("💡 Tip: Try checking your spelling or using a broader search term (e.g., 'Sofa' instead of 'Nebula Sofa').")
    st.stop()

# --- PAGINATION LOGIC ---
total_items = len(filtered)
total_pages = (total_items - 1) // ITEMS_PER_PAGE + 1

if "page_num" not in st.session_state:
    st.session_state.page_num = 0
st.session_state.page_num = min(st.session_state.page_num, total_pages - 1)

def _pagination(pos):
    col1, col2, col3 = st.columns([1, 8, 1])
    with col1:
        if st.button("◀ Prev", key=f"prev_{pos}", disabled=(st.session_state.page_num == 0)):
            st.session_state.page_num -= 1
            st.rerun()
    with col2:
        st.markdown(f"<div style='text-align: center; padding-top: 5px;'>Showing Page <b>{st.session_state.page_num + 1}</b> of {total_pages} ({total_items} total products)</div>", unsafe_allow_html=True)
    with col3:
        if st.button("Next ▶", key=f"next_{pos}", disabled=(st.session_state.page_num >= total_pages - 1)):
            st.session_state.page_num += 1
            st.rerun()

_pagination("top")
st.markdown("---")

start_idx = st.session_state.page_num * ITEMS_PER_PAGE
page_items = filtered[start_idx:start_idx + ITEMS_PER_PAGE]

# --- RENDER PRODUCTS ---
def render_product(product, disc_date, disc_items):
    p_name = product["name"]

    # Discontinued Marquee Alert
    if disc_date:
        st.markdown(
            f"""
            <marquee style="color: white; background-color: #d9534f; padding: 5px; font-weight: bold; border-radius: 4px;">
            🚨 THIS PRODUCT HAS BEEN DISCONTINUED SINCE {str(disc_date).upper()} 🚨
            </marquee>
            """,
            unsafe_allow_html=True
        )

    img = os.path.join(IMAGE_DIR, product["image"]) if product.get("image") else ""
    if img and os.path.exists(img):
        st.image(img, use_container_width=True)
    else:
        st.info("No product image available.")

    # Breadcrumbs & Title
    st.caption(f"{product['room']} > {product['subcategory']}")
    st.markdown(f"#### {p_name}")

    # Discontinued Sub-label
    if disc_date:
        st.markdown("<h5 style='color: #d9534f; margin-top: -10px;'><b>DISCONTINUED</b></h5>", unsafe_allow_html=True)
    elif disc_items:
        st.markdown(
            f"<div style='color: #d9534f; font-weight: bold;'>⚠️ {len(disc_items)} item code(s) "
            f"DISCONTINUED — see Price & Item Codes</div>",
            unsafe_allow_html=True,
        )

    sizes = size_lines(product)
    for line in sizes[:2]:
        st.markdown(f"<small>{line}</small>", unsafe_allow_html=True)
    if len(sizes) > 2:
        st.caption(f"+{len(sizes) - 2} more size(s)")

    with st.expander("Key points, sizes & price"):
        tab1, tab2, tab3 = st.tabs(["Key Points", "Measurements", "Price & Item Codes"])

        with tab1:
            fab = product.get("fab") or []
            if len(fab) == 3:
                for lbl, text in zip(("Feature", "Advantage", "Benefit"), fab):
                    st.markdown(f"**{lbl}:** {text}")
            elif fab:
                st.markdown("\n".join(f"- {t}" for t in fab))
            else:
                st.info("No key points listed.")

        with tab2:
            if sizes:
                st.markdown("\n\n".join(f"🔹 {line}" for line in sizes))
                st.caption("W = width, D = depth, H = height.")
            else:
                st.info("No detailed measurements available.")
            if product.get("page"):
                st.caption(f"Catalogue page {product['page']}")

        with tab3:
            groups = product.get("prices") or []
            if not groups:
                st.info("No linked price list items for this product.")
            for g in groups:
                st.markdown(f"**{g['label']}** — {price_range(g['items'])}")
                rows = []
                for it in g["items"]:
                    d = disc_items.get(it["code"])
                    rows.append({
                        "Item Code": it["code"],
                        "Description": it["name"],
                        "MRP": fmt_price(it["price"]),
                        "Status": f"❌ DISCONTINUED ({d})" if d else (it.get("status") or "Active"),
                    })
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

for row_start in range(0, len(page_items), GRID_COLUMNS):
    cols = st.columns(GRID_COLUMNS)
    for col, (product, disc_date, disc_items) in zip(cols, page_items[row_start:row_start + GRID_COLUMNS]):
        with col:
            with st.container(border=True):
                render_product(product, disc_date, disc_items)

st.markdown("---")
_pagination("bottom")
