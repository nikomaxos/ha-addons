import os
import time
import sys
import json
import requests
from datetime import datetime, timedelta
import pytz
from google import genai
from google.genai import types
import unicodedata

# --- CONFIG ---
OPTIONS_PATH = "/data/options.json"
SUPERVISOR_API = "http://supervisor/core/api"
INTERNAL_HA_API = "http://homeassistant:8123/api"
CONFIG_PATH = "/config"

# --- LOGGING ---
def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

# --- HELPER ---
def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

# --- HA CLIENT ---
class HA:
    def __init__(self, override_token=None):
        self.token = override_token if override_token else os.getenv("SUPERVISOR_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        if override_token:
            self.base_url = INTERNAL_HA_API
            log("🔑 Using Long-Lived Access Token (Direct API Mode)")
        else:
            self.base_url = SUPERVISOR_API
            log("🔐 Using Supervisor Token (Add-on Mode)")

        self._debug_connectivity()
        self._sync_tz()

    def _debug_connectivity(self):
        log(f"🕵️ DIAGNOSTIC: Testing API access ({self.base_url})...")
        try:
             # Check Core API (admin access)
            res = requests.get(f"{self.base_url}/config", headers=self.headers, timeout=5)
            log(f"   -> Core API (Config): {res.status_code}")
            if not res.ok: 
                 log(f"   -> Body: {res.text}")
        except Exception as e:
            log(f"   -> Network Error: {e}")

    def _sync_tz(self):
        try:
            res = requests.get(f"{self.base_url}/config", headers=self.headers, timeout=5)
            if res.ok:
                self.tz = pytz.timezone(res.json().get("time_zone", "UTC"))
                log(f"✅ Timezone Detected: {self.tz}")
            else:
                self.tz = pytz.utc
                log(f"⚠️ TZ Sync Failed: {res.status_code}, using UTC", "WARN")
                log(f"   -> Response: {res.text}", "WARN")
                log(f"   -> Token present: {bool(self.token)}", "WARN")
        except Exception as e:
            self.tz = pytz.utc
            log(f"⚠️ TZ Sync Error: {e}, using UTC", "WARN")

    def get_state(self, entity_id):
        try:
            url = f"{self.base_url}/states/{entity_id}"
            res = requests.get(url, headers=self.headers, timeout=5)
            if res.ok:
                return res.json().get("state", "unknown")
            return "NOT_FOUND"
        except Exception as e:
            log(f"Error getting state: {e}", "ERR")
            return "ERROR"
            
    def find_entities(self, keyword):
        """Search for entities matching a keyword."""
        try:
            url = f"{self.base_url}/states"
            res = requests.get(url, headers=self.headers, timeout=5)
            if res.ok:
                all_states = res.json()
                matches = []
                
                # Normalize keyword: lowercase + remove accents
                def normalize(s):
                    return remove_accents(s.lower())

                terms = normalize(keyword).split()
                
                for entity in all_states:
                    eid = normalize(entity.get('entity_id', ''))
                    friendly = normalize(entity.get('attributes', {}).get('friendly_name', ''))
                    domain = eid.split('.')[0]
                    device_class = normalize(entity.get('attributes', {}).get('device_class', ''))
                    
                    # Search text includes ID, Name, Domain, and Device Class
                    # We also add 'thermostat' alias for climate domain
                    aliases = "thermostat temperature" if domain == "climate" else ""
                    
                    search_text = f"{eid} {friendly} {domain} {device_class} {aliases}"
                    
                    # Match if ALL terms are present
                    if all(term in search_text for term in terms):
                         matches.append(f"{entity['entity_id']} ({entity.get('attributes', {}).get('friendly_name', 'No Name')}): {entity['state']}")
                
                if not matches:
                    return f"No matching entities found for '{keyword}'. Strategy hint: Search for just the location (e.g. 'living room') without the device type."
                return "\n".join(matches[:50]) # Limit to 50 results
            return "Error fetching states."
        except Exception as e:
            return f"Exception finding entities: {e}"

    def get_history(self, entity_id, days_back=1):
        """Get history for an entity."""
        try:
            start_time = (datetime.now(self.tz) - timedelta(days=days_back)).isoformat()
            url = f"{self.base_url}/history/period/{start_time}"
            params = {"filter_entity_id": entity_id, "end_time": datetime.now(self.tz).isoformat()}
            
            res = requests.get(url, headers=self.headers, params=params, timeout=10)
            if res.ok:
                data = res.json()
                if not data or not data[0]:
                    return f"No history found for {entity_id}"
                
                # Simplify data for LLM
                simplified = []
                for entry in data[0]:
                    simplified.append(f"{entry.get('last_changed')}: {entry.get('state')}")
                return "\n".join(simplified[-100:]) # Return last 100 entries to fit context
            return f"Error fetching history: {res.text}"
        except Exception as e:
            return f"Exception fetching history: {e}"

    def call_service(self, domain, service, service_data=None):
        """Call a Home Assistant service."""
        try:
            url = f"{self.base_url}/services/{domain}/{service}"
            res = requests.post(url, headers=self.headers, json=service_data or {}, timeout=10)
            if res.ok:
                return f"Service {domain}.{service} called successfully."
            return f"Failed to call service: {res.status_code} - {res.text}"
        except Exception as e:
            return f"Exception calling service: {e}"

    def list_files(self, path="."):
        """List files in the config directory."""
        try:
            full_path = os.path.join(CONFIG_PATH, path)
            if not os.path.exists(full_path):
                return "Path does not exist."
            
            items = []
            for item in os.listdir(full_path):
                items.append(item)
            return "\n".join(items)
        except Exception as e:
            return f"Error listing files: {e}"

    def read_file(self, path):
        """Read a file from the config directory."""
        try:
            full_path = os.path.join(CONFIG_PATH, path)
            if not os.path.exists(full_path):
                return "File does not exist."
            
            with open(full_path, "r") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(self, path, content):
        """Write content to a file in the config directory."""
        try:
            full_path = os.path.join(CONFIG_PATH, path)
            with open(full_path, "w") as f:
                f.write(content)
            return f"File {path} written successfully."
        except Exception as e:
            return f"Error writing file: {e}"

    def fire_event(self, event_type, event_data):
        try:
            requests.post(f"{self.base_url}/events/{event_type}", headers=self.headers, json=event_data, timeout=5)
        except: pass


# --- GEMINI CLIENT ---
class GeminiAgent:
    def __init__(self, api_key, ha_client):
        self.client = genai.Client(api_key=api_key)
        self.ha = ha_client
        self.model_name = "gemini-2.0-flash" 

        # Define Tools
        self.tools = [
            # Discovery Tool
            types.Tool(
                function_declarations=[
                     types.FunctionDeclaration(
                        name="find_entities",
                        description="[FALLBACK ONLY] Search for entities when NO entity ID was provided in the user's request. Use the SAME LANGUAGE as the request for keywords (e.g., if user asks in Greek, search in Greek).",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "keyword": types.Schema(type=types.Type.STRING, description="Keywords in the user's original language (e.g., 'σαλόνι θερμοκρασία' for Greek, 'living room temperature' for English)"),
                            },
                            required=["keyword"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="get_history",
                        description="Get the state history of a Home Assistant entity for analysis.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "entity_id": types.Schema(type=types.Type.STRING, description="The entity ID (e.g., sensor.temperature)"),
                                "days_back": types.Schema(type=types.Type.INTEGER, description="Number of days to look back (default 1)"),
                            },
                            required=["entity_id"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="call_service",
                        description="Call a Home Assistant service to control devices or run scripts.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "domain": types.Schema(type=types.Type.STRING, description="The service domain (e.g., light, switch, automation)"),
                                "service": types.Schema(type=types.Type.STRING, description="The service name (e.g., turn_on, trigger)"),
                                "service_data": types.Schema(type=types.Type.OBJECT, description="Data/parameters for the service call"),
                            },
                            required=["domain", "service"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="list_files",
                        description="List files in the Home Assistant configuration directory.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "path": types.Schema(type=types.Type.STRING, description="Subdirectory path to list (default root)"),
                            }
                        )
                    ),
                    types.FunctionDeclaration(
                        name="read_file",
                        description="Read the content of a configuration file.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "path": types.Schema(type=types.Type.STRING, description="Relative path to the file"),
                            },
                            required=["path"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="write_file",
                        description="Write content to a configuration file (Overwrite or Create).",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "path": types.Schema(type=types.Type.STRING, description="Relative path to the file"),
                                "content": types.Schema(type=types.Type.STRING, description="The content to write"),
                            },
                            required=["path", "content"]
                        )
                    ),
                ]
            )
        ]
        
        self.system_instruction = """You are Jarvis, an advanced AI Home Assistant Agent with deep system access.

**YOUR ROLE:**
You handle complex tasks that require:
- Historical data analysis (get_history)
- System file operations (read_file, write_file, list_files)
- Advanced service calls (call_service)
- Automation/script creation

**ENTITY RESOLUTION STRATEGY:**
1. **Check if entity IDs are already in the request** (e.g., "sensor.thermokrasia_saloniou_2", "climate.living_room")
   - If provided: USE THEM DIRECTLY. Do not search.
2. **Only use `find_entities` as a FALLBACK** when:
   - No entity ID is mentioned in the request, AND
   - You need an entity to complete the task
3. When searching with `find_entities`:
   - Use the SAME LANGUAGE as the user's request
   - Try location-specific terms first (e.g., "σαλόνι", "saloni" for Greek)
   - If that fails, try English equivalents

**IMPORTANT RULES:**
- **LANGUAGE**: Always reply in the SAME LANGUAGE as the user's request
- **TRUST THE CONTEXT**: If an entity ID is provided in the request, it's already been resolved. Use it directly.
- **AUTONOMY**: Use tools to complete tasks without asking the user for clarification
- **HELPFULNESS**: Provide clear, human-readable summaries of your actions
"""

    def process_request(self, prompt):
        log(f"🤖 Processing with Gemini: {prompt[:50]}...")
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=self.tools,
                    system_instruction=self.system_instruction
                )
            )
            
            # Handle Function Calls logic manually if needed, or let the library handle chat. 
            # For simplicity in this loop, we handle single-turn tool use or simplest flow.
            # The 'google-genai' library 0.2+ handles automatic tool execution if using chat, 
            # but here we might need to manually invoke if managing state.
            
            # Let's simple implementation: Check for tool calls
            final_text = ""
            
            # Check for function calls in candidates
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        fc = part.function_call
                        fn_name = fc.name
                        args = fc.args
                        
                        log(f"🛠️ Tool Call: {fn_name}({args})")
                        
                        # Execute Tool
                        result = "Error: Tool execution failed"
                        if fn_name == "get_history":
                            result = self.ha.get_history(args.get("entity_id"), args.get("days_back", 1))
                        elif fn_name == "call_service":
                            result = self.ha.call_service(args.get("domain"), args.get("service"), args.get("service_data"))
                        elif fn_name == "list_files":
                            result = self.ha.list_files(args.get("path", "."))
                        elif fn_name == "read_file":
                            result = self.ha.read_file(args.get("path"))
                        elif fn_name == "write_file":
                            result = self.ha.write_file(args.get("path"), args.get("content"))
                        elif fn_name == "find_entities":
                            result = self.ha.find_entities(args.get("keyword"))
                            
                        log(f"  -> Result: {str(result)[:50]}...")
                        
                        # Send result back to Gemini (simplified manual turn)
                        # In a real chat app we'd append to history. 
                        # Here we just do a follow-up generate for summary.
                        
                        response2 = self.client.models.generate_content(
                            model=self.model_name,
                            contents=[
                                types.Content(role="user", parts=[types.Part(text=prompt)]),
                                response.candidates[0].content, # The model's tool call
                                types.Content(role="tool", parts=[types.Part(function_response=types.FunctionResponse(name=fn_name, response={"result": result}))])
                            ],
                            config=types.GenerateContentConfig(tools=self.tools)
                        )
                        if response2.text:
                             final_text += response2.text

                    elif part.text:
                        final_text += part.text

            return final_text if final_text else "Processed action."

        except Exception as e:
            log(f"Gemini Error: {e}", "ERR")
            return f"I encountered an error: {e}"


# --- MAIN ---
if __name__ == "__main__":
    log("🚀 Jarvis Agent Starting...")
    
    # Load Options
    try:
        with open(OPTIONS_PATH) as f: opts = json.load(f)
        input_ent = opts.get("prompt_entity", "input_text.gemini_prompt")
        api_key = opts.get("gemini_api_key")
        ha_token = opts.get("ha_token")
    except:
        log("❌ Config Error: Could not read options.json", "ERR"); sys.exit(1)

    if not api_key:
        log("❌ No Gemini API Key found!", "ERR")
        # Loop mainly to keep container alive and warn user
        while True: time.sleep(60)

    ha = HA(override_token=ha_token)
    agent = GeminiAgent(api_key, ha)
    
    log(f"👀 Watching: {input_ent}")
    
    # startup diagnostic
    initial_state = ha.get_state(input_ent)
    log(f"🔍 Startup Check: {input_ent} = '{initial_state}'")

    while True:
        try:
            curr = ha.get_state(input_ent)
            
            # Trigger Logic: Any non-empty text starts the flow.
            # We ignore "NOT_FOUND", "TIMEOUT", "unknown", "ERROR" and empty string "".
            if curr not in ["NOT_FOUND", "TIMEOUT", "unknown", "ERROR", ""]:
                log(f"⚡ Request: '{curr}'")
                
                # 1. Process
                response_text = agent.process_request(curr)
                
                # 2. Respond
                log(f"🗣️ Response: {response_text}")
                ha.fire_event("jarvis_response", {"text": response_text, "original_request": curr})
                
                # 3. RESET INPUT
                # We clear the input text so we are ready for the next request.
                # This prevents looping on the same old request and allows re-triggering.
                log(f"🧹 Clearing {input_ent}...")
                ha.call_service("input_text", "set_value", {"entity_id": input_ent, "value": ""})
                
                # Wait a bit to ensure HA processes the clear before we poll again
                time.sleep(2)

        except Exception as e:
            log(f"🔥 Loop Error: {e}", "ERR")
        
        time.sleep(1)