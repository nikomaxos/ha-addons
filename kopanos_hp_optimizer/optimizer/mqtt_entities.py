"""MQTT discovery for all hp_opt_* entities of contract v1 (retained), availability + LWT."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, Optional

import requests

from .const import ADDON_SLUG, VERSION

log = logging.getLogger(__name__)
BASE = ADDON_SLUG
AVAIL = f"{BASE}/availability"
DISC = "homeassistant"
COMMANDS = ("pause", "rollback", "run_report_now")
DEVICE = {"identifiers": [ADDON_SLUG], "name": "Kopanos HP Optimizer", "manufacturer": "Kopanos Home",
          "model": "HP Optimizer add-on", "sw_version": VERSION}

# key -> (component, name, extra)
ENTITIES: Dict[str, tuple] = {
    "mode": ("sensor", "HP Opt Mode", {"icon": "mdi:brain"}),
    "phase": ("sensor", "HP Opt Phase", {"icon": "mdi:stairs"}),
    "ab_today": ("sensor", "HP Opt A/B Today", {"icon": "mdi:ab-testing"}),
    "zone": ("sensor", "HP Opt Zone", {"icon": "mdi:thermometer-lines"}),
    "effect_pct": ("sensor", "HP Opt Effect", {"unit_of_measurement": "%", "state_class": "measurement", "icon": "mdi:percent"}),
    "kwh_per_hdd_7d": ("sensor", "HP Opt kWh/HDD 7d", {"unit_of_measurement": "kWh/HDD", "state_class": "measurement"}),
    "last_cycle_kwh": ("sensor", "HP Opt Last Cycle kWh", {"unit_of_measurement": "kWh", "icon": "mdi:lightning-bolt"}),
    "last_cycle_cost": ("sensor", "HP Opt Last Cycle Cost", {"unit_of_measurement": "€", "icon": "mdi:currency-eur"}),
    "last_action": ("sensor", "HP Opt Last Action", {"icon": "mdi:history"}),
    "last_report": ("sensor", "HP Opt Last Report", {"icon": "mdi:file-document"}),
    "online": ("binary_sensor", "HP Opt Online", {"device_class": "connectivity"}),
    "pause": ("button", "HP Opt Pause", {"icon": "mdi:pause"}),
    "rollback": ("button", "HP Opt Rollback", {"icon": "mdi:undo"}),
    "run_report_now": ("button", "HP Opt Run Report Now", {"icon": "mdi:file-chart"}),
}
assert len(ENTITIES) == 14


def discovery_payloads() -> Dict[str, Dict[str, Any]]:
    """topic -> config payload (pure; tested)."""
    out = {}
    for key, (comp, name, extra) in ENTITIES.items():
        oid = f"hp_opt_{key}"
        p: Dict[str, Any] = {"name": name, "unique_id": f"{ADDON_SLUG}_{oid}",
                             "default_entity_id": f"{comp}.{oid}", "device": DEVICE}
        p.update(extra)
        if comp == "binary_sensor":  # online: driven by availability topic itself (LWT -> off)
            p.update({"state_topic": AVAIL, "payload_on": "online", "payload_off": "offline"})
        elif comp == "button":
            p.update({"command_topic": f"{BASE}/cmd/{key}", "payload_press": "PRESS",
                      "availability_topic": AVAIL})
        else:
            p.update({"state_topic": f"{BASE}/state/{key}", "json_attributes_topic": f"{BASE}/attr/{key}",
                      "availability_topic": AVAIL})
        out[f"{DISC}/{comp}/{ADDON_SLUG}/{oid}/config"] = p
    return out


def fetch_mqtt_service(token: str, url: str = "http://supervisor/services/mqtt") -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        r.raise_for_status()
        return r.json().get("data")
    except Exception as e:  # noqa: BLE001
        log.error("MQTT service lookup failed: %s", type(e).__name__)
        return None


class MqttBridge:
    def __init__(self, cfg: Dict[str, Any], on_command: Callable[[str], None]):
        import paho.mqtt.client as mqtt  # local import keeps tests light
        self._mqtt = mqtt
        self.on_command = on_command
        self.cache: Dict[str, Any] = {}
        self.connected = False
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=ADDON_SLUG)
        if cfg.get("username"):
            self.c.username_pw_set(cfg["username"], cfg.get("password"))
        if cfg.get("ssl"):
            self.c.tls_set()
        self.c.will_set(AVAIL, "offline", qos=1, retain=True)
        self.c.on_connect = self._on_connect
        self.c.on_disconnect = self._on_disconnect
        self.c.on_message = self._on_message
        self.c.reconnect_delay_set(2, 60)
        self.host, self.port = cfg.get("host", "core-mosquitto"), int(cfg.get("port", 1883))

    def start(self) -> None:
        self.c.connect_async(self.host, self.port, keepalive=60)
        self.c.loop_start()

    def stop(self) -> None:
        try:
            self.c.publish(AVAIL, "offline", qos=1, retain=True).wait_for_publish(3)
        except Exception:  # noqa: BLE001
            pass
        self.c.loop_stop()
        self.c.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            log.error("MQTT connect failed: %s", reason_code)
            return
        self.connected = True
        for topic, payload in discovery_payloads().items():
            client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)
        client.publish(AVAIL, "online", qos=1, retain=True)
        for key in COMMANDS:
            client.subscribe(f"{BASE}/cmd/{key}", qos=1)
        for key, (state, attrs) in list(self.cache.items()):
            self._pub(key, state, attrs)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        key = msg.topic.rsplit("/", 1)[-1]
        if key in COMMANDS and msg.payload == b"PRESS":
            threading.Thread(target=self.on_command, args=(key,), daemon=True).start()

    def _pub(self, key: str, state: Any, attrs: Optional[Dict[str, Any]]) -> None:
        s = "" if state is None else str(state)
        self.c.publish(f"{BASE}/state/{key}", s[:255], qos=1, retain=True)
        self.c.publish(f"{BASE}/attr/{key}", json.dumps(attrs or {}, ensure_ascii=False, default=str), qos=1, retain=True)

    def publish(self, key: str, state: Any, attrs: Optional[Dict[str, Any]] = None) -> None:
        if key not in ENTITIES or ENTITIES[key][0] != "sensor":
            raise ValueError(f"unknown sensor key {key}")
        self.cache[key] = (state, attrs)
        if self.connected:
            self._pub(key, state, attrs)

    def online(self) -> None:
        if self.connected:
            self.c.publish(AVAIL, "online", qos=1, retain=True)
