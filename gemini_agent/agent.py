import os
import time
import requests
import json
import google.generativeai as genai
from datetime import datetime, timedelta
import re

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
            response = requests.get(url, headers=headers, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=30)
        
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

# --- MEMORY SYSTEM (FIXED SYNTAX) ---
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
        return "No previous context."
    output = []
    for m in mem:
        output.append(f"{m['role'].upper()}: {m['text']}")
    return "\n".join(output)

# --- UNIVERSAL HISTORY ENGINE ---
def get_relevant_history(user_input):
    """Smart fetching of history based on keywords and timeframe."""
    
    # 1. Determine Timeframe
    lookback_hours = 24 # Default
    lower_input = user_input.lower()
    
    if "εβδομάδα" in lower_input or "week" in lower_input:
        lookback_hours = 168 # 7 days
    elif "μήνα" in lower_input or "month" in lower_input:
        lookback_hours = 720 # 30 days
    elif "μέρες" in lower_input or "days" in lower_input:
        lookback_hours = 72 # 3 days
    elif "ώρα" in lower_input or "hour" in lower_input:
        lookback_hours = 2 # 2 hours
    
    start_time = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
    
    # 2. Find Relevant Entities
    states = call_ha_api("states")
    if not states:
        return "No states available."
    
    # Filter common stop words
    ignored_words = ["είναι", "ήταν", "για", "την", "τον", "στο", "από", "και", "τι", "πώς", "πόση", "πόσο", "check", "the", "what", "how", "log", "history", "with", "that"]
    user_words = [w for w in lower_input.split() if len(w) > 2 and w not in ignored_words]
    
    relevant_entities = []
    
    for s in states:
        eid = s['entity_id'].lower()
        name = s.get('attributes', {}).get('friendly_name', '').lower()
        
        match_score = 0
        for word in user_words:
            if word in eid or word in name:
                match_score += 1
        
        if match_score > 0:
            relevant_entities.append(s['entity_id'])
            
    if not relevant_entities:
        return f"No relevant entities found matching: {user_words}"

    # Limit to top 10 relevant entities
    target_entities = relevant_entities[:10]
    entity_filter = ",".join(target_entities)
    print(f"🔎 Fetching History for: {target_entities} (Past {lookback_hours}h)")

    # 3. Call History API
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
        
        # Dynamic Sampling based on timeframe
        step = 1
        if lookback_hours > 24: step = 10
        if lookback_hours > 100: step = 50
        
        for entry in entity_history[::step]: 
            val = entry.get('state')
            if val not in ['unknown', 'unavailable']:
                try:
                    ts_obj = datetime.fromisoformat(entry['last_changed'].replace("Z", "+00:00"))
                    fmt = "%H:%M" if lookback_hours < 24 else "%d/%m %H:%M"
                    ts = ts_obj.strftime(fmt)
                    readings.append(f"[{ts}={val}]")
                except:
                    pass
        
        if readings:
            data_str = ", ".join(readings)
            summary.append(f"ENTITY: {eid}\nDATA: {data_str}\n")
            
    return "\n".join(summary)

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    # Memory
    memory = get_memory_string()
    
    # Universal History Fetch
    history_context = get_relevant_history(user_input)

    # Current States (Filtered for performance)
    states = call_ha_api("states")
    current_status = ""
    if states:
        for s in states:
            if s['state'] not in ['unknown', 'unavailable']:
                eid = s['entity_id']
                # Include broad categories
                if any(x in eid for x in ["light", "switch", "climate", "sensor", "binary_sensor", "input"]):
                     current_status += f"{eid}: {s['state']}\n"
    
    prompt = (
        f"You are Jarvis, an Omniscient Home Assistant AI.\n"
        f"--- CONVERSATION HISTORY ---\n{memory}\n"
        f"--- RELEVANT HISTORY DATA (Times are UTC) ---\n{history_context}\n"
        f"--- CURRENT STATES ---\n{current_status}\n"
        f"--- USER REQUEST ---\n{user_input}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. You have raw historical data (timestamps=values). USE IT to calculate durations, sums, or trends.\n"
        f"2. Example: If asked 'how long was heating on?', look for 'heating' or 'on' states in the DATA, calculate duration between timestamps.\n"
        f"3. If data is missing, admit it. Do not hallucinate.\n"
        f"4. Timestamps are UTC. Add +2/3 hours for Greece context.\n"
        f"5. Reply in Greek if asked in Greek."
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
    except Exception as e:
        return f"Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v15.1 (Syntax Fixed) Starting...")
print(f"👂 Listening on {PROMPT_ENTITY}")

last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ NEW: {current_command}")
            last_command = current_command
            
            print("🧠 Thinking (Fetching Universal History)...")
            
            try:
                reply = analyze_and_reply(current_command)
                save_memory(current_command, reply)
            except Exception as inner_e:
                print(f"🔥 Error: {inner_e}")
                reply = f"Σφάλμα επεξεργασίας: {str(inner_e)[:50]}"
            
            print(f"✅ Reply: {reply[:50]}...")
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1)