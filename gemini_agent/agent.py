import os
import time
import requests
import json
import google.generativeai as genai
from datetime import datetime, timedelta

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"
MEMORY_FILE = "/config/gemini_memory.json"
HASS_API = "http://supervisor/core/api"
HASS_TOKEN = os.getenv("SUPERVISOR_TOKEN")

try:
    with open(OPTIONS_PATH, "r") as f:
        options = json.load(f)
    API_KEY = options.get("gemini_api_key")
    PROMPT_ENTITY = options.get("prompt_entity", "input_text.gemini_prompt")
    USER_TOKEN = options.get("ha_token", "")
    
    if USER_TOKEN:
        print("🔑 Auth: User Token (Direct)")
        HASS_TOKEN = USER_TOKEN
        HASS_API = "http://homeassistant:8123/api"
except Exception:
    pass

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-pro')

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
            response = requests.get(url, headers=headers, timeout=60)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=60)
        
        if response.status_code < 300:
            return response.json()
        return None
    except:
        return None

def get_ha_state(entity_id):
    res = call_ha_api(f"states/{entity_id}")
    if res:
        return res.get("state", "")
    return ""

# --- MEMORY (FIXED SYNTAX) ---
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
    
    if len(mem) > 10:
        mem = mem[-10:]
        
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(mem, f, indent=2)
    except:
        pass

def get_memory_string():
    mem = load_memory()
    if not mem:
        return "No context."
    output = []
    for m in mem:
        output.append(f"{m['role'].upper()}: {m['text']}")
    return "\n".join(output)

# --- HISTORY ENGINE ---
def get_relevant_history(user_input):
    try:
        # 1. Determine Timeframe & Anchors
        # Container Time (Local if timezone set correctly, else UTC)
        # We use utcnow for calculations to match HA DB
        utc_now = datetime.utcnow()
        
        lookback_hours = 24
        lower_input = user_input.lower()
        
        if "εβδομάδα" in lower_input or "week" in lower_input:
            lookback_hours = 168
        elif "μήνα" in lower_input:
            lookback_hours = 720
        elif "μέρες" in lower_input:
            lookback_hours = 72
        elif "ώρα" in lower_input or "hour" in lower_input:
            lookback_hours = 2 # Last 2 hours for precision
        
        start_time_iso = (utc_now - timedelta(hours=lookback_hours)).isoformat()
        
        # 2. Category Detection
        states = call_ha_api("states")
        if not states:
            return "Error: No states."
        
        target_entities = []
        is_temp = any(w in lower_input for w in ["θερμοκρασ", "temp", "klimat", "κλιματ", "heating", "θερμανσ", "heat"])
        is_light = any(w in lower_input for w in ["light", "φως", "φώτα", "διακοπτ", "switch"])
        
        for s in states:
            eid = s['entity_id'].lower()
            attrs = s.get('attributes', {})
            
            # BLACKLIST: Ignore summary stats for short-term history
            if lookback_hours < 24 and any(bad in eid for bad in ["daily", "weekly", "monthly", "cost", "energy", "power"]):
                continue

            match = False
            if is_temp:
                if eid.startswith("climate."): match = True
                elif "temperature" in str(attrs.get('device_class', '')): match = True
            
            if is_light:
                if eid.startswith("light.") or eid.startswith("switch."): match = True
            
            # Fallback text match
            if not match:
                words = [w for w in lower_input.split() if len(w)>3]
                if any(w in eid for w in words): match = True
            
            if match and "update" not in eid:
                target_entities.append(s['entity_id'])

        if not target_entities:
            return "No relevant sensors."
        
        final_list = target_entities[:20]
        entity_filter = ",".join(final_list)
        endpoint = f"history/period/{start_time_iso}?filter_entity_id={entity_filter}"
        
        history_data = call_ha_api(endpoint)
        if not history_data:
            return "No history data."
        
        summary = []
        for entity_history in history_data:
            if not entity_history:
                continue
                
            eid = entity_history[0]['entity_id']
            readings = []
            
            # Sampling logic
            step = 1
            if lookback_hours > 24:
                step = 10
            
            for entry in entity_history[::step]: 
                state = entry.get('state')
                attrs = entry.get('attributes', {})
                
                # Enrich Climate Data
                val = state
                if eid.startswith("climate."):
                    action = attrs.get('hvac_action', 'unknown')
                    curr = attrs.get('current_temperature', '')
                    val = f"{state} (Active:{action}, Temp:{curr})"
                
                if state not in ['unknown', 'unavailable']:
                    try:
                        ts_str = entry['last_changed']
                        readings.append(f"[{ts_str}={val}]")
                    except:
                        pass
            
            if readings:
                # Last 50 readings
                data_str = ", ".join(readings[-50:])
                summary.append(f"ENTITY: {eid}\nDATA: {data_str}\n")
                
        return "\n".join(summary)

    except Exception as e:
        return f"History Error: {e}"

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    try:
        # Time Anchors
        now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        memory = get_memory_string()
        history_context = get_relevant_history(user_input)
        
        current_status = ""
        states = call_ha_api("states")
        if states:
            for s in states:
                if s['state'] not in ['unknown', 'unavailable']:
                    eid = s['entity_id']
                    if any(x in eid for x in ["light", "switch", "climate"]):
                         current_status += f"{eid}: {s['state']}\n"
        
        prompt = (
            f"You are Jarvis. Smart Home Analyst.\n"
            f"--- CRITICAL TIME CONTEXT ---\n"
            f"Current Local Time: {now_local}\n"
            f"Current UTC Time: {now_utc}\n"
            f"(Note: HA Logs below are in UTC. Add +2h/+3h for Greece).\n\n"
            f"--- LOGS (UTC) ---\n{history_context}\n"
            f"--- CURRENT STATES ---\n{current_status}\n"
            f"--- MEMORY ---\n{memory}\n"
            f"--- REQUEST ---\n{user_input}\n\n"
            f"RULES:\n"
            f"1. IGNORE data older than the requested timeframe. Compare Log timestamps with 'Current UTC Time'.\n"
            f"2. For 'Last Hour': If the logs show the last 'heating' event was 4 hours ago, then the answer is '0 minutes'.\n"
            f"3. Ignore sensors like 'daily_heating_hours' for short-term queries.\n"
            f"4. Reply in Greek."
        )
        
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
        
    except Exception as e:
        return f"Analysis Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v18.1 (Syntax Clean) Starting...")
last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ NEW: {current_command}")
            last_command = current_command
            
            try:
                reply = analyze_and_reply(current_command)
                save_memory(current_command, reply)
            except Exception as final_e:
                reply = f"Error: {final_e}"
            
            print(f"✅ Reply: {reply[:50]}...")
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1)