import os
import time
import requests
import json
import google.generativeai as genai

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"

# Load Options
try:
    with open(OPTIONS_PATH, "r") as f:
        options = json.load(f)
    API_KEY = options.get("gemini_api_key")
    PROMPT_ENTITY = options.get("prompt_entity", "input_text.gemini_prompt")
    USER_TOKEN = options.get("ha_token", "")
except Exception as e:
    print(f"Error loading options: {e}")
    exit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-pro')

# --- API CONNECTION LOGIC ---
if USER_TOKEN:
    print("🔑 Using User Provided Token (Direct Connection)")
    HASS_TOKEN = USER_TOKEN
    # Δοκιμάζουμε την εσωτερική διεύθυνση Docker
    HASS_API = "http://homeassistant:8123/api"
else:
    print("🛡️ Using Supervisor Auto-Token (Proxy Connection)")
    HASS_TOKEN = os.getenv("SUPERVISOR_TOKEN")
    HASS_API = "http://supervisor/core/api"

# --- API HELPERS ---
def call_ha_api(endpoint, method="GET", data=None):
    headers = {
        "Authorization": f"Bearer {HASS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Χειρισμός του slash για να αποφύγουμε διπλά //
    base = HASS_API.rstrip("/")
    path = endpoint.lstrip("/")
    url = f"{base}/{path}"
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code < 300:
            return response.json()
        else:
            print(f"⚠️ API Error ({endpoint}): {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Connection Error ({endpoint}): {e}")
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
print("🚀 Agent v11.1 (Fixed API Check) Starting...")

# 1. Connection Check (Χτυπάμε το root API που επιστρέφει πάντα 200 OK)
print(f"Testing connection to: {HASS_API}/")
test = call_ha_api("") # <--- ΑΛΛΑΓΗ: Κενό string για να χτυπήσει το root /api/

if test and test.get("message") == "API running.":
    print("✅ API Connected Successfully!")
else:
    # Αν αποτύχει το root check, δοκιμάζουμε το config endpoint
    print("⚠️ Root check failed, trying config endpoint...")
    test_conf = call_ha_api("config")
    if test_conf:
        print("✅ API Connected Successfully (via Config)!")
    else:
        print("❌ API Connection Failed.")
        print("💡 Check your Token and make sure Home Assistant is running.")
        time.sleep(60)
        exit(1)

last_command = get_ha_state(PROMPT_ENTITY)
print(f"👂 Listening on {PROMPT_ENTITY}")

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ New Command: {current_command}")
            last_command = current_command
            
            print("🧠 Thinking...")
            reply = analyze_and_reply(current_command)
            print(f"✅ Reply: {reply[:30]}...")
            
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1)