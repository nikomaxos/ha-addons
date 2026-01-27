import os
import time
import requests
import json
import google.generativeai as genai
import yaml

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

# --- DIAGNOSTIC: LIST AVAILABLE MODELS ---
print("--- CHECKING AVAILABLE MODELS ---")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"FOUND MODEL: {m.name}")
except Exception as e:
    print(f"Could not list models: {e}")
print("-------------------------------")

# Select Model (Change this later based on the logs above)
# We use 'gemini-pro' as a safe fallback
MODEL_NAME = 'gemini-pro' 
print(f"Selected Model: {MODEL_NAME}")
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
        response = requests.post(f"{HASS_API}/services/persistent_notification/create", headers=headers, json=data)
        if response.status_code != 200:
            print(f"Failed to send notification: {response.text}")
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

def get_history():
    """Fetches rudimentary history (placeholder for now)."""
    # In a full version, we would query the history API.
    # For now, we return a generic message to verify connectivity.
    return "History access requires advanced SQL querying. For now, assume systems are nominal."

def get_logs():
    """Fetches last 50 lines of logs."""
    # Reading files directly requires mapping /config, which we have.
    # Trying to read home-assistant.log
    log_path = "/config/home-assistant.log"
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                lines = f.readlines()
                return "".join(lines[-50:]) # Return last 50 lines
        else:
            return "Log file not found at /config/home-assistant.log"
    except Exception as e:
        return f"Error reading logs: {e}"

def analyze_with_gemini(user_request):
    """Main logic to gather context and ask Gemini."""
    
    # 1. Determine what the user wants (Logs or General)
    context_data = ""
    
    if "log" in user_request.lower() or "error" in user_request.lower():
        print("AI requested tool: LOGS")
        context_data = f"LOGS:\n{get_logs()}"
    elif "history" in user_request.lower():
        print("AI requested tool: HISTORY")
        context_data = f"HISTORY SUMMARY:\n{get_history()}"
    else:
        context_data = "No specific logs requested."

    # 2. Build Prompt
    full_prompt = (
        f"You are a Home Assistant technical expert.\n"
        f"User Question: {user_request}\n\n"
        f"System Context:\n{context_data}\n\n"
        f"Analyze the above and provide a short, helpful answer."
    )

    # 3. Call API
    try:
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"Error from Gemini API: {e}"

# --- MAIN LOOP ---
print(f"Agent started. Listening for commands on entity: {PROMPT_ENTITY}")
last_command = get_ha_state(PROMPT_ENTITY)

while True:
    try:
        current_command = get_ha_state(PROMPT_ENTITY)
        
        # Check if command changed and is not empty
        if current_command and current_command != last_command and current_command != "unknown":
            print(f"New command detected: {current_command}")
            
            # Update last command immediately to avoid loops
            last_command = current_command
            
            print(f"Processing command: {current_command}")
            send_notification("Analyzing request...", "Gemini Working")
            
            # Analyze
            result = analyze_with_gemini(current_command)
            
            # Reply
            print("Response generated. Sending notification.")
            send_notification(result, "Gemini Report")
            
    except Exception as e:
        print(f"Error in process loop: {e}")
        send_notification(f"Agent crashed: {e}", "Agent Fail")
        time.sleep(10) # Sleep longer on error

    time.sleep(2)