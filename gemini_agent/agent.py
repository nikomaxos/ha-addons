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
            response = requests.get(url, headers=headers, timeout=40)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=40)
        return response.json() if response.status_code < 300 else None
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
    if len(mem) > 10: mem = mem[-10:]
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(mem, f, indent=2)
    except: pass

def get_memory_string():
    mem = load_memory()
    if not mem: return "No previous context."
    output = []
    for m in mem:
        output.append(f"{m['role'].upper()}: {m['text']}")
    return "\n".join(output)

# --- SEMANTIC MAPPING (The Brain Fix) ---
# Εδώ συνδέουμε λέξεις με Domains
DOMAIN_MAP = {
    "light": ["light"],
    "φως": ["light"],
    "φώτα": ["light"],
    "διακόπτ": ["switch", "light"],
    "switch": ["switch"],
    "θερμανση": ["climate", "sensor"],
    "heating": ["climate", "sensor"],
    "klimatistiko": ["climate"],
    "κλιματιστ": ["climate"],
    "θερμοκρασ": ["sensor", "climate"],
    "temp": ["sensor", "climate"],
    "υγρασια": ["sensor"],
    "humidity": ["sensor"],
    "πόρτα": ["binary_sensor", "cover"],
    "door": ["binary_sensor", "cover"],
    "παραθυρ": ["binary_sensor", "cover"],
    "window": ["binary_sensor", "cover"],
    "παραβίασ": ["alarm_control_panel", "binary_sensor"]
}

def get_relevant_history(user_input):
    """
    1. Timeframe detection.
    2. Domain Mapping (Semantic Search).
    3. Keyword Matching (Fallback).
    """
    
    # 1. Timeframe
    lookback_hours = 24
    lower_input = user_input.lower()
    
    if "εβδομάδα" in lower_input or "week" in lower_input:
        lookback_hours = 168
    elif "μήνα" in lower_input or "month" in lower_input:
        lookback_hours = 720
    elif "μέρες" in lower_input or "days" in lower_input:
        lookback_hours = 72
    elif "ώρα" in lower_input or "hour" in lower_input:
        lookback_hours = 3 # Λίγο παραπάνω για context
    
    start_time = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
    
    # 2. Get All States
    states = call_ha_api("states")
    if not states: return "No states available."
    
    target_entities = []
    found_domains = set()

    # 3. Semantic Domain Matching
    # Αν βρούμε λέξη κλειδί (π.χ. "θέρμανση"), τραβάμε ΟΛΑ τα entities του domain (π.χ. climate.*)
    for keyword, domains in DOMAIN_MAP.items():
        if keyword in lower_input:
            found_domains.update(domains)
            print(f"🔎 Keyword '{keyword}' detected -> Searching domains: {domains}")

    # 4. Filter Entities
    # Σπάμε την ερώτηση σε λέξεις για keyword matching στα ονόματα
    user_words = [w for w in lower_input.split() if len(w) > 3]

    for s in states:
        eid = s['entity_id'].lower()
        domain = eid.split('.')[0]
        name = s.get('attributes', {}).get('friendly_name', '').lower()
        
        # Κριτήριο Α: Ανήκει σε Domain που ζητήθηκε (π.χ. climate)
        is_in_domain = domain in found_domains
        
        # Κριτήριο Β: Το όνομα περιέχει λέξη από την ερώτηση
        name_match = any(w in eid or w in name for w in user_words)
        
        if is_in_domain or name_match:
            # Εξαίρεση άχρηστων entities για να μην μπουκώσει
            if "update" not in eid and "device_tracker" not in eid:
                target_entities.append(s['entity_id'])

    if not target_entities:
        return f"No relevant entities found. (Searched for domains: {found_domains})"

    # Limit (Top 15 relevant)
    final_list = target_entities[:15]
    print(f"🎯 History Target List: {final_list}")
    
    entity_filter = ",".join(final_list)

    # 5. History Call
    # Αφαιρέσαμε το 'minimal_response' για να πάρουμε και Attributes (π.χ. hvac_action)
    # Αυτό είναι κρίσιμο για τη θέρμανση!
    endpoint = f"history/period/{start_time}?filter_entity_id={entity_filter}"
    history_data = call_ha_api(endpoint)
    
    if not history_data: return "Could not fetch history data."
    
    summary = []
    for entity_history in history_data:
        if not entity_history: continue
        eid = entity_history[0]['entity_id']
        readings = []
        
        # Sampling Strategy
        step = 1
        if lookback_hours > 24: step = 10
        if lookback_hours > 100: step = 50
        
        for entry in entity_history[::step]: 
            state = entry.get('state')
            # Προσπαθούμε να βρούμε αν δουλεύει η θέρμανση από τα attributes
            attrs = entry.get('attributes', {})
            hvac_action = attrs.get('hvac_action', '') # heating, cooling, idle
            
            val = state
            if hvac_action:
                val = f"{state} (Action: {hvac_action})"
                
            if state not in ['unknown', 'unavailable']:
                try:
                    ts_obj = datetime.fromisoformat(entry['last_changed'].replace("Z", "+00:00"))
                    fmt = "%H:%M" if lookback_hours < 24 else "%d/%m %H:%M"
                    ts = ts_obj.strftime(fmt)
                    readings.append(f"[{ts}={val}]")
                except: pass
        
        if readings:
            data_str = ", ".join(readings)
            summary.append(f"ENTITY: {eid}\nDATA: {data_str}\n")
            
    return "\n".join(summary)

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    memory = get_memory_string()
    
    # History Fetch
    history_context = get_relevant_history(user_input)

    # Current States (Compact)
    states = call_ha_api("states")
    current_status = ""
    if states:
        for s in states:
            if s['state'] not in ['unknown', 'unavailable']:
                eid = s['entity_id']
                if any(x in eid for x in ["light", "switch", "climate", "sensor"]):
                     current_status += f"{eid}: {s['state']}\n"
    
    prompt = (
        f"You are Jarvis. Omniscient Home Assistant AI.\n"
        f"--- MEMORY ---\n{memory}\n"
        f"--- HISTORY DATA (UTC Times) ---\n{history_context}\n"
        f"--- CURRENT STATE ---\n{current_status}\n"
        f"--- USER REQUEST ---\n{user_input}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Check 'DATA' lines. Timestamps are [HH:MM=State].\n"
        f"2. For Heating Duration: Look for 'hvac_action' being 'heating' OR state being 'heat' (if action is missing).\n"
        f"3. Calculate total duration manually by summing time differences between 'heating' and 'idle' entries.\n"
        f"4. If no history exists, list the entities you checked so the user knows.\n"
        f"5. Reply in Greek."
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
    except Exception as e:
        return f"Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v16.0 (Semantic Domain Mapping) Starting...")
print(f"👂 Listening on {PROMPT_ENTITY}")

last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ NEW: {current_command}")
            last_command = current_command
            
            print("🧠 Thinking...")
            try:
                reply = analyze_and_reply(current_command)
                save_memory(current_command, reply)
            except Exception as inner_e:
                print(f"🔥 Error: {inner_e}")
                reply = f"Error: {str(inner_e)[:50]}"
            
            print(f"✅ Reply: {reply[:50]}...")
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1)