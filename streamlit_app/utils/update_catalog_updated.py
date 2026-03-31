import os
import io
import fitz  # PyMuPDF
import gspread
import pickle
import time
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# CONFIGURATION
# ==========================================
PDF_FILE_PATH = r"C:\Users\User\Desktop\AI_Business_Agent\b2c_catalog.pdf" 
CREDENTIALS_FILE = "../../config/credentials.json"
CLIENT_SECRET_FILE = "../../config/client_secret.json" 
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
CATALOG_SHEET_NAME = "Product Catalog"
DRIVE_IMAGE_FOLDER_ID = "1PGdL47AQXliSpX9i8MIQz3oeAknxJM8I" 

def authenticate_google_services():
    sheets_creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheets_client = gspread.authorize(sheets_creds)

    drive_creds = None
    token_path = "../../config/token.pickle"
    
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            drive_creds = pickle.load(token)
            
    if not drive_creds or not drive_creds.valid:
        if drive_creds and drive_creds.expired and drive_creds.refresh_token:
            drive_creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, scopes=["https://www.googleapis.com/auth/drive"])
            drive_creds = flow.run_local_server(port=0)
        with open(token_path, 'wb') as token:
            pickle.dump(drive_creds, token)

    drive_service = build('drive', 'v3', credentials=drive_creds)
    return sheets_client, drive_service

def upload_image_to_drive(drive_service, image_bytes, filename):
    file_metadata = {'name': filename, 'parents': [DRIVE_IMAGE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/png', resumable=True)
    try:
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return f"https://drive.google.com/thumbnail?id={file.get('id')}&sz=w1000"
    except Exception as e:
        print(f"      [!] Failed to upload {filename}: {e}")
        return ""

def process_page_half(page, min_x, max_x, drive_service, doc):
    page_dict = page.get_text("dict")
    half_spans = []
    
    # 1. Grab all text elements strictly inside this half of the page
    for block in page_dict["blocks"]:
        if block['type'] == 0:  
            for line in block["lines"]:
                for span in line["spans"]:
                    span_center_x = (span["bbox"][0] + span["bbox"][2]) / 2
                    if min_x <= span_center_x < max_x:
                        text = span["text"].strip()
                        if text and "Download PDF" not in text and "interio by godrej" not in text.lower():
                            half_spans.append({
                                "text": text, "size": span["size"],
                                "y0": span["bbox"][1], "x0": span["bbox"][0]  
                            })

    if not half_spans: return None

    # 2. Extract Title & Breadcrumbs
    page_height = page.rect.height
    top_half_spans = [s for s in half_spans if s["y0"] < (page_height / 3)]
    if not top_half_spans: return None
        
    max_size = max(s["size"] for s in top_half_spans)
    title_spans = [s for s in top_half_spans if abs(s["size"] - max_size) < 1.0]
    title_spans.sort(key=lambda s: s["x0"]) 
    product_name = " ".join([s["text"] for s in title_spans])
    title_y0 = min(s["y0"] for s in title_spans) 

    above_title = [s for s in half_spans if s["y0"] < (title_y0 - 2)]
    above_title.sort(key=lambda s: s["x0"]) 
    main_category = above_title[0]["text"] if len(above_title) >= 1 else "Unknown"
    sub_category = above_title[1]["text"] if len(above_title) >= 2 else "Unknown"

    if "Unknown" in main_category: return None

    # 3. Extract Features, Measurements, and Colors using Y-Coordinate Line Matching
    below_title_spans = [s for s in half_spans if s["y0"] >= title_y0 and s not in title_spans]
    below_title_spans.sort(key=lambda s: (s["y0"], s["x0"]))
    
    # Group text spans into perfectly horizontal lines (Crucial for tables)
    lines = []
    current_line = []
    current_y = None
    
    for s in below_title_spans:
        if current_y is None:
            current_y = s["y0"]
            current_line.append(s)
        elif abs(s["y0"] - current_y) < 6: # 6 pixels tolerance for being on the same line
            current_line.append(s)
        else:
            current_line.sort(key=lambda x: x["x0"])
            lines.append(current_line)
            current_y = s["y0"]
            current_line = [s]
            
    if current_line:
        current_line.sort(key=lambda x: x["x0"])
        lines.append(current_line)

    capture_mode = None
    features, measurements, colors = [], [], []

    for line_spans in lines:
        raw_texts = [s["text"].strip() for s in line_spans if s["text"].strip()]
        if not raw_texts: continue
        
        text_spaced = " ".join(raw_texts)
        text_lower = text_spaced.lower()
        
        # Switch State Machine gears
        if "features" in text_lower and len(text_spaced) < 15:
            capture_mode = "features"
            continue
        elif "measurements" in text_lower and len(text_spaced) < 20:
            capture_mode = "measurements"
            continue
        elif ("colour & material" in text_lower or "colour" in text_lower) and len(text_spaced) < 25:
            capture_mode = "colors"
            continue
        elif text_lower in ["details", "proportion", "in the set", "design registration"]:
            capture_mode = None 
            continue
            
        # Capture Data
        if capture_mode == "features":
            clean = text_spaced.lstrip("•*- ").strip()
            if clean: features.append(f"✨ {clean}")
                
        elif capture_mode == "measurements":
            # For measurements, we join the columns with a pipe (|) so the CRM can easily split them into a table!
            measurements.append(" | ".join(raw_texts))
                
        elif capture_mode == "colors":
            colors.append(text_spaced)

    specs_str = "\n".join(features)
    measurements_str = "\n".join(measurements)
    colors_str = "\n".join(colors)

    # 4. Grab Images & Sort by Size (Product vs Swatch)
    product_images = []
    swatch_images = []
    
    for img_info in page.get_image_info(xrefs=True):
        img_bbox = img_info["bbox"]
        img_center_x = (img_bbox[0] + img_bbox[2]) / 2
        
        if min_x <= img_center_x < max_x:
            if img_bbox[1] < (title_y0 - 20): # Ignore logos at the very top
                continue
                
            xref = img_info.get("xref")
            if not xref: continue
            
            try:
                base_image = doc.extract_image(xref)
                w, h = base_image["width"], base_image["height"]
                img_bytes = base_image["image"]
                
                safe_name = "".join([c for c in product_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                
                # LARGE IMAGES -> Product Gallery
                if w > 300 and h > 300 and len(img_bytes) > 20000:
                    print(f"      Uploading Product Image ({w}x{h}) for {product_name}...")
                    url = upload_image_to_drive(drive_service, img_bytes, f"{safe_name.replace(' ', '_')}_main_{xref}.png")
                    if url: product_images.append(url)
                
                # SMALL IMAGES -> Swatches / Materials
                elif w > 40 and h > 40 and len(img_bytes) > 2000:
                    print(f"      Uploading Swatch Image ({w}x{h}) for {product_name}...")
                    url = upload_image_to_drive(drive_service, img_bytes, f"{safe_name.replace(' ', '_')}_swatch_{xref}.png")
                    if url: swatch_images.append(url)
                    
            except Exception:
                pass

    return [
        main_category, sub_category, product_name, 
        specs_str, measurements_str, colors_str, 
        ",".join(product_images), ",".join(swatch_images)
    ]

def live_process_and_upload(sheets_client, drive_service):
    print("\n=========================================")
    print("PREPARING GOOGLE SHEET...")
    sh = sheets_client.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(CATALOG_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=CATALOG_SHEET_NAME, rows=1000, cols=10)

    ws.clear()
    ws.append_row([
        "Main Category", "Sub Category", "Product Name", 
        "Specifications", "Measurements", "Colour & Material", 
        "Product Image URLs", "Swatch Image URLs"
    ])
    print("✅ Sheet is ready for Live Sync!")
    print("=========================================\n")

    print(f"Opening PDF: {PDF_FILE_PATH}...")
    try:
        doc = fitz.open(PDF_FILE_PATH)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return

    try:
        for page_num in range(8, len(doc)):
            print(f"\nProcessing Page {page_num + 1}/{len(doc)}...")
            page = doc.load_page(page_num)
            
            page_width = page.rect.width
            mid_x = page_width / 2
            
            # Process Left Side
            left_product = process_page_half(page, 0, mid_x, drive_service, doc)
            if left_product:
                ws.append_row(left_product)
                print(f"   ✅ Saved Left Product: '{left_product[2]}'")
                
            # Process Right Side
            right_product = process_page_half(page, mid_x, page_width, drive_service, doc)
            if right_product:
                ws.append_row(right_product)
                print(f"   ✅ Saved Right Product: '{right_product[2]}'")
            
            time.sleep(1) # API Safety
            
    except KeyboardInterrupt:
        print("\n\n[!] Script stopped manually. Data saved.")

def main():
    print("Starting Catalog Synchronization...")
    sheets_client, drive_service = authenticate_google_services()
    live_process_and_upload(sheets_client, drive_service)
    print("\n🎉 Synchronization Complete!")

if __name__ == "__main__":
    main()