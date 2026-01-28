import os
import time
import requests
import json
import sqlite3
import google.generativeai as genai
from datetime import datetime, timedelta
import pytz
from dateutil import parser

# --- CONSTANTS ---
OPTIONS_PATH = "/data/options.json"
DB_PATH = "/data/jarvis_memory.db" # Persistent Storage
SUPERVISOR_API = "http://supervisor/core/api"
INTERNAL_HA_API = "http://homeassistant:8123/api"

# --- CLASS: PERSISTENT MEMORY (SQLite) ---
class PersistentMemory:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Δημιουργία πίνακα αν δεν υπάρχει
        c.execute('''CREATE TABLE IF NOT EXISTS conversation
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      timestamp TEXT,
                      role TEXT,
                      content TEXT)''')
        conn.commit()
        conn.close()

    def add_message(self, role, content):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        ts = datetime.utcnow().isoformat()
        c.execute("INSERT INTO conversation (timestamp, role, content) VALUES (?, ?, ?)", 
                  (ts, role, content))
        conn.commit()
        conn.close()

    def get_context(self, limit=10):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT role, content FROM conversation ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        # Επιστροφή με σωστή σειρά (χρονική)
        return [{"role": r[0], "text": r[1]} for r in reversed(rows)]

# --- CLASS: HOME ASSISTANT CLIENT (Native API) ---
class HomeAssistantClient:
    def __init__(self):
        self.token = os.getenv("SUPERVISOR_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self.timezone = pytz.utc # Default
        self._sync_config()

    def _sync_config(self):
        """Τραβάει το configuration του HA για να βρει το Timezone του χρήστη."""
        try:
            print("⚙️ Syncing System Configuration...")
            # Χτυπάμε το API για να βρούμε το timezone
            res = requests.get(f"{SUPERVISOR_API}/config", headers=self.headers)
            if res.status_code == 200:
                data = res.json()
                tz_str = data.get("time_zone", "UTC")
                self.timezone = pytz.timezone(tz_str)
                print(f"✅ System Timezone Detected: {self.timezone}")
            else:
                # Fallback στον Supervisor if core fails
                print("⚠️ Config fetch via Supervisor failed, trying internal...")
                res = requests.get(f"{INTERNAL_HA_API}/config", headers=self.headers)
                if res.status_code == 200:
                    tz_str = res.json().get("time_zone", "UTC")
                    self.timezone = pytz.timezone(tz_str)
                    print(f"✅ System Timezone Detected (Internal): {self.timezone}")
        except Exception as e:
            print(f"❌ Timezone Sync Error: {e}. Defaulting to UTC.")

    def get_local_time(self):
        return datetime.now(self.timezone)

    def fetch_state(self, entity_id):
        try:
            res = requests.get(f"{SUPERVISOR_API}/states/{entity_id}", headers=self.headers, timeout=5)
            return res.json().get("state", "") if res.status_code == 200 else ""
        except: return ""

    def fetch_all_states(self):
        try:
            res = requests.get(f"{SUPERVISOR_API}/states", headers=self.headers, timeout=10)
            return res.json() if res.status_code == 200 else []
        except: return []

    def post_event(self, event_type, data):
        try:
            requests.post(f"{SUPERVISOR_API}/events/{event_type}", headers=self.headers, json=data)
        except Exception as e:
            print(f"❌ Failed to fire event: {e}")

    def get_history(self, start_time_utc, entities):
        """Τραβάει ιστορικό από το native API."""
        try:
            entity_filter = ",".join(entities)
            # API format requires ISO format
            start_iso = start_time_utc.isoformat()
            
            url = f"{SUPERVISOR_API}/history/period/{start_iso}?filter_entity_id={entity_filter}"
            res = requests.get(url, headers=self.headers, timeout=60)
            
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 401 or res.status_code == 404:
                # Fallback to internal IP if supervisor proxy fails
                url = f"{INTERNAL_HA_API}/history/period/{start_iso}?filter_entity_id={entity_filter}"
                res = requests.get(url, headers=self.headers, timeout=60)
                return res.json() if res.status_code == 200 else []
            return []
        except Exception as e:
            print(f"❌ History Fetch Error: {e}")
            return []

# --- CLASS: JARVIS BRAIN (Logic) ---
class JarvisBrain:
    def __init__(self, ha_client, memory, model):
        self.ha = ha_client
        self.memory = memory
        self.model = model

    def _detect_time_intent(self, user_input):
        """
        Αναλύει αν ο χρήστης ρωτάει για 'χθες', 'προχθές' και υπολογίζει το UTC offset.
        Επιστρέφει (start_time_utc, duration_description).
        """
        now_local = self.ha.get_local_time()
        lower_input = user_input.lower()
        
        start_time = now_local - timedelta(hours=24) # Default fallback
        mode = "recent"

        if "χθες" in lower_input or "yesterday" in lower_input:
            # Αν λέει "χθες την ίδια ώρα", πάμε 24 ώρες πίσω
            start_time = now_local - timedelta(hours=24)
            mode = "history_point"
        elif "προχθές" in lower_input:
            start_time = now_local - timedelta(hours=48)
            mode = "history_point"
        elif "ώρα" in lower_input and ("τελευταία" in lower_input or "last" in lower_input):
            start_time = now_local - timedelta(hours=1)
            mode = "history_range"
        
        # Convert to UTC for API
        start_time_utc = start_time.astimezone(pytz.utc)
        return start_time_utc, mode, start_time

    def _identify_entities(self, user_input):
        """Semantic search για να βρει ποια entities αφορά η ερώτηση."""
        all_states = self.ha.fetch_all_states()
        relevant = []
        
        keywords = {
            "θερμοκρασ": ["temperature", "climate", "temp"],
            "θερμανσ": ["climate", "heating"],
            "σαλον": ["salon", "living"],
            "δωματι": ["room", "bed", "child"],
            "φως": ["light"],
            "καταναλωσ": ["energy", "power", "cost"]
        }

        # Βρες λέξεις κλειδιά
        found_types = []
        user_filter_words = []
        for k, v in keywords.items():
            if k in user_input.lower():
                found_types.extend(v)
        
        # Λέξεις για φιλτράρισμα ονόματος (π.χ. "σαλόνι")
        words = user_input.lower().split()
        user_filter_words = [w for w in words if len(w) > 3]

        for s in all_states:
            eid = s['entity_id'].lower()
            attrs = s.get('attributes', {})
            dev_class = str(attrs.get('device_class', ''))
            friendly = str(attrs.get('friendly_name', '')).lower()
            
            # Match Logic
            is_match = False
            
            # Αν βρήκαμε τύπο (π.χ. temperature)
            if found_types:
                if any(t in dev_class or t in eid for t in found_types) or eid.startswith("climate."):
                    is_match = True
            
            # Αν βρήκαμε λέξη τοποθεσίας (π.χ. σαλόνι)
            name_match = any(w in eid or w in friendly for w in user_filter_words)
            
            # Συνδυασμός: Αν ζήτησε θερμοκρασία σαλονιού, πρέπει να ταιριάζει και ο τύπος και το όνομα
            if found_types and user_filter_words:
                 if is_match and name_match: relevant.append(s['entity_id'])
            elif found_types: # Ζήτησε γενικά θερμοκρασίες
                 if is_match: relevant.append(s['entity_id'])
            elif user_filter_words: # Ζήτησε "τι κάνει το σαλόνι"
                 if name_match: relevant.append(s['entity_id'])

        return relevant[:15] # Limit

    def process(self, user_input):
        # 1. Καταγραφή στη μνήμη
        self.memory.add_message("user", user_input)
        
        # 2. Ανάλυση Χρόνου & Entities
        start_utc, mode, start_local = self._detect_time_intent(user_input)
        entities = self._identify_entities(user_input)
        
        history_text = "No relevant history data found."
        
        if entities:
            print(f"🔎 Fetching History for {len(entities)} entities from {start_local}...")
            raw_history = self.ha.get_history(start_utc, entities)
            
            # 3. Parsing History (Smart Filter)
            parsed_lines = []
            for item in raw_history:
                if not item: continue
                eid = item[0]['entity_id']
                
                # Αν ψάχνουμε "την ίδια ώρα χθες", θέλουμε ένα μικρό παράθυρο γύρω από την ώρα-στόχο
                target_window_start = start_utc
                target_window_end = start_utc + timedelta(minutes=60) # Δίνουμε 1 ώρα παράθυρο
                
                for entry in item:
                    try:
                        ts_str = entry['last_changed']
                        ts_dt = parser.isoparse(ts_str) # Aware datetime
                        
                        # Αν είναι μέσα στο παράθυρο που θέλουμε
                        if mode == "history_point":
                            # Ελέγχουμε αν η εγγραφή είναι κοντά στην ώρα στόχο ( π.χ. +/- 30 λεπτά)
                            diff = abs((ts_dt - target_window_start).total_seconds())
                            if diff < 3600: # 1 hour proximity
                                val = entry['state']
                                # Convert timestamp back to User Time for the AI
                                ts_user = ts_dt.astimezone(self.ha.timezone).strftime("%H:%M")
                                parsed_lines.append(f"{eid} at {ts_user}: {val}")
                        else:
                            # Range mode (π.χ. τελευταία ώρα), τα παίρνουμε όλα
                            val = entry['state']
                            ts_user = ts_dt.astimezone(self.ha.timezone).strftime("%H:%M")
                            parsed_lines.append(f"[{ts_user}] {eid}={val}")
                    except: pass
            
            if parsed_lines:
                history_text = "\n".join(parsed_lines[-50:]) # Keep it concise

        # 4. Current State (Context)
        current_states = ""
        # Φέρνουμε μόνο τα entities που βρήκαμε ότι σχετίζονται
        for eid in entities:
            state = self.ha.fetch_state(eid)
            current_states += f"{eid}: {state}\n"

        # 5. Build Prompt
        now_local_str = self.ha.get_local_time().strftime("%Y-%m-%d %H:%M:%S")
        memory_str = "\n".join([f"{m['role']}: {m['text']}" for m in self.memory.get_context()])
        
        prompt = (
            f"Current Time (User TZ): {now_local_str}\n"
            f"User Location Timezone: {self.ha.timezone}\n"
            f"--- CONVERSATION MEMORY ---\n{memory_str}\n"
            f"--- HISTORICAL DATA (Relative to Request) ---\n{history_text}\n"
            f"--- CURRENT LIVE VALUES ---\n{current_states}\n"
            f"--- USER QUESTION ---\n{user_input}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. You are a Professional Home Assistant Analyst.\n"
            f"2. Look at 'HISTORICAL DATA'. If user asks 'Yesterday same time', look for timestamps in data matching yesterday's date/time.\n"
            f"3. Do NOT generalize. Use the specific values found.\n"
            f"4. If data shows temperature 20.5 at 10:00 yesterday, say 'Yesterday at 10:00 it was 20.5°C'.\n"
            f"5. Reply in Greek."
        )

        try:
            response = self.model.generate_content(prompt)
            reply_text = response.text.replace("*", "")
            
            # Save Reply
            self.memory.add_message("assistant", reply_text)
            return reply_text
        except Exception as e:
            return f"Error generating response: {e}"

# --- MAIN EXECUTION ---
def main():
    print("🚀 Starting Jarvis AI Professional (v20.0)...")
    
    # Load Config
    try:
        with open(OPTIONS_PATH, "r") as f: options = json.load(f)
        api_key = options.get("gemini_api_key")
        prompt_entity = options.get("prompt_entity", "input_text.gemini_prompt")
    except:
        print("❌ Critical: Could not load config.")
        exit(1)

    # Initialize Components
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-pro')
    
    mem = PersistentMemory(DB_PATH)
    ha = HomeAssistantClient()
    brain = JarvisBrain(ha, mem, model)

    print(f"👂 Listening on {prompt_entity}")
    last_command = ha.fetch_state(prompt_entity)

    while True:
        try:
            current_command = ha.fetch_state(prompt_entity)
            if current_command and current_command != last_command and current_command not in ["", "unknown"]:
                print(f"🗣️ Processing: {current_command}")
                last_command = current_command
                
                # Processing
                reply = brain.process(current_command)
                
                print(f"✅ Reply: {reply[:50]}...")
                ha.post_event("jarvis_response", {"text": reply})
                
        except Exception as e:
            print(f"🔥 Loop Error: {e}")
            time.sleep(5)
        
        time.sleep(1)

if __name__ == "__main__":
    main()