import os
import time
import requests
import json
import sqlite3
import signal
import sys
from google import genai # Νέα βιβλιοθήκη
from datetime import datetime, timedelta
import pytz
from dateutil import parser

# --- CONSTANTS ---
OPTIONS_PATH = "/data/options.json"
DB_PATH = "/data/jarvis_memory.db"
SUPERVISOR_API = "http://supervisor/core/api"
INTERNAL_HA_API = "http://homeassistant:8123/api"

# --- GRACEFUL SHUTDOWN ---
def handle_sigterm(*args):
    print("🛑 Received Shutdown Signal. Exiting...")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

# --- CLASS: PERSISTENT MEMORY ---
class PersistentMemory:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
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
        return [{"role": r[0], "text": r[1]} for r in reversed(rows)]

# --- CLASS: HA CLIENT ---
class HomeAssistantClient:
    def __init__(self):
        self.token = os.getenv("SUPERVISOR_TOKEN")
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        self.timezone = pytz.utc
        self._sync_config()

    def _sync_config(self):
        try:
            print("⚙️ Syncing Timezone...")
            res = requests.get(f"{SUPERVISOR_API}/config", headers=self.headers)
            if res.status_code == 200:
                self.timezone = pytz.timezone(res.json().get("time_zone", "UTC"))
                print(f"✅ Timezone: {self.timezone}")
            else:
                res = requests.get(f"{INTERNAL_HA_API}/config", headers=self.headers)
                if res.status_code == 200:
                    self.timezone = pytz.timezone(res.json().get("time_zone", "UTC"))
                    print(f"✅ Timezone (Internal): {self.timezone}")
        except: print("⚠️ Timezone Sync Failed. Using UTC.")

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
        try: requests.post(f"{SUPERVISOR_API}/events/{event_type}", headers=self.headers, json=data)
        except: pass

    def get_history(self, start_utc, entities):
        try:
            entity_filter = ",".join(entities)
            start_iso = start_utc.isoformat()
            url = f"{SUPERVISOR_API}/history/period/{start_iso}?filter_entity_id={entity_filter}"
            res = requests.get(url, headers=self.headers, timeout=30)
            if res.status_code == 200: return res.json()
            url = f"{INTERNAL_HA_API}/history/period/{start_iso}?filter_entity_id={entity_filter}"
            res = requests.get(url, headers=self.headers, timeout=30)
            return res.json() if res.status_code == 200 else []
        except: return []

# --- CLASS: BRAIN ---
class JarvisBrain:
    def __init__(self, ha, mem, client):
        self.ha = ha
        self.mem = mem
        self.client = client # Google GenAI Client

    def process(self, user_input):
        self.mem.add_message("user", user_input)
        
        # 1. Detect Time Intent
        now_local = self.ha.get_local_time()
        lower_input = user_input.lower()
        start_time = now_local - timedelta(hours=24)
        mode = "recent"

        if "χθες" in lower_input or "yesterday" in lower_input:
            start_time = now_local - timedelta(hours=24)
            mode = "point"
        elif "προχθές" in lower_input:
            start_time = now_local - timedelta(hours=48)
            mode = "point"
        elif "ώρα" in lower_input and ("τελευταία" in lower_input or "last" in lower_input):
            start_time = now_local - timedelta(hours=1)
            mode = "range"
        
        start_utc = start_time.astimezone(pytz.utc)

        # 2. Identify Entities
        all_states = self.ha.fetch_all_states()
        relevant_ids = []
        keywords = {
            "θερμοκρασ": ["temperature", "climate"], "θερμανσ": ["climate", "heating"],
            "φως": ["light"], "διακοπτ": ["switch"],
            "σαλον": ["living", "salon"], "δωματι": ["room", "bed"]
        }
        found_types = [t for k, t in keywords.items() if k in lower_input]
        found_types = [item for sublist in found_types for item in sublist]
        user_words = [w for w in lower_input.split() if len(w) > 3]

        for s in all_states:
            eid = s['entity_id'].lower()
            attrs = s.get('attributes', {})
            dev_class = str(attrs.get('device_class', ''))
            match = False
            if found_types and any(t in dev_class or t in eid for t in found_types): match = True
            if not match and any(w in eid for w in user_words): match = True
            if match: relevant_ids.append(s['entity_id'])

        relevant_ids = relevant_ids[:15]
        
        # 3. Fetch History
        history_text = "No history."
        if relevant_ids:
            print(f"🔎 Fetching History for: {relevant_ids} (Mode: {mode})")
            raw_data = self.ha.get_history(start_utc, relevant_ids)
            lines = []
            for item in raw_data:
                if not item: continue
                eid = item[0]['entity_id']
                for entry in item:
                    try:
                        ts = parser.isoparse(entry['last_changed'])
                        is_relevant = True
                        if mode == "point":
                            if abs((ts - start_utc).total_seconds()) > 2700: is_relevant = False
                        if is_relevant:
                            local_ts = ts.astimezone(self.ha.timezone).strftime("%H:%M")
                            lines.append(f"{eid} at {local_ts}: {entry['state']}")
                    except: pass
            if lines: history_text = "\n".join(lines[-60:])

        # 4. Current State
        current_text = "\n".join([f"{eid}: {self.ha.fetch_state(eid)}" for eid in relevant_ids])

        # 5. Prompt
        prompt = (
            f"Role: Professional Home Assistant Analyst.\n"
            f"Time Now: {now_local.strftime('%Y-%m-%d %H:%M')} ({self.ha.timezone})\n"
            f"--- MEMORY ---\n{'\n'.join([f'{m['role']}: {m['text']}' for m in self.mem.get_context()])}\n"
            f"--- HISTORY DATA ---\n{history_text}\n"
            f"--- CURRENT DATA ---\n{current_text}\n"
            f"--- QUESTION ---\n{user_input}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Use HISTORY DATA to answer 'yesterday/past' questions.\n"
            f"2. Compare specific timestamps found in data.\n"
            f"3. Reply in Greek."
        )

        try:
            # NEW GOOGLE GENAI CALL
            response = self.client.models.generate_content(
                model='gemini-2.0-flash', 
                contents=prompt
            )
            reply = response.text.replace("*", "")
            self.mem.add_message("assistant", reply)
            return reply
        except Exception as e:
            return f"AI Error: {e}"

# --- MAIN ---
if __name__ == "__main__":
    print("🚀 Jarvis AI Pro v21.1 (Modern API) Starting...")
    
    try:
        with open(OPTIONS_PATH, "r") as f: opts = json.load(f)
        api_key = opts["gemini_api_key"]
        prompt_entity = opts.get("prompt_entity", "input_text.gemini_prompt")
    except:
        print("❌ Config Error.")
        sys.exit(1)

    # Initialize New Client
    client = genai.Client(api_key=api_key)
    mem = PersistentMemory(DB_PATH)
    ha = HomeAssistantClient()
    brain = JarvisBrain(ha, mem, client)

    print(f"👂 Monitoring {prompt_entity}")
    last_val = ha.fetch_state(prompt_entity)

    while True:
        try:
            curr = ha.fetch_state(prompt_entity)
            if curr and curr != last_val and curr not in ["", "unknown"]:
                print(f"🗣️ New Request: {curr}")
                last_val = curr
                reply = brain.process(curr)
                print(f"✅ Reply: {reply[:50]}...")
                ha.post_event("jarvis_response", {"text": reply})
        except Exception as e:
            print(f"🔥 Loop Error: {e}")
        time.sleep(1)