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
        # FIX 1: Use the Thumbnail API for Streamlit compatibility
        return f"https://drive.google.com/thumbnail?id={file.get('id')}&sz=w1000"
    except Exception as e:
        print(f"      [!] Failed to upload {filename}: {e}")
        return ""

def process_page_half(page, min_x, max_x, drive_service, doc):
    """Processes only a specific vertical half of the PDF page."""
    page_dict = page.get_text("dict")
    spans = []
    
    # 1. Grab Title & Breadcrumbs within this half
    for block in page_dict["blocks"]:
        if block['type'] == 0:  
            for line in block["lines"]:
                for span in line["spans"]:
                    # ONLY look at text inside our current half (Left or Right)
                    if min_x <= span["bbox"][0] < max_x:
                        text = span["text"].strip()
                        if text and "Download PDF" not in text and "interio by godrej" not in text.lower():
                            spans.append({
                                "text": text, "size": span["size"],
                                "y0": span["bbox"][1], "x0": span["bbox"][0]  
                            })

    if not spans: return None

    page_height = page.rect.height
    top_half_spans = [s for s in spans if s["y0"] < (page_height / 2)]
    if not top_half_spans: return None
        
    max_size = max(s["size"] for s in top_half_spans)
    title_spans = [s for s in top_half_spans if abs(s["size"] - max_size) < 1.0]
    title_spans.sort(key=lambda s: s["x0"]) 
    product_name = " ".join([s["text"] for s in title_spans])
    title_y0 = min(s["y0"] for s in title_spans) 

    above_title = [s for s in spans if s["y0"] < (title_y0 - 2)]
    above_title.sort(key=lambda s: s["x0"]) 
    main_category = above_title[0]["text"] if len(above_title) >= 1 else "Unknown"
    sub_category = above_title[1]["text"] if len(above_title) >= 2 else "Unknown"

    if "Unknown" in main_category: return None

    # 2. Grab Features using Paragraph BLOCKS (Fixes Fragmented Sentences)
    features = []
    capture = False
    stop_words = ["Measurements", "Colour & Material", "Proportion", "Details", "In the set", "Fabric", "Standard"]
    
    blocks = page.get_text("blocks")
    # Get blocks in this half, sorted top-to-bottom
    area_blocks = [b for b in blocks if b[6] == 0 and min_x <= b[0] < max_x and b[1] >= title_y0]
    area_blocks.sort(key=lambda b: (b[1], b[0]))
    
    for b in area_blocks:
        block_text = b[4].strip()
        
        if any(stop.lower() in block_text.lower() for stop in stop_words):
            capture = False
            
        if capture:
            # Replace physical line breaks with spaces to reconstruct the sentence
            clean_text = block_text.replace('\n', ' ').strip()
            
            # Split multiple bullets if they share the same block
            if '•' in clean_text:
                bullets = clean_text.split('•')
                for bullet in bullets:
                    if bullet.strip(): features.append(bullet.strip())
            else:
                if clean_text: features.append(clean_text.lstrip("*- ").strip())
                
        if block_text.lower() == "features":
            capture = True

    specs = " | ".join(features)

    # 3. Grab Images within this half
    image_urls = []
    for img_info in page.get_image_info(xrefs=True):
        img_bbox = img_info["bbox"]
        
        # Check if the image starts in this half of the page
        if min_x <= img_bbox[0] < max_x:
            xref = img_info.get("xref")
            if not xref:
                continue
            try:
                base_image = doc.extract_image(xref)
                if base_image["width"] > 300 and base_image["height"] > 300 and len(base_image["image"]) > 25000:
                    safe_name = "".join([c for c in product_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                    filename = f"{safe_name.replace(' ', '_')}_img{xref}.png"
                    
                    print(f"      Uploading image for {product_name}...")
                    url = upload_image_to_drive(drive_service, base_image["image"], filename)
                    if url: image_urls.append(url)
            except Exception:
                pass

    return [main_category, sub_category, product_name, specs, ",".join(image_urls)]


def live_process_and_upload(sheets_client, drive_service):
    print("\n=========================================")
    print("PREPARING GOOGLE SHEET...")
    sh = sheets_client.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(CATALOG_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=CATALOG_SHEET_NAME, rows=1000, cols=10)

    ws.clear()
    ws.append_row(["Main Category", "Sub Category", "Product Name", "Specifications", "Image URLs"])
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
            
            # FIX 3: Slice the page in half to process 2-page spreads
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