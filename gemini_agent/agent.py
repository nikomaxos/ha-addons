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

# --- CONFIG ---
OPTIONS_PATH = "/data/options.json"
DB_PATH = "/data/jarvis_memory.db"
SUPERVISOR_API = "http://supervisor/core/api"
INTERNAL_HA_API = "http://homeassistant:8123/api"

# --- LOGGING ---
def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

# --- HA CLIENT ---
class HA:
    def __init__(self):
        self.token = os.getenv("SUPERVISOR_TOKEN")
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        self.tz = pytz.utc
        self._sync_tz()

    def _sync_tz(self):
        try:
            res = requests.get(f"{SUPERVISOR_API}/config", headers=self.headers, timeout=5)
            if res.ok:
                self.tz = pytz.timezone(res.json().get("time_zone", "UTC"))
                log(f"✅ Timezone Detected: {self.tz}")
        except: log("⚠️ TZ Sync Failed, using UTC", "WARN")

    def get_state(self, entity_id):
        # Τώρα χρησιμοποιούμε TIMEOUT για να μην κολλάει το loop
        try:
            url = f"{SUPERVISOR_API}/states/{entity_id}"
            res = requests.get(url, headers=self.headers, timeout=3) # Timeout 3 sec
            
            if res.status_code == 200:
                return res.json().get("state", "unknown")
            elif res.status_code == 404:
                return "NOT_FOUND"
            else:
                return f"ERROR_{res.status_code}"
        except requests.exceptions.Timeout:
            return "TIMEOUT"
        except Exception as e:
            return f"EXCEPTION: {e}"

    def get_history(self, start_utc, entity_ids):
        # ... (Ο κώδικας ιστορικού παραμένει ίδιος, τον αφαιρώ για συντομία στο debug) ...
        # Για το debug μας ενδιαφέρει τώρα η λήψη της εντολής, όχι το ιστορικό.
        return [] 
    
    def fire_event(self, text):
        try:
            requests.post(f"{SUPERVISOR_API}/events/jarvis_response", headers=self.headers, json={"text": text}, timeout=5)
        except: pass

# --- MAIN ---
if __name__ == "__main__":
    log("🚀 Jarvis v23.0 (DEBUG LOOP) Starting...")
    
    # Load Options
    try:
        with open(OPTIONS_PATH) as f: opts = json.load(f)
        input_ent = opts["prompt_entity"]
    except:
        log("❌ Config Error", "ERR"); sys.exit(1)

    ha = HA()
    log(f"👀 WATCHING TARGET: {input_ent}")

    last_val = "INITIAL_STARTUP"

    while True:
        try:
            # 1. Διαβάζουμε την τρέχουσα τιμή
            curr = ha.get_state(input_ent)
            
            # DEBUG PRINT: Τυπώνουμε τι βλέπουμε κάθε φορά (για να δούμε αν δουλεύει το API)
            log(f"🔍 DEBUG PROBE: {input_ent} = '{curr}'")

            # 2. Έλεγχος αλλαγής
            if curr not in ["NOT_FOUND", "TIMEOUT", "unknown", "", last_val]:
                log(f"⚡ TRIGGER DETECTED! Old: '{last_val}' -> New: '{curr}'")
                last_val = curr
                
                # Απάντηση Test (για να δούμε αν φτάνει μέχρι εδώ)
                log("✅ Sending Test Reply...")
                ha.fire_event(f"Ελήφθη: {curr}. Το σύστημα λειτουργεί.")

        except Exception as e:
            log(f"🔥 CRITICAL LOOP ERROR: {e}", "ERR")
        
        # Περιμένουμε 3 δευτερόλεπτα
        time.sleep(3)