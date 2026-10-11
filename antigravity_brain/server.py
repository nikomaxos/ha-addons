import os
import json
import time
import uuid
import subprocess
import re
import uvicorn
import requests as http_requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import memory_manager

memory_manager.init_db()

# ---------------------------------------------------------------------------
# Load addon options from HA options.json
# ---------------------------------------------------------------------------
OPTIONS_PATH = "/data/options.json"
DEFAULT_API_KEY = "YOUR_API_KEY_HERE"
DEFAULT_MODEL = "3.8 flash high"
PORT = 8000

options = {}
if os.path.exists(OPTIONS_PATH):
    with open(OPTIONS_PATH, "r") as f:
        options = json.load(f)

# Phase 1: Fast Agent Settings
fast_agent_engine = options.get("fast_agent_engine", "gemini_api")
fast_agent_model = options.get("fast_agent_model", options.get("model", DEFAULT_MODEL))
fast_agent_thinking = options.get("fast_agent_thinking", "low")
fast_agent_token = options.get("fast_agent_token", "") or options.get("gemini_api_key", "") or DEFAULT_API_KEY

# Phase 2: Heavy Agent Settings
heavy_agent_engine = options.get("heavy_agent_engine", "codex_fallback")
heavy_agent_model = options.get("heavy_agent_model", "auto")
heavy_agent_thinking = options.get("heavy_agent_thinking", "high")

# Legacy compatibility
api_key = fast_agent_token
selected_model = fast_agent_model
PORT = options.get("api_port", PORT)



# Supervisor API access (available inside addon containers with hassio_api: true)

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

SUPERVISOR_URL = "http://supervisor/core/api"



# ---------------------------------------------------------------------------

# Model mapping

# ---------------------------------------------------------------------------

MODEL_MAP = {
    "3.8 flash high": "gemini-3.8-flash",
    "3.1 pro high": "gemini-3.1-pro-preview",
    "antigravity": "antigravity-preview-latest",
}



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

    """Run a READ-ONLY SQL query on the HA MariaDB database."""

    if not query.strip().upper().startswith("SELECT"):

        return "Error: Only SELECT (read-only) queries are allowed."

    try:

        cmd = [

            "mysql", "-h", "core-mariadb",

            "-u", "homeassistant", "-pRene1122",

            "homeassistant", "-e", query

        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        if result.returncode != 0:

            return f"Query error: {result.stderr.strip()}"

        return result.stdout.strip() or "(empty result)"

    except Exception as e:

        return f"Error executing query: {e}"





def tool_call_ha_service(domain: str, service: str, service_data: dict = None) -> str:

    """Call a Home Assistant service (e.g. turn_on light, set thermostat)."""

    if not SUPERVISOR_TOKEN:

        return "Error: SUPERVISOR_TOKEN not available. Addon may not have hassio_api enabled."

    url = f"{SUPERVISOR_URL}/services/{domain}/{service}"

    try:

        resp = http_requests.post(url, headers=_supervisor_headers(), json=service_data or {}, timeout=10)

        if resp.status_code == 200:

            return f"Service {domain}.{service} called successfully."

        return f"Service call failed: HTTP {resp.status_code} - {resp.text[:300]}"

    except Exception as e:

        return f"Error calling service: {e}"





def tool_get_ha_states(entity_id: str = "") -> str:

    """Get current states of HA entities. If entity_id is empty, returns all states."""

    if not SUPERVISOR_TOKEN:

        return "Error: SUPERVISOR_TOKEN not available."

    url = f"{SUPERVISOR_URL}/states"

    if entity_id:

        url = f"{SUPERVISOR_URL}/states/{entity_id}"

    try:

        resp = http_requests.get(url, headers=_supervisor_headers(), timeout=10)

        if resp.status_code == 200:

            data = resp.json()

            if isinstance(data, list):

                # Summarize: return entity_id and state

                summary = []

                for s in data:

                    summary.append(f"{s['entity_id']}: {s['state']}")

                return "\n".join(summary)

            elif isinstance(data, dict):

                return json.dumps({

                    "entity_id": data.get("entity_id"),

                    "state": data.get("state"),

                    "attributes": data.get("attributes", {}),

                    "last_changed": data.get("last_changed"),

                }, ensure_ascii=False, indent=2)

        return f"Error: HTTP {resp.status_code} - {resp.text[:300]}"

    except Exception as e:

        return f"Error getting states: {e}"






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

    """Search the web using DuckDuckGo."""

    try:

        from ddgs import DDGS

        with DDGS() as ddgs:

            results = list(ddgs.text(query, max_results=5))

        if not results:

            return "No results found."

        output = []

        for r in results:

            output.append(f"**{r.get('title', '')}**\n{r.get('body', '')}\nURL: {r.get('href', '')}\n")

        return "\n".join(output)

    except Exception as e:

        return f"Web search error: {e}"





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


def _execute_codex_cli(task_description: str, thinking_level: str = "high") -> tuple[str, bool]:
    """Execute Codex CLI non-interactively.
    Returns (output_text, limit_or_error_exceeded).
    """
    import shutil
    codex_bin = None
    for cand in ["./codex", "/usr/src/app/codex", "codex", "codex.exe"]:
        if os.path.exists(cand) or shutil.which(cand):
            codex_bin = cand
            break

    if not codex_bin:
        print("[Heavy Agent - Codex] Codex binary not found in container, falling back.", flush=True)
        return "", True

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
        "   - Use python3 with urllib or ddgs, curl, jq, etc., to search the web or process data.\n\n"
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
        full_prompt
    ]
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


def _check_codex_auth_on_startup():
    """Check Codex login status on addon startup and print device code if not logged in."""
    import shutil
    import threading
    time.sleep(2)
    codex_bin = None
    for cand in ["./codex", "/usr/src/app/codex", "codex"]:
        if os.path.exists(cand) or shutil.which(cand):
            codex_bin = cand
            break
    if not codex_bin:
        return
    try:
        res = subprocess.run([codex_bin, "login", "status"], capture_output=True, text=True, timeout=10)
        combined = (res.stdout + res.stderr).lower()
        if "not logged in" in combined:
            print("\n" + "=" * 60, flush=True)
            print("⚠️ CODEX AUTHENTICATION REQUIRED ON STARTUP! ⚠️", flush=True)
            print("Requesting device authorization code...", flush=True)
            print("=" * 60 + "\n", flush=True)
            proc = subprocess.Popen([codex_bin, "login", "--device-auth"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                print(line, end='', flush=True)
                if "Continue only if you started this login" in line:
                    break
        else:
            print("[Startup] Codex CLI is authenticated and ready!", flush=True)
    except Exception as e:
        print(f"[Startup] Codex auth check error: {e}", flush=True)

import threading
threading.Thread(target=_check_codex_auth_on_startup, daemon=True).start()


def _execute_antigravity_cli(task_description: str, thinking_level: str = "high") -> tuple[str, bool]:
    """Execute Antigravity CLI non-interactively."""
    import shutil
    agy_bin = None
    for cand in ["./agy", "/usr/src/app/agy", "agy", "antigravity"]:
        if os.path.exists(cand) or shutil.which(cand):
            agy_bin = cand
            break

    if not agy_bin:
        print("[Heavy Agent - Antigravity] Antigravity binary not found in container.", flush=True)
        return "", True

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
        "   - Use python3 with urllib or ddgs, curl, jq, etc., to search the web or process data.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. NEVER give up or say you lack access to Home Assistant! Use your shell tools to inspect states, query the database, calculate the metrics, and deliver the answer.\n"
        "2. ALL RESPONSES MUST BE IN GREEK (Ελληνικά).\n"
        "3. Output your final answer STRICTLY as a JSON object containing TWO fields:\n"
        "   - `markdown_response`: Full detailed analysis with formatting, numbers, tables or bullet points for the Home Assistant UI notification.\n"
        "   - `spoken_response`: Clear, natural, conversational spoken Greek WITHOUT asterisks, markdown, hashes, or technical symbols, suitable for HD text-to-speech."
    )

    print(f"[Heavy Agent - Antigravity] Running Antigravity CLI for: {task_description[:80]}...", flush=True)
    cmd = [agy_bin, "exec", full_prompt]
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




def _run_heavy_agent(task_description: str):

    import threading

    print(f"[Heavy Agent] Starting task: {task_description}")

    

    system_instruction = (
        "You are the Antigravity Heavy Agent running inside a Home Assistant add-on container. "
        "CRITICAL: ALL YOUR RESPONSES MUST BE IN GREEK (Ελληνικά). Never use English in your final answer to the user. "
        "Your task is to autonomously solve complex problems. You have access to tools including "
        "execute_shell, query_database, call_ha_service, get_ha_states, and search_web. "
        "You have absolute freedom and MUST use your tools dynamically to solve problems. "
        "You have absolute freedom to interact with Home Assistant. You can use the `execute_shell` tool with `curl` to query or control the Home Assistant REST API at `http://supervisor/core/api/...` using the `$SUPERVISOR_TOKEN` environment variable (e.g., `curl -H 'Authorization: Bearer $SUPERVISOR_TOKEN' http://supervisor/core/api/states`). "
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

                    "description": "Execute a shell command inside the Home Assistant addon container (Alpine Linux).",

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

                    "description": "Run a READ-ONLY SQL SELECT query on the Home Assistant MariaDB database to get historical data about energy consumption, temperatures, costs, etc. The database has tables: statistics_meta (entity_id -> metadata_id mapping), statistics (hourly stats with start_ts, state, sum, min, max, mean), statistics_short_term (5-min stats).",

                    "parameters": {

                        "type": "OBJECT",

                        "properties": {

                            "query": {"type": "STRING", "description": "The SQL SELECT query to execute."},

                        },

                        "required": ["query"],

                    },

                },

                GEMINI_TOOLS[0]["function_declarations"][0], # call_ha_service

                GEMINI_TOOLS[0]["function_declarations"][1], # get_ha_states

                GEMINI_TOOLS[0]["function_declarations"][2], # search_web

                GEMINI_TOOLS[0]["function_declarations"][5], # store_memory

            ]

        }

    ]

    

    heavy_dispatch = {

        "execute_shell": lambda args: tool_execute_shell(args.get("command", "")),

        "query_database": lambda args: tool_query_database(args.get("query", "")),

        "call_ha_service": lambda args: tool_call_ha_service(args.get("domain", ""), args.get("service", ""), args.get("service_data")),

        "get_ha_states": lambda args: tool_get_ha_states(args.get("entity_id", "")),

        "search_web": lambda args: tool_search_web(args.get("query", "")),

        "store_memory": lambda args: tool_store_memory(args.get("fact", "")),

    }



    config = {

        "system_instruction": system_instruction,

        "tools": heavy_tools_schema,

    }

    

    chat_history = [

        {"role": "user", "parts": [{"text": f"Task: {task_description}"}]}
    ]

    final_result = ""

    # 1. Attempt Codex CLI if configured
    if heavy_agent_engine in ["codex_fallback", "codex_only"]:
        print(f"[Heavy Agent] Evaluating task with Codex CLI (thinking: {heavy_agent_thinking})...", flush=True)
        codex_out, limit_or_error = _execute_codex_cli(task_description, heavy_agent_thinking)
        if not limit_or_error and codex_out:
            final_result = codex_out
        elif limit_or_error:
            print("[Heavy Agent] Codex CLI hit limit, quota, or is unavailable. Proceeding to fallback...", flush=True)

    # 2. Attempt Antigravity CLI if configured or after Codex limit
    if not final_result and heavy_agent_engine in ["codex_fallback", "antigravity_only"]:
        print(f"[Heavy Agent] Evaluating task with Antigravity CLI (thinking: {heavy_agent_thinking})...", flush=True)
        agy_out, limit_or_error = _execute_antigravity_cli(task_description, heavy_agent_thinking)
        if not limit_or_error and agy_out:
            final_result = agy_out
        elif limit_or_error:
            print("[Heavy Agent] Antigravity CLI hit limit or unavailable. Falling back to Gemini Pro agent...", flush=True)

    # 3. Fallback to Gemini Pro Agent if CLIs didn't produce a final answer
    if not final_result:
        fallback_model = MODEL_MAP.get(heavy_agent_model, "gemini-3.1-pro-preview") if heavy_agent_model != "auto" else "gemini-3.1-pro-preview"
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
            resp = http_requests.post(event_url, headers=_supervisor_headers(), json={"result": final_result, "markdown_response": markdown_response, "spoken_response": spoken_response, "task": task_description}, timeout=5)
            if resp.status_code != 200:
                print(f"Error firing completion event: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Error firing completion event: {e}")





def tool_delegate_to_antigravity(task_description: str, immediate_reply: str = "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο.") -> str:

    """Delegate a complex task to the Antigravity heavy agent."""

    import threading

    threading.Thread(target=_run_heavy_agent, args=(task_description,), daemon=True).start()

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

            "description": "Search the web for simple facts only (weather, current events). DO NOT use this for deep research, local places, restaurants, or menus! If the user asks for restaurants, places, or complex local info, DO NOT call search_web. You MUST call delegate_to_antigravity instead.",

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

            "description": "Delegate a complex or heavy task to the Antigravity heavy agent. It will send a persistent notification to HA.",

            "parameters": {

                "type": "OBJECT",

                "properties": {

                    "task_description": {"type": "STRING", "description": "Description of the task to delegate."},

                    "immediate_reply": {"type": "STRING", "description": "A natural, contextual sentence you must speak to the user right now to confirm you are working on it (e.g. 'Έγινε, βάζω υπενθύμιση', 'Μισό λεπτό να ελέγξω'). Must be in the user's language."}

                },

                "required": ["task_description", "immediate_reply"],

            },

        },

        {

            "name": "store_memory",

            "description": "Store an important user preference, fact, or instruction into the persistent memory database for future reference. Use this autonomously when the user shares something you should remember.",

            "parameters": {

                "type": "OBJECT",

                "properties": {

                    "fact": {"type": "STRING", "description": "The fact or preference to remember."},

                },

                "required": ["fact"],

            },

        },

    ]

}]



# Map tool names to implementations

TOOL_DISPATCH = {

    "query_database": lambda args: tool_query_database(args.get("query", "")),

    "call_ha_service": lambda args: tool_call_ha_service(

        args.get("domain", ""), args.get("service", ""), args.get("service_data")

    ),

    "get_ha_states": lambda args: tool_get_ha_states(args.get("entity_id", "")),

    "search_web": lambda args: tool_search_web(args.get("query", "")),

    "keep_mic_open": lambda args: tool_keep_mic_open(),

    "delegate_to_antigravity": lambda args: tool_delegate_to_antigravity(args.get("task_description", ""), args.get("immediate_reply", "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο.")),

    "store_memory": lambda args: tool_store_memory(args.get("fact", "")),

}



# ---------------------------------------------------------------------------

# FastAPI app

# ---------------------------------------------------------------------------

app = FastAPI(title="Antigravity Brain", version="2.0.0")



SYSTEM_INSTRUCTION = (

    "You are the Brain of a smart Home Assistant running on a local server (Fast Agent). "

    "You have tools to control devices, get current states, search the web, and more. "

    "CRITICAL: Always respond in Greek (Ελληνικά), no matter what. "

    "Be concise and output natural language suitable for Text-to-Speech (TTS). "

    "Do not include markdown, code blocks, or special formatting in your response. "

    "When you ask the user a question, always call the keep_mic_open tool so the microphone stays open for their answer. "

    "CRITICAL: You have a tool called `delegate_to_antigravity`. The user expects to speak naturally and never be trained on how to talk to you. "

    "If a question requires historical data, analytics, or complex logic, you MUST call `delegate_to_antigravity`. However, if you can find the current status or location of an entity (like a car, light, or sensor) directly in the data returned by `get_ha_states`, answer immediately yourself! "

    "If you try to use `search_web` to answer a question and you cannot find the answer, you MUST call `delegate_to_antigravity` so the Heavy Agent can do a deep search. "

    "If the user asks to play a specific radio station, FIRST use the `search_radio_browser` tool to find the direct audio stream URL. If you find it, play it using `call_ha_service` on the media player (set media_content_type to 'music' and media_content_id to the stream URL). If you CANNOT find it via `search_radio_browser`, DO NOT use `search_web`. IMMEDIATELY call `delegate_to_antigravity`! "

    "you MUST NOT just say you can't do it. Instead, you MUST automatically call the `delegate_to_antigravity` tool to trigger the Antigravity flow."

)





def _build_gemini_contents(messages: list) -> tuple:

    """Convert OpenAI-style messages to Gemini contents format.



    Returns (system_instruction, contents).

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

        elif role == "assistant":

            contents.append({"role": "model", "parts": [{"text": text}]})

        else:

            contents.append({"role": "user", "parts": [{"text": text}]})



    system_text = "\n".join(system_parts) if system_parts else None

    return system_text, contents





def _execute_tool_calls(response, model_name, chat_history, config):
    MAX_ROUNDS = 5
    current_response = response
    
    for _ in range(MAX_ROUNDS):
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
                    return "Συγγνώμη, παρακαλώ επαναλάβετε."
                return t
            except ValueError:
                return "(No response generated)"
        
        function_responses = []
        for fc in function_calls:
            fn_name = fc.name
            fn_args = dict(fc.args) if fc.args else {}
            
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
                return fn_args.get("immediate_reply", "Το ελέγχω αναλυτικά. Δώσε μου λίγο χρόνο να το ψάξω.")

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
    
    # If we exhausted rounds, return whatever we have
    try:
        final_text = current_response.text
        if not final_text or final_text.strip() == "":
            return "Συγγνώμη, δεν μπόρεσα να βρω την απάντηση. Παρακαλώ δοκιμάστε ξανά."
        return final_text
    except ValueError:
        return "Συγγνώμη, κάτι πήγε στραβά κατά την επεξεργασία του αιτήματος."


@app.post("/v1/chat/completions")

async def chat_completions(request: Request):

    """OpenAI-compatible chat completions endpoint backed by Gemini with tool use."""

    data = await request.json()

    messages = data.get("messages", [])

    req_model = data.get("model", selected_model)
    gemini_model_name = MODEL_MAP.get(req_model, req_model)

    if req_model == "heavy_direct":
        if messages:
            last_msg = messages[-1].get("content", "")
            if last_msg:
                import threading
                t = threading.Thread(target=_run_heavy_agent, args=(last_msg,))
                t.start()
        
        return {
            "id": "chatcmpl-heavy",
            "object": "chat.completion",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Το ψάχνω αμέσως. Δώσε μου λίγο χρόνο."
                }
            }]
        }

    if not api_key:

        return JSONResponse(

            status_code=500,

            content={"error": {"message": "Gemini API key not configured.", "type": "server_error"}},

        )



    system_instruction, contents = _build_gemini_contents(messages)

    

    # Extract user's latest message to search memories

    user_text = ""

    for msg in reversed(messages):

        if msg.get("role") == "user":

            user_text = msg.get("content", "")

            break

            

    facts = []

    if user_text:

        facts = memory_manager.search_memories(user_text, api_key)

        

    memory_context = ""

    if facts:

        memory_context = "System context from memory:\n- " + "\n- ".join(facts)



    # Merge system instructions

    final_system = SYSTEM_INSTRUCTION

    if system_instruction:

        final_system = system_instruction + "\n\n" + SYSTEM_INSTRUCTION

    if memory_context:

        final_system += "\n\n" + memory_context



    try:

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

        content = _execute_tool_calls(response, gemini_model_name, chat_history, config)

        

    except Exception as e:

        content = f"Error calling Gemini API: {e}"



    return {

        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",

        "object": "chat.completion",

        "created": int(time.time()),

        "model": gemini_model_name,

        "choices": [

            {

                "index": 0,

                "message": {

                    "role": "assistant",

                    "content": content,

                },

                "finish_reason": "stop",

            }

        ],

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
    print(f"Starting Antigravity Brain v3.0.0")
    print(f"  Phase 1 (Fast Agent): engine={fast_agent_engine}, model={fast_agent_model}, thinking={fast_agent_thinking}")
    print(f"  Phase 2 (Heavy Agent): engine={heavy_agent_engine}, thinking={heavy_agent_thinking}")
    print(f"  Port: {PORT}")
    print(f"  Fast Agent Token: {'set' if fast_agent_token else 'NOT SET'}")
    print(f"  Supervisor Token: {'set' if SUPERVISOR_TOKEN else 'NOT SET'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)