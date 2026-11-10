"""Ingress dashboard (FastAPI). Only reachable via HA ingress (172.30.32.2) — no host port is exposed."""
from __future__ import annotations

import html
import json
from typing import Any, Iterable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .const import VERSION

INGRESS_IPS = frozenset({"172.30.32.2", "127.0.0.1"})

PAGE = """<!doctype html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>HP Optimizer</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#111827;color:#e5e7eb}}
main{{max-width:1100px;margin:auto;padding:16px}} h1{{font-size:1.3rem}} h2{{font-size:1.05rem;margin-top:24px}}
.card{{background:#1f2937;border-radius:10px;padding:12px 16px;margin:10px 0}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}} td,th{{border-bottom:1px solid #374151;padding:4px 6px;text-align:left}}
button{{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:8px 14px;margin-right:8px;cursor:pointer}}
button.warn{{background:#b45309}} button.danger{{background:#b91c1c}} .muted{{color:#9ca3af}} pre{{white-space:pre-wrap}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}} .k{{font-size:.75rem;color:#9ca3af}} .v{{font-size:1.1rem}}
</style></head><body><main>
<h1>🧠 Kopanos HP Optimizer <span class="muted">v{version}</span></h1>
<div class="card"><div class="grid">{status}</div></div>
<div class="card">
<button onclick="act('pause')" class="warn">⏸ Pause</button>
<button onclick="act('resume')">▶ Resume</button>
<button onclick="if(confirm('Rollback όλων των αλλαγών του add-on;'))act('rollback')" class="danger">↩ Rollback</button>
<button onclick="act('run_report')">📄 Run report</button> <span id="msg" class="muted"></span></div>
<h2>Τελευταία αναφορά</h2><div class="card"><pre>{report}</pre></div>
<h2>Ιστορικό κύκλων</h2><div class="card"><table><tr><th>Κύκλος</th><th>Mode</th><th>A/B</th><th>Ζώνη</th><th>kWh</th><th>€</th><th>HDD</th><th>kWh/HDD</th><th>Εκκ.</th><th>≤22Hz%</th><th>EEPROM</th><th>Έγκυρη</th></tr>{cycles}</table></div>
<h2>Change log</h2><div class="card"><table><tr><th>Χρόνος</th><th>Entity</th><th>Παλιά</th><th>Νέα</th><th>Αιτία</th><th>OK</th><th>Σφάλμα</th></tr>{changes}</table></div>
<h2>Συμβάντα</h2><div class="card"><table><tr><th>Χρόνος</th><th>Είδος</th><th>Μήνυμα</th></tr>{events}</table></div>
</main><script>
async function act(a){{const m=document.getElementById('msg');m.textContent='…';
try{{const r=await fetch('api/'+a,{{method:'POST',headers:{{'X-Requested-With':'hp-optimizer'}}}});
m.textContent=r.ok?'OK':('Σφάλμα '+r.status);if(r.ok)setTimeout(()=>location.reload(),800);}}catch(e){{m.textContent='Σφάλμα';}}}}
</script></body></html>"""


def e(v: Any) -> str:
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return html.escape("—" if v is None else str(v))


def _rows(items: Iterable[Iterable[Any]]) -> str:
    return "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in items)


def create_app(opt: Any, allowed_ips: frozenset = INGRESS_IPS) -> FastAPI:
    app = FastAPI(title="Kopanos HP Optimizer", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def ingress_only(request: Request, call_next):
        host = request.client.host if request.client else ""
        if host not in allowed_ips:
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        if request.method == "POST" and request.headers.get("x-requested-with") != "hp-optimizer":
            return JSONResponse({"detail": "missing X-Requested-With"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'self';"
        )
        return resp

    def status() -> dict:
        s = opt.store
        return {"mode": opt.mode, "paused": opt.paused, "pause_reason": s.get("pause_reason", ""),
                "zone": s.get("zone"), "last_heartbeat": s.get("last_heartbeat"), "last_closed": s.get("last_closed"),
                "health_issues": s.get("health_issues", []), "ab_result": s.get("ab_result"),
                "last_action": s.get("last_action"), "kwh_per_hdd_7d": opt.kwh_per_hdd_7d()}

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        st = status()
        ab = st["ab_result"] or {}
        tiles = {
            "Mode": st["mode"] + (" ⏸" if st["paused"] else ""), "Αιτία παύσης": st["pause_reason"] or "—",
            "Ζώνη": st["zone"], "kWh/HDD 7d": st["kwh_per_hdd_7d"],
            "Επίδραση A/B": f"{ab.get('effect_pct')}% [{ab.get('ci_low_pct')}…{ab.get('ci_high_pct')}] n={ab.get('n_pairs')}" if ab else "—",
            "Heartbeat": st["last_heartbeat"], "Τελ. κύκλος": st["last_closed"],
            "Υγεία": ", ".join(st["health_issues"]) or "OK",
            "Τελ. ενέργεια": (st["last_action"] or {}).get("text"),
        }
        status_html = "".join(f'<div><div class="k">{e(k)}</div><div class="v">{e(v)}</div></div>' for k, v in tiles.items())
        cyc = [(c["cycle_date"], c["mode"], c["assignment"], c["zone"], c["kpi"].get("kwh"), c["kpi"].get("cost_eur"),
                c["kpi"].get("hdd"), c["kpi"].get("kwh_per_hdd"), c["kpi"].get("starts"), c["kpi"].get("low_hz_ratio_pct"),
                c["kpi"].get("eeprom_writes"), "✔" if c["valid"] else "✖ " + ",".join(c["exclusions"]))
               for c in opt.store.cycles(60)]
        ch = [(c["ts"][:19], c["entity"], c["old"], c["new"], c["reason"], "✔" if c["ok"] else "✖", c["error"])
              for c in opt.store.changes(100)]
        ev = [(x["ts"][:19], x["kind"], x["message"]) for x in opt.store.events(50)]
        rep = (opt.store.get("last_report") or {}).get("markdown") or "—"
        return PAGE.format(version=VERSION, status=status_html, report=e(rep), cycles=_rows(cyc),
                           changes=_rows(ch), events=_rows(ev))

    @app.get("/api/status")
    def api_status() -> dict:
        return status()

    @app.get("/api/cycles")
    def api_cycles(limit: int = 60) -> list:
        return opt.store.cycles(max(1, min(limit, 400)))

    @app.get("/api/changes")
    def api_changes(limit: int = 100) -> list:
        return opt.store.changes(max(1, min(limit, 1000)))

    @app.get("/api/tuner")
    def api_tuner() -> dict:
        return opt.tuner_state()

    @app.post("/api/{action}")
    def api_action(action: str) -> dict:
        mapping = {"pause": "pause", "resume": "resume", "rollback": "rollback", "run_report": "run_report_now"}
        if action not in mapping:
            raise HTTPException(404)
        res = opt.command(mapping[action])
        return {"ok": True, "result": res if isinstance(res, dict) else None}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    return app
