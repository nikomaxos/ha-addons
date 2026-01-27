import os
import time
import requests
import json
import google.generativeai as genai

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"

# Τραβάμε το Token αυτόματα από το σύστημα (τώρα θα δουλέψει λόγω του config.yaml)
HASS_TOKEN = os.getenv("SUPERVISOR_TOKEN")
# Η εσωτερική διεύθυνση του Supervisor API
HASS_API = "http://supervisor/core/api"

# Load Options
try:
    with open(OPTIONS_PATH, "r") as f:
        options = json.load(f)
    API_KEY = options.get("gemini_api_key")
    PROMPT_ENTITY = options.get("prompt_entity", "input_text.gemini_prompt")
except Exception as e:
    print(f"Error loading options: {e}")
    exit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-pro')

# --- API HELPERS ---
def call_ha_api(endpoint, method="GET", data=None):
    headers = {
        "Authorization": f"Bearer {HASS_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        url = f"{HASS_API}/{endpoint}"
        if method == "GET":
            response = requests.get(url, headers=headers)
        else:
            response = requests.post(url, headers=headers, json=data)
        
        if response.status_code < 300:
            return response.json()
        else:
            print(f"⚠️ API Error ({endpoint}): {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return None

def get_ha_state(entity_id):
    res = call_ha_api(f"states/{entity_id}")
    return res.get("state", "") if res else ""

# --- LOG READER ---
def get_system_logs():
    log_files = ["/config/home-assistant.log.1", "/config/home-assistant.log"]
    logs = ""
    for log_path in log_files:
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    lines = f.readlines()
                    filtered = [line for line in lines[-50:] if "ERROR" in line or "WARNING" in line]
                    if not filtered: filtered = lines[-10:]
                    logs += f"--- LOG FILE: {log_path} ---\n" + "".join(filtered) + "\n"
            except: pass
    return logs[:4000]

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    logs_text = get_system_logs()
    states = call_ha_api("states")
    
    system_status = ""
    if states:
        for s in states:
            if s['state'] not in ['unknown', 'unavailable'] and ("light" in s['entity_id'] or "switch" in s['entity_id']):
                 system_status += f"{s['entity_id']}: {s['state']}\n"
    
    prompt = (
        f"You are Jarvis. Answer concisely for a chat interface.\n"
        f"--- LOGS ---\n{logs_text}\n"
        f"--- STATES ---\n{system_status}\n"
        f"--- USER REQUEST ---\n{user_input}\n\n"
        f"RULES:\n"
        f"1. If user speaks Greek, reply in Greek.\n"
        f"2. Keep it short and direct.\n"
        f"3. No markdown."
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
    except Exception as e:
        return f"Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v10.0 (Native Permissions) Starting...")

# Verify Connection
test = call_ha_api("discovery_info")
if test:
    print("✅ Supervisor API Connected Successfully (Automatic Auth).")
else:
    print(f"❌ API Failed. Token present? {bool(HASS_TOKEN)}")
    # Αν αποτύχει, περιμένουμε λίγο και ξαναδοκιμάζουμε (boot timing)
    time.sleep(10)

last_command = get_ha_state(PROMPT_ENTITY)
print(f"👂 Listening on {PROMPT_ENTITY}")

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ New Command: {current_command}")
            last_command = current_command
            
            # Analyze
            print("🧠 Thinking...")
            reply = analyze_and_reply(current_command)
            print(f"✅ Reply: {reply[:30]}...")
            
            # FIRE EVENT (Reply back to Script)
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1)