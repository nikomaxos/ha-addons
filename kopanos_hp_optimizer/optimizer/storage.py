"""SQLite persistence in /data/optimizer.db (thread-safe, single connection + lock)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle_date TEXT UNIQUE NOT NULL,
  start TEXT NOT NULL, end TEXT NOT NULL,
  mode TEXT, assignment TEXT, pair_id TEXT, arm TEXT, zone TEXT, applied_json TEXT,
  valid INTEGER, exclusions TEXT, kpi_json TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, entity TEXT NOT NULL, old TEXT, new TEXT, reason TEXT, mode TEXT, ok INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
  plan_date TEXT PRIMARY KEY, assignment TEXT, pair_id TEXT, arm TEXT, zone TEXT, applied_json TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.executescript(SCHEMA)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.commit()

    # kv -------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self.db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, json.dumps(value, ensure_ascii=False)))
            self.db.commit()

    # cycles ---------------------------------------------------------------
    def save_cycle(self, cycle_date: str, start: str, end: str, kpi: Dict[str, Any], *, mode: str,
                   assignment: Optional[str], pair_id: Optional[str], arm: Optional[str], zone: Optional[str],
                   applied: Optional[Dict[str, Any]], valid: bool, exclusions: List[str]) -> None:
        with self._lock:
            self.db.execute(
                """INSERT INTO cycles(cycle_date,start,end,mode,assignment,pair_id,arm,zone,applied_json,valid,exclusions,kpi_json,created)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(cycle_date) DO UPDATE SET start=excluded.start,end=excluded.end,mode=excluded.mode,
                   assignment=excluded.assignment,pair_id=excluded.pair_id,arm=excluded.arm,zone=excluded.zone,
                   applied_json=excluded.applied_json,valid=excluded.valid,exclusions=excluded.exclusions,
                   kpi_json=excluded.kpi_json,created=excluded.created""",
                (cycle_date, start, end, mode, assignment, pair_id, arm, zone, json.dumps(applied),
                 1 if valid else 0, json.dumps(exclusions, ensure_ascii=False), json.dumps(kpi, ensure_ascii=False), _now()))
            self.db.commit()

    def has_cycle(self, cycle_date: str) -> bool:
        with self._lock:
            return self.db.execute("SELECT 1 FROM cycles WHERE cycle_date=?", (cycle_date,)).fetchone() is not None

    def cycles(self, limit: int = 60) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM cycles ORDER BY cycle_date DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["kpi"] = json.loads(d.pop("kpi_json"))
            d["applied"] = json.loads(d.pop("applied_json") or "null")
            d["exclusions"] = json.loads(d["exclusions"] or "[]")
            d["valid"] = bool(d["valid"])
            out.append(d)
        return out

    # plans ------------------------------------------------------------------
    def save_plan(self, plan_date: str, assignment: str, pair_id: Optional[str], arm: Optional[str],
                  zone: Optional[str], applied: Optional[Dict[str, Any]]) -> None:
        with self._lock:
            self.db.execute("""INSERT INTO plans VALUES(?,?,?,?,?,?) ON CONFLICT(plan_date) DO UPDATE SET
                               assignment=excluded.assignment,pair_id=excluded.pair_id,arm=excluded.arm,
                               zone=excluded.zone,applied_json=excluded.applied_json""",
                            (plan_date, assignment, pair_id, arm, zone, json.dumps(applied)))
            self.db.commit()

    def plan(self, plan_date: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self.db.execute("SELECT * FROM plans WHERE plan_date=?", (plan_date,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["applied"] = json.loads(d.pop("applied_json") or "null")
        return d

    # change log -------------------------------------------------------------------
    def log_change(self, entity: str, old: Any, new: Any, reason: str, mode: str, ok: bool, error: str = "") -> None:
        with self._lock:
            self.db.execute("INSERT INTO changes(ts,entity,old,new,reason,mode,ok,error) VALUES(?,?,?,?,?,?,?,?)",
                            (_now(), entity, json.dumps(old), json.dumps(new), reason, mode, 1 if ok else 0, error[:500]))
            self.db.commit()

    def changes(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM changes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def first_old_values(self) -> Dict[str, Any]:
        """Value each entity had before the add-on's FIRST successful change (rollback snapshot)."""
        with self._lock:
            rows = self.db.execute(
                "SELECT entity, old FROM changes WHERE ok=1 AND id IN (SELECT MIN(id) FROM changes WHERE ok=1 GROUP BY entity)"
            ).fetchall()
        return {r["entity"]: json.loads(r["old"]) for r in rows}

    # events -----------------------------------------------------------------------
    def event(self, kind: str, message: str) -> None:
        with self._lock:
            self.db.execute("INSERT INTO events(ts,kind,message) VALUES(?,?,?)", (_now(), kind, message[:2000]))
            self.db.commit()

    def events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
