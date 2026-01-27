import os
import time
import requests
import json
import google.generativeai as genai
from datetime import datetime, timedelta

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"
MEMORY_FILE = "/config/gemini_memory.json"

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
            response = requests.get(url, headers=headers, timeout=20)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=20)
        
        if response.status_code < 300:
            return response.json()
        return None
    except Exception as e:
        print(f"❌ API Error [{endpoint}]: {e}")
        return None

def get_ha_state(entity_id):
    res = call_ha_api(f"states/{entity_id}")
    if res:
        return res.get("state", "")
    return ""

# --- MEMORY SYSTEM ---
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_memory(user, agent):
    mem = load_memory()
    mem.append({"timestamp": datetime.now().isoformat(), "role": "user", "text": user})
    mem.append({"timestamp": datetime.now().isoformat(), "role": "assistant", "text": agent})
    
    # Keep last 6 interactions
    if len(mem) > 6:
        mem = mem[-6:]
        
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(mem, f, indent=2)
    except:
        pass

def get_memory_string():
    mem = load_memory()
    if not mem:
        return "No previous context."
    output = []
    for m in mem:
        output.append(f"{m['role'].upper()}: {m['text']}")
    return "\n".join(output)

# --- SMART HISTORY ENGINE ---
def get_history_context(lookback_hours=24):
    """Fetches history for ANY sensor with temperature units."""
    start_time = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
    
    states = call_ha_api("states")
    if not states:
        return "No states available."
    
    target_entities = []
    for s in states:
        attrs = s.get('attributes', {})
        unit = attrs.get('unit_of_measurement', '')
        if unit in ['°C', '°F', '%'] or s['entity_id'].startswith("climate."):
             target_entities.append(s['entity_id'])
    
    if not target_entities:
        return "No temperature sensors found."
    
    # Priority filtering
    priority = [e for e in target_entities if "temp" in e or "climate" in e]
    if not priority:
        priority = target_entities
    final_list = priority[:10]
    
    entity_filter = ",".join(final_list)
    
    # History API Call
    endpoint = f"history/period/{start_time}?filter_entity_id={entity_filter}&minimal_response"
    history_data = call_ha_api(endpoint)
    
    if not history_data:
        return "Could not fetch history data."
    
    summary = []
    for entity_history in history_data:
        if not entity_history:
            continue
            
        eid = entity_history[0]['entity_id']
        readings = []
        
        # Sampling (1 every 5 readings)
        for entry in entity_history[::5]: 
            val = entry.get('state')
            if val not in ['unknown', 'unavailable']:
                try:
                    ts_obj = datetime.fromisoformat(entry['last_changed'].replace("Z", "+00:00"))
                    ts = ts_obj.strftime("%H:%M")
                    readings.append(f"{ts}={val}")
                except:
                    pass
        
        if readings:
            summary.append(f"{eid}: " + ", ".join(readings[-15:]))
            
    return "\n".join(summary)

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    # 1. Memory
    memory = get_memory_string()
    
    # 2. History Trigger
    history_context = ""
    keywords = ["χθες", "πριν", "history", "ago", "yesterday", "was", "ήταν"]
    trigger_words = ["ναι", "nai", "yes"]
    
    should_fetch_history = False
    if any(k in user_input.lower() for k in keywords):
        should_fetch_history = True
    elif user_input.lower() in trigger_words and "history" in memory.lower():
        should_fetch_history = True
        
    if should_fetch_history:
        print("🕰️ History Request Detected...")
        history_context = get_history_context(lookback_hours=24)
    else:
        history_context = "History not requested."

    # 3. Current State
    states = call_ha_api("states")
    system_status = ""
    if states:
        for s in states:
            eid = s['entity_id']
            if s['state'] not in ['unknown', 'unavailable']:
                if "light" in eid or "switch" in eid or "climate" in eid:
                     system_status += f"{eid}: {s['state']}\n"

    # 4. Prompt
    prompt = (
        f"You are Jarvis. Answer concisely.\n"
        f"--- CONVERSATION HISTORY ---\n{memory}\n"
        f"--- SENSOR HISTORY (Past 24h) ---\n{history_context}\n"
        f"--- CURRENT STATES ---\n{system_status}\n"
        f"--- USER REQUEST ---\n{user_input}\n\n"
        f"RULES:\n"
        f"1. Reply in Greek if user speaks Greek.\n"
        f"2. Use History to answer 'what was the temp?'. Times are UTC, adjust roughly if needed.\n"
        f"3. If user says 'Yes' (Nai), look at History/Memory context.\n"
        f"4. Keep it short."
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
    except Exception as e:
        return f"Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v13.1 (Syntax Fixed) Starting...")
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
            
            save_memory(current_command, reply)
            
            print(f"✅ Reply: {reply[:50]}...")
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1)