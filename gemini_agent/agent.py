import os
import time
import requests
import json
import google.generativeai as genai
import datetime

# --- CONFIGURATION ---
OPTIONS_PATH = "/data/options.json"
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

# Configure Gemini
genai.configure(api_key=API_KEY)
MODEL_NAME = 'gemini-2.5-pro' 
print(f"Initializing God-Mode Agent with model: {MODEL_NAME}")
model = genai.GenerativeModel(MODEL_NAME)

# --- CORE FUNCTIONS ---

def call_ha_api(endpoint, method="GET", data=None):
    """Generic function to call Home Assistant API."""
    headers = {
        "Authorization": f"Bearer {HASS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        if method == "GET":
            response = requests.get(f"{HASS_API}/{endpoint}", headers=headers)
        else:
            response = requests.post(f"{HASS_API}/{endpoint}", headers=headers, json=data)
        
        if response.status_code < 300:
            return response.json() if response.content else {"status": "ok"}
        else:
            print(f"API Error {endpoint}: {response.text}")
            return None
    except Exception as e:
        print(f"Request Error: {e}")
        return None

def send_notification(message, title="Gemini Agent"):
    call_ha_api("services/persistent_notification/create", "POST", {"message": message, "title": title})

def get_ha_state(entity_id):
    state_data = call_ha_api(f"states/{entity_id}")
    return state_data.get("state", "") if state_data else ""

# --- GOD MODE: INFO GATHERING ---

def get_all_entities_summary():
    """Fetches a summary of ALL entities and their current states."""
    states = call_ha_api("states")
    if not states: return "No states found."
    
    summary = []
    for s in states:
        eid = s['entity_id']
        state = s['state']
        # Filter out massive text blobs to save space
        if len(str(state)) < 200: 
            summary.append(f"{eid}: {state}")
    return "\n".join(summary)

def read_config_files():
    """Reads key YAML files to understand automation logic."""
    files_to_read = [
        "/config/automations.yaml",
        "/config/scripts.yaml",
        "/config/configuration.yaml",
        "/config/scenes.yaml"
    ]
    config_dump = ""
    for file_path in files_to_read:
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as f:
                    content = f.read()
                    # Limit very large files
                    if len(content) > 50000: content = content[:50000] + "\n...[TRUNCATED]"
                    config_dump += f"\n--- FILE: {file_path} ---\n{content}\n"
            except Exception as e:
                config_dump += f"\nError reading {file_path}: {e}\n"
    return config_dump

def get_smart_history(user_request):
    """
    Intelligently fetches history ONLY for entities mentioned in the user request.
    Fetching 'everything' is impossible (too much data), so we filter.
    """
    # 1. Get all entity IDs
    all_states = call_ha_api("states")
    all_ids = [s['entity_id'] for s in all_states] if all_states else []
    
    # 2. Find which entities are relevant to the user's question
    relevant_entities = [eid for eid in all_ids if eid in user_request]
    
    if not relevant_entities:
        return "No specific entities identified in request for historical analysis."

    # 3. Fetch history for those entities (last 24 hours default, or more)
    # Note: For simplicity we fetch 48 hours. Can be extended.
    history_data = ""
    timestamp = datetime.datetime.now() - datetime.timedelta(hours=48)
    time_str = timestamp.isoformat()
    
    print(f"Fetching history for: {relevant_entities}")
    
    # Use History API
    filter_str = ",".join(relevant_entities)
    data = call_ha_api(f"history/period/{time_str}?filter_entity_id={filter_str}&minimal_response=true")
    
    if data:
        # Convert JSON to a readable summary string
        history_data = json.dumps(data, indent=1)
        # Limit size just in case
        if len(history_data) > 100000: history_data = history_data[:100000] + "...[TRUNCATED]"
        return history_data
    else:
        return "History API returned no data."

def execute_action(action_json):
    """Executes an action requested by the AI."""
    try:
        cmd = json.loads(action_json)
        domain, service = cmd['service'].split('.')
        target = cmd.get('target', {})
        data = cmd.get('data', {})
        
        full_payload = {**target, **data}
        
        print(f"EXECUTING ACTION: {domain}.{service} with {full_payload}")
        call_ha_api(f"services/{domain}/{service}", "POST", full_payload)
        return True
    except Exception as e:
        print(f"Action Execution Failed: {e}")
        return False

# --- MAIN ANALYSIS ENGINE ---

def analyze_with_gemini(user_request):
    print("Gathering System Context...")
    
    # 1. Get Structure (Configs)
    config_context = read_config_files()
    
    # 2. Get Current Status (Real-time)
    state_context = get_all_entities_summary()
    
    # 3. Get History (Targeted)
    history_context = get_smart_history(user_request)

    full_prompt = (
        f"You are the 'Home Assistant Architect'. You have full read/write access.\n"
        f"User Request: {user_request}\n\n"
        f"--- CURRENT STATE OF ALL ENTITIES ---\n{state_context}\n\n"
        f"--- CONFIGURATION & LOGIC (YAML) ---\n{config_context}\n\n"
        f"--- HISTORICAL DATA (Targeted) ---\n{history_context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Analyze the system deeply based on the user request.\n"
        f"2. If the user asks to CHANGE something (turn on/off, set temp), output a JSON block ONLY for the action.\n"
        f"   Format: {{'service': 'domain.service', 'target': {{'entity_id': '...'}}, 'data': {{...}}}}\n"
        f"3. If the user asks for analysis, explain clearly in Greek/English.\n"
        f"4. If you spot configuration errors in YAML, point them out."
    )

    try:
        response = model.generate_content(full_prompt)
        text = response.text
        
        # Check if AI wants to execute an action (JSON detection)
        if "{" in text and "service" in text:
            # Try to extract and execute JSON
            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                json_str = text[start:end]
                execute_action(json_str)
                return f"Action Executed. AI Analysis: {text}"
            except:
                pass # Just return text if JSON fails
                
        return text
    except Exception as e:
        return f"Gemini API Error: {e}"

# --- MAIN LOOP ---
print(f"GOD MODE Agent started. Listening on: {PROMPT_ENTITY}")
last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command != "unknown":
            print(f"New command: {current_command}")
            last_command = current_command 
            
            send_notification("Analyzing System (Deep Scan)...", "Agent Working")
            
            result = analyze_with_gemini(current_command)
            
            print("Response ready.")
            send_notification(result[:1500], "Gemini Architect Report") # Limit notification size
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)

    time.sleep(2)