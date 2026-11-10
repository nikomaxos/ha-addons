"""Notifications: local HA persistent_notification + notify targets, optional remote TTS on a
second Home Assistant (Ωραιόκαστρο) gated by conditions. Tokens are never logged."""
from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .config import is_safe_remote_url
from .const import TZ

log = logging.getLogger(__name__)
ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
TTS_RE = re.compile(r"^tts\.[a-z0-9_]+$")
MP_RE = re.compile(r"^media_player\.[a-z0-9_]+$")
PENDING_TTL = timedelta(hours=24)


def parse_hours(spec: str) -> Tuple[time, time]:
    a, b = spec.split("-")
    return time.fromisoformat(a.strip()), time.fromisoformat(b.strip())


class RemoteTTS:
    """Speaks on the remote HA ONLY via tts.speak with the configured tts entity + media player.

    Gate = local time inside work_hours AND every condition in `conditions`:
      "binary_sensor.workday_sensor=on"        state on the REMOTE HA (alternatives with '|')
      "device_tracker.x!=not_home"             negation
      "binary_sensor.office_motion_sensor_occupancy=on~30"
                                               state == on, OR last_changed within 30 minutes
                                               (i.e. it was 'on' until ≤30' ago)
    """

    def __init__(self, url: str, token: str, tts_entity: str, media_player: str, conditions: List[str],
                 work_hours: str = "09:00-18:00", voice: str = "", language: str = "el-GR",
                 session: Optional[requests.Session] = None, timeout: float = 10.0):
        self.url = (url or "").rstrip("/")
        self._token = token or ""
        self.tts_entity = tts_entity if TTS_RE.match(tts_entity or "") else ""
        self.media_player = media_player if MP_RE.match(media_player or "") else ""
        self.conditions = list(conditions or [])
        self.work_hours = work_hours
        self.voice = voice
        self.language = language or "el-GR"
        self.s = session or requests.Session()
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"RemoteTTS({self.url!r}, {self.tts_entity!r}, {self.media_player!r})"

    @property
    def configured(self) -> bool:
        return bool(self.url and self._token and self.tts_entity and self.media_player and is_safe_remote_url(self.url))

    def _h(self) -> dict:
        if not is_safe_remote_url(self.url):
            raise PermissionError("unsafe remote_ha_url: plain http only permitted for Tailscale CGNAT (100.64.0.0/10) or localhost")
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _remote_state(self, entity_id: str) -> Optional[dict]:
        if not ENTITY_RE.match(entity_id):
            return None
        r = self.s.get(f"{self.url}/api/states/{entity_id}", headers=self._h(), timeout=self.timeout)
        if r.status_code != 200:
            return None
        return r.json()

    def _remote_history(self, entity_id: str, start: datetime, end: datetime) -> Optional[List[dict]]:
        if not ENTITY_RE.match(entity_id):
            return None
        ts = start.isoformat()
        try:
            r = self.s.get(f"{self.url}/api/history/period/{ts}?filter_entity_id={entity_id}&end_time={end.isoformat()}",
                           headers=self._h(), timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    return data[0] if isinstance(data[0], list) else data
        except Exception:
            pass
        return None

    def check_conditions(self, now: datetime) -> Tuple[bool, List[str]]:
        local = now.astimezone(TZ)
        failed: List[str] = []
        try:
            ta, tb = parse_hours(self.work_hours)
            if not (ta <= local.time() <= tb):
                failed.append(f"work_hours {self.work_hours}")
        except Exception:  # noqa: BLE001
            failed.append("work_hours (invalid)")
        if failed:  # cheap local check first: no remote calls outside work hours
            return False, failed
        for c in self.conditions:
            c = c.strip()
            try:
                neg = "!=" in c
                ent, val = c.split("!=" if neg else "=", 1)
                recent_min = None
                if "~" in val:
                    val, rm = val.split("~", 1)
                    recent_min = float(rm)
                wanted = {v.strip() for v in val.split("|")}
                st = self._remote_state(ent.strip())
                if st is None:
                    failed.append(f"{c} (unavailable)")
                    continue
                state = st.get("state")
                match = (state not in wanted) if neg else (state in wanted)
                if not match and recent_min is not None:
                    h_pts = self._remote_history(ent.strip(), now - timedelta(minutes=recent_min), now)
                    if h_pts is not None:
                        match = any(pt.get("state") in wanted for pt in h_pts)
                    elif st.get("last_changed"):
                        lc = datetime.fromisoformat(st["last_changed"].replace("Z", "+00:00"))
                        match = (now - lc) <= timedelta(minutes=recent_min)
                if not match:
                    failed.append(c)
            except Exception as e:  # noqa: BLE001 — never leak token / url details
                failed.append(f"{c} ({type(e).__name__})")
        return (not failed), failed

    def speak(self, message: str) -> None:
        payload: Dict[str, Any] = {"entity_id": self.tts_entity, "media_player_entity_id": self.media_player,
                                   "message": message[:600], "language": self.language, "cache": False}
        if self.voice:
            payload["options"] = {"voice": self.voice}
        r = self.s.post(f"{self.url}/api/services/tts/speak", headers=self._h(), json=payload, timeout=self.timeout)
        if r.status_code >= 300:
            raise RuntimeError(f"remote tts HTTP {r.status_code}")


class Notifier:
    def __init__(self, ha: Any, targets: List[str], remote: Optional[RemoteTTS] = None,
                 event_cb: Optional[Callable[[str, str], None]] = None):
        self.ha = ha
        self.targets = list(targets or [])
        self.remote = remote
        self.event_cb = event_cb or (lambda k, m: None)
        self.pending_tts: Optional[Dict[str, Any]] = None  # deferred MAIN morning report only

    def _try_tts(self, text: str, now: datetime) -> Tuple[bool, List[str]]:
        if not (self.remote and self.remote.configured):
            return False, ["remote not configured"]
        allowed, failed = self.remote.check_conditions(now)
        if not allowed:
            return False, failed
        self.remote.speak(text)
        return True, []

    def notify(self, kind: str, title: str, message: str, tts: Optional[str] = None,
               now: Optional[datetime] = None, defer_tts: bool = False) -> List[str]:
        """Send to all channels. defer_tts=True (main morning report only) keeps the spoken summary
        pending until the remote conditions hold (TTL 24h, replaced by newer reports)."""
        now = now or datetime.now(TZ)
        ok: List[str] = []
        try:
            self.ha.persistent_notification(title, message, f"hp_optimizer_{kind}")
            ok.append("persistent")
        except Exception as e:  # noqa: BLE001
            self.event_cb("notify_error", f"persistent_notification: {type(e).__name__}")
        for t in self.targets:
            try:
                self.ha.notify(t, title, message)
                ok.append(t)
            except Exception as e:  # noqa: BLE001
                self.event_cb("notify_error", f"{t}: {type(e).__name__}")
        if tts and self.remote and self.remote.configured:
            try:
                spoken, failed = self._try_tts(tts, now)
                if spoken:
                    ok.append("remote_tts")
                    if defer_tts:
                        self.pending_tts = None
                else:
                    if defer_tts:
                        self.pending_tts = {"text": tts, "created": now}
                    self.event_cb("tts_skipped", "conditions: " + "; ".join(failed))
            except Exception as e:  # noqa: BLE001
                if defer_tts:
                    self.pending_tts = {"text": tts, "created": now}
                self.event_cb("notify_error", f"remote_tts: {type(e).__name__}")
        return ok

    def retry_pending(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(TZ)
        p = self.pending_tts
        if not p:
            return False
        if now - p["created"] > PENDING_TTL:
            self.pending_tts = None
            return False
        try:
            spoken, _ = self._try_tts(p["text"], now)
        except Exception as e:  # noqa: BLE001
            self.event_cb("notify_error", f"remote_tts retry: {type(e).__name__}")
            return False
        if spoken:
            self.pending_tts = None
        return spoken
