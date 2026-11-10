"""Home Assistant REST client with a STRICT write allowlist.

Write path rules (defence in depth):
  1. Only entities in const.ALLOWLIST (9 helpers) can be written — anything else raises WriteRejected.
  2. The service is derived internally from the helper kind; callers can NOT choose a service.
  3. Values are validated and clamped / snapped to the contract ranges.
  4. Mode gating: observe -> heartbeat only; ab_test / autotune -> const.MODE_WRITABLE.
  5. Paused -> heartbeat only (unless explicit rollback restore).
  6. off_only helpers (autotune consent switch) can only be switched OFF.
  7. The low-level _post() re-checks the (domain, service) pair against a fixed set.
Notifications go through dedicated methods (persistent_notification.create / notify.<name>),
which carry no entity_id and cannot reach the heat pump.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from .const import ALLOWLIST, HEARTBEAT, MODE_WRITABLE, READONLY_SERVICES, TZ, HelperSpec

log = logging.getLogger(__name__)

_KIND_SERVICE = {
    "select": ("input_select", "select_option"),
    "number": ("input_number", "set_value"),
    "datetime": ("input_datetime", "set_datetime"),
    "text": ("input_text", "set_value"),
}
_WRITE_SERVICES = frozenset({
    ("input_boolean", "turn_on"), ("input_boolean", "turn_off"),
    *_KIND_SERVICE.values(),
    ("persistent_notification", "create"),
})
NOTIFY_RE = re.compile(r"^notify\.[a-z0-9_]{1,64}$")


class WriteRejected(Exception):
    """Raised for any write that violates the allowlist / policy."""


def validate_helper_value(entity_id: str, value: Any) -> Tuple[str, str, Dict[str, Any], Any]:
    """Return (domain, service, data, normalized_value) or raise WriteRejected. Pure function."""
    spec: Optional[HelperSpec] = ALLOWLIST.get(entity_id) if isinstance(entity_id, str) else None
    if spec is None:
        raise WriteRejected(f"entity not in allowlist: {entity_id!r}")
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise WriteRejected(f"{entity_id}: bool required")
        if spec.off_only and value:
            raise WriteRejected(f"{entity_id}: add-on may only switch this OFF (user consent switch)")
        return "input_boolean", "turn_on" if value else "turn_off", {"entity_id": entity_id}, value
    if spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WriteRejected(f"{entity_id}: number required")
        v = float(value)
        if not math.isfinite(v):
            raise WriteRejected(f"{entity_id}: non-finite value")
        lo, hi, st = float(spec.minimum), float(spec.maximum), float(spec.step)
        v = min(max(v, lo), hi)
        v = lo + round((v - lo) / st) * st
        v = round(min(max(v, lo), hi), 4)
        dom, srv = _KIND_SERVICE["number"]
        return dom, srv, {"entity_id": entity_id, "value": v}, v
    if spec.kind in ("select", "text"):
        if not isinstance(value, str) or value not in spec.options:
            raise WriteRejected(f"{entity_id}: value {value!r} not in {spec.options}")
        dom, srv = _KIND_SERVICE[spec.kind]
        key = "option" if spec.kind == "select" else "value"
        return dom, srv, {"entity_id": entity_id, key: value}, value
    if spec.kind == "datetime":
        if not isinstance(value, datetime):
            raise WriteRejected(f"{entity_id}: datetime required")
        local = value.astimezone(TZ) if value.tzinfo else value.replace(tzinfo=TZ)
        s = local.strftime("%Y-%m-%d %H:%M:%S")
        dom, srv = _KIND_SERVICE["datetime"]
        return dom, srv, {"entity_id": entity_id, "datetime": s}, s
    raise WriteRejected(f"{entity_id}: unsupported kind {spec.kind}")  # pragma: no cover


def check_policy(entity_id: str, value: Any, mode: str, paused: bool, restore: bool = False) -> None:
    """Mode / pause policy on top of the allowlist. Raises WriteRejected."""
    if entity_id not in ALLOWLIST:
        raise WriteRejected(f"entity not in allowlist: {entity_id!r}")
    if mode not in MODE_WRITABLE:
        raise WriteRejected(f"unknown mode {mode!r}")
    if entity_id == HEARTBEAT:
        return
    if mode == "observe":
        raise WriteRejected("observe mode: no helper writes except heartbeat")
    if paused and not restore:
        raise WriteRejected("optimizer paused: no helper writes except heartbeat")
    if entity_id not in MODE_WRITABLE[mode] and not restore:
        raise WriteRejected(f"mode {mode}: {entity_id} not writable")


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class HAClient:
    def __init__(self, base_url: str, token: str, timeout: float = 20.0, session: Optional[requests.Session] = None):
        self.base = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self.s = session or requests.Session()

    def __repr__(self) -> str:  # never leak token
        return f"HAClient({self.base!r})"

    @property
    def _h(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    # ---------------------------------------------------------------- reads
    def _get(self, path: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> Any:
        r = self.s.get(self.base + path, headers=self._h, params=params, timeout=timeout or self.timeout)
        r.raise_for_status()
        return r.json()

    def ping(self) -> bool:
        try:
            return self._get("/").get("message") is not None
        except Exception:  # noqa: BLE001
            return False

    def get_state(self, entity_id: str) -> Optional[dict]:
        try:
            return self._get(f"/states/{entity_id}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise

    def get_states(self) -> List[dict]:
        return self._get("/states")

    def history(self, entity_ids: Iterable[str], start: datetime, end: datetime,
                attributes: bool = False) -> Dict[str, List[Tuple[datetime, Any]]]:
        ids = list(entity_ids)
        params = {"filter_entity_id": ",".join(ids), "end_time": end.isoformat(),
                  "significant_changes_only": "0"}
        if not attributes:
            params["minimal_response"] = ""
            params["no_attributes"] = ""
        data = self._get(f"/history/period/{start.isoformat()}", params=params, timeout=120)
        out: Dict[str, List[Tuple[datetime, Any]]] = {e: [] for e in ids}
        for series in data or []:
            if not series:
                continue
            eid = series[0].get("entity_id")
            for p in series:
                ts = p.get("last_changed") or p.get("last_updated")
                if attributes:
                    val: Any = {"state": p.get("state"), **(p.get("attributes") or {})}
                else:
                    val = p.get("state")
                out.setdefault(eid, []).append((parse_ts(ts), val))
        return out

    def call_readonly_service(self, domain: str, service: str, data: dict) -> Any:
        if (domain, service) not in READONLY_SERVICES:
            raise WriteRejected(f"service {domain}.{service} not in read-only allowlist")
        r = self.s.post(f"{self.base}/services/{domain}/{service}?return_response", headers=self._h,
                        json=data, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def daily_forecast(self, weather_entity: str) -> List[dict]:
        try:
            res = self.call_readonly_service("weather", "get_forecasts", {"entity_id": weather_entity, "type": "daily"})
            return (res.get("service_response") or {}).get(weather_entity, {}).get("forecast", []) or []
        except Exception as e:  # noqa: BLE001
            log.warning("forecast unavailable: %s", type(e).__name__)
            return []

    # ---------------------------------------------------------------- writes
    def _post(self, domain: str, service: str, data: dict) -> None:
        if (domain, service) not in _WRITE_SERVICES and not (domain == "notify" and NOTIFY_RE.match(f"notify.{service}")):
            raise WriteRejected(f"service {domain}.{service} not allowed")
        if domain.startswith("input_") and data.get("entity_id") not in ALLOWLIST:
            raise WriteRejected("entity not in allowlist")
        r = self.s.post(f"{self.base}/services/{domain}/{service}", headers=self._h, json=data, timeout=self.timeout)
        r.raise_for_status()

    def set_helper(self, entity_id: str, value: Any, *, mode: str, paused: bool, restore: bool = False) -> Any:
        """The ONLY helper write entry point. Returns the normalized value actually written."""
        domain, service, data, norm = validate_helper_value(entity_id, value)
        check_policy(entity_id, value, mode, paused, restore)
        self._post(domain, service, data)
        return norm

    def persistent_notification(self, title: str, message: str, notification_id: str) -> None:
        self._post("persistent_notification", "create",
                   {"title": title[:200], "message": message[:8000], "notification_id": notification_id[:64]})

    def notify(self, target: str, title: str, message: str, data: Optional[dict] = None) -> None:
        if not isinstance(target, str) or not NOTIFY_RE.match(target):
            raise WriteRejected(f"invalid notify target {target!r}")
        payload: Dict[str, Any] = {"title": title[:200], "message": message[:4000]}
        if data:
            payload["data"] = data
        self._post("notify", target.split(".", 1)[1], payload)
