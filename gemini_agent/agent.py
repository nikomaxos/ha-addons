import os
import time
import requests
import json
import google.generativeai as genai
from datetime import datetime, timedelta

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"
MEMORY_FILE = "/config/gemini_memory.json"

# Safety Defaults
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
    else:
        print("🛡️ Auth: Supervisor (Proxy)")

except Exception as e:
    print(f"Error loading options: {e}")
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
        print(f"⚠️ API Status {response.status_code} for {url}")
        return None
    except Exception as e:
        print(f"❌ API Error [{endpoint}]: {e}")
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
    
    # Keep last 10 messages
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

# --- HISTORY ENGINE (CATEGORY BASED) ---
def get_relevant_history(user_input):
    """
    Fetches history based on category detection (Temperature, Light, Cover).
    """
    try:
        # 1. Timeframe
        lookback_hours = 24
        lower_input = user_input.lower()
        
        if "εβδομάδα" in lower_input or "week" in lower_input:
            lookback_hours = 168
        elif "μήνα" in lower_input:
            lookback_hours = 720
        elif "μέρες" in lower_input:
            lookback_hours = 72
        elif "ώρα" in lower_input or "hour" in lower_input:
            lookback_hours = 4
        
        print(f"🕒 Timeframe: {lookback_hours}h")
        start_time = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
        
        # 2. Get All States
        states = call_ha_api("states")
        if not states:
            return "Error: No states."
        
        # 3. Detect Category Intent
        target_entities = []
        
        # Keywords
        is_temp_query = any(w in lower_input for w in ["θερμοκρασ", "temp", "βαθμ", "klimat", "κλιματ", "heating", "θερμανσ", "heat"])
        is_light_query = any(w in lower_input for w in ["light", "φως", "φώτα", "διακοπτ", "switch"])
        is_cover_query = any(w in lower_input for w in ["porta", "πόρτα", "παραθυρ", "window", "cover"])
        
        for s in states:
            eid = s['entity_id'].lower()
            attrs = s.get('attributes', {})
            unit = attrs.get('unit_of_measurement', '')
            dev_class = attrs.get('device_class', '')
            
            match = False
            
            # Category Logic
            if is_temp_query:
                if eid.startswith("climate."): match = True
                if unit in ['°C', '°F']: match = True
                if 'temperature' in str(dev_class): match = True
            
            if is_light_query:
                if eid.startswith("light.") or eid.startswith("switch."): match = True
                
            if is_cover_query:
                if eid.startswith("cover.") or eid.startswith("binary_sensor."): match = True
                
            # Fallback Keyword Match
            if not match and not (is_temp_query or is_light_query or is_cover_query):
                 user_words = [w for w in lower_input.split() if len(w) > 3]
                 if any(w in eid for w in user_words): match = True

            if match and "update" not in eid:
                target_entities.append(s['entity_id'])

        if not target_entities:
            return "No relevant sensors found for this category."

        # Limit to top 20
        final_list = target_entities[:20]
        print(f"🎯 Fetching History for: {final_list}")
        
        # 4. History API Call
        entity_filter = ",".join(final_list)
        endpoint = f"history/period/{start_time}?filter_entity_id={entity_filter}"
        
        history_data = call_ha_api(endpoint)
        if not history_data:
            return "API returned no history data."
        
        summary = []
        for entity_history in history_data:
            if not entity_history:
                continue
                
            eid = entity_history[0]['entity_id']
            readings = []
            
            # Sampling
            step = 1
            if lookback_hours > 24:
                step = 10
            
            for entry in entity_history[::step]: 
                state = entry.get('state')
                attrs = entry.get('attributes', {})
                
                # Enrich data
                val = state
                if eid.startswith("climate."):
                    action = attrs.get('hvac_action', '')
                    curr = attrs.get('current_temperature', '')
                    if action or curr:
                        val = f"{state} (Action:{action}, Cur:{curr})"
                
                if state not in ['unknown', 'unavailable']:
                    try:
                        ts_obj = datetime.fromisoformat(entry['last_changed'].replace("Z", "+00:00"))
                        fmt = "%H:%M" if lookback_hours < 48 else "%d/%m %H:%M"
                        ts = ts_obj.strftime(fmt)
                        readings.append(f"[{ts}={val}]")
                    except:
                        pass
            
            if readings:
                data_str = ", ".join(readings[-100:])
                summary.append(f"ENTITY: {eid}\nDATA: {data_str}\n")
                
        return "\n".join(summary)

    except Exception as e:
        return f"History Error: {e}"

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    try:
        memory = get_memory_string()
        history_context = get_relevant_history(user_input)
        
        # Current States
        current_status = ""
        states = call_ha_api("states")
        if states:
            for s in states:
                if s['state'] not in ['unknown', 'unavailable']:
                    eid = s['entity_id']
                    if any(x in eid for x in ["light", "switch", "climate", "sensor"]):
                         current_status += f"{eid}: {s['state']}\n"
        
        prompt = (
            f"You are Jarvis. Omniscient Home Assistant AI.\n"
            f"--- HISTORY DATA (UTC Times) ---\n{history_context}\n"
            f"--- CURRENT STATE ---\n{current_status}\n"
            f"--- MEMORY ---\n{memory}\n"
            f"--- USER REQUEST ---\n{user_input}\n\n"
            f"RULES:\n"
            f"1. Check 'DATA' lines. Timestamps are [HH:MM=State].\n"
            f"2. You have ALL sensors of the requested category. Find the right one using common sense (e.g. 'saloniou' matches 'salon').\n"
            f"3. For heating, look for 'Action:heating' or state 'heat'.\n"
            f"4. Reply in Greek."
        )
        
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
        
    except Exception as e:
        return f"Analysis Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v17.1 (Syntax Clean) Starting...")
print(f"👂 Listening on {PROMPT_ENTITY}")

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