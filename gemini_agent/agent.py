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
# Χρησιμοποιούμε το 2.5 Pro για μέγιστη ευφυΐα και μνήμη
model = genai.GenerativeModel('gemini-2.5-pro')

# --- API HELPER ---
def call_ha_api(endpoint, method="GET", data=None):
    headers = {"Authorization": f"Bearer {HASS_TOKEN}", "Content-Type": "application/json"}
    try:
        if method == "GET":
            response = requests.get(f"{HASS_API}/{endpoint}", headers=headers)
        else:
            response = requests.post(f"{HASS_API}/{endpoint}", headers=headers, json=data)
        return response.json() if response.status_code < 300 else None
    except:
        return None

def get_ha_state(entity_id):
    res = call_ha_api(f"states/{entity_id}")
    return res.get("state", "") if res else ""

# --- SELF-INSTALLATION ENGINE (The Constructor) ---
def install_infrastructure():
    """
    Checks if the necessary automations exist in automations.yaml.
    If not, it INJECTS them automatically and reloads HA.
    """
    print("👷 Checking Infrastructure...")
    
    jarvis_automation_yaml = """
# --- JARVIS AI AUTO-GENERATED AUTOMATION ---
- id: 'jarvis_voice_loop_v1'
  alias: 'Jarvis Voice Loop (Auto-Generated)'
  description: 'Handles TTS and re-opens the microphone for conversation.'
  trigger:
  - platform: event
    event_type: jarvis_response
  action:
  - service: tts.google_translate_say
    data:
      entity_id: all  # WARNING: Speaks on ALL speakers by default. Change this if needed.
      message: "{{ trigger.event.data.text }}"
  - delay:
      hours: 0
      minutes: 0
      seconds: "{{ (trigger.event.data.text | length / 12) | int + 2 }}" # Dynamic delay based on text length
  - service: assist_satellite.start_listening
    target:
      all: true # Forces ALL satellites to listen. Change to specific entity if needed.
    data: {}
  mode: restart
# -------------------------------------------
"""
    try:
        current_content = ""
        if os.path.exists(AUTOMATIONS_FILE):
            with open(AUTOMATIONS_FILE, "r") as f:
                current_content = f.read()
        
        # Check if already installed
        if "id: 'jarvis_voice_loop_v1'" not in current_content:
            print("⚙️ Infrastructure missing. Injecting Automation...")
            with open(AUTOMATIONS_FILE, "a") as f:
                f.write("\n" + jarvis_automation_yaml)
            
            print("🔄 Reloading Automations...")
            call_ha_api("services/automation/reload", "POST")
            print("✅ Infrastructure Installed Successfully.")
        else:
            print("✅ Infrastructure already exists.")
            
    except Exception as e:
        print(f"❌ Failed to install infrastructure: {e}")

# --- MEMORY SYSTEM ---
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f: return json.load(f)
        except: return []
    return []

def save_memory(user, agent):
    mem = load_memory()
    mem.append({"timestamp": datetime.datetime.now().isoformat(), "user": user, "agent": agent})
    if len(mem) > 30: mem = mem[-30:] # Keep last 30 turns
    with open(MEMORY_FILE, "w") as f: json.dump(mem, f, indent=2)

def get_memory_string():
    mem = load_memory()
    return "\n".join([f"User: {m['user']}\nAI: {m['agent']}" for m in mem[-4:]])

# --- MAIN LOGIC ---
def analyze_and_reply(user_input):
    print("🧠 Thinking...")
    
    # Context Gathering
    memory = get_memory_string()
    
    # Smart Data Fetching (States & Config)
    # (Simplified for speed - fetches problematic entities)
    states = call_ha_api("states")
    system_status = ""
    if states:
        for s in states:
            if s['state'] in ['unavailable', 'unknown'] or "sensor" in s['entity_id']:
                 system_status += f"{s['entity_id']}: {s['state']}\n"
    system_status = system_status[:5000] # Limit size

    prompt = (
        f"You are Jarvis, the Home Assistant Voice AI.\n"
        f"--- MEMORY ---\n{memory}\n"
        f"--- SYSTEM STATUS ---\n{system_status}\n"
        f"--- USER INPUT ---\n{user_input}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. You are in a SPOKEN conversation loop.\n"
        f"2. Answer concisely. Do not list long IDs.\n"
        f"3. If you ask a question, the microphone will open automatically for the user to reply.\n"
        f"4. Be helpful and proactive."
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("*", "") # Remove markdown for TTS
        return text
    except Exception as e:
        return f"Error: {e}"

# --- RUNTIME ---
print("🚀 Agent v6.0 Starting...")
install_infrastructure() # <--- Εδώ γίνεται η αυτόματη εγκατάσταση
print(f"👂 Listening on {PROMPT_ENTITY}")

last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command not in ["", "unknown"]:
            print(f"🗣️ Command: {current_command}")
            last_command = current_command
            
            # Analyze
            reply = analyze_and_reply(current_command)
            
            # Save Memory
            save_memory(current_command, reply)
            
            # Trigger TTS & Loop via the injected automation
            print(f"🔊 Speaking: {reply[:50]}...")
            call_ha_api("events/jarvis_response", "POST", {"text": reply})
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
    
    time.sleep(1.5)