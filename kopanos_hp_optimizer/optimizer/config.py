"""Add-on options (/data/options.json) loading + validation. Secrets are never logged."""
from __future__ import annotations

import ipaddress
import json
import logging
import re
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List
from urllib.parse import urlparse

from .const import MODES, OPTIONS_PATH

log = logging.getLogger(__name__)
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
NOTIFY = re.compile(r"^notify\.[a-z0-9_]{1,64}$")
PERSON_RE = re.compile(r"^person\.[a-z0-9_]{1,64}$")
VOICE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
SECRET_FIELDS = {"anthropic_api_key", "remote_ha_token"}
LLM_PROVIDERS = ("brain_openai", "anthropic", "none")
# Site-specific values (remote URL, devices, people, notify targets) are NOT defaulted here: the repo is public.
# They are set in the add-on options at install time.


def _normalize_brain_url(url: str) -> str:
    """Normalize Brain OpenAI URL so /v1 or /v1/ automatically appends /chat/completions."""
    if not url:
        return ""
    u = url.strip()
    if u.endswith("/chat/completions") or u.endswith("/chat/completions/"):
        return u.rstrip("/")
    if u.endswith("/v1"):
        return u + "/chat/completions"
    if u.endswith("/v1/"):
        return u + "chat/completions"
    return u


def is_safe_remote_url(url: str) -> bool:
    """Allow https to any host, but plain http only to Tailscale CGNAT (100.64.0.0/10) or localhost."""
    if not url:
        return False
    try:
        p = urlparse(url)
        if p.scheme == "https":
            return True
        if p.scheme != "http":
            return False
        host = (p.hostname or "").strip("[]")
        if host in ("localhost", "127.0.0.1", "::1"):
            return True
        ip = ipaddress.ip_address(host)
        cgnat = ipaddress.ip_network("100.64.0.0/10")
        return ip in cgnat or ip.is_loopback
    except (ValueError, Exception):
        return False


@dataclass
class Options:
    mode: str = "observe"
    report_hour: str = "10:30"
    notify_targets: List[str] = field(default_factory=list)
    llm_provider: str = "none"
    llm_brain_url: str = ""
    llm_model: str = "gemini-3.8-flash"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    person_entity: str = ""
    remote_ha_url: str = ""
    remote_ha_token: str = ""
    remote_tts_entity: str = "tts.google_ai_tts"
    remote_tts_voice: str = "laomedeia"
    remote_media_player: str = ""
    remote_tts_language: str = "el-GR"
    remote_work_hours: str = "09:00-18:00"
    remote_conditions: List[str] = field(default_factory=list)
    ab_seed: int = 20261114
    away_exclusion: bool = False
    log_level: str = "info"

    def redacted(self) -> Dict[str, Any]:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        for k in SECRET_FIELDS:
            d[k] = "***" if d.get(k) else ""
        return d

    def __repr__(self) -> str:
        return f"Options({self.redacted()})"


def parse_options(raw: Dict[str, Any]) -> Options:
    o = Options()
    known = {f.name for f in fields(Options)}
    for k, v in (raw or {}).items():
        if k in known and v is not None:
            setattr(o, k, v)
    if o.mode not in MODES:
        log.warning("invalid mode -> observe")
        o.mode = "observe"
    if not isinstance(o.report_hour, str) or not HHMM.match(o.report_hour):
        log.warning("invalid report_hour -> 10:30")
        o.report_hour = "10:30"
    o.notify_targets = [t for t in (o.notify_targets or []) if isinstance(t, str) and NOTIFY.match(t)]
    if o.person_entity and (not isinstance(o.person_entity, str) or not PERSON_RE.match(o.person_entity)):
        log.warning("invalid person_entity -> cleared")
        o.person_entity = ""
    if o.llm_provider not in LLM_PROVIDERS:
        o.llm_provider = "none"
    if o.llm_brain_url:
        if not re.match(r"^https?://[A-Za-z0-9.\-:]+(/.*)?$", o.llm_brain_url):
            o.llm_brain_url = ""
        else:
            o.llm_brain_url = _normalize_brain_url(o.llm_brain_url)
    if o.remote_tts_voice and (not isinstance(o.remote_tts_voice, str) or not VOICE_RE.match(o.remote_tts_voice)):
        log.warning("invalid remote_tts_voice -> laomedeia")
        o.remote_tts_voice = "laomedeia"
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$", o.remote_work_hours or ""):
        log.warning("invalid remote_work_hours -> 09:00-18:00")
        o.remote_work_hours = "09:00-18:00"
    if o.remote_ha_url:
        if not re.match(r"^https?://[A-Za-z0-9.\-:\[\]]+(/.*)?$", o.remote_ha_url) or not is_safe_remote_url(o.remote_ha_url):
            log.warning("unsafe remote_ha_url (http only allowed for Tailscale 100.64.0.0/10 or localhost) -> remote TTS disabled")
            o.remote_ha_url = ""
    o.remote_conditions = [c for c in (o.remote_conditions or []) if isinstance(c, str) and c.strip()]
    try:
        o.ab_seed = int(o.ab_seed)
    except (TypeError, ValueError):
        o.ab_seed = 20261114
    o.away_exclusion = bool(o.away_exclusion)
    return o


def load_options(path: str = OPTIONS_PATH) -> Options:
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_options(json.load(fh))
    except FileNotFoundError:
        log.warning("options file missing, using defaults")
        return Options()
