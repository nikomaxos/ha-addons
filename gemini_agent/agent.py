import os
import time
import requests
import json
import google.generativeai as genai

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"
HASS_TOKEN = os.getenv("SUPERVISOR_TOKEN")
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

# --- HELPERS ---
def call_ha_api(endpoint, method="GET", data=None):
    headers = {"Authorization": f"Bearer {HASS_TOKEN}", "Content-Type": "application/json"}
    try:
        if method == "GET":
            response = requests.get(f"{HASS_API}/{endpoint}", headers=headers)
        else:
            response = requests.post(f"{HASS_API}/{endpoint}", headers=headers, json=data)
        return response.json() if response.status_code < 300 else None
    except: return None

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
    
    # State Dump (Filtered for speed)
    states = call_ha_api("states")
    system_status = ""
    if states:
        for s in states:
            if s['state'] not in ['unknown', 'unavailable'] and ("light" in s['entity_id'] or "switch" in s['entity_id']):
                 system_status += f"{s['entity_id']}: {s['state']}\n"
    
    prompt = (
        f"You are Jarvis. Answer concisely.\n"
        f"--- LOGS ---\n{logs_text}\n"
        f"--- STATES ---\n{system_status}\n"
        f"--- USER REQUEST ---\n{user_input}\n\n"
        f"RULES:\n"
        f"1. If user speaks Greek, reply in Greek.\n"
        f"2. Summarize findings in 2-3 sentences max (for chat readability).\n"
        f"3. Do not use Markdown formatting."
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
    except Exception as e:
        return f"Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v9.0 (Event Emitter) Starting...")
last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        # Check if command changed AND is not empty
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ Processing: {current_command}")
            last_command = current_command
            
            # Analyze
            reply = analyze_and_reply(current_command)
            print(f"✅ Reply Ready: {reply[:30]}...")
            
            # FIRE EVENT (This sends the text back to the waiting Script)
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(5)
    
    time.sleep(1)