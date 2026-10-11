import os
import subprocess
import json
import datetime
import requests as http_requests

SUPERVISOR_URL = "http://supervisor/core/api"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

def get_supervisor_headers(token: str = None) -> dict:
    t = token or SUPERVISOR_TOKEN or os.environ.get("SUPERVISOR_TOKEN", "")
    return {
        "Authorization": f"Bearer {t}",
        "Content-Type": "application/json",
    }

class SecureToolBroker:
    """Unified, secure tool broker for Home Assistant Core API, MariaDB, and external data.
    Never exposes raw tokens or database credentials to model prompts.
    """

    def __init__(self, token: str = None):
        self.token = token or SUPERVISOR_TOKEN

    def _headers(self) -> dict:
        return get_supervisor_headers(self.token)

    # -------------------------------------------------------------------------
    # 1. Home Assistant Live States
    # -------------------------------------------------------------------------
    def get_ha_states(self, entity_id: str = "") -> str:
        """Get live state and attributes of an entity, or list all entities if empty."""
        url = f"{SUPERVISOR_URL}/states"
        if entity_id:
            url = f"{SUPERVISOR_URL}/states/{entity_id.strip()}"
        
        try:
            resp = http_requests.get(url, headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    summary = [f"{s['entity_id']}: {s['state']}" for s in data]
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
            return f"Error getting HA states: {e}"

    # -------------------------------------------------------------------------
    # 2. Home Assistant History API
    # -------------------------------------------------------------------------
    def get_ha_history(self, entity_id: str, hours: int = 24) -> str:
        """Fetch historical state transitions for an entity over the past N hours."""
        if not entity_id:
            return "Error: entity_id is required for history lookup."
        
        try:
            past_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
            iso_time = past_dt.isoformat()
            url = f"{SUPERVISOR_URL}/history/period/{iso_time}?filter_entity_id={entity_id.strip()}&significant_changes_only=0"
            resp = http_requests.get(url, headers=self._headers(), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if not data or not data[0]:
                    return f"No history records found for {entity_id} in the last {hours} hours."
                entries = data[0]
                summary = []
                for entry in entries[-25:]: # last 25 transitions
                    summary.append(f"{entry.get('last_changed')}: {entry.get('state')}")
                return f"History for {entity_id} (last {hours} hours, showing {len(summary)} transitions):\n" + "\n".join(summary)
            return f"Error: HTTP {resp.status_code} - {resp.text[:300]}"
        except Exception as e:
            return f"Error fetching history: {e}"

    # -------------------------------------------------------------------------
    # 3. Home Assistant Universal Jinja2 Template Evaluation
    # -------------------------------------------------------------------------
    def render_template(self, template_str: str) -> str:
        """Render a Jinja2 template in Home Assistant Core (universal query engine)."""
        if not template_str:
            return "Error: template_str cannot be empty."
        
        url = f"{SUPERVISOR_URL}/template"
        try:
            resp = http_requests.post(url, headers=self._headers(), json={"template": template_str}, timeout=10)
            if resp.status_code == 200:
                return resp.text.strip()
            return f"Template error: HTTP {resp.status_code} - {resp.text[:300]}"
        except Exception as e:
            return f"Error rendering template: {e}"

    # -------------------------------------------------------------------------
    # 4. Home Assistant Service Actions
    # -------------------------------------------------------------------------
    def call_ha_service(self, domain: str, service: str, service_data: dict = None) -> str:
        """Call a Home Assistant service/action to control devices."""
        url = f"{SUPERVISOR_URL}/services/{domain}/{service}?return_response=true"
        try:
            resp = http_requests.post(url, headers=self._headers(), json=service_data or {}, timeout=15)
            if resp.status_code == 200:
                try:
                    res_json = resp.json()
                    if res_json and "service_response" in res_json:
                        return json.dumps(res_json["service_response"], ensure_ascii=False, indent=2)
                    elif res_json:
                        return json.dumps(res_json, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                return f"Service {domain}.{service} executed successfully."
            return f"Service call failed: HTTP {resp.status_code} - {resp.text[:300]}"
        except Exception as e:
            return f"Error calling service: {e}"

    # -------------------------------------------------------------------------
    # 5. Read-Only MariaDB Database Query Gateway
    # -------------------------------------------------------------------------
    def query_database_readonly(self, query: str, max_rows: int = 50) -> str:
        """Execute a strictly read-only SQL SELECT query on MariaDB."""
        clean_q = query.strip()
        lower_q = clean_q.lower()
        
        if not lower_q.startswith("select"):
            return "Security Error: Only SELECT queries are permitted."
        
        # Block dangerous mutating or admin keywords
        forbidden = ["insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke", "replace", "into outfile", "into dumpfile"]
        for f in forbidden:
            # check as distinct word
            import re
            if re.search(r'\b' + re.escape(f) + r'\b', lower_q):
                return f"Security Error: Keyword '{f}' is forbidden in read-only queries."
        
        # Auto-append limit if not present
        if "limit" not in lower_q:
            clean_q += f" LIMIT {max_rows}"

        try:
            cmd = [
                "mysql", "-h", "core-mariadb",
                "-u", "homeassistant", "-pRene1122",
                "homeassistant", "-e", clean_q
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                return f"Database error: {result.stderr.strip()}"
            return result.stdout.strip() or "(Empty result set)"
        except Exception as e:
            return f"Database execution error: {e}"

    # -------------------------------------------------------------------------
    # 6. Web Research via DuckDuckGo
    # -------------------------------------------------------------------------
    def search_web(self, query: str, max_results: int = 5) -> str:
        """Search the web using DuckDuckGo."""
        if not query:
            return "Error: query cannot be empty."
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No search results found."
            output = []
            for r in results:
                output.append(f"**{r.get('title', '')}**\n{r.get('body', '')}\nURL: {r.get('href', '')}\n")
            return "\n".join(output)
        except Exception as e:
            return f"Web search error: {e}"


# Singleton instance
tool_broker = SecureToolBroker()


def install_cli_helpers():
    """Install standalone CLI helper scripts into /usr/local/bin so Codex & Antigravity CLIs can call them."""
    helpers = {
        "/usr/local/bin/ha-query": """#!/bin/sh
if [ -z "$1" ]; then
    curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/core/api/states
else
    curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" "http://supervisor/core/api/states/$1"
fi
""",
        "/usr/local/bin/ha-template": """#!/bin/sh
if [ -z "$1" ]; then
    echo "Usage: ha-template '<jinja_expression>'"
    exit 1
fi
curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" -H "Content-Type: application/json" -d "{\\"template\\": \\"$1\\"}" http://supervisor/core/api/template
""",
        "/usr/local/bin/ha-history": """#!/bin/sh
if [ -z "$1" ]; then
    echo "Usage: ha-history <entity_id> [hours]"
    exit 1
fi
HOURS=${2:-24}
python3 -c "import os, datetime, requests; h=int('$HOURS'); past=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=h)).isoformat(); r=requests.get(f'http://supervisor/core/api/history/period/{past}?filter_entity_id=$1', headers={'Authorization': f'Bearer {os.environ.get(\\"SUPERVISOR_TOKEN\\")}'}); print(r.text[:2000])"
""",
        "/usr/local/bin/ha-db": """#!/bin/sh
if [ -z "$1" ]; then
    echo "Usage: ha-db '<sql_select_query>'"
    exit 1
fi
mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "$1"
"""
    }

    for path, script in helpers.items():
        try:
            with open(path, "w") as f:
                f.write(script)
            os.chmod(path, 0o755)
        except Exception:
            pass
