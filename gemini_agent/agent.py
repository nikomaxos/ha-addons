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
            response = requests.get(url, headers=headers, timeout=15)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=15)
        
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
    if len(mem) > 6: mem = mem[-6:]
    try:
        with open(MEMORY_FILE, "w") as f: json.dump(mem, f, indent=2)
    except: pass

def get_memory_string():
    mem = load_memory()
    if not mem: return "No previous context."
    return "\n".join([f"{m['role'].upper()}: {m['text']}" for m in mem])

# --- HISTORY ENGINE (Improved) ---
def get_history_context(lookback_hours=3): # Reduced to 3h for speed
    """Fetches history for relevant sensors."""
    start_time = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
    
    states = call_ha_api("states")
    if not states: return "No states available."
    
    target_entities = []
    for s in states:
        eid = s['entity_id']
        attrs = s.get('attributes', {})
        unit = attrs.get('unit_of_measurement', '')
        dev_class = attrs.get('device_class', '')
        
        # Broader Filter: Units OR Device Class
        is_temp = unit in ['°C', '°F'] or 'temperature' in dev_class
        is_climate = eid.startswith("climate.")
        
        if is_temp or is_climate:
             target_entities.append(eid)
    
    if not target_entities: return "No temperature sensors found."
    
    # Priority: Sensors with 'temp' in name first
    priority = [e for e in target_entities if "temp" in e]
    if not priority: priority = target_entities
    
    # Limit to top 8 entities to be fast
    final_list = priority[:8]
    entity_filter = ",".join(final_list)
    
    # History API Call
    endpoint = f"history/period/{start_time}?filter_entity_id={entity_filter}&minimal_response"
    history_data = call_ha_api(endpoint)
    
    if not history_data: return "Could not fetch history data."
    
    summary = []
    for entity_history in history_data:
        if not entity_history: continue
        eid = entity_history[0]['entity_id']
        readings = []
        
        # Smart Sampling: Keep roughly 10 points
        step = max(1, len(entity_history) // 10)
        
        for entry in entity_history[::step]: 
            val = entry.get('state')
            if val not in ['unknown', 'unavailable']:
                try:
                    ts_obj = datetime.fromisoformat(entry['last_changed'].replace("Z", "+00:00"))
                    ts = ts_obj.strftime("%H:%M")
                    readings.append(f"{ts}={val}")
                except: pass
        
        if readings:
            summary.append(f"{eid}: " + ", ".join(readings))
            
    return "\n".join(summary)

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    memory = get_memory_string()
    
    # History Trigger Logic
    history_context = ""
    keywords = ["χθες", "πριν", "history", "ago", "last", "was", "ήταν"]
    # Αν η μνήμη έχει history keywords, τότε ίσως η τωρινή ερώτηση (π.χ "ναι" ή "πες") αφορά ιστορικό
    context_has_history = "history" in memory.lower() or "πριν" in memory.lower()
    
    if any(k in user_input.lower() for k in keywords) or (context_has_history and len(user_input) < 10):
        print("🕰️ History Request Detected...")
        history_context = get_history_context(lookback_hours=4)
    else:
        history_context = "History not requested."

    # Current States (Only relevant ones)
    states = call_ha_api("states")
    system_status = ""
    if states:
        for s in states:
            eid = s['entity_id']
            if s['state'] not in ['unknown', 'unavailable']:
                 # Include sensors in current state too
                if "light" in eid or "switch" in eid or "climate" in eid or "sensor" in eid:
                     system_status += f"{eid}: {s['state']}\n"
    
    # Prompt
    prompt = (
        f"You are Jarvis. Answer concisely.\n"
        f"--- CONVERSATION HISTORY ---\n{memory}\n"
        f"--- SENSOR HISTORY (Past 3-4h) ---\n{history_context}\n"
        f"--- CURRENT STATES ---\n{system_status}\n"
        f"--- USER REQUEST ---\n{user_input}\n\n"
        f"RULES:\n"
        f"1. Reply in Greek if user speaks Greek.\n"
        f"2. Check HISTORY timestamps (HH:MM) to answer 'what was the temp?'.\n"
        f"3. If history is empty, say 'No history data found for sensors'.\n"
        f"4. Keep it short."
    )
    
    response = model.generate_content(prompt)
    text = response.text.replace("*", "").replace("#", "")
    return text

# --- RUNTIME ---
print("🚀 Agent v14.0 (Robust) Starting...")
print(f"👂 Listening on {PROMPT_ENTITY}")

last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ NEW: {current_command}")
            last_command = current_command
            
            print("🧠 Thinking...")
            
            # --- SAFE EXECUTION BLOCK ---
            try:
                reply = analyze_and_reply(current_command)
                save_memory(current_command, reply)
            except Exception as inner_e:
                print(f"🔥 CRASH during analysis: {inner_e}")
                reply = f"Συγγνώμη, προέκυψε σφάλμα: {str(inner_e)[:50]}"
            
            print(f"✅ Reply: {reply[:50]}...")
            
            # ALWAYS send event back
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1)