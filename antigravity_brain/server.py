import os
import sys
import datetime

class TimestampedStream:
    _is_timestamped = True

    def __init__(self, stream):
        self.stream = stream
        self.at_line_start = True

    def write(self, data):
        if not data:
            return
        lines = data.split('\n')
        for i, line in enumerate(lines):
            if i > 0:
                self.stream.write('\n')
                self.at_line_start = True
            if line:
                if self.at_line_start:
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.stream.write(f"[{now}] ")
                    self.at_line_start = False
                self.stream.write(line)

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return getattr(self.stream, 'isatty', lambda: False)()

if not getattr(sys.stdout, '_is_timestamped', False):
    sys.stdout = TimestampedStream(sys.stdout)
if not getattr(sys.stderr, '_is_timestamped', False):
    sys.stderr = TimestampedStream(sys.stderr)

import json
import time
import uuid
import subprocess
import re
import threading
import logging
import uvicorn
import requests as http_requests

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "/api/status" not in msg and "/health" not in msg

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from collections import deque, OrderedDict
from dataclasses import dataclass, field
import memory_manager
from auth_manager import CodexAuthManager, AntigravityAuthManager
from dashboard_html import get_dashboard_html

@dataclass
class ConversationState:
    messages: list = field(default_factory=list)
    last_access: float = field(default_factory=time.monotonic)

CONVERSATIONS: OrderedDict[str, ConversationState] = OrderedDict()
SESSION_TTL_SECONDS = 3600  # 1 hour
MAX_CONVERSATIONS = 1000
MAX_MESSAGES_PER_SESSION = 20

def get_or_create_conversation(conv_id: str) -> ConversationState:
    now = time.monotonic()
    if len(CONVERSATIONS) > 0:
        oldest_conv = next(iter(CONVERSATIONS.values()))
        if now - oldest_conv.last_access > SESSION_TTL_SECONDS or len(CONVERSATIONS) > MAX_CONVERSATIONS:
            expired_keys = [k for k, v in CONVERSATIONS.items() if (now - v.last_access > SESSION_TTL_SECONDS)]
            for k in expired_keys:
                CONVERSATIONS.pop(k, None)
            while len(CONVERSATIONS) >= MAX_CONVERSATIONS:
                CONVERSATIONS.popitem(last=False)

    if conv_id not in CONVERSATIONS:
        CONVERSATIONS[conv_id] = ConversationState()
    state = CONVERSATIONS[conv_id]
    state.last_access = now
    CONVERSATIONS.move_to_end(conv_id)
    return state

from tool_broker import tool_broker, install_cli_helpers
from delegation import (
    DelegationEnvelope,
    REASON_HISTORICAL_ANALYSIS,
    REASON_EXTERNAL_RESEARCH,
    REASON_ENTITY_NOT_FOUND,
    REASON_MULTI_STEP_ANALYSIS,
    REASON_LOW_CONFIDENCE,
    REASON_TOOL_FAILURE,
    REASON_GENERAL_ESCALATION,
)

# Install CLI helpers for Codex / terminal agents
install_cli_helpers()

memory_manager.init_db()

# ---------------------------------------------------------------------------
# Model mapping & Normalization
# ---------------------------------------------------------------------------
MODEL_MAP = {
    # Gemini models
    "gemini-3.8-flash": "gemini-3.8-flash",
    "gemini-3.1-pro": "gemini-3.1-pro-preview",
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini-2.0-flash": "gemini-2.0-flash",

    # OpenAI modern models (2026 generation)
    "gpt-6-luna": "gpt-6-luna",
    "gpt-6.1-sol": "gpt-6.1-sol",
    "gpt-6-astra": "gpt-6-astra",

    # OpenAI other models
    "o3-mini": "o3-mini",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4.5-preview": "gpt-4.5-preview",
    "o1": "o1",
    "gpt-5": "gpt-5",
    "o3": "o3",

    # Legacy saved names
    "3.8 flash high": "gemini-3.8-flash",
    "3.8 flash": "gemini-3.8-flash",
    "3.1 pro high": "gemini-3.1-pro-preview",
    "3.1 pro": "gemini-3.1-pro-preview",

    # Existing internal alias
    "antigravity": "antigravity-preview-latest",
}

MODEL_OPTION_ALIASES = {
    "3.8 flash high": "gemini-3.8-flash",
    "3.8 flash": "gemini-3.8-flash",
    "3.1 pro high": "gemini-3.1-pro",
    "3.1 pro": "gemini-3.1-pro",
}

def _normalize_model_option(value, default):
    """Return a clean option name while accepting legacy saved values."""
    if not isinstance(value, str) or not value.strip():
        return default
    normalized = " ".join(value.strip().lower().split())
    return MODEL_OPTION_ALIASES.get(normalized, value.strip())

# ---------------------------------------------------------------------------
# Load addon options from HA options.json
# ---------------------------------------------------------------------------
OPTIONS_PATH = "/data/options.json"
DEFAULT_API_KEY = "YOUR_API_KEY_HERE"
DEFAULT_MODEL = "gemini-3.8-flash"
PORT = 8000

options = {}
if os.path.exists(OPTIONS_PATH):
    with open(OPTIONS_PATH, "r") as f:
        options = json.load(f)

# Phase 1: Fast Agent Settings
fast_agent_engine = options.get("fast_agent_engine", "gemini_api")
fast_agent_model = _normalize_model_option(
    options.get("fast_agent_model", options.get("model", DEFAULT_MODEL)),
    DEFAULT_MODEL
)
fast_agent_thinking = options.get("fast_agent_thinking", "low")
fast_agent_token = (
    options.get("fast_agent_api_key", "")
    or options.get("fast_agent_token", "")
    or options.get("gemini_api_key", "")
    or DEFAULT_API_KEY
)
fast_agent_api_key = fast_agent_token

# Phase 2: Heavy Agent Settings
heavy_agent_engine = options.get("heavy_agent_engine", "codex_fallback")
heavy_agent_model = _normalize_model_option(
    options.get("heavy_agent_model", "auto"),
    "auto"
)
heavy_agent_thinking = options.get("heavy_agent_thinking", "high")

# Legacy compatibility
api_key = fast_agent_token
selected_model = fast_agent_model
PORT = options.get("api_port", PORT)



# Supervisor API access (available inside addon containers with hassio_api: true)

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

SUPERVISOR_URL = "http://supervisor/core/api"

codex_mgr = CodexAuthManager(supervisor_url=SUPERVISOR_URL, get_supervisor_token_fn=lambda: SUPERVISOR_TOKEN)
agy_mgr = AntigravityAuthManager(supervisor_url=SUPERVISOR_URL, get_supervisor_token_fn=lambda: SUPERVISOR_TOKEN)
recent_tasks = deque(maxlen=20)

GOOGLE_AI_VOICE_IDS = {
    "zephyr", "puck", "charon", "kore", "fenrir", "leda", "orus", "aoede",
    "callirrhoe", "autonoe", "enceladus", "iapetus", "umbriel", "algieba",
    "despina", "erinome", "algenib", "rasalgethi", "laomedeia", "achernar",
    "alnilam", "schedar", "gacrux", "pulcherrima", "achird", "zubenelgenubi",
    "vindemiatrix", "sadachbia", "sadaltager", "sulafat"
}

def get_tts_config():
    """Retrieve current TTS engine and voice from options.json or default."""
    engine = "tts.google_cloud"
    voice = "el-GR-Chirp3-HD-Laomedeia"
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, "r") as f:
                opts = json.load(f)
            engine = opts.get("tts_engine", engine)
            voice = opts.get("tts_voice", voice)
        except Exception:
            pass

    normalized_voice = voice
    if engine == "tts.google_ai_tts" and voice:
        first_token = voice.split()[0].lower()
        if first_token in GOOGLE_AI_VOICE_IDS:
            normalized_voice = first_token

    return engine, normalized_voice

def check_reauth_flags():
    """Check if reauth was requested via Add-on Settings tab (options.json)."""
    if not os.path.exists(OPTIONS_PATH):
        return
    try:
        with open(OPTIONS_PATH, "r") as f:
            opts = json.load(f)
        needs_save = False
        if opts.get("reauth_codex"):
            print("[Settings Tab] 'reauth_codex' enabled! Triggering Codex CLI auth flow...", flush=True)
            codex_mgr.start_auth_flow(force=True)
            opts["reauth_codex"] = False
            needs_save = True

        if opts.get("reauth_antigravity"):
            print("[Settings Tab] 'reauth_antigravity' enabled! Triggering Antigravity CLI auth flow...", flush=True)
            agy_mgr.start_auth_flow(force=True)
            opts["reauth_antigravity"] = False
            needs_save = True

        if needs_save:
            with open(OPTIONS_PATH, "w") as f:
                json.dump(opts, f, indent=2)
    except Exception as e:
        print(f"[Settings Tab] Error checking reauth flags: {e}", flush=True)

def _options_watcher():
    """Background thread watching for options changes."""
    last_mtime = 0
    while True:
        try:
            if os.path.exists(OPTIONS_PATH):
                mtime = os.path.getmtime(OPTIONS_PATH)
                if mtime != last_mtime:
                    last_mtime = mtime
                    check_reauth_flags()
        except Exception:
            pass
        time.sleep(3)

threading.Thread(target=_options_watcher, daemon=True).start()
check_reauth_flags()






# ---------------------------------------------------------------------------

# Configure the Gemini client

# ---------------------------------------------------------------------------

from google import genai



client = genai.Client(api_key=api_key)



# ---------------------------------------------------------------------------

# Tool implementations

# ---------------------------------------------------------------------------



def _supervisor_headers():

    """Headers for Supervisor/HA Core API calls."""

    return {

        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",

        "Content-Type": "application/json",

    }





def tool_query_database(query: str) -> str:
    """Run a READ-ONLY SQL query on the HA MariaDB database via tool_broker."""
    return tool_broker.query_database_readonly(query)


def tool_call_ha_service(domain: str, service: str, service_data: dict = None) -> str:
    """Call a Home Assistant service via tool_broker."""
    return tool_broker.call_ha_service(domain, service, service_data)


def tool_get_ha_states(entity_id: str = "") -> str:
    """Get current states of HA entities via tool_broker."""
    return tool_broker.get_ha_states(entity_id)


def tool_search_radio_browser(query: str) -> str:
    """Search for a radio station using the Radio Browser API (built-in to HA)."""
    try:
        import requests
        res = requests.get(f"https://de1.api.radio-browser.info/json/stations/search?name={query}", timeout=5)
        if res.status_code == 200:
            data = res.json()
            if not data:
                return "No stations found."
            output = []
            for d in data[:5]:
                output.append(f"Name: {d.get('name')}\nStream URL: {d.get('url_resolved')}")
            return "\n\n".join(output)
        return f"API Error: HTTP {res.status_code}"
    except Exception as e:
        return f"Error searching radio: {e}"


def tool_search_web(query: str) -> str:
    """Search the web using DuckDuckGo via tool_broker."""
    return tool_broker.search_web(query)





def tool_keep_mic_open() -> str:

    """Fire the keep_mic_open_event event to keep the microphone open for follow-up."""

    if not SUPERVISOR_TOKEN:

        return "Error: SUPERVISOR_TOKEN not available."

    url = f"{SUPERVISOR_URL}/events/keep_mic_open_event"

    try:

        resp = http_requests.post(url, headers=_supervisor_headers(), json={}, timeout=5)

        if resp.status_code == 200:

            return "Microphone will stay open for follow-up."

        return f"Error firing event: HTTP {resp.status_code}"

    except Exception as e:

        return f"Error: {e}"





def tool_execute_shell(command: str) -> str:

    """Execute a shell command inside the Home Assistant addon container."""

    try:

        result = subprocess.run(command, shell=True, capture_output=True, text=True)

        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    except Exception as e:

        return f"Error executing shell command: {e}"









def tool_store_memory(fact: str) -> str:
    import memory_manager
    return memory_manager.store_memory(fact, api_key)


def tool_play_music(query: str, player: str = None) -> str:
    import music_bridge
    return music_bridge.play_music(query, player=player)


def tool_control_music(action: str, player: str = None, volume: float = None) -> str:
    import music_bridge
    return music_bridge.control_music(action, player=player, volume=volume)



def _execute_codex_cli(task_description: str, thinking_level: str = "high") -> tuple[str, bool]:
    """Execute Codex CLI non-interactively.
    Returns (output_text, limit_or_error_exceeded).
    """
    import shutil
    codex_bin = None
    for cand in ["/data/codex", "./codex", "/usr/src/app/codex", "codex", "codex.exe"]:
        if os.path.exists(cand) or shutil.which(cand):
            codex_bin = cand
            break

    if not codex_bin:
        print("[Heavy Agent - Codex] Codex binary not found in container, falling back.", flush=True)
        return "", True

    if not codex_mgr.is_authenticated:
        if not codex_mgr.check_status():
            print("[Heavy Agent - Codex] Codex CLI is not authenticated! Triggering autonomous auth flow...", flush=True)
            if codex_mgr.auth_state in ["expired", "idle"] or not codex_mgr.auth_pending:
                codex_mgr.start_auth_flow(force=True)
            return "Απαιτείται σύνδεση του Codex CLI στο Home Assistant.", True

    out_file = "/tmp/codex_out.txt"
    if os.path.exists(out_file):
        try:
            os.remove(out_file)
        except Exception:
            pass

    full_prompt = (
        f"You are the autonomous Antigravity Heavy Brain of Home Assistant, running directly inside the container as a powerful terminal AI agent.\n\n"
        f"TASK TO SOLVE:\n{task_description}\n\n"
        "CAPABILITIES & TOOLS AVAILABLE IN YOUR SHELL:\n"
        "You have full terminal access and can execute any bash command to fetch data, calculate, and solve the task:\n"
        "1. Home Assistant REST API (via Supervisor):\n"
        "   - Query entity states: curl -s -H \"Authorization: Bearer $SUPERVISOR_TOKEN\" http://supervisor/core/api/states | jq .\n"
        "   - Query specific entity: curl -s -H \"Authorization: Bearer $SUPERVISOR_TOKEN\" http://supervisor/core/api/states/<entity_id> | jq .\n"
        "   - Query history: curl -s -H \"Authorization: Bearer $SUPERVISOR_TOKEN\" 'http://supervisor/core/api/history/period/<ISO_TIMESTAMP>?filter_entity_id=<entity_id>' | jq .\n"
        "2. MariaDB Database (Full historical sensor data, long-term statistics & energy records):\n"
        "   - Execute SQL: mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e \"SELECT ...\"\n"
        "   - Tables: statistics_meta (metadata_id, statistic_id, unit_of_measurement), statistics (metadata_id, start_ts, state, sum, min, max, mean), statistics_short_term, states (entity_id, state, last_updated_ts), states_meta.\n"
        "3. Web Search & Data Processing:\n"
        "   - Use python3 with urllib or ddgs, curl, jq, etc., to search the web or process data.\n"
        "4. Playing Music / Audio / Radio via Music Assistant & YouTube Streaming:\n"
        "   - CRITICAL: Home Assistant satellite speakers (e.g. `media_player.antigravity_satellites` / ESPHome) DO NOT support raw YouTube web URLs (https://www.youtube.com/...). Never send raw YouTube web URLs to media_player.play_media!\n"
        "   - Use the unified CLI tool available in your PATH: `ha-music`\n"
        "     * Play radio / song / playlist: ha-music play \"<query>\" [--player satellites|tv|hisense]\n"
        "       Examples: ha-music play \"Imagine 89.7\", ha-music play \"Paidaki 97.5\", ha-music play \"Queen Bohemian Rhapsody\"\n"
        "     * Playback controls: ha-music pause, ha-music resume, ha-music stop, ha-music next, ha-music volume 50\n"
        "     * Direct YouTube caching: ha-play-youtube \"<YouTube URL or Song Title>\" [target_entity_id]\n"
        "   - ha-music automatically searches Music Assistant first, streams live radio, and seamlessly falls back to cached YouTube audio streaming.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. NEVER give up or say you lack access to Home Assistant! Use your shell tools to inspect states, query the database, calculate the metrics, and deliver the answer.\n"
        "2. ALL RESPONSES MUST BE IN GREEK (Ελληνικά).\n"
        "3. Output your final answer STRICTLY as a JSON object containing TWO fields:\n"
        "   - `markdown_response`: Full detailed analysis with formatting, numbers, tables or bullet points for the Home Assistant UI notification.\n"
        "   - `spoken_response`: Clear, natural, conversational spoken Greek WITHOUT asterisks, markdown, hashes, or technical symbols, suitable for HD text-to-speech."
    )

    print(f"[Heavy Agent - Codex] Running Codex CLI (thinking: {thinking_level}) for: {task_description[:80]}...", flush=True)
    cmd = [
        codex_bin, "exec",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "-o", out_file,
    ]
    if heavy_agent_model and heavy_agent_model != "auto":
        cmd.extend(["-m", heavy_agent_model])
    cmd.append(full_prompt)
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
        combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")

        url_match = re.search(r'(https://[^\s]+(?:auth|device|login)[^\s]+)', combined_output)
        if url_match:
            print("\n" + "=" * 60, flush=True)
            print("⚠️ CODEX LOGIN REQUIRED! ⚠️", flush=True)
            print(f"Please open this link in your browser to authenticate:\n{url_match.group(1)}", flush=True)
            print("=" * 60 + "\n", flush=True)

        lower_out = combined_output.lower()
        if "rate limit exceeded" in lower_out or "quota exceeded" in lower_out or "insufficient_quota" in lower_out or "too many requests" in lower_out or "status 429" in lower_out or "error 429" in lower_out:
            print("[Heavy Agent - Codex] Rate limit or quota exceeded detected!", flush=True)
            return combined_output, True

        if proc.returncode != 0:
            print(f"[Heavy Agent - Codex] Error/non-zero return code ({proc.returncode}): {proc.stderr[:200]}", flush=True)
            return combined_output, True

        clean_out = ""
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8", errors="replace") as f:
                clean_out = f.read().strip()

        return clean_out or proc.stdout.strip(), False
    except subprocess.TimeoutExpired:
        print("[Heavy Agent - Codex] Timed out after 120s.", flush=True)
        return "Codex process timed out.", True
    except Exception as e:
        print(f"[Heavy Agent - Codex] Execution failed: {e}", flush=True)
        return str(e), True


def _run_autonomous_startup_auth():
    """Check Codex & Antigravity login on boot. If unauthenticated, autonomously trigger device auth flow."""
    time.sleep(2)
    try:
        if not codex_mgr.check_status():
            print("\n" + "=" * 60, flush=True)
            print("⚠️ CODEX AUTHENTICATION REQUIRED ON STARTUP! ⚠️", flush=True)
            print("Triggering autonomous device code flow & HA notifications...", flush=True)
            print("=" * 60 + "\n", flush=True)
            codex_mgr.start_auth_flow()
        else:
            print("[Startup] Codex CLI is authenticated and ready!", flush=True)
    except Exception as e:
        print(f"[Startup] Codex auth check error: {e}", flush=True)

    time.sleep(1)
    try:
        if not agy_mgr.check_status():
            print("\n" + "=" * 60, flush=True)
            print("⚠️ ANTIGRAVITY AUTHENTICATION REQUIRED ON STARTUP! ⚠️", flush=True)
            print("Triggering autonomous Google auth flow & HA notifications...", flush=True)
            print("=" * 60 + "\n", flush=True)
            agy_mgr.start_auth_flow()
        else:
            print("[Startup] Antigravity CLI is authenticated and ready!", flush=True)
    except Exception as e:
        print(f"[Startup] Antigravity auth check error: {e}", flush=True)

threading.Thread(target=_run_autonomous_startup_auth, daemon=True).start()


def _execute_antigravity_cli(task_description: str, thinking_level: str = "high") -> tuple[str, bool]:
    """Execute Antigravity CLI non-interactively."""
    import shutil
    agy_bin = None
    for cand in ["/data/agy", "./agy", "/usr/local/bin/agy", "/usr/src/app/agy", "agy", "antigravity"]:
        if os.path.exists(cand) or shutil.which(cand):
            agy_bin = cand
            break

    if not agy_bin:
        print("[Heavy Agent - Antigravity] Antigravity binary not found in container.", flush=True)
        return "", True

    if not agy_mgr.is_authenticated:
        if not agy_mgr.check_status():
            print("[Heavy Agent - Antigravity] Antigravity CLI is not authenticated! Triggering auth flow...", flush=True)
            if agy_mgr.auth_state in ["expired", "idle"] or not agy_mgr.auth_pending:
                agy_mgr.start_auth_flow(force=True)
            return "Απαιτείται σύνδεση του Antigravity CLI στο Home Assistant.", True

    full_prompt = (
        f"You are the autonomous Antigravity Heavy Brain of Home Assistant, running directly inside the container as a powerful terminal AI agent.\n\n"
        f"TASK TO SOLVE:\n{task_description}\n\n"
        "CAPABILITIES & TOOLS AVAILABLE IN YOUR SHELL:\n"
        "You have full terminal access and can execute any bash command to fetch data, calculate, and solve the task:\n"
        "1. Home Assistant REST API (via Supervisor):\n"
        "   - Query entity states: curl -s -H \"Authorization: Bearer $SUPERVISOR_TOKEN\" http://supervisor/core/api/states | jq .\n"
        "   - Query specific entity: curl -s -H \"Authorization: Bearer $SUPERVISOR_TOKEN\" http://supervisor/core/api/states/<entity_id> | jq .\n"
        "   - Query history: curl -s -H \"Authorization: Bearer $SUPERVISOR_TOKEN\" 'http://supervisor/core/api/history/period/<ISO_TIMESTAMP>?filter_entity_id=<entity_id>' | jq .\n"
        "2. MariaDB Database (Full historical sensor data, long-term statistics & energy records):\n"
        "   - Execute SQL: mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e \"SELECT ...\"\n"
        "   - Tables: statistics_meta (metadata_id, statistic_id, unit_of_measurement), statistics (metadata_id, start_ts, state, sum, min, max, mean), statistics_short_term, states (entity_id, state, last_updated_ts), states_meta.\n"
        "3. Web Search & Data Processing:\n"
        "   - Use python3 with urllib or ddgs, curl, jq, etc., to search the web or process data.\n"
        "4. Playing Music / Audio / Radio via Music Assistant & YouTube Streaming:\n"
        "   - CRITICAL: Home Assistant satellite speakers (e.g. `media_player.antigravity_satellites` / ESPHome) DO NOT support raw YouTube web URLs (https://www.youtube.com/...). Never send raw YouTube web URLs to media_player.play_media!\n"
        "   - Use the unified CLI tool available in your PATH: `ha-music`\n"
        "     * Play radio / song / playlist: ha-music play \"<query>\" [--player satellites|tv|hisense]\n"
        "       Examples: ha-music play \"Imagine 89.7\", ha-music play \"Paidaki 97.5\", ha-music play \"Queen Bohemian Rhapsody\"\n"
        "     * Playback controls: ha-music pause, ha-music resume, ha-music stop, ha-music next, ha-music volume 50\n"
        "     * Direct YouTube caching: ha-play-youtube \"<YouTube URL or Song Title>\" [target_entity_id]\n"
        "   - ha-music automatically searches Music Assistant first, streams live radio, and seamlessly falls back to cached YouTube audio streaming.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. NEVER give up or say you lack access to Home Assistant! Use your shell tools to inspect states, query the database, calculate the metrics, and deliver the answer.\n"
        "2. ALL RESPONSES MUST BE IN GREEK (Ελληνικά).\n"
        "3. Output your final answer STRICTLY as a JSON object containing TWO fields:\n"
        "   - `markdown_response`: Full detailed analysis with formatting, numbers, tables or bullet points for the Home Assistant UI notification.\n"
        "   - `spoken_response`: Clear, natural, conversational spoken Greek WITHOUT asterisks, markdown, hashes, or technical symbols, suitable for HD text-to-speech."
    )

    print(f"[Heavy Agent - Antigravity] Running Antigravity CLI for: {task_description[:80]}...", flush=True)
    cmd = [agy_bin, "--dangerously-skip-permissions", "--print", full_prompt]
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
        combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")

        url_match = re.search(r'(https://[^\s]+(?:auth|device|login)[^\s]+)', combined_output)
        if url_match:
            print("\n" + "=" * 60, flush=True)
            print("⚠️ ANTIGRAVITY LOGIN REQUIRED! ⚠️", flush=True)
            print(f"Please open this link in your browser to authenticate:\n{url_match.group(1)}", flush=True)
            print("=" * 60 + "\n", flush=True)

        lower_out = combined_output.lower()
        if "rate limit exceeded" in lower_out or "quota exceeded" in lower_out or "insufficient_quota" in lower_out or "too many requests" in lower_out or "status 429" in lower_out or "error 429" in lower_out:
            return combined_output, True

        if proc.returncode != 0:
            return combined_output, True

        return proc.stdout.strip(), False
    except Exception as e:
        return str(e), True




def _run_heavy_agent(task_or_envelope, is_voice: bool = True):
    import threading
    start_time = time.time()
    
    if isinstance(task_or_envelope, DelegationEnvelope):
        envelope = task_or_envelope
        task_description = envelope.user_query
        full_context_prompt = envelope.to_heavy_prompt()
    else:
        task_description = str(task_or_envelope)
        full_context_prompt = task_description

    task_id = str(uuid.uuid4())[:8]
    task_record = {
        "id": task_id,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task": task_description,
        "status": "running",
        "duration": 0
    }
    recent_tasks.appendleft(task_record)

    print(f"[Heavy Agent] Starting task: {task_description}")

    system_instruction = (
        "You are the Antigravity Heavy Agent running inside a Home Assistant add-on container. "
        "CRITICAL: ALL YOUR RESPONSES MUST BE IN GREEK (Ελληνικά). Never use English in your final answer to the user. "
        "Your task is to autonomously solve complex problems. You have access to tools including "
        "execute_shell, query_database, render_template, get_ha_history, call_ha_service, get_ha_states, and search_web. "
        "You have absolute freedom and MUST use your tools dynamically to solve problems. "
        "You have absolute freedom to interact with Home Assistant. You can use the `execute_shell` tool with `curl` to query or control the Home Assistant REST API at `http://supervisor/core/api/...` using the `$SUPERVISOR_TOKEN` environment variable (e.g., `curl -H 'Authorization: Bearer $SUPERVISOR_TOKEN' http://supervisor/core/api/states`), or use helper commands: ha-template, ha-query, ha-history, ha-db. "
        "If the user asks you to wait or set a timer/reminder, you MUST use `execute_shell` to run `sleep <seconds>` "
        "or write a background python script to actually block execution for the requested time. "
        "Do not just reply that you did it, do it! "
        "Work through the problem step by step. When you have achieved the goal or encountered a fatal error, "
        "output your final answer strictly as a JSON object containing TWO fields: `markdown_response` (a detailed markdown response) and `spoken_response` (a conversational, TTS-friendly version without asterisks, hashes, or markdown formatting)."
    )

    heavy_tools_schema = [
        {
            "function_declarations": [
                {
                    "name": "execute_shell",
                    "description": "Execute a shell command inside the Home Assistant addon container (Alpine Linux). Available helper CLI tools: ha-query, ha-template, ha-history, ha-db.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "command": {"type": "STRING", "description": "The shell command to execute."}
                        },
                        "required": ["command"]
                    }
                },
                {
                    "name": "query_database",
                    "description": "Run a READ-ONLY SQL SELECT query on the Home Assistant MariaDB database to get historical data about energy consumption, temperatures, costs, etc.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "query": {"type": "STRING", "description": "The SQL SELECT query to execute."},
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "render_template",
                    "description": "Evaluate a Jinja2 template in Home Assistant. Extremely powerful: can inspect any entity state, attributes, forecasts, or calculate formulas (e.g. {{ states('weather.forecast_home') }}).",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "template": {"type": "STRING", "description": "The Jinja2 template string."}
                        },
                        "required": ["template"]
                    }
                },
                {
                    "name": "get_ha_history",
                    "description": "Fetch historical state transitions for an entity over the past N hours.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "entity_id": {"type": "STRING", "description": "The entity_id to inspect."},
                            "hours": {"type": "INTEGER", "description": "Number of past hours (default: 24)."}
                        },
                        "required": ["entity_id"]
                    }
                },
                {
                    "name": "get_ha_states",
                    "description": "Get current state and attributes of an entity or list all entities.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "entity_id": {"type": "STRING", "description": "Entity ID. Leave empty for all."}
                        }
                    }
                },
                {
                    "name": "call_ha_service",
                    "description": "Call a Home Assistant service/action.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "domain": {"type": "STRING", "description": "Service domain."},
                            "service": {"type": "STRING", "description": "Service name."},
                            "service_data": {"type": "OBJECT", "description": "Service payload."}
                        },
                        "required": ["domain", "service"]
                    }
                },
                {
                    "name": "search_web",
                    "description": "Search the web using DuckDuckGo.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "query": {"type": "STRING", "description": "The search query."}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "store_memory",
                    "description": "Store an important user preference or fact into the memory database.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "fact": {"type": "STRING", "description": "The fact to remember."}
                        },
                        "required": ["fact"]
                    }
                }
            ]
        }
    ]
    
    heavy_dispatch = {
        "execute_shell": lambda args: tool_execute_shell(args.get("command", "")),
        "query_database": lambda args: tool_broker.query_database_readonly(args.get("query", "")),
        "render_template": lambda args: tool_broker.render_template(args.get("template", "")),
        "get_ha_history": lambda args: tool_broker.get_ha_history(args.get("entity_id", ""), args.get("hours", 24)),
        "get_ha_states": lambda args: tool_broker.get_ha_states(args.get("entity_id", "")),
        "call_ha_service": lambda args: tool_broker.call_ha_service(args.get("domain", ""), args.get("service", ""), args.get("service_data")),
        "search_web": lambda args: tool_broker.search_web(args.get("query", "")),
        "store_memory": lambda args: tool_store_memory(args.get("fact", "")),
    }

    config = {
        "system_instruction": system_instruction,
        "tools": heavy_tools_schema,
    }

    chat_history = [
        {"role": "user", "parts": [{"text": f"Task:\n{full_context_prompt}"}]}
    ]

    final_result = ""

    # 1. Attempt Codex CLI if configured
    if heavy_agent_engine in ["codex_fallback", "codex_only"]:
        print(f"[Heavy Agent] Evaluating task with Codex CLI (thinking: {heavy_agent_thinking})...", flush=True)
        codex_out, limit_or_error = _execute_codex_cli(full_context_prompt, heavy_agent_thinking)
        if not limit_or_error and codex_out:
            final_result = codex_out
        elif limit_or_error:
            print("[Heavy Agent] Codex CLI hit limit, quota, or is unavailable. Proceeding to fallback...", flush=True)

    # 2. Attempt Antigravity CLI if configured or after Codex limit
    if not final_result and heavy_agent_engine in ["codex_fallback", "antigravity_only"]:
        print(f"[Heavy Agent] Evaluating task with Antigravity CLI (thinking: {heavy_agent_thinking})...", flush=True)
        agy_out, limit_or_error = _execute_antigravity_cli(full_context_prompt, heavy_agent_thinking)
        if not limit_or_error and agy_out:
            final_result = agy_out
        elif limit_or_error:
            print("[Heavy Agent] Antigravity CLI hit limit or unavailable. Falling back to Gemini Pro agent...", flush=True)

    if not final_result:
        if heavy_agent_model == "auto":
            fallback_model = "gemini-3.1-pro-preview"
        else:
            fallback_model = MODEL_MAP.get(heavy_agent_model, heavy_agent_model)
            if fallback_model.startswith("gpt-") or fallback_model in ["o3", "o1"]:
                fallback_model = "gemini-3.1-pro-preview"
        print(f"[Heavy Agent] Running fallback model: {fallback_model}...", flush=True)
        try:
            MAX_STEPS = 15
            for step in range(MAX_STEPS):
                print(f"[Heavy Agent] Step {step+1}: Calling generate_content...", flush=True)
                response = client.models.generate_content(
                    model=fallback_model,
                    contents=chat_history,
                    config=config
                )
                print(f"[Heavy Agent] Step {step+1}: generate_content returned.", flush=True)

                candidate = response.candidates[0]
                function_calls = []

                for part in candidate.content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        function_calls.append(part.function_call)

                if not function_calls:
                    final_result = response.text
                    break

                function_responses = []
                for fc in function_calls:
                    fn_name = fc.name
                    fn_args = dict(fc.args) if fc.args else {}
                    print(f"[Heavy Agent Tool Call] {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:200]})", flush=True)

                    handler = heavy_dispatch.get(fn_name)
                    if handler:
                        try:
                            res = handler(fn_args)
                        except Exception as e:
                            res = f"Tool error: {e}"
                    else:
                        res = f"Unknown tool: {fn_name}"

                    print(f"[Heavy Agent Tool Result] {str(res)[:200]}", flush=True)

                    function_responses.append({
                        "function_response": {
                            "name": fn_name,
                            "response": {"result": str(res)}
                        }
                    })

                chat_history.append(candidate.content)
                chat_history.append({
                    "role": "user",
                    "parts": function_responses,
                })

            if not final_result:
                final_result = "Heavy Agent reached maximum steps without a final text response."

        except Exception as e:
            final_result = f"Heavy Agent encountered a fatal error: {e}"

    print(f"[Heavy Agent] Finished. Result: {final_result}", flush=True)
    
    # Parse the final JSON response
    markdown_response = final_result
    spoken_response = final_result
    try:
        cleaned_result = final_result.strip()
        if cleaned_result.startswith("```json"):
            cleaned_result = cleaned_result[7:]
        elif cleaned_result.startswith("```"):
            cleaned_result = cleaned_result[3:]
        if cleaned_result.endswith("```"):
            cleaned_result = cleaned_result[:-3]
        final_json = json.loads(cleaned_result.strip())
        markdown_response = final_json.get("markdown_response", markdown_response)
        spoken_response = final_json.get("spoken_response", spoken_response)
    except Exception:
        print("[Heavy Agent] Failed to parse JSON from final_result. Using as raw text.")

    task_record["status"] = "completed"
    task_record["result"] = markdown_response
    task_record["spoken"] = spoken_response
    task_record["duration"] = round(time.time() - start_time, 1)
    
    if SUPERVISOR_TOKEN:
        url = f"{SUPERVISOR_URL}/services/notify/notify"
        payload = {
            "message": markdown_response,
            "title": "Antigravity Heavy Agent"
        }
        try:
            resp = http_requests.post(url, headers=_supervisor_headers(), json=payload, timeout=5)
            if resp.status_code != 200:
                print(f"Error sending completion notification: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Error sending completion notification: {e}")
            
        event_url = f"{SUPERVISOR_URL}/events/antigravity_task_completed"
        try:
            curr_engine, curr_voice = get_tts_config()
            event_payload = {
                "result": final_result,
                "markdown_response": markdown_response,
                "spoken_response": spoken_response,
                "task": task_description,
                "tts_engine": curr_engine,
                "tts_voice": curr_voice,
                "is_voice": is_voice
            }
            resp = http_requests.post(event_url, headers=_supervisor_headers(), json=event_payload, timeout=5)
            if resp.status_code != 200:
                print(f"Error firing completion event: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Error firing completion event: {e}")

    return markdown_response, spoken_response





def tool_delegate_to_antigravity(
    task_description: str,
    immediate_reply: str = "Το ελέγχω αναλυτικά και θα σε ενημερώσω.",
    reason_code: str = REASON_GENERAL_ESCALATION,
    resolved_entities: list = None,
    is_voice: bool = True
) -> str:
    """Delegate a complex task to the Antigravity heavy agent using a structured DelegationEnvelope."""
    import threading
    if not codex_mgr.is_authenticated and (codex_mgr.auth_state in ["expired", "idle"] or not codex_mgr.auth_pending):
        print("[Delegate] Codex CLI is unauthenticated. Triggering autonomous device code flow...", flush=True)
        codex_mgr.start_auth_flow(force=True)

    envelope = DelegationEnvelope(
        user_query=task_description,
        reason_code=reason_code or REASON_GENERAL_ESCALATION,
        resolved_entities=resolved_entities or [],
        delegation_depth=1
    )
    threading.Thread(target=_run_heavy_agent, args=(envelope,), kwargs={"is_voice": is_voice}, daemon=True).start()
    return "I have delegated the task to the Heavy Agent. I will notify you when it's done."





# ---------------------------------------------------------------------------

# Gemini tool declarations (function calling schema)

# ---------------------------------------------------------------------------

GEMINI_TOOLS = [{

    "function_declarations": [

        {

            "name": "call_ha_service",

            "description": "Call a Home Assistant service to control devices (e.g. turn on/off lights, set thermostat temperature, lock/unlock doors, play media, etc.).",

            "parameters": {

                "type": "OBJECT",

                "properties": {

                    "domain": {"type": "STRING", "description": "Service domain (e.g. 'light', 'switch', 'climate', 'media_player')."},

                    "service": {"type": "STRING", "description": "Service name (e.g. 'turn_on', 'turn_off', 'set_temperature')."},

                    "service_data": {"type": "OBJECT", "description": "Service data payload (e.g. {entity_id: 'light.living_room', brightness: 255})."},

                },

                "required": ["domain", "service"],

            },

        },

        {

            "name": "get_ha_states",

            "description": "Get current states of Home Assistant entities. Pass a specific entity_id for details, or empty string to list all entities.",

            "parameters": {

                "type": "OBJECT",

                "properties": {

                    "entity_id": {"type": "STRING", "description": "Entity ID (e.g. 'sensor.temperature'). Leave empty for all entities."},

                },

            },

        },

        {
            "name": "search_web",
            "description": "Search the web for simple facts only. If the query requires research or comparisons, call delegate_to_antigravity instead.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING", "description": "The search query."},
                },
                "required": ["query"],
            },
        },
        {
            "name": "keep_mic_open",
            "description": "Keep the microphone open for a follow-up conversation. Call this when you ask the user a question and expect an answer.",
            "parameters": {
                "type": "OBJECT",
                "properties": {},
            },
        },
        {
            "name": "delegate_to_antigravity",
            "description": "Delegate a complex, historical, analytical, or external research task to the Antigravity Heavy Agent.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "task_description": {"type": "STRING", "description": "Description of the task to delegate."},
                    "immediate_reply": {"type": "STRING", "description": "A natural, conversational sentence to speak to the user right now to acknowledge handoff (e.g. 'Το ελέγχω αναλυτικά και θα σε ενημερώσω.'). Must be in Greek."},
                    "reason_code": {"type": "STRING", "description": "Reason: 'HISTORICAL_ANALYSIS', 'EXTERNAL_RESEARCH', 'ENTITY_NOT_FOUND', 'MULTI_STEP_ANALYSIS', 'LOW_CONFIDENCE', or 'GENERAL_ESCALATION'."}
                },
                "required": ["task_description", "immediate_reply"],
            },
        },
        {
            "name": "store_memory",
            "description": "Store an important user preference, personal fact, habit, or instruction into the persistent long-term memory database for future reference. MUST be called whenever the user states a personal preference (e.g. favorite food, music) or explicitly asks to remember/store something ('αποθήκευσέ το στη μνήμη σου', 'να το θυμάσαι', 'apothikeyse to'). You MUST resolve pronouns ('το', 'την', 'αυτό') and short answers using the preceding dialogue history to form a complete, standalone Greek statement (e.g. 'Το αγαπημένο φαγητό του χρήστη είναι η φασολάδα.') before calling this tool.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "fact": {
                        "type": "STRING",
                        "description": "The complete, standalone fact or preference to remember in Greek. Never store unresolved pronouns like 'αυτό' or single words like 'φασολάδα'."
                    },
                },
                "required": ["fact"],
            },
        },
        {
            "name": "play_music",
            "description": "Play music, radio stations, songs, or playlists using the Music Assistant bridge and streaming engine. Call this whenever the user asks to play music, a radio station (e.g. 'Βάλε Imagine 89.7', 'Βάλε Παιδάκι 97.5', 'βάλε ραδιόφωνο'), a song, artist, playlist, or YouTube audio.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "The song title, radio station name, artist, or playlist to play (e.g. 'Imagine 89.7', 'Paidaki 97.5', 'Queen Bohemian Rhapsody', 'παιδικά τραγούδια')."
                    },
                    "player": {
                        "type": "STRING",
                        "description": "Optional target player: 'satellites' (default, smart speakers), 'tv' (living room TV / OLED), 'hisense', or a specific media_player entity ID."
                    }
                },
                "required": ["query"],
            },
        },
        {
            "name": "control_music",
            "description": "Control currently playing music (pause, resume, stop, next track, previous track, volume up/down/set). Call this whenever the user asks to stop, pause, resume, or adjust music volume.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action": {
                        "type": "STRING",
                        "description": "The action: 'stop', 'pause', 'resume', 'next', 'previous', 'volume_up', 'volume_down', 'volume_set'."
                    },
                    "volume": {
                        "type": "NUMBER",
                        "description": "Volume level (0-100) if action is volume_set."
                    },
                    "player": {
                        "type": "STRING",
                        "description": "Optional target player or media_player entity."
                    }
                },
                "required": ["action"],
            },
        },
    ]
}]

# Map tool names to implementations
TOOL_DISPATCH = {
    "call_ha_service": lambda args: tool_call_ha_service(
        args.get("domain", ""), args.get("service", ""), args.get("service_data")
    ),
    "get_ha_states": lambda args: tool_get_ha_states(args.get("entity_id", "")),
    "search_web": lambda args: tool_search_web(args.get("query", "")),
    "keep_mic_open": lambda args: tool_keep_mic_open(),
    "delegate_to_antigravity": lambda args: tool_delegate_to_antigravity(
        args.get("task_description", ""),
        args.get("immediate_reply", "Το ελέγχω αναλυτικά και θα σε ενημερώσω."),
        args.get("reason_code", REASON_GENERAL_ESCALATION),
        args.get("resolved_entities", []),
        is_voice=args.get("is_voice", True)
    ),
    "store_memory": lambda args: tool_store_memory(args.get("fact", "")),
    "play_music": lambda args: tool_play_music(args.get("query", ""), player=args.get("player")),
    "control_music": lambda args: tool_control_music(args.get("action", ""), player=args.get("player"), volume=args.get("volume")),
}



# ---------------------------------------------------------------------------

# FastAPI app

# ---------------------------------------------------------------------------

app = FastAPI(title="Antigravity Brain", version="2.0.0")



SYSTEM_INSTRUCTION = (
    "You are the Light Voice Assistant Brain of Home Assistant (Fast Agent). "
    "Your primary responsibility is low-latency (< 1.5s), natural Greek conversation, controlling devices, and reporting current entity states. "
    "CRITICAL: Always respond in Greek (Ελληνικά), no matter what. "
    "Be concise and output natural language suitable for Text-to-Speech (TTS). "
    "Do not include markdown, code blocks, or special formatting in your response. "
    "When you ask the user a question, always call the keep_mic_open tool so the microphone stays open for their answer. "
    "\n\n"
    "MUSIC & AUDIO PLAYBACK POLICY:\n"
    "1. For ANY music or radio playback request (e.g. 'βάλε μουσική', 'παίξε Imagine 89.7', 'βάλε Παιδάκι 97.5', 'παίξε ένα παιδικό τραγούδι', 'παίξε Beatles', 'play music'), you MUST call the `play_music` tool immediately!\n"
    "   - Pass the query (e.g. 'Imagine 89.7', 'Paidaki 97.5', 'Queen Bohemian Rhapsody').\n"
    "   - If the user specifies a device/room (e.g. 'στην τηλεόραση', 'στο σαλόνι', 'στο ηχείο'), pass player='tv' or player='satellites'. Default is 'satellites'.\n"
    "2. For music playback controls (e.g. 'σταμάτα τη μουσική', 'παύση', 'συνέχισε', 'δυνάμωσε', 'χαμήλωσε', 'επόμενο τραγούδι'), call the `control_music` tool immediately.\n"
    "3. Never attempt to manually call media_player.play_media with raw YouTube URLs or guess stream URLs yourself. Always use `play_music`.\n"
    "\n\n"
    "PERSISTENT LONG-TERM MEMORY POLICY:\n"
    "1. You have access to the `store_memory` tool. You MUST call `store_memory` whenever:\n"
    "   - The user shares a personal fact, preference, habit, or favorite thing (e.g., favorite food, music, hobbies, daily routines).\n"
    "   - The user asks you to save, store, or remember something (e.g., 'αποθήκευσέ το', 'κράτα το στη μνήμη σου', 'να το θυμάσαι για πάντα', 'apothikeyse to sti mnimi sou').\n"
    "2. COREFERENCE RESOLUTION: When the user refers to previous context using pronouns or short answers (e.g., 'η φασολάδα', 'να την αποθηκεύσεις', 'εννοούσα για τη φασολάδα', 'oxi. thelo na to apothikeyseis'), you MUST resolve what they are referring to using the preceding conversation history.\n"
    "   Store the fact as a complete, standalone Greek statement (e.g., store_memory(fact='Το αγαπημένο φαγητό του χρήστη είναι η φασολάδα.')). Never pass isolated pronouns like 'το' or single words like 'φασολάδα'.\n"
    "3. Once `store_memory` succeeds, warmly confirm to the user in Greek that you saved it to your permanent memory.\n"
    "\n\n"
    "CRITICAL ESCALATION POLICY: You have a tool called `delegate_to_antigravity`. "
    "1. If a query can be answered directly and definitively from current live states returned by `get_ha_states` (e.g. device status, temperatures, lights, car location), answer immediately yourself. "
    "2. For ANY question requiring historical data (e.g. yesterday, last week, trends, energy consumption over time), future weather forecasts or predictions over time (e.g. until when it will rain, tomorrow's forecast, rain duration), complex multi-sensor calculations, external research not in HA states, or if an entity is not found, you MUST IMMEDIATELY call `delegate_to_antigravity` without checking live states! "
    "3. Never guess, never attempt repeated blind searches, and NEVER apologize with 'δεν μπόρεσα να βρω'. If you do not have the complete answer immediately in live states, call `delegate_to_antigravity` so the Heavy Agent can solve it."
)





def _build_gemini_contents(messages: list) -> tuple:
    """Convert OpenAI-style messages to Gemini contents format.
    Returns (system_instruction, contents).
    Ensures strictly alternating 'user' and 'model' turns required by Gemini.
    """
    system_parts = []
    contents = []

    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")
        if not text:
            continue

        if role == "system":
            system_parts.append(text)
            continue

        gemini_role = "model" if role == "assistant" else "user"

        if contents and contents[-1]["role"] == gemini_role:
            contents[-1]["parts"][0]["text"] += f"\n{text}"
        else:
            if not contents and gemini_role != "user":
                continue
            contents.append({"role": gemini_role, "parts": [{"text": text}]})

    system_text = "\n".join(system_parts) if system_parts else None
    return system_text, contents





def _execute_tool_calls(response, model_name, chat_history, config, user_prompt: str = "", is_voice: bool = True):
    MAX_ROUNDS = 5
    current_response = response
    mic_opened = False
    
    for round_idx in range(MAX_ROUNDS):
        candidate = current_response.candidates[0]
        function_calls = []
        
        for part in candidate.content.parts:
            if hasattr(part, 'function_call') and part.function_call:
                function_calls.append(part.function_call)
        
        if not function_calls:
            # No more tool calls
            try:
                t = current_response.text
                if not t or t.strip() == "":
                    if user_prompt:
                        print(f"[Fallback] Empty text in round {round_idx}, auto-delegating to Heavy Agent: {user_prompt}")
                        import threading
                        t_thread = threading.Thread(target=_run_heavy_agent, args=(user_prompt,), kwargs={"is_voice": is_voice})
                        t_thread.start()
                        return "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω.", mic_opened
                    return "Συγγνώμη, παρακαλώ επαναλάβετε.", mic_opened
                
                lower_t = t.lower()
                if any(phrase in lower_t for phrase in ["δεν μπόρεσα να βρω", "δεν βρήκα", "δεν γνωρίζω", "δεν μπορώ να βρω", "δυστυχώς δεν"]) and user_prompt:
                    print(f"[Fallback] Fast agent apologized, auto-delegating to Heavy Agent: {user_prompt}")
                    import threading
                    t_thread = threading.Thread(target=_run_heavy_agent, args=(user_prompt,), kwargs={"is_voice": is_voice})
                    t_thread.start()
                    return "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω.", mic_opened

                return t, mic_opened
            except ValueError:
                if user_prompt:
                    print(f"[Fallback] ValueError on response.text, auto-delegating to Heavy Agent: {user_prompt}")
                    import threading
                    t_thread = threading.Thread(target=_run_heavy_agent, args=(user_prompt,), kwargs={"is_voice": is_voice})
                    t_thread.start()
                    return "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω.", mic_opened
                return "(No response generated)", mic_opened
        
        function_responses = []
        for fc in function_calls:
            fn_name = fc.name
            fn_args = dict(fc.args) if fc.args else {}
            if fn_name == "delegate_to_antigravity":
                fn_args["is_voice"] = is_voice
            if fn_name == "keep_mic_open":
                mic_opened = True
            
            print(f"[Tool Call] {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:200]})")
            
            handler = TOOL_DISPATCH.get(fn_name)
            if handler:
                try:
                    result = handler(fn_args)
                except Exception as e:
                    result = f"Tool error: {e}"
            else:
                result = f"Unknown tool: {fn_name}"
            
            print(f"[Tool Result] {result[:200]}")
            
            if fn_name == "delegate_to_antigravity":
                print("[System] Short-circuiting response for delegate_to_antigravity to prevent LLM apology.")
                return fn_args.get("immediate_reply", "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω."), False

            function_responses.append({
                "function_response": {
                    "name": fn_name,
                    "response": {"result": result}
                }
            })
        
        chat_history.append(candidate.content)
        chat_history.append({
            "role": "user",
            "parts": function_responses,
        })
        
        current_response = client.models.generate_content(
            model=model_name,
            contents=chat_history,
            config=config
        )
    
    # If we exhausted rounds, check if we have text
    try:
        final_text = current_response.text
        if final_text and final_text.strip():
            lower_text = final_text.lower()
            if any(phrase in lower_text for phrase in ["δεν μπόρεσα να βρω", "δεν βρήκα", "δεν γνωρίζω", "δεν μπορώ να", "δυστυχώς δεν"]) and user_prompt:
                print(f"[Fallback] Fast Agent apologized after exhausting rounds, auto-delegating to Heavy Agent: {user_prompt}")
                import threading
                t_thread = threading.Thread(target=_run_heavy_agent, args=(user_prompt,), kwargs={"is_voice": is_voice})
                t_thread.start()
                return "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω.", mic_opened
            return final_text, mic_opened
    except Exception:
        pass

    if user_prompt:
        print(f"[Fallback] Exhausted rounds without final text. Auto-delegating to Heavy Agent: {user_prompt}")
        import threading
        t_thread = threading.Thread(target=_run_heavy_agent, args=(user_prompt,), kwargs={"is_voice": is_voice})
        t_thread.start()
        return "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω.", mic_opened

    return "(No response generated)", mic_opened

def _get_openai_tools():
    """Convert GEMINI_TOOLS function declarations into OpenAI tools schema."""
    tools = []
    for fd in GEMINI_TOOLS[0].get("function_declarations", []):
        params = json.loads(json.dumps(fd.get("parameters", {})))
        def _lower_types(d):
            if isinstance(d, dict):
                for k, v in list(d.items()):
                    if k == "type" and isinstance(v, str):
                        d[k] = v.lower()
                    else:
                        _lower_types(v)
            elif isinstance(d, list):
                for item in d:
                    _lower_types(item)
        _lower_types(params)
        tools.append({
            "type": "function",
            "function": {
                "name": fd["name"],
                "description": fd.get("description", ""),
                "parameters": params
            }
        })
    return tools


def _execute_openai_chat(messages, system_prompt, model_name, token, user_prompt, is_voice: bool = True):
    """Execute Fast Agent query against OpenAI API with tool support."""
    tools = _get_openai_tools()
    openai_msgs = [{"role": "system", "content": system_prompt}]
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, list):
            c_text = " ".join(part.get("text", "") for part in c if isinstance(part, dict) and "text" in part)
        else:
            c_text = str(c)
        openai_msgs.append({"role": m.get("role", "user"), "content": c_text})

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    req_model = model_name
    if not req_model or "flash" in req_model.lower() or "gemini" in req_model.lower():
        req_model = "gpt-6-luna"

    mic_opened = False
    for round_idx in range(5):
        payload = {
            "model": req_model,
            "messages": openai_msgs,
            "tools": tools,
            "tool_choice": "auto"
        }
        if "o3-mini" in req_model or "o1" in req_model:
            if fast_agent_thinking in ["low", "medium", "high"]:
                payload["reasoning_effort"] = fast_agent_thinking
        res = http_requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=20)
        if res.status_code != 200:
            raise Exception(f"OpenAI API error {res.status_code}: {res.text}")
        data = res.json()
        choice = data["choices"][0]["message"]
        openai_msgs.append(choice)

        tool_calls = choice.get("tool_calls", [])
        if not tool_calls:
            return choice.get("content", ""), mic_opened

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"].get("arguments", "{}"))
            except Exception:
                fn_args = {}
            if fn_name == "delegate_to_antigravity":
                fn_args["is_voice"] = is_voice
            if fn_name == "keep_mic_open":
                mic_opened = True
            print(f"[OpenAI Tool Call] {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:200]})")
            handler = TOOL_DISPATCH.get(fn_name)
            res_val = handler(fn_args) if handler else f"Unknown tool: {fn_name}"

            if fn_name == "delegate_to_antigravity":
                print("[System] Short-circuiting response for delegate_to_antigravity to prevent LLM apology.")
                return fn_args.get("immediate_reply", "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω."), False

            openai_msgs.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": str(res_val)
            })

    return "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω.", mic_opened


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint backed by Gemini or OpenAI with tool use."""

    data = await request.json()

    messages = data.get("messages", [])
    is_voice = data.get("is_voice", False)
    conv_id = data.get("conversation_id") or uuid.uuid4().hex

    req_model = _normalize_model_option(data.get("model", selected_model), selected_model)
    gemini_model_name = MODEL_MAP.get(req_model, req_model)

    if req_model == "heavy_direct":
        last_msg = ""
        if messages:
            last_msg = messages[-1].get("content", "")

        if is_voice:
            # Voice Mode: immediate spoken reassurance, background execution, announce on speaker
            if last_msg:
                import threading
                t = threading.Thread(target=_run_heavy_agent, args=(last_msg,), kwargs={"is_voice": True}, daemon=True)
                t.start()
            return {
                "id": "chatcmpl-heavy",
                "conversation_id": conv_id,
                "object": "chat.completion",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Το ψάχνω αμέσως. Δώσε μου λίγο χρόνο."
                    }
                }]
            }
        else:
            # Text Chat Mode: run synchronously, return written answer directly to chat, keep group speakers silent!
            print(f"[Heavy Direct] Running synchronously for chat query: {last_msg[:80]}", flush=True)
            if last_msg:
                import asyncio
                loop = asyncio.get_event_loop()
                markdown_res, _ = await loop.run_in_executor(None, _run_heavy_agent, last_msg, False)
            else:
                markdown_res = "Δεν δόθηκε ερώτημα για επεξεργασία."

            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "conversation_id": conv_id,
                "object": "chat.completion",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": markdown_res
                    }
                }]
            }

    if not api_key:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Gemini API key not configured.", "type": "server_error"}},
        )

    # Multi-turn conversation state tracking per conversation_id
    conv_state = get_or_create_conversation(conv_id)
    if len(messages) > 1:
        conv_state.messages = list(messages[-MAX_MESSAGES_PER_SESSION:])
    elif messages:
        for msg in messages:
            conv_state.messages.append(msg)
        conv_state.messages = conv_state.messages[-MAX_MESSAGES_PER_SESSION:]

    effective_messages = list(conv_state.messages) if conv_state.messages else messages

    system_instruction, contents = _build_gemini_contents(effective_messages)

    # Extract user's latest message to search memories
    user_text = ""
    for msg in reversed(effective_messages):
        if msg.get("role") == "user":
            user_text = msg.get("content", "")
            break

    # If user_text is very short (e.g. "φασολάδα" or "η φασολάδα"), include prior context in memory query
    search_query = user_text
    if len(user_text.split()) <= 2 and len(effective_messages) >= 3:
        for prev_msg in reversed(effective_messages[:-1]):
            if prev_msg.get("role") == "user":
                search_query = f"{prev_msg.get('content', '')} {user_text}"
                break

    facts = []
    if search_query:
        facts = memory_manager.search_memories(search_query, api_key)

    memory_context = ""
    if facts:
        memory_context = "System context from persistent memory:\n- " + "\n- ".join(facts)

    # Merge system instructions
    final_system = SYSTEM_INSTRUCTION
    if system_instruction:
        final_system = system_instruction + "\n\n" + SYSTEM_INSTRUCTION
    if memory_context:
        final_system += "\n\n" + memory_context

    mic_opened = False
    try:
        # Smart engine auto-routing: never fails even if user picked mismatched engine/model
        effective_model = req_model or fast_agent_model
        is_openai_model = any(effective_model.startswith(p) for p in ["gpt-", "o1", "o3", "chatgpt"])
        is_gemini_model = any(effective_model.startswith(p) for p in ["gemini-", "3.8", "3.1"])

        use_openai = False
        if is_openai_model:
            use_openai = True
        elif is_gemini_model:
            use_openai = False
        else:
            use_openai = (fast_agent_engine == "openai_api")

        if use_openai:
            content, mic_opened = _execute_openai_chat(effective_messages, final_system, effective_model, fast_agent_api_key, user_text, is_voice=is_voice)
        else:
            config = {
                "system_instruction": final_system,
                "tools": GEMINI_TOOLS,
            }

            # Build the chat history for potential multi-turn tool calling
            chat_history = []
            for c in contents:
                chat_history.append({
                    "role": c["role"],
                    "parts": [{"text": t["text"]} for t in c["parts"]],
                })

            response = client.models.generate_content(
                model=gemini_model_name,
                contents=chat_history,
                config=config
            )
            content, mic_opened = _execute_tool_calls(response, gemini_model_name, chat_history, config, user_prompt=user_text, is_voice=is_voice)

    except Exception as e:
        print(f"Error calling {fast_agent_engine}: {e}")
        if user_text:
            print(f"[Fallback] {fast_agent_engine} error, auto-delegating to Heavy Agent: {user_text}")
            import threading
            t = threading.Thread(target=_run_heavy_agent, args=(user_text,), kwargs={"is_voice": is_voice})
            t.start()
            content = "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω."
        else:
            content = f"Error calling {fast_agent_engine}: {e}"

    # Record assistant turn in session state
    conv_state.messages.append({
        "role": "assistant",
        "content": content
    })
    conv_state.messages = conv_state.messages[-MAX_MESSAGES_PER_SESSION:]

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "conversation_id": conv_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": gemini_model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "continue_conversation": mic_opened,
                },
                "finish_reason": "stop",
            }
        ],
        "continue_conversation": mic_opened,
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }





@app.get("/v1/models")

async def list_models():

    """OpenAI-compatible models list endpoint."""

    models = []

    for key, name in MODEL_MAP.items():

        models.append({

            "id": key,

            "object": "model",

            "created": 1700000000,

            "owned_by": "google",

        })

    return {"object": "list", "data": models}





@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Home Assistant Ingress Web Dashboard."""
    return HTMLResponse(content=get_dashboard_html(), status_code=200)


@app.get("/api/status")
async def get_api_status():
    """Live system status for Web Dashboard and sensors."""
    codex_mgr.check_status()
    agy_mgr.check_status()
    curr_tts_engine, curr_tts_voice = get_tts_config()
    return {
        "status": "ok",
        "version": "3.3.6",
        "fast_agent": {
            "engine": fast_agent_engine,
            "model": fast_agent_model,
            "thinking": fast_agent_thinking,
            "status": "ready"
        },
        "heavy_agent": {
            "engine": heavy_agent_engine,
            "model": heavy_agent_model,
            "thinking": heavy_agent_thinking,
            "codex": codex_mgr.get_status_dict(),
            "antigravity": agy_mgr.get_status_dict()
        },
        "tts": {
            "engine": curr_tts_engine,
            "voice": curr_tts_voice
        },
        "recent_tasks": list(recent_tasks)
    }


@app.post("/api/settings/fast-agent")
async def post_fast_agent_settings(request: Request):
    """Save Fast Agent engine, model, and thinking settings from Web Dashboard."""
    global fast_agent_engine, fast_agent_model, fast_agent_thinking
    data = await request.json()
    engine = data.get("engine", fast_agent_engine)
    model = _normalize_model_option(data.get("model", fast_agent_model), fast_agent_model)
    thinking = data.get("thinking", fast_agent_thinking)
    
    opts = {}
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, "r") as f:
                opts = json.load(f)
        except Exception:
            pass
    opts["fast_agent_engine"] = engine
    opts["fast_agent_model"] = model
    opts["fast_agent_thinking"] = thinking
    try:
        with open(OPTIONS_PATH, "w") as f:
            json.dump(opts, f, indent=2)
        fast_agent_engine = engine
        fast_agent_model = model
        fast_agent_thinking = thinking
        print(f"[Settings] Saved Fast Agent config: engine={engine}, model={model}, thinking={thinking}", flush=True)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "engine": engine, "model": model, "thinking": thinking}


@app.post("/api/settings/tts")
async def post_tts_settings(request: Request):
    """Save TTS engine and voice settings from Web Dashboard."""
    data = await request.json()
    engine = data.get("engine", "tts.google_cloud")
    voice = data.get("voice", "el-GR-Chirp3-HD-Laomedeia")
    opts = {}
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, "r") as f:
                opts = json.load(f)
        except Exception:
            pass
    opts["tts_engine"] = engine
    opts["tts_voice"] = voice
    try:
        with open(OPTIONS_PATH, "w") as f:
            json.dump(opts, f, indent=2)
        print(f"[Settings] Saved TTS config: engine={engine}, voice={voice}", flush=True)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "engine": engine, "voice": voice}


@app.post("/api/auth/codex/start")
async def post_auth_start():
    """Trigger manual device auth flow for Codex CLI."""
    res = codex_mgr.start_auth_flow(force=True)
    return res


@app.post("/api/auth/codex/check")
async def post_auth_check():
    """Check Codex login status."""
    is_auth = codex_mgr.check_status()
    return {
        "authenticated": is_auth,
        "auth_pending": codex_mgr.auth_pending,
        "device_code": codex_mgr.device_code,
        "auth_url": codex_mgr.auth_url
    }


@app.post("/api/auth/antigravity/start")
async def post_agy_auth_start():
    """Trigger Google OAuth flow for Antigravity CLI."""
    res = agy_mgr.start_auth_flow(force=True)
    return res


@app.post("/api/auth/antigravity/submit-code")
async def post_agy_submit_code(request: Request):
    """Submit authorization code pasted by user for Antigravity CLI."""
    data = await request.json()
    code = data.get("code", "")
    res = agy_mgr.submit_auth_code(code)
    return res


@app.post("/api/auth/antigravity/check")
async def post_agy_auth_check():
    """Check Antigravity CLI login status."""
    is_auth = agy_mgr.check_status()
    return agy_mgr.get_status_dict()


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "fast_agent": {
            "engine": fast_agent_engine,
            "model": fast_agent_model,
            "thinking": fast_agent_thinking,
            "token_configured": bool(fast_agent_token),
        },
        "heavy_agent": {
            "engine": heavy_agent_engine,
            "model": heavy_agent_model,
            "thinking": heavy_agent_thinking,
        },
        "supervisor_token_set": bool(SUPERVISOR_TOKEN),
    }


if __name__ == "__main__":
    print(f"Starting Antigravity Brain v3.3.6")
    print(f"  Phase 1 (Fast Agent): engine={fast_agent_engine}, model={fast_agent_model}, thinking={fast_agent_thinking}")
    print(f"  Phase 2 (Heavy Agent): engine={heavy_agent_engine}, thinking={heavy_agent_thinking}")
    print(f"  Port: {PORT}")
    print(f"  Fast Agent Token: {'set' if fast_agent_token else 'NOT SET'}")
    print(f"  Supervisor Token: {'set' if SUPERVISOR_TOKEN else 'NOT SET'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)