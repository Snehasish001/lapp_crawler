import requests
import re
import easyocr
import os
from bs4 import BeautifulSoup
from io import BytesIO
from PIL import Image
from datetime import datetime, timezone, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================= CONFIGURATION =================

# Scheduled hours for Nagaland (IST 24-hour format)
SLOT_CONFIG = {
    "mor": {"url": "https://lotterysambad.one/nagaland-state-lottery-result-1-pm/", "hour": 13},  # 1 PM
    "day": {"url": "https://lotterysambad.one/nagaland-state-lottery-result-6-00-pm/", "hour": 18}, # 6 PM
    "evn": {"url": "https://lotterysambad.one/nagaland-state-lottery-result-8-00-pm/", "hour": 20}, # 8 PM
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"}

# APIs
API_DEAR = "https://supervillain.pythonanywhere.com/api/dear/"
API_FAX = "https://supervillain.pythonanywhere.com/api/fax/"
API_GET_STATE = f"{API_DEAR}last-three-digit/"

# Initialize OCR
reader = easyocr.Reader(['en'], gpu=False)

# ================= CORE FUNCTIONS =================

def get_now_ist():
    """Returns current IST time (UTC+5:30)"""
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def create_session():
    """Creates a requests session with retry logic"""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(HEADERS)
    return session

def api_get_today_state(session, today):
    """Searches the API list for the dictionary matching today's date"""
    try:
        print(f"[DEBUG] Searching DB for exact date: {today}")
        
        r = session.get(API_GET_STATE, params={"date": today}, timeout=10)
        r.raise_for_status()
        data = r.json()

        # If the API returns a list, find the one matching 'today'
        if isinstance(data, list):
            for entry in data:
                if entry.get("date") == today:
                    print(f"[DEBUG] Success! Found today's record: {entry}")
                    return entry
            
            # If we looped through everything and didn't find the date
            print(f"[DEBUG] Date {today} not found in the list. Starting fresh.")
            return {"date": today, "mor": "-", "day": "-", "evn": "-"}
        
        # If it's just a single dictionary
        return data

    except Exception as e:
        print(f"[ERROR] API check failed: {e}")
        return {"date": today, "mor": "-", "day": "-", "evn": "-"}

def extract_digits(image_bytes):
    """Uses EasyOCR to find the 5-digit 1st prize number"""
    results = reader.readtext(image_bytes, detail=0)
    full_text = " ".join(results)
    match = re.search(r'\d{5}', full_text)
    if not match:
        raise ValueError(f"1st Prize not detected. OCR saw: {full_text[:50]}")
    num = match.group(0)
    return {"l1": num[-1], "l2": num[-2:], "l3": num[-3:]}

def post_data(today, slot, digits, image_bytes):
    """Uploads digits and the compressed image to the APIs"""
    # 1. Post to Digit APIs
    endpoints = ["last-digit", "last-two-digit", "last-three-digit"]
    vals = [digits["l1"], digits["l2"], digits["l3"]]
    
    for ep, val in zip(endpoints, vals):
        payload = {"date": today, "mor": "-", "day": "-", "evn": "-"}
        payload[slot] = val
        requests.post(f"{API_DEAR}{ep}/", json=payload, timeout=10)

    # 2. Compress and Post Image
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", optimize=True, quality=60)
    
    files = {"image": ("result.jpg", buf.getvalue(), "image/jpeg")}
    data = {"type": "dear", "date": today, "time": slot}
    requests.post(API_FAX, files=files, data=data, timeout=15)

# ================= LOGIC ENGINE =================

def get_needed_slots(db):
    """Cumulative Logic: Finds missing slots based on current IST hour"""
    now = get_now_ist()
    hour = now.hour
    needed = []

    # Check Morning (Available after 1 PM)
    if hour >= 13 and db.get("mor") == "-":
        needed.append("mor")
    # Check Day (Available after 6 PM)
    if hour >= 18 and db.get("day") == "-":
        needed.append("day")
    # Check Evening (Available after 8 PM)
    if hour >= 20 and db.get("evn") == "-":
        needed.append("evn")

    return needed

def main():
    session = create_session()
    ist_now = get_now_ist()
    today_str = ist_now.strftime("%Y-%m-%d")
    
    print(f"🕒 Current Time: {ist_now.strftime('%Y-%m-%d %I:%M %p')} IST")

    # Step 1: Check DB status
    db = api_get_today_state(session, today_str)
    
    # Step 2: Determine which slots to crawl
    needed = get_needed_slots(db)

    if not needed:
        print("✅ No new slots to process right now.")
        return

    print(f"🚀 Found slots to process: {needed}")

    for slot in needed:
        try:
            print(f"🔍 Fetching {slot} from {SLOT_CONFIG[slot]['url']}")
            resp = session.get(SLOT_CONFIG[slot]["url"], timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            img_tag = soup.find("img", {"fetchpriority": "high", "class": re.compile(r'aligncenter')})
            if not img_tag:
                print(f"⚠️ No result image found for {slot}")
                continue
            
            img_url = img_tag.get("src")

            # Date Gate: Ensure the URL folder matches /2026/01/
            date_path = ist_now.strftime("/%Y/%m/")
            if date_path not in img_url:
                print(f"⏭️ Skipping {slot}: URL shows old result date ({img_url})")
                continue

            img_data = session.get(img_url, timeout=20).content
            digits = extract_digits(img_data)
            
            post_data(today_str, slot, digits, img_data)
            print(f"✔️ {slot} processed and uploaded successfully.")

        except Exception as e:
            print(f"❌ Error during {slot}: {e}")

if __name__ == "__main__":
    main()