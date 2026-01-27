import os
import time
import requests
import json
import google.generativeai as genai
import datetime

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"
MEMORY_FILE = "/config/gemini_memory.json"
AUTOMATIONS_FILE = "/config/automations.yaml"
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

# --- API HELPER ---
def call_ha_api(endpoint, method="GET", data=None):
    headers = {"Authorization": f"Bearer {HASS_TOKEN}", "Content-Type": "application/json"}
    try:
        if method == "GET":
            response = requests.get(f"{HASS_API}/{endpoint}", headers=headers)
        else:
            response = requests.post(f"{HASS_API}/{endpoint}", headers=headers, json=data)
        
        if response.status_code < 300:
            return response.json()
        print(f"API Error {endpoint}: {response.status_code}") # Debug print
        return None
    except Exception as e:
        print(f"Request Exception: {e}")
        return None

def get_ha_state(entity_id):
    res = call_ha_api(f"states/{entity_id}")
    if res:
        return res.get("state", "")
    return ""

# --- LOG READER ---
def get_system_logs():
    """Reads the actual text log file properly."""
    log_files = ["/config/home-assistant.log.1", "/config/home-assistant.log"]
    logs = ""
    for log_path in log_files:
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    lines = f.readlines()
                    filtered = [line for line in lines[-100:] if "ERROR" in line or "WARNING" in line]
                    if not filtered: 
                        filtered = lines[-20:] 
                    logs += f"--- LOG FILE: {log_path} ---\n" + "".join(filtered) + "\n"
            except:
                pass
    return logs[:5000]

# --- THE CONSTRUCTOR ---
def install_infrastructure():
    print("👷 Checking Infrastructure...")
    jarvis_automation_yaml = """
# --- JARVIS AI AUTO-GENERATED AUTOMATION (FIXED v4) ---
- id: 'jarvis_voice_loop_v4'
  alias: 'Jarvis Voice Loop (Auto-Generated)'
  description: 'Handles TTS and re-opens the microphone seamlessly.'
  trigger:
  - platform: event
    event_type: jarvis_response
  action:
  - service: tts.google_translate_say
    data:
      entity_id: all  # <--- CHANGE THIS IF NO SOUND!
      message: "{{ trigger.event.data.text }}"
      language: "el" # Default to Greek support in TTS request
  - delay:
      hours: 0
      minutes: 0
      seconds: "{{ (trigger.event.data.text | length / 11) | int + 2 }}"
  - if:
      - condition: template
        value_template: "{{ states.assist_satellite | count > 0 }}"
    then:
      - service: assist_satellite.start_listening
        target:
          entity_id: "{{ states.assist_satellite | map(attribute='entity_id') | list }}"
    else:
      - service: system_log.write
        data:
          message: "Jarvis: No assist_satellite entities found to listen."
  mode: restart
# -------------------------------------------
"""
    try:
        current_content = ""
        if os.path.exists(AUTOMATIONS_FILE):
            with open(AUTOMATIONS_FILE, "r") as f:
                current_content = f.read()
        
        if "id: 'jarvis_voice_loop_v4'" not in current_content:
            print("⚙️ Injecting Fixed Automation (v4 - Greek Support)...")
            with open(AUTOMATIONS_FILE, "a") as f:
                f.write("\n" + jarvis_automation_yaml)
            call_ha_api("services/automation/reload", "POST")
    except Exception as e:
        print(f"Infrastructure Error: {e}")

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
    mem.append({"timestamp": datetime.datetime.now().isoformat(), "user": user, "agent": agent})
    if len(mem) > 30:
        mem = mem[-30:]
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=2)

def get_memory_string():
    mem = load_memory()
    output = []
    for m in mem[-4:]:
        output.append(f"User: {m['user']}\nAI: {m['agent']}")
    return "\n".join(output)

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    print("🧠 Thinking...")
    memory = get_memory_string()
    logs_text = get_system_logs()
    
    # State Dump
    states = call_ha_api("states")
    system_status = ""
    if states:
        for s in states:
            if s['state'] not in ['unknown', 'unavailable']:
                eid = s['entity_id']
                if "light" in eid or "switch" in eid or "climate" in eid or "cover" in eid:
                     system_status += f"{eid}: {s['state']}\n"
    
    # MULTILINGUAL PROMPT
    prompt = (
        f"You are Jarvis, a smart Home Assistant Analyst.\n"
        f"--- MEMORY ---\n{memory}\n"
        f"--- LOGS ---\n{logs_text}\n"
        f"--- STATES ---\n{system_status}\n"
        f"--- USER REQUEST ---\n{user_input}\n\n"
        f"RULES:\n"
        f"1. **LANGUAGE DETECTION:** If the User Request is in GREEK, you MUST reply in GREEK. If English, reply in English.\n"
        f"2. **SAFETY:** Do NOT change states (turn on/off) unless explicitly asked. If asked to 'check logs', just read and summarize the text logs provided above.\n"
        f"3. **STYLE:** Speak naturally, concisely, and friendly. No markdown characters.\n"
        f"4. If checking logs, look for 'ERROR' lines in the LOGS section and explain them simply."
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("*", "").replace("#", "")
        return text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return f"Error analyzing: {e}"

# --- RUNTIME ---
print("🚀 Agent v7.2 (Multilingual) Starting...")
install_infrastructure()
print(f"👂 Listening on {PROMPT_ENTITY}")

last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ Command detected: {current_command}")
            last_command = current_command
            
            reply = analyze_and_reply(current_command)
            save_memory(current_command, reply)
            
            print(f"🔊 Speaking (Language Auto-Detect): {reply[:50]}...")
            
            # Fire event
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1.5)