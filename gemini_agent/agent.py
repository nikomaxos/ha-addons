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
import traceback
import threading

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
            
    def get_bulk_states(self):
        """Fetch simplified states of key domains for proactive AI analysis."""
        try:
            url = f"{self.base_url}/states"
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.ok:
                all_states = res.json()
                simplified = {}
                for s in all_states:
                    domain = s["entity_id"].split(".")[0]
                    if domain in ["light", "switch", "climate", "sensor", "media_player", "person", "cover", "lock", "water_heater"]:
                        simplified[s["entity_id"]] = {
                            "state": s["state"],
                            "name": s["attributes"].get("friendly_name")
                        }
                return json.dumps(simplified, ensure_ascii=False)
            return "{}"
        except Exception as e:
            log(f"Bulk state error: {e}", "ERR")
            return "{}"

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
            # Secure path resolution to stay inside CONFIG_PATH
            safe_path = path.lstrip("/\\") if path else "."
            full_path = os.path.abspath(os.path.join(CONFIG_PATH, safe_path))
            
            if not full_path.startswith(CONFIG_PATH):
                return "Error: Path is outside the config directory."
            
            if not os.path.exists(full_path):
                return f"Path does not exist: {safe_path}"
            
            items = []
            for item in os.listdir(full_path):
                items.append(item)
            return "\n".join(items) if items else "Directory is empty."
        except Exception as e:
            return f"Error listing files: {e}"

    def read_file(self, path):
        """Read a file from the config directory."""
        try:
            safe_path = path.lstrip("/\\")
            full_path = os.path.abspath(os.path.join(CONFIG_PATH, safe_path))
            
            if not full_path.startswith(CONFIG_PATH):
                return "Error: Path is outside the config directory."
                
            if not os.path.exists(full_path):
                return "File does not exist."
            
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(self, path, content):
        """Write content to a file in the config directory."""
        try:
            safe_path = path.lstrip("/\\")
            full_path = os.path.abspath(os.path.join(CONFIG_PATH, safe_path))
            
            if not full_path.startswith(CONFIG_PATH):
                return "Error: Path is outside the config directory."
                
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"File {safe_path} written successfully."
        except Exception as e:
            return f"Error writing file: {e}"

    def reload_config(self, domain="automation"):
        """Reload a Home Assistant configuration domain (like automation or script)."""
        try:
            url = f"{self.base_url}/services/{domain}/reload"
            res = requests.post(url, headers=self.headers, timeout=10)
            if res.ok:
                return f"Successfully reloaded {domain}."
            return f"Failed to reload {domain}: {res.status_code} - {res.text}"
        except Exception as e:
            return f"Error reloading config: {e}"

    def fire_event(self, event_type, event_data):
        try:
            requests.post(f"{self.base_url}/events/{event_type}", headers=self.headers, json=event_data, timeout=5)
        except: pass


# --- GEMINI CLIENT ---
class GeminiAgent:
    def __init__(self, api_key, ha_client, model_name="gemini-2.5-pro"):
        self.client = genai.Client(api_key=api_key)
        self.ha = ha_client
        self.model_name = model_name

        # Define Tools
        self.tools = [
            # Discovery Tool
            types.Tool(
                function_declarations=[
                     types.FunctionDeclaration(
                        name="find_entities",
                        description="[FALLBACK ONLY] Search for entities when NO entity ID was provided. If your first search fails, try a SINGLE broad keyword (e.g. 'car' instead of 'car charger cost'). Try English if local language fails.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "keyword": types.Schema(type=types.Type.STRING, description="A single broad keyword to search for (e.g. 'car', 'θερμοσίφωνας')"),
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
                    types.FunctionDeclaration(
                        name="reload_config",
                        description="Reload a Home Assistant configuration domain after creating or modifying YAML files.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "domain": types.Schema(type=types.Type.STRING, description="The domain to reload (e.g., 'automation', 'script', 'core', 'group')"),
                            },
                            required=["domain"]
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
- Zero-Touch Automation/Script creation (Write the file, then call `reload_config`)

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
- **LANGUAGE**: Always reply in the SAME LANGUAGE as the user's request. 
  - NOTE: The request you receive may have been reformulated by the Main Assistant, but it should preserve the original language.
  - If you detect Greek characters (α-ω) in the request, respond in Greek.
  - If the request is in English, respond in English.
- **TRUST THE CONTEXT**: If an entity ID is provided in the request, it's already been resolved. Use it directly.
- **AUTONOMY**: Use tools to complete tasks without asking the user for clarification
- **ZERO-TOUCH CREATION**: When asked to create an automation or script, write the valid YAML to the correct file (e.g., automations.yaml or scripts.yaml), AND THEN IMMEDIATELY call `reload_config` for that domain (e.g., domain="automation") so it takes effect instantly without user input!
- **HELPFULNESS**: Provide clear, human-readable summaries of your actions

**DATA PRESENTATION (VOICE-FRIENDLY):**
When presenting historical data from get_history:
1. **ALWAYS auto-summarize** - Never dump raw timestamps and values
2. **Calculate key statistics**:
   - Average (μέση/average)
   - Minimum with timestamp (ελάχιστη/minimum)
   - Maximum with timestamp (μέγιστη/maximum)
3. **Identify trends**: Was the value increasing, decreasing, or stable?
4. **Keep it concise**: Maximum 5 lines for voice output
5. **Only provide raw data** if user explicitly requests:
   - "δώσε μου όλα τα δεδομένα" / "give me all the data"
   - "show me the raw values"
   - "I need the full list"

**Example Response (Greek)**:
"Χθες το βράδυ στο υπνοδωμάτιο:
- Μέση θερμοκρασία: 24.1°C
- Ελάχιστη: 24.0°C (00:13)
- Μέγιστη: 24.3°C (20:53)
Η θερμοκρασία μειώθηκε σταδιακά κατά τη διάρκεια της νύχτας."
"""

    def process_request(self, prompt):
        log(f"🤖 Processing with Gemini: {prompt[:50]}...")
        try:
            contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=self.tools,
                    system_instruction=self.system_instruction
                )
            )
            
            max_turns = 15
            turns = 0
            
            while turns < max_turns:
                turns += 1
                
                if not response.candidates or not response.candidates[0].content.parts:
                    break
                    
                has_function_call = False
                contents.append(response.candidates[0].content)
                tool_responses = []
                
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        has_function_call = True
                        fc = part.function_call
                        fn_name = fc.name
                        args = fc.args
                        
                        log(f"🛠️ Tool Call: {fn_name}({args})")
                        
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
                        elif fn_name == "reload_config":
                            result = self.ha.reload_config(args.get("domain", "automation"))
                        elif fn_name == "find_entities":
                            result = self.ha.find_entities(args.get("keyword"))
                            
                        log(f"  -> Result: {str(result)[:50]}...")
                        
                        tool_responses.append(
                            types.Part(function_response=types.FunctionResponse(name=fn_name, response={"result": result}))
                        )
                
                if has_function_call:
                    contents.append(types.Content(role="tool", parts=tool_responses))
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(tools=self.tools, system_instruction=self.system_instruction)
                    )
                else:
                    break
                    
            final_text = ""
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        final_text += part.text
                        
            return final_text if final_text else "Processed action."

        except Exception as e:
            log(f"Gemini Error: {e}", "ERR")
            return f"I encountered an error: {e}"


# --- PROACTIVE ENGINE ---
def is_dnd_active(tz, start_str, end_str):
    """Check if current time is within DND hours."""
    try:
        now = datetime.now(tz).time()
        start = datetime.strptime(start_str, "%H:%M").time()
        end = datetime.strptime(end_str, "%H:%M").time()
        
        if start <= end:
            return start <= now <= end
        else: # Crosses midnight
            return start <= now or now <= end
    except Exception as e:
        log(f"DND Parse Error: {e}", "WARN")
        return False

def proactive_worker(agent_instance, ha_instance, opts):
    interval_hours = int(opts.get("proactive_interval_hours", 12))
    speaker = opts.get("proactive_media_player", "media_player.living_room_speaker")
    tts_service = opts.get("proactive_tts_service", "tts.google_en_com")
    dnd_start = opts.get("proactive_dnd_start", "22:00")
    dnd_end = opts.get("proactive_dnd_end", "08:00")
    
    log(f"🧠 Proactive Engine Initialized (Interval: {interval_hours}h)")
    log(f"💤 Proactive Engine sleeping for {interval_hours} hours. (A proposal will be generated after this time).")
    
    # Optional debug rapid-fire mode: if interval_hours is 0, test it every minute
    sleep_seconds = interval_hours * 3600 if interval_hours > 0 else 60
    
    while True:
        time.sleep(sleep_seconds)
        log("🔍 Proactive Engine waking up to analyze home state...")
        
        # Check DND
        if is_dnd_active(ha_instance.tz, dnd_start, dnd_end):
            log(f"🤫 DND is active ({dnd_start}-{dnd_end}). Skipping proactive analysis.")
            continue
            
        try:
            states = ha_instance.get_bulk_states()
            prompt = f"""
            SYSTEM: You are the autonomous proactive engine of Jarvis, the Smart Home AI.
            Analyze the following current state of the user's home:
            {states}
            
            Identify ONE single actionable efficiency, energy-saving, or convenience proposal.
            Respond ONLY with the spoken text of the proposal. Do not include markdown or explanations.
            You MUST use the SAME LANGUAGE as the user's primary interface (e.g. Greek if entity names are Greek, English otherwise).
            Make the proposal conversational, friendly, and brief (like a smart butler speaking).
            
            Example: 'Παρατήρησα ότι τα φώτα στο σαλόνι είναι ανοιχτά αλλά δεν υπάρχει κανείς εκεί. Να τα κλείσω;'
            """
            
            response = agent_instance.client.models.generate_content(
                model=agent_instance.model_name,
                contents=prompt
            )
            
            if response.text:
                proposal = response.text.replace('"', '').replace('`', '').strip()
                log(f"💡 Proactive Proposal Generated: {proposal}")
                
                 # Send event (for UI/Dashboard logging)
                ha_instance.fire_event("jarvis_proactive_proposal", {"text": proposal})
                
                # Directly Speak the Proposal via Native TTS target!
                domain, srv = tts_service.split('.')
                tts_data = {
                    "entity_id": tts_service,
                    "media_player_entity_id": speaker,
                    "message": proposal
                }
                res = ha_instance.call_service(domain, srv, tts_data)
                log(f"📢 Proactive TTS Triggered: {res}")
                
        except Exception as e:
            log(f"Proactive Engine Error: {e}", "ERR")

# --- MAIN ---
if __name__ == "__main__":
    log("🚀 Jarvis Agent Starting...")
    
    # Load Options
    try:
        with open(OPTIONS_PATH) as f: opts = json.load(f)
        input_ent = opts.get("prompt_entity", "input_text.gemini_prompt")
        api_key = opts.get("gemini_api_key")
        gemini_model = opts.get("gemini_model", "gemini-2.5-pro")
        ha_token = opts.get("ha_token")
    except:
        log("❌ Config Error: Could not read options.json", "ERR"); sys.exit(1)

    if not api_key:
        log("❌ No Gemini API Key found!", "ERR")
        # Loop mainly to keep container alive and warn user
        while True: time.sleep(60)

    ha = HA(override_token=ha_token)
    agent = GeminiAgent(api_key, ha, gemini_model)
    
    # Start Proactive Engine
    t = threading.Thread(target=proactive_worker, args=(agent, ha, opts), daemon=True)
    t.start()
    
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
            err_msg = traceback.format_exc()
            log(f"🔥 Loop Error: {e}\n{err_msg}", "ERR")
            try:
                crash_path = os.path.join(CONFIG_PATH, "jarvis_crash_reports.txt")
                with open(crash_path, "a") as f:
                    f.write(f"\n\n=== CRASH REPORT {datetime.now()} ===\n{err_msg}")
                ha.fire_event("jarvis_response", {"text": "Αντιμετώπισα ένα κρίσιμο σφάλμα Python. Έχω αποθηκεύσει την αναφορά σφάλματος στο jarvis_crash_reports.txt για τον προγραμματιστή μου.", "original_request": "CRASH"})
            except: pass
        
        time.sleep(1)