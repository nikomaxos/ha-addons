"""CLI: replay KPIs + HA watchdog rules over recorded history.

  python -m optimizer.replay --from 2026-11-03 --to 2026-11-10T10:30 --file history.json.gz
  python -m optimizer.replay --from 2026-11-03 --to 2026-11-10T10:30 --url http://supervisor/core/api
      (token from env SUPERVISOR_TOKEN or HA_TOKEN — never pass tokens as arguments)
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict

from .const import E, TZ
from .kpi import compute_kpis, needed_entities
from .watchdog_replay import WATCHDOG_ENTITIES, replay, summarize


def parse_dt(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def load_file(path: str) -> Dict[str, Any]:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        d = json.load(fh)
    h = d.get("history", d)
    return {e: [(datetime.fromisoformat(t), v) for t, v in pts] for e, pts in h.items()}


def load_api(url: str, start: datetime, end: datetime) -> Dict[str, Any]:
    from .ha_client import HAClient
    token = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN") or ""
    ha = HAClient(url, token)
    ents = sorted(set(needed_entities()) | set(WATCHDOG_ENTITIES))
    hist: Dict[str, Any] = {}
    t = start
    while t < end:  # day chunks keep responses small
        t2 = min(t + timedelta(days=1), end)
        for e, pts in ha.history(ents, t, t2).items():
            hist.setdefault(e, []).extend(pts)
        t = t2
    return hist


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="optimizer.replay")
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file")
    src.add_argument("--url")
    ap.add_argument("--starts-limit", type=int, default=3)
    ap.add_argument("--kpi", action="store_true", help="also print daily KPIs")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    start, end = parse_dt(a.start), parse_dt(a.end)
    hist = load_file(a.file) if a.file else load_api(a.url, start, end)
    out: Dict[str, Any] = {"window": [start.isoformat(), end.isoformat()],
                           "watchdog": summarize(replay(hist, start, end, a.starts_limit))}
    if a.kpi:
        days = []
        d = start
        while d < end:
            d2 = min(d + timedelta(days=1), end)
            k = compute_kpis(hist, d, d2)
            days.append({x: k[x] for x in ("start", "kwh", "kwh_per_hdd", "starts", "max_starts_per_hour",
                                           "max_starts_per_hour_room", "low_hz_ratio_pct", "comfort_within_03_pct",
                                           "eeprom_max_daily", "defrosts", "defrosts_tout_gt7", "low_flow_minutes_room")})
            d = d2
        out["kpi_days"] = days
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    else:
        print(f"Watchdog replay {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} (Europe/Athens)")
        for k, v in out["watchdog"].items():
            if k.startswith("_"):
                print(f"  {k}: {v}")
            else:
                print(f"  {k:28s} {v['count']:4d}  {v['per_day']}  first={v['first']}")
        for d in out.get("kpi_days", []):
            print("  ", d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
