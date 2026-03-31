import os
import io
import fitz
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# CONFIGURATION
# ==========================================
PDF_FILE_PATH = r"C:\Users\User\Desktop\AI_Business_Agent\b2c_catalog.pdf"
CREDENTIALS_FILE = r"..\..\config\credentials.json"
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
CATALOG_SHEET_NAME = "Product Catalog"
DRIVE_IMAGE_FOLDER_ID = "1PGdL47AQXliSpX9i8MIQz3oeAknxJM8I" 

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def authenticate_google_services():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    sheets_client = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return sheets_client, drive_service

def upload_image_to_drive(drive_service, image_bytes, filename):
    file_metadata = {'name': filename, 'parents': [DRIVE_IMAGE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/png', resumable=True)
    try:
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return f"https://drive.google.com/uc?id={file.get('id')}"
    except Exception as e:
        print(f"Failed to upload {filename}: {e}")
        return ""

def extract_intelligent_layout(page):
    """
    Analyzes the specific visual layout of the Godrej Interio Catalog.
    Uses coordinate math to find Breadcrumbs, Titles, and Features.
    """
    page_dict = page.get_text("dict")
    spans = []
    
    # 1. Flatten all text elements with their coordinates and sizes
    for block in page_dict["blocks"]:
        if block['type'] == 0:  
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    # Filter out obvious header/footer noise
                    if text and "Download PDF" not in text and "interio by godrej" not in text.lower():
                        spans.append({
                            "text": text,
                            "size": span["size"],
                            "y0": span["bbox"][1], # Top Y coordinate
                            "x0": span["bbox"][0]  # Left X coordinate
                        })

    if not spans:
        return None, None, None, None

    # 2. Find Product Name (Largest font size in the top half of the page)
    page_height = page.rect.height
    top_half_spans = [s for s in spans if s["y0"] < (page_height / 2)]
    
    if not top_half_spans:
        return None, None, None, None
        
    max_size = max(s["size"] for s in top_half_spans)
    
    # Group spans that share this max font size (in case title is split)
    title_spans = [s for s in top_half_spans if abs(s["size"] - max_size) < 1.0]
    title_spans.sort(key=lambda s: s["x0"]) # Sort left-to-right
    product_name = " ".join([s["text"] for s in title_spans])
    title_y0 = min(s["y0"] for s in title_spans) # The Y-level of the title

    # 3. Extract Categories (Breadcrumbs placed *above* the Title)
    above_title = [s for s in spans if s["y0"] < (title_y0 - 2)]
    above_title.sort(key=lambda s: s["x0"]) # Sort left-to-right
    
    main_category = above_title[0]["text"] if len(above_title) >= 1 else "Unknown"
    sub_category = above_title[1]["text"] if len(above_title) >= 2 else "Unknown"

    # 4. Extract Features
    features = []
    capture = False
    # Headers that indicate the "Features" section is over
    stop_words = ["Measurements", "Colour & Material", "Proportion", "Details", "In the set", "Fabric"]
    
    # Sort remaining elements top-to-bottom, then left-to-right
    below_title = [s for s in spans if s["y0"] >= title_y0 and s not in title_spans]
    below_title.sort(key=lambda s: (s["y0"], s["x0"]))
    
    for s in below_title:
        txt = s["text"]
        
        # Stop capturing if we hit a new structural header
        if any(stop.lower() in txt.lower() for stop in stop_words):
            capture = False
            
        if capture:
            # Clean up bullet points and ignore tiny design registration numbers
            clean_txt = txt.lstrip("•*- ").strip()
            if clean_txt and s["size"] > 7.0: 
                features.append(clean_txt)
                
        # Start capturing when we see the word "Features"
        if txt.lower() == "features":
            capture = True

    specs = " | ".join(features)
    
    return main_category, sub_category, product_name, specs

def process_pdf_and_upload(drive_service):
    print(f"Opening PDF: {PDF_FILE_PATH}...")
    try:
        doc = fitz.open(PDF_FILE_PATH)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return []

    extracted_products = []

    # Start looking from page 9 (Index 8 in Python)
    for page_num in range(8, len(doc)):
        print(f"Processing Page {page_num + 1}/{len(doc)}...")
        page = doc.load_page(page_num)
        
        # Extract Data
        main_cat, sub_cat, product_name, specs = extract_intelligent_layout(page)
        
        if not product_name or "Unknown" in main_cat:
            continue # Skip pages that don't match product layout
            
        # Extract Images
        image_urls = []
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            image_info = doc.extract_image(xref)
            
            # The layout shows the main product image is massive. 
            # 300x300 ensures we completely ignore color swatches and tiny diagrams.
            if image_info["width"] > 300 and image_info["height"] > 300 and len(image_info["image"]) > 25000:
                safe_name = "".join([c for c in product_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                filename = f"{safe_name.replace(' ', '_')}_img{img_index}.png"
                
                url = upload_image_to_drive(drive_service, image_info["image"], filename)
                if url:
                    image_urls.append(url)
                    
        extracted_products.append([
            main_cat,        # e.g., "Living Room"
            sub_cat,         # e.g., "Sofa"
            product_name,    # e.g., "Nebula V3"
            specs,           # e.g., "Contemporary design... | Adjustable headrest..."
            ",".join(image_urls)
        ])
        
    return extracted_products

def update_google_sheet(sheets_client, products_data):
    print("Updating Google Sheet...")
    sh = sheets_client.open_by_key(SPREADSHEET_ID)
    
    try:
        ws = sh.worksheet(CATALOG_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=CATALOG_SHEET_NAME, rows=1000, cols=10)

    ws.clear()
    
    # Updated Headers
    payload = [["Main Category", "Sub Category", "Product Name", "Specifications", "Image URLs"]] + products_data
    ws.update('A1', payload)
    print(f"Successfully uploaded {len(products_data)} products to Google Sheets!")

def main():
    print("Starting Catalog Synchronization...")
    sheets_client, drive_service = authenticate_google_services()
    products_data = process_pdf_and_upload(drive_service)
    
    if products_data:
        update_google_sheet(sheets_client, products_data)
    else:
        print("No data extracted from PDF. Sheet was not updated.")

if __name__ == "__main__":
    main()