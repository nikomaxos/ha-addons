import os
import time
import json
import requests
import google.generativeai as genai
import sys

# --- LOAD CONFIG ---
try:
    with open("/data/options.json", "r") as f:
        options = json.load(f)
except:
    options = {}

GEMINI_API_KEY = options.get("gemini_api_key")
PROMPT_ENTITY = options.get("prompt_entity", "input_text.gemini_prompt")

# HA API SETUP
HA_URL = "http://supervisor/core/api"
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "content-type": "application/json",
}

# --- HELPER FUNCTIONS ---

def send_notification(message, title="Gemini Agent"):
    print(f"NOTIFY: {title} - {message}")
    # Truncate message to avoid HA API limits (4096 chars usually)
    safe_message = message[:4000]
    payload = {"message": safe_message, "title": title}
    try:
        requests.post(f"{HA_URL}/services/persistent_notification/create", headers=HEADERS, json=payload)
    except Exception as e:
        print(f"Error sending notification: {e}")

def get_history(entity_id):
    # Get last 24h history
    from datetime import datetime, timedelta
    start = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    try:
        url = f"{HA_URL}/history/period/{start}?filter_entity_id={entity_id}"
        res = requests.get(url, headers=HEADERS)
        data = res.json()
        if not data: return "No history found."
        
        # Simplify data to save tokens (keep only time and state)
        simple = [{"t": x["last_updated"], "s": x["state"]} for x in data[0]]
        # Limit to 15k characters to avoid blowing up the context window
        return str(simple)[:15000] 
    except Exception as e:
        return f"Error getting history: {str(e)}"

def read_config_file(filename):
    try:
        # Security check: prevent reading outside /config
        if ".." in filename or filename.startswith("/"):
            return "Security Error: Cannot read outside config folder."
            
        with open(f"/config/{filename}", "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

# --- MAIN LOGIC ---

def process_command(command):
    print(f"Processing command: {command}")
    send_notification("Analyzing request...", "Gemini Working")
    
    if not GEMINI_API_KEY:
        send_notification("Error: Gemini API Key is missing in configuration.", "Config Error")
        return

    # Configure Gemini
    # We use 'gemini-1.5-pro' as it is fast and cheap on tokens
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-pro')
    except Exception as e:
        send_notification(f"Model Config Error: {e}", "Gemini Error")
        return
    
    # Phase 1: Tool Selection Strategy
    # We ask the AI to decide IF it needs data and WHAT data.
    tool_prompt = f"""
    You are a Home Assistant Expert Agent.
    User Request: "{command}"
    
    Determine if you need to inspect the system to answer.
    Available Tools:
    - READ:filename  (e.g., READ:automations.yaml, READ:configuration.yaml) -> Use this to see config code.
    - HIST:entity_id (e.g., HIST:climate.thermostat, HIST:sensor.power) -> Use this to analyze trends/history (last 24h).
    - STATE:entity_id (e.g., STATE:sun.sun, STATE:zone.home) -> Use this to check current value/attributes.
    - NONE -> Use this if the user is just asking a general question or chatting.
    
    OUTPUT FORMAT:
    Reply ONLY with the tool code. If you need multiple, pick the SINGLE most critical one.
    Example: READ:automations.yaml
    """
    
    try:
        res1 = model.generate_content(tool_prompt)
        tool_req = res1.text.strip()
        print(f"AI requested tool: {tool_req}")
        
        context_data = "No additional system data retrieved."
        
        # Execute Tool
        if "READ:" in tool_req:
            fname = tool_req.split(":")[1].strip()
            content = read_config_file(fname)
            context_data = f"--- CONTENT OF {fname} ---\n{content}\n--- END OF FILE ---"
            
        elif "HIST:" in tool_req:
            eid = tool_req.split(":")[1].strip()
            hist = get_history(eid)
            context_data = f"--- HISTORY FOR {eid} (Last 24h) ---\n{hist}\n--- END OF HISTORY ---"
            
        elif "STATE:" in tool_req:
            eid = tool_req.split(":")[1].strip()
            try:
                r = requests.get(f"{HA_URL}/states/{eid}", headers=HEADERS)
                context_data = f"--- CURRENT STATE OF {eid} ---\n{r.text}\n--- END OF STATE ---"
            except Exception as e:
                context_data = f"Error fetching state: {e}"
        
        # Phase 2: Final Analysis
        final_prompt = f"""
        You are a smart Home Assistant assistant.
        
        USER COMMAND: "{command}"
        
        SYSTEM DATA RETRIEVED (Context):
        {context_data}
        
        INSTRUCTIONS:
        1. Answer the user's request based on the context provided.
        2. If you see an error in the logs/history, point it out.
        3. If the user asked for optimization (like heating), analyze the numbers.
        4. Keep the answer concise but technical if needed.
        """
        
        res2 = model.generate_content(final_prompt)
        final_answer = res2.text
        
        # Send result back to HA
        send_notification(final_answer, "Gemini Result")
        
    except Exception as e:
        print(f"Error in process loop: {e}")
        send_notification(f"Agent crashed: {str(e)}", "Agent Fail")

def main():
    print("Agent started. Listening for commands on entity: " + PROMPT_ENTITY)
    
    # Init loop variables
    last_cmd = ""
    
    # Main Loop
    while True:
        try:
            r = requests.get(f"{HA_URL}/states/{PROMPT_ENTITY}", headers=HEADERS)
            
            if r.status_code == 200:
                data = r.json()
                curr = data.get("state", "")
                
                # Logic: Only process if state is valid, not empty, and CHANGED from last time
                if curr and curr not in ["unknown", "unavailable", ""] and curr != last_cmd:
                    print(f"New command detected: {curr}")
                    last_cmd = curr # Update last command so we don't loop forever
                    process_command(curr)
            else:
                print(f"Warning: Could not read {PROMPT_ENTITY}. Status: {r.status_code}")
                
        except Exception as e:
            print(f"Loop error: {e}")
            
        # Sleep to prevent high CPU usage
        time.sleep(5)

if __name__ == "__main__":
    main()
