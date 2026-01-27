import os
import time
import requests
import json
import google.generativeai as genai

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

# --- MODEL SELECTION ---
MODEL_NAME = 'gemini-2.5-pro' 
print(f"Initializing Gemini Agent with model: {MODEL_NAME}")
model = genai.GenerativeModel(MODEL_NAME)

# --- HELPER FUNCTIONS ---
def send_notification(message, title="Gemini Agent"):
    """Sends a persistent notification to Home Assistant."""
    headers = {
        "Authorization": f"Bearer {HASS_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {"message": message, "title": title}
    try:
        requests.post(f"{HASS_API}/services/persistent_notification/create", headers=headers, json=data)
    except Exception as e:
        print(f"Error sending notification: {e}")

def get_ha_state(entity_id):
    """Gets the state of an entity."""
    headers = {
        "Authorization": f"Bearer {HASS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(f"{HASS_API}/states/{entity_id}", headers=headers)
        if response.status_code == 200:
            return response.json().get("state", "")
        return ""
    except:
        return ""

def get_logs():
    """Smart Log Fetcher: Tries main log, then backups (.1), then crash logs (.fault)."""
    # Λίστα προτεραιότητας αρχείων
    files_to_check = [
        "/config/home-assistant.log",
        "/config/home-assistant.log.1",      # Το αμέσως προηγούμενο log
        "/config/home-assistant.log.fault"   # Αν έγινε crash
    ]

    for log_path in files_to_check:
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    lines = f.readlines()
                    print(f"Reading logs from: {log_path}")
                    # Επιστρέφουμε τις τελευταίες 60 γραμμές και το όνομα του αρχείου
                    return f"SOURCE FILE: {log_path}\n" + "".join(lines[-60:])
            except Exception:
                continue # Αν αποτύχει, πάμε στο επόμενο

    # Αν δεν βρει τίποτα από τα παραπάνω
    try:
        files = os.listdir("/config")
        return f"ERROR: No readable log files found. Directory contents: {', '.join(files)}"
    except Exception as e:
        return f"Critical Error reading /config: {e}"

def analyze_with_gemini(user_request):
    """Main logic to gather context and ask Gemini."""
    
    context_data = ""
    if "log" in user_request.lower() or "error" in user_request.lower():
        print("AI looking at: LOGS")
        context_data = f"SYSTEM LOGS:\n{get_logs()}"
    else:
        context_data = "No specific system logs requested. Answer based on general knowledge."

    full_prompt = (
        f"You are an expert Home Assistant technician named 'Gemini Agent'.\n"
        f"User Request: {user_request}\n\n"
        f"Technical Context:\n{context_data}\n\n"
        f"Analyze the context and answer the user briefly and clearly."
    )

    try:
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"Gemini API Error: {e}"

# --- MAIN LOOP ---
print(f"Agent started. Listening for commands on entity: {PROMPT_ENTITY}")
last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        if current_command and current_command != last_command and current_command != "unknown":
            print(f"New command detected: {current_command}")
            last_command = current_command 
            
            send_notification("Analyzing request...", "Agent Working")
            
            result = analyze_with_gemini(current_command)
            
            print("Response ready. Sending notification.")
            send_notification(result, "Gemini Report")
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)

    time.sleep(2)