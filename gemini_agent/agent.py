import os
import time
import sys
import json
import sqlite3
import requests
import signal
from datetime import datetime, timedelta
import pytz
from dateutil import parser
from google import genai
from google.genai import types

# --- CONFIG ---
OPTIONS_PATH = "/data/options.json"
DB_PATH = "/data/jarvis_memory.db"
SUPERVISOR_API = "http://supervisor/core/api"
INTERNAL_HA_API = "http://homeassistant:8123/api"

# --- LOGGING ---
def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

# --- SHUTDOWN ---
def handle_exit(*args):
    log("🛑 Stopping Agent...", "WARN")
    sys.exit(0)
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

# --- DATABASE ---
class MemoryDB:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS msgs (id INTEGER PRIMARY KEY, role TEXT, content TEXT, ts TEXT)")
        self.conn.commit()

    def add(self, role, content):
        ts = datetime.now().isoformat()
        self.conn.execute("INSERT INTO msgs (role, content, ts) VALUES (?, ?, ?)", (role, content, ts))
        self.conn.commit()

    def get_last(self, limit=10):
        cur = self.conn.execute("SELECT role, content FROM msgs ORDER BY id DESC LIMIT ?", (limit,))
        return [{"role": r[0], "text": r[1]} for r in reversed(cur.fetchall())]

# --- HA CLIENT ---
class HA:
    def __init__(self):
        self.token = os.getenv("SUPERVISOR_TOKEN")
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        self.tz = pytz.utc
        self._sync_tz()

    def _sync_tz(self):
        try:
            res = requests.get(f"{SUPERVISOR_API}/config", headers=self.headers)
            if res.ok:
                self.tz = pytz.timezone(res.json().get("time_zone", "UTC"))
                log(f"✅ Timezone Detected: {self.tz}")
        except Exception as e:
            log(f"⚠️ TZ Sync Failed: {e}", "ERR")

    def get_state(self, entity_id):
        try:
            res = requests.get(f"{SUPERVISOR_API}/states/{entity_id}", headers=self.headers)
            return res.json().get("state", "") if res.ok else ""
        except: return ""

    def get_all_states(self):
        try:
            res = requests.get(f"{SUPERVISOR_API}/states", headers=self.headers)
            return res.json() if res.ok else []
        except: return []

    def fire_event(self, text):
        try:
            requests.post(f"{SUPERVISOR_API}/events/jarvis_response", headers=self.headers, json={"text": text})
        except: pass

    def get_history(self, start_utc, entity_ids):
        if not entity_ids: return []
        try:
            # Construct URL
            start_str = start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            filter_str = ",".join(entity_ids)
            url = f"{SUPERVISOR_API}/history/period/{start_str}?filter_entity_id={filter_str}&minimal_response&end_time={(start_utc + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
            
            log(f"🔎 Calling History API: Period={start_str} Entities={len(entity_ids)}")
            
            res = requests.get(url, headers=self.headers, timeout=20)
            
            if res.status_code == 401 or res.status_code == 404:
                # Retry Internal
                url = url.replace(SUPERVISOR_API, INTERNAL_HA_API)
                log("⚠️ Supervisor failed, trying Internal API...")
                res = requests.get(url, headers=self.headers, timeout=20)

            if res.ok:
                data = res.json()
                log(f"✅ History Received: Found {len(data)} series.")
                return data
            else:
                log(f"❌ API Error {res.status_code}: {res.text}", "ERR")
                return []
        except Exception as e:
            log(f"🔥 History Exception: {e}", "ERR")
            return []

# --- LOGIC ---
class Brain:
    def __init__(self, ha, db, client):
        self.ha = ha
        self.db = db
        self.client = client

    def think(self, user_text):
        self.db.add("user", user_text)
        
        # 1. Analyze Request
        lower = user_text.lower()
        now_loc = datetime.now(self.ha.tz)
        
        # Default: Lookback 24h
        start_time = now_loc - timedelta(hours=24)
        mode = "POINT" # Point in time (yesterday) vs RANGE (duration)

        if "ώρα" in lower and "τελευταία" in lower:
            start_time = now_loc - timedelta(hours=2)
            mode = "RANGE"
        elif "προχθές" in lower:
            start_time = now_loc - timedelta(hours=48)
        
        # Convert to UTC for API
        start_utc = start_time.astimezone(pytz.utc)

        # 2. Find Entities (Aggressive Search)
        all_states = self.ha.get_all_states()
        targets = []
        
        keywords = {
            "temp": ["temperature", "climate", "°C"],
            "heat": ["climate", "heating"],
            "light": ["light", "switch"],
            "humid": ["humidity", "%"],
            "power": ["power", "energy", "W", "kWh"]
        }
        
        # Detect intent
        wanted_types = []
        if any(x in lower for x in ["θερμοκρασ", "βαθμ", "temp", "κλιμα", "heat"]): wanted_types.extend(keywords["temp"])
        if any(x in lower for x in ["φως", "φώτα", "light"]): wanted_types.extend(keywords["light"])
        
        # Filter entities
        for s in all_states:
            eid = s['entity_id']
            attrs = s.get('attributes', {})
            
            # Skip irrelevant
            if "update" in eid or "device_tracker" in eid: continue

            # Match Logic
            is_match = False
            
            # A. Attribute Match (Unit or Device Class)
            if wanted_types:
                uom = str(attrs.get('unit_of_measurement', ''))
                dc = str(attrs.get('device_class', ''))
                if any(t in uom or t in dc or t in eid for t in wanted_types):
                    is_match = True
            
            # B. Name Match (Fallback)
            if not is_match:
                # Split user query into significant words (len > 3)
                words = [w for w in lower.split() if len(w) > 3]
                if any(w in eid or w in str(attrs.get('friendly_name','')).lower() for w in words):
                    is_match = True

            if is_match: targets.append(eid)

        # Limit to top 20 to save API limits
        targets = targets[:20]
        log(f"🎯 Targeted Entities: {targets}")

        # 3. Fetch History
        hist_txt = "No history data found."
        if targets:
            raw = self.ha.get_history(start_utc, targets)
            parsed = []
            
            for series in raw:
                if not series: continue
                eid = series[0]['entity_id']
                
                # Sample data (First, Middle, Last) to save tokens
                points = [series[0], series[len(series)//2], series[-1]] if len(series) > 3 else series
                
                for p in points:
                    try:
                        val = p['state']
                        if val in ['unknown', 'unavailable']: continue
                        
                        ts_dt = parser.isoparse(p['last_changed'])
                        ts_loc = ts_dt.astimezone(self.ha.tz).strftime("%d/%m %H:%M")
                        
                        parsed.append(f"{eid} [{ts_loc}] = {val}")
                    except: pass
            
            if parsed:
                hist_txt = "\n".join(parsed)

        # 4. Prompt
        prompt = (
            f"Role: Home Assistant Expert.\n"
            f"Context: answering user about past/current home state.\n"
            f"Now: {now_loc.strftime('%Y-%m-%d %H:%M')}\n"
            f"User Asked: {user_text}\n\n"
            f"--- SENSOR HISTORY (Relevant to query) ---\n{hist_txt}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. If user asks about 'yesterday' or 'past', rely ONLY on SENSOR HISTORY.\n"
            f"2. If history is empty, say 'I checked sensors [list names] but found no data for that time'.\n"
            f"3. Do NOT make up numbers.\n"
            f"4. Reply in Greek."
        )

        try:
            resp = self.client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            reply = resp.text.replace("*", "")
            self.db.add("assistant", reply)
            return reply
        except Exception as e:
            log(f"AI Gen Error: {e}", "ERR")
            return "Error generating response."

# --- MAIN ---
if __name__ == "__main__":
    log("🚀 Jarvis v22.0 Starting...")
    
    # Load Options
    try:
        with open(OPTIONS_PATH) as f: opts = json.load(f)
        api_key = opts["gemini_api_key"]
        input_ent = opts["prompt_entity"]
    except:
        log("❌ Config Error", "ERR"); sys.exit(1)

    # Init
    client = genai.Client(api_key=api_key)
    ha = HA()
    db = MemoryDB()
    brain = Brain(ha, db, client)

    log(f"👂 Watching {input_ent}")
    last_val = ha.get_state(input_ent)

    while True:
        try:
            curr = ha.get_state(input_ent)
            if curr and curr != last_val and curr not in ["", "unknown"]:
                log(f"🗣️ Request: {curr}")
                last_val = curr
                
                # PROCESS
                reply = brain.think(curr)
                
                log(f"✅ Reply: {reply[:50]}...")
                ha.fire_event(reply)
                
        except Exception as e:
            log(f"Loop Error: {e}", "ERR")
        
        time.sleep(1)