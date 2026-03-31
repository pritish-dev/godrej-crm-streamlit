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
    # 1. Sheets Authentication (Service Account)
    sheets_creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE, 
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    sheets_client = gspread.authorize(sheets_creds)

    # 2. Drive Authentication (Human OAuth)
    drive_creds = None
    token_path = "../../config/token.pickle"
    
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            drive_creds = pickle.load(token)
            
    if not drive_creds or not drive_creds.valid:
        if drive_creds and drive_creds.expired and drive_creds.refresh_token:
            drive_creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, 
                scopes=["https://www.googleapis.com/auth/drive"]
            )
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
        return f"https://drive.google.com/uc?id={file.get('id')}"
    except Exception as e:
        print(f"      [!] Failed to upload {filename}: {e}")
        return ""

def extract_intelligent_layout(page):
    page_dict = page.get_text("dict")
    spans = []
    
    for block in page_dict["blocks"]:
        if block['type'] == 0:  
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text and "Download PDF" not in text and "interio by godrej" not in text.lower():
                        spans.append({
                            "text": text,
                            "size": span["size"],
                            "y0": span["bbox"][1], 
                            "x0": span["bbox"][0]  
                        })

    if not spans:
        return None, None, None, None

    page_height = page.rect.height
    top_half_spans = [s for s in spans if s["y0"] < (page_height / 2)]
    
    if not top_half_spans:
        return None, None, None, None
        
    max_size = max(s["size"] for s in top_half_spans)
    
    title_spans = [s for s in top_half_spans if abs(s["size"] - max_size) < 1.0]
    title_spans.sort(key=lambda s: s["x0"]) 
    product_name = " ".join([s["text"] for s in title_spans])
    title_y0 = min(s["y0"] for s in title_spans) 

    above_title = [s for s in spans if s["y0"] < (title_y0 - 2)]
    above_title.sort(key=lambda s: s["x0"]) 
    
    main_category = above_title[0]["text"] if len(above_title) >= 1 else "Unknown"
    sub_category = above_title[1]["text"] if len(above_title) >= 2 else "Unknown"

    features = []
    capture = False
    stop_words = ["Measurements", "Colour & Material", "Proportion", "Details", "In the set", "Fabric"]
    
    below_title = [s for s in spans if s["y0"] >= title_y0 and s not in title_spans]
    below_title.sort(key=lambda s: (s["y0"], s["x0"]))
    
    for s in below_title:
        txt = s["text"]
        
        if any(stop.lower() in txt.lower() for stop in stop_words):
            capture = False
            
        if capture:
            clean_txt = txt.lstrip("•*- ").strip()
            if clean_txt and s["size"] > 7.0: 
                features.append(clean_txt)
                
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

    # Iterate through the pages
    for page_num in range(8, len(doc)):
        print(f"\nProcessing Page {page_num + 1}/{len(doc)}...")
        page = doc.load_page(page_num)
        
        main_cat, sub_cat, product_name, specs = extract_intelligent_layout(page)
        
        if not product_name or "Unknown" in main_cat:
            print("   -> Skipping: Does not match standard product layout.")
            continue 
            
        print(f"   -> Found Product: {product_name} ({main_cat} > {sub_cat})")
            
        image_urls = []
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            image_info = doc.extract_image(xref)
            
            if image_info["width"] > 300 and image_info["height"] > 300 and len(image_info["image"]) > 25000:
                safe_name = "".join([c for c in product_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                filename = f"{safe_name.replace(' ', '_')}_img{img_index}.png"
                
                url = upload_image_to_drive(drive_service, image_info["image"], filename)
                if url:
                    image_urls.append(url)
                    
        extracted_products.append([
            main_cat,        
            sub_cat,         
            product_name,    
            specs,           
            ",".join(image_urls)
        ])
        
        # Add a tiny delay to prevent Google Drive from temporarily blocking us for uploading too fast
        time.sleep(0.5) 
        
    return extracted_products

def update_google_sheet(sheets_client, products_data):
    print("\n=========================================")
    print("UPDATING GOOGLE SHEET...")
    sh = sheets_client.open_by_key(SPREADSHEET_ID)
    
    try:
        ws = sh.worksheet(CATALOG_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=CATALOG_SHEET_NAME, rows=1000, cols=10)

    # Clear old data
    ws.clear()
    
    # Use append_rows instead of update to bypass gspread version conflicts
    payload = [["Main Category", "Sub Category", "Product Name", "Specifications", "Image URLs"]] + products_data
    ws.append_rows(payload)
    
    print(f"✅ SUCCESSFULLY SAVED {len(products_data)} PRODUCTS TO GOOGLE SHEETS!")
    print("=========================================")

def main():
    print("Starting Catalog Synchronization...")
    sheets_client, drive_service = authenticate_google_services()
    products_data = []
    
    try:
        # Wrap the massive processing task in a try block
        products_data = process_pdf_and_upload(drive_service)
    except Exception as e:
        print(f"\n[!] AN ERROR OCCURRED: {e}")
        print("[!] The script was interrupted, but we will save the data we have collected so far!")
    finally:
        # This ALWAYS runs, even if you press Ctrl+C or Google Drive crashes
        if products_data:
            update_google_sheet(sheets_client, products_data)
        else:
            print("\nNo valid product data was found to save to the sheet.")

if __name__ == "__main__":
    main()