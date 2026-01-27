import os
import time
import requests
import json
import google.generativeai as genai
from datetime import datetime, timedelta

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

# --- AUTH SETUP ---
if USER_TOKEN:
    print("🔑 Auth: User Token (Direct)")
    HASS_TOKEN = USER_TOKEN
    HASS_API = "http://homeassistant:8123/api"
else:
    print("🛡️ Auth: Supervisor (Proxy)")
    HASS_TOKEN = os.getenv("SUPERVISOR_TOKEN")
    HASS_API = "http://supervisor/core/api"

# --- API HELPERS ---
def call_ha_api(endpoint, method="GET", data=None):
    headers = {
        "Authorization": f"Bearer {HASS_TOKEN}",
        "Content-Type": "application/json"
    }
    base = HASS_API.rstrip("/")
    path = endpoint.lstrip("/")
    url = f"{base}/{path}"
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=15)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=15)
        return response.json() if response.status_code < 300 else None
    except Exception as e:
        print(f"❌ API Error [{endpoint}]: {e}")
        return None

def get_ha_state(entity_id):
    res = call_ha_api(f"states/{entity_id}")
    return res.get("state", "") if res else ""

# --- HISTORY ENGINE (NEW!) ---
def get_history_context(lookback_hours=3):
    """Fetches history for relevant sensors (temperature, climate) for the last X hours."""
    # Calculate start time (UTC)
    start_time = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
    
    # 1. Get all entities first to find relevant ones
    states = call_ha_api("states")
    if not states: return "No history available."
    
    # Filter for interesting entities (climate, temperature sensors)
    # We limit to 10 entities to avoid context overflow
    target_entities = []
    for s in states:
        eid = s['entity_id']
        # Prioritize Climate and Temperature/Humidity sensors
        if "climate" in eid or "temperature" in eid or "humid" in eid:
             target_entities.append(eid)
    
    if not target_entities: return "No sensors found."
    
    # Limit to top 15 to be safe
    target_entities = target_entities[:15]
    entity_filter = ",".join(target_entities)
    
    # 2. Call History API
    # endpoint: /api/history/period/<timestamp>?filter_entity_id=...
    endpoint = f"history/period/{start_time}?filter_entity_id={entity_filter}&minimal_response"
    history_data = call_ha_api(endpoint)
    
    if not history_data: return "Could not fetch history."
    
    # 3. Format for LLM (Compact format)
    # Output: "sensor.living_room_temp: [10:00=21C, 10:30=21.5C, ...]"
    summary = []
    for entity_history in history_data:
        if not entity_history: continue
        
        eid = entity_history[0]['entity_id']
        readings = []
        
        # Sample every 3rd reading to save space
        for entry in entity_history[::5]: 
            val = entry.get('state')
            # Only keep numeric values or distinct states
            if val not in ['unknown', 'unavailable']:
                # Format time as HH:MM
                ts = datetime.fromisoformat(entry['last_changed'].replace("Z", "+00:00")).strftime("%H:%M")
                readings.append(f"{ts}={val}")
        
        if readings:
            summary.append(f"{eid}: " + ", ".join(readings[-10:])) # Keep last 10 readings per sensor
            
    return "\n".join(summary)

# --- LOG READER ---
def get_system_logs():
    # ... (ίδιο με πριν) ...
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
    return logs[:3000]

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    logs_text = get_system_logs()
    
    # Current States
    states = call_ha_api("states")
    system_status = ""
    if states:
        for s in states:
            if s['state'] not in ['unknown', 'unavailable'] and ("light" in s['entity_id'] or "switch" in s['entity_id']):
                 system_status += f"{s['entity_id']}: {s['state']}\n"

    # --- INTELLIGENT HISTORY FETCH ---
    # Αν ο χρήστης ρωτάει για παρελθόν, φέρνουμε ιστορικό
    history_context = ""
    keywords = ["χθες", "πριν", "προηγούμενη", "history", "ago", "yesterday", "last", "ήταν", "was"]
    if any(k in user_input.lower() for k in keywords):
        print("🕰️ History Request Detected! Fetching data...")
        history_context = get_history_context(lookback_hours=24)
    else:
        history_context = "History not requested."

    prompt = (
        f"You are Jarvis. Answer concisely.\n"
        f"--- CURRENT STATES ---\n{system_status}\n"
        f"--- SENSOR HISTORY (Past 24h) ---\n{history_context}\n"
        f"--- ERROR LOGS ---\n{logs_text}\n"
        f"--- USER REQUEST ---\n{user_input}\n\n"
        f"RULES:\n"
        f"1. If user speaks Greek, reply in Greek.\n"
        f"2. Use the HISTORY section to answer questions like 'What was the temp 1 hour ago?'.\n"
        f"3. The history format is HH:MM=Value.\n"
        f"4. Keep it short."
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
    except Exception as e:
        return f"Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v12.0 (History Enabled) Starting...")
print(f"👂 Listening on {PROMPT_ENTITY}")
last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ NEW: {current_command}")
            last_command = current_command
            
            print("🧠 Thinking...")
            reply = analyze_and_reply(current_command)
            print(f"✅ Reply: {reply[:50]}...")
            
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(5)
    
    time.sleep(1)