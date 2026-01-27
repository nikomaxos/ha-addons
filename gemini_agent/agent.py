import os
import time
import requests
import json
import google.generativeai as genai
from datetime import datetime, timedelta

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"
MEMORY_FILE = "/config/gemini_memory.json"

# Global fallback for safety
HASS_API = "http://supervisor/core/api"
HASS_TOKEN = os.getenv("SUPERVISOR_TOKEN")

try:
    with open(OPTIONS_PATH, "r") as f:
        options = json.load(f)
    API_KEY = options.get("gemini_api_key")
    PROMPT_ENTITY = options.get("prompt_entity", "input_text.gemini_prompt")
    USER_TOKEN = options.get("ha_token", "")
    
    # Setup Auth based on config
    if USER_TOKEN:
        print("🔑 Auth: User Token (Direct)")
        HASS_TOKEN = USER_TOKEN
        HASS_API = "http://homeassistant:8123/api"
    else:
        print("🛡️ Auth: Supervisor (Proxy)")

except Exception as e:
    print(f"Error loading options: {e}")
    # Don't exit, try to stay alive to report error
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
        # Timeout increased to 60s for heavy history queries
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=60)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=60)
        
        if response.status_code < 300:
            return response.json()
        print(f"⚠️ API Status {response.status_code} for {url}")
        return None
    except requests.exceptions.Timeout:
        print(f"⏰ API TIMEOUT for {url}")
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
        except: return []
    return []

def save_memory(user, agent):
    mem = load_memory()
    mem.append({"timestamp": datetime.now().isoformat(), "role": "user", "text": user})
    mem.append({"timestamp": datetime.now().isoformat(), "role": "assistant", "text": agent})
    if len(mem) > 10: mem = mem[-10:]
    try:
        with open(MEMORY_FILE, "w") as f: json.dump(mem, f, indent=2)
    except: pass

def get_memory_string():
    mem = load_memory()
    if not mem: return "No context."
    return "\n".join([f"{m['role'].upper()}: {m['text']}" for m in mem])

# --- SEMANTIC MAPPING ---
DOMAIN_MAP = {
    "light": ["light"], "φως": ["light"], "φώτα": ["light"],
    "διακόπτ": ["switch", "light"], "switch": ["switch"],
    "θερμανση": ["climate", "sensor"], "heating": ["climate", "sensor"],
    "καλοριφερ": ["climate", "switch"], "aircon": ["climate"],
    "κλιματιστ": ["climate"], "thermostat": ["climate"],
    "θερμοκρασ": ["sensor", "climate"], "temp": ["sensor", "climate"],
    "υγρασια": ["sensor"], "humidity": ["sensor"],
    "πόρτα": ["binary_sensor", "cover"], "door": ["binary_sensor", "cover"],
    "παραθυρ": ["binary_sensor", "cover"], "window": ["binary_sensor", "cover"]
}

def get_relevant_history(user_input):
    """Robust History Fetcher"""
    try:
        # 1. Timeframe
        lookback_hours = 24
        lower_input = user_input.lower()
        
        if "εβδομάδα" in lower_input or "week" in lower_input: lookback_hours = 168
        elif "μήνα" in lower_input or "month" in lower_input: lookback_hours = 720
        elif "μέρες" in lower_input: lookback_hours = 72
        elif "ώρα" in lower_input or "hour" in lower_input: lookback_hours = 4
        
        print(f"🕒 Timeframe detected: {lookback_hours} hours")
        start_time = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
        
        # 2. Get All States
        states = call_ha_api("states")
        if not states: return "Error: Could not fetch system states."
        
        # 3. Semantic Search
        target_entities = []
        found_domains = set()
        
        # Check Keywords
        for keyword, domains in DOMAIN_MAP.items():
            if keyword in lower_input:
                found_domains.update(domains)
                print(f"🔎 Keyword '{keyword}' -> Domains: {domains}")

        # Check Name Matches
        user_words = [w for w in lower_input.split() if len(w) > 3]
        
        for s in states:
            eid = s['entity_id'].lower()
            domain = eid.split('.')[0]
            name = s.get('attributes', {}).get('friendly_name', '').lower()
            
            is_in_domain = domain in found_domains
            name_match = any(w in eid or w in name for w in user_words)
            
            if (is_in_domain or name_match) and "update" not in eid:
                target_entities.append(s['entity_id'])

        if not target_entities:
            return f"No entities found for domains: {found_domains}"

        # Limit to top 15 to prevent timeout
        final_list = target_entities[:15]
        print(f"🎯 Fetching History for: {final_list}")
        
        # 4. History API Call
        entity_filter = ",".join(final_list)
        endpoint = f"history/period/{start_time}?filter_entity_id={entity_filter}"
        
        history_data = call_ha_api(endpoint)
        
        if not history_data: return "History API returned no data (or timed out)."
        
        summary = []
        for entity_history in history_data:
            if not entity_history: continue
            eid = entity_history[0]['entity_id']
            readings = []
            
            # Sampling logic
            step = 1
            if lookback_hours > 24: step = 10
            if lookback_hours > 100: step = 50
            
            for entry in entity_history[::step]: 
                state = entry.get('state')
                # Extract attributes specifically for climate
                attrs = entry.get('attributes', {})
                hvac_action = attrs.get('hvac_action', '')
                current_temp = attrs.get('current_temperature', '')
                
                val = state
                details = []
                if hvac_action: details.append(f"Action:{hvac_action}")
                if current_temp: details.append(f"Temp:{current_temp}")
                
                if details: val = f"{state} ({','.join(details)})"
                    
                if state not in ['unknown', 'unavailable']:
                    try:
                        ts_obj = datetime.fromisoformat(entry['last_changed'].replace("Z", "+00:00"))
                        # Rough formatting
                        fmt = "%H:%M" if lookback_hours < 48 else "%d/%m %H:%M"
                        ts = ts_obj.strftime(fmt)
                        readings.append(f"[{ts}={val}]")
                    except: pass
            
            if readings:
                # Limit readings per entity to avoid token overflow
                data_str = ", ".join(readings[-100:]) 
                summary.append(f"ENTITY: {eid}\nDATA: {data_str}\n")
                
        return "\n".join(summary)
        
    except Exception as e:
        print(f"🔥 History Error: {e}")
        return f"Error fetching history: {e}"

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    try:
        memory = get_memory_string()
        print("🧠 Fetching History...")
        history_context = get_relevant_history(user_input)
        
        # Current States (Lightweight)
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
            f"INSTRUCTIONS:\n"
            f"1. Check 'DATA' lines. Timestamps are [HH:MM=State].\n"
            f"2. For Heating Duration: Look for 'Action:heating' or state 'heat'.\n"
            f"3. Sum up the duration manually.\n"
            f"4. If no data, explain what entities you checked.\n"
            f"5. Reply in Greek."
        )
        
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
        
    except Exception as e:
        print(f"🔥 AI Analysis Error: {e}")
        return f"Σφάλμα κατά την ανάλυση: {e}"

# --- RUNTIME ---
print("🚀 Agent v16.1 (Safe Mode) Starting...")
print(f"👂 Listening on {PROMPT_ENTITY}")

last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ NEW: {current_command}")
            last_command = current_command
            
            # --- EXECUTION BLOCK ---
            reply = "..."
            try:
                reply = analyze_and_reply(current_command)
                save_memory(current_command, reply)
            except Exception as final_e:
                reply = f"Critical Error: {final_e}"
            
            print(f"✅ Reply: {reply[:50]}...")
            
            # GUARANTEED EVENT FIRE
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1)