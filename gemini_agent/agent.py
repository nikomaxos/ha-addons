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
# Χρησιμοποιούμε το κορυφαίο μοντέλο που είδαμε ότι έχεις
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
    """Fetches last 40 lines of logs or lists files if missing."""
    log_path = "/config/home-assistant.log"
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                lines = f.readlines()
                return "".join(lines[-40:])
        else:
            # DEBUG MODE: Αν δεν το βρει, πες μας τι βλέπεις στον φάκελο
            try:
                files = os.listdir("/config")
                file_list = ", ".join(files)
                return f"ERROR: Log file not found at {log_path}.\nBUT I see these files in /config: {file_list}"
            except Exception as e:
                return f"Log missing and cannot list /config folder. Permission error? {e}"
    except Exception as e:
        return f"Error reading logs: {e}"

def analyze_with_gemini(user_request):
    """Main logic to gather context and ask Gemini."""
    
    context_data = ""
    # Αν ο χρήστης ζητάει logs/errors, διάβασε το αρχείο
    if "log" in user_request.lower() or "error" in user_request.lower():
        print("AI looking at: LOGS")
        context_data = f"SYSTEM LOGS / FILE STATUS:\n{get_logs()}"
    else:
        context_data = "No specific system logs requested. Answer based on general knowledge."

    full_prompt = (
        f"You are an expert Home Assistant technician named 'Gemini Agent'.\n"
        f"User Request: {user_request}\n\n"
        f"Technical Context:\n{context_data}\n\n"
        f"Analyze the context and answer the user briefly and clearly. "
        f"If you see a list of files instead of logs, tell the user exactly which file looks like the log file."
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
            last_command = current_command # Reset trigger immediately
            
            # Notify user we are working
            send_notification("Analyzing your request with Gemini 2.5...", "Agent Working")
            
            # Run Analysis
            result = analyze_with_gemini(current_command)
            
            # Send Result
            print("Response ready. Sending notification.")
            send_notification(result, "Gemini Report")
            
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)

    time.sleep(2)