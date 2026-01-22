import requests
import random
from datetime import datetime, timezone, timedelta

# ================= CONFIG =================
API_URL = "https://supervillain.pythonanywhere.com/api/luckyNumber/"
TYPES = ["singapore", "dear"]

def get_now_ist():
    """Returns current IST time (UTC+5:30)"""
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def generate_lucky_string():
    """Generates 4 random digits as requested: '9, 8, 0, 7'"""
    digits = [str(random.randint(0, 9)) for _ in range(4)]
    return ", ".join(digits)

def check_if_exists(lotto_type, today_str):
    """
    Calls your GET logic to check if data already exists.
    Expected Response: status 200 and data['lucky'] != ""
    """
    try:
        params = {"type": lotto_type, "date": today_str}
        response = requests.get(API_URL, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            # If 'lucky' contains data, it means it already exists
            if data.get("lucky") and data.get("lucky") != "":
                return True
        return False
    except Exception as e:
        print(f"⚠️ [WARN] Could not verify existence for {lotto_type}: {e}")
        return False

def update_numbers():
    ist_now = get_now_ist()
    today_str = ist_now.strftime("%Y-%m-%d")
    
    print(f"🕒 Processing Lucky Numbers for: {today_str}")

    for lotto_type in TYPES:
        # STEP 1: Check if DB already has data
        if check_if_exists(lotto_type, today_str):
            print(f"✅ [{lotto_type.upper()}] Data already exists in DB. Skipping.")
            continue

        # STEP 2: Only run if data does NOT exist
        payload = {
            "type": lotto_type,
            "date": today_str,
            "lucky": generate_lucky_string(),
            "active": True
        }
        
        print(f"🚀 [{lotto_type.upper()}] No data found. Sending: {payload}")
        
        try:
            response = requests.post(API_URL, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                print(f"✔️ Success: {lotto_type} updated.")
            else:
                print(f"❌ Error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    update_numbers()