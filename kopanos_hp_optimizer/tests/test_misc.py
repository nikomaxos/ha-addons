import json
import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml  # noqa: F401  (pyyaml optional)

from optimizer.config import Options, parse_options
from optimizer.const import TZ, VERSION
from optimizer.mqtt_entities import ENTITIES, discovery_payloads
from optimizer.notifier import Notifier, RemoteTTS
from optimizer.reporter import Reporter, WordingProvider, validate_wording

ROOT = Path(__file__).resolve().parents[1]

CONTRACT_MQTT = {
    "sensor.hp_opt_mode", "sensor.hp_opt_phase", "sensor.hp_opt_ab_today", "sensor.hp_opt_zone",
    "sensor.hp_opt_effect_pct", "sensor.hp_opt_kwh_per_hdd_7d", "sensor.hp_opt_last_cycle_kwh",
    "sensor.hp_opt_last_cycle_cost", "sensor.hp_opt_last_action", "sensor.hp_opt_last_report",
    "binary_sensor.hp_opt_online", "button.hp_opt_pause", "button.hp_opt_rollback", "button.hp_opt_run_report_now",
}


def test_mqtt_discovery_matches_contract():
    p = discovery_payloads()
    assert {v["default_entity_id"] for v in p.values()} == CONTRACT_MQTT
    online = next(v for v in p.values() if v["default_entity_id"] == "binary_sensor.hp_opt_online")
    assert online["state_topic"].endswith("/availability") and "availability_topic" not in online
    for v in p.values():
        assert v["unique_id"].startswith("kopanos_hp_optimizer_")
        if v["default_entity_id"].startswith("button."):
            assert v["payload_press"] == "PRESS"


def test_options_parse_and_redaction():
    o = parse_options({"mode": "bogus", "report_hour": "25:00", "notify_targets": ["notify.ok_1", "light.x"],
                       "remote_ha_token": "SECRET", "anthropic_api_key": "SK", "remote_ha_url": "javascript:alert(1)",
                       "llm_provider": "evil", "remote_work_hours": "9-5"})
    assert o.mode == "observe" and o.report_hour == "10:30" and o.notify_targets == ["notify.ok_1"]
    assert o.remote_ha_url == "" and o.llm_provider == "none" and o.remote_work_hours == "09:00-18:00"
    assert "SECRET" not in repr(o) and "SK" not in json.dumps(o.redacted())


def test_config_yaml_consistent():
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    import yaml as y
    cfg = y.safe_load(text)
    assert cfg["version"] == VERSION and cfg["ingress_port"] == 8010 and cfg["homeassistant_api"] is True
    assert cfg["services"] == ["mqtt:need"] and "ports" not in cfg
    assert cfg["watchdog"].startswith("tcp://")
    assert set(cfg["options"]) <= set(cfg["schema"])
    assert cfg["options"]["mode"] == "observe"
    for secret in ("remote_ha_token", "anthropic_api_key"):
        assert cfg["schema"][secret] == "password?" and secret not in cfg["options"]
    # option defaults must satisfy their own match() schemas
    for k, sch in cfg["schema"].items():
        sch = sch[0] if isinstance(sch, list) else sch
        m = re.match(r"match\((.*)\)\??$", str(sch))
        if m and k in cfg["options"]:
            vals = cfg["options"][k] if isinstance(cfg["options"][k], list) else [cfg["options"][k]]
            for v in vals:
                assert re.match(m.group(1), str(v)), (k, v)
    # defaults equal dataclass defaults
    o = Options()
    for k, v in cfg["options"].items():
        assert getattr(o, k) == v, k


def test_validate_wording_blocks_new_numbers():
    facts = "Κατανάλωση 15,60 kWh, 2,520 kWh/HDD, 17 εκκινήσεις, -10%."
    assert validate_wording("Χθες καταναλώσαμε 15,6 kWh με 17 εκκινήσεις και -10%.", facts)
    assert validate_wording("Χθες καταναλώσαμε 15,6 kWh, εξοικονόμηση 30%.", facts) is None
    assert validate_wording("Χθες καταναλώσαμε 15,6 kWh και +10%.", facts) is None
    assert validate_wording("Δες λεπτομέρειες στο https://example.com", facts) is None
    assert validate_wording("Δες λεπτομέρειες στο http://example.com", facts) is None
    assert validate_wording("![γράφημα](image.png)", facts) is None
    assert validate_wording("", facts) is None and validate_wording("x" * 2000, facts) is None
    assert validate_wording("10 kWh", "1 kWh") is None


class BadLLM(WordingProvider):
    name = "bad"

    def rephrase(self, draft):
        return "Εξοικονομήσαμε 99% σήμερα!"


class BoomLLM(WordingProvider):
    name = "boom"

    def rephrase(self, draft):
        raise TimeoutError()


@pytest.mark.parametrize("prov", [WordingProvider(), BadLLM(), BoomLLM()])
def test_report_falls_back_to_template(prov):
    rep = Reporter(prov).build(cycle_date="2026-11-12", mode="ab_test", assignment="ON", zone="7–12",
                               action="ramp_multiplier 2.0 → 2.5", kpi={"kwh": 15.6, "cost_eur": 2.59, "kwh_per_hdd": 2.52,
                                                                       "starts": 17, "eeprom_writes": 9, "eeprom_max_daily": 9},
                               baseline={"kwh_per_hdd": 2.8, "kwh": 16.0}, ab=None, next_text="μέρα OFF",
                               exclusions=[])
    assert rep["wording"] == "template"
    assert "| kWh/HDD | 2,520 | 2,800 | -10,0% |" in rep["markdown"]
    assert "99%" not in rep["markdown"] and len(rep["short"]) <= 255
    assert rep["title"].startswith("🧠 HP Optimizer · Κύκλος 2026-11-12 (ON) · Ζώνη 7–12")


class FakeRemoteSession:
    def __init__(self, states):
        self.states = states
        self.posts = []

    def get(self, url, headers=None, timeout=None):
        class R:
            pass
        if "/api/history/period/" in url:
            eid = url.split("filter_entity_id=")[1].split("&")[0] if "filter_entity_id=" in url else ""
            st = self.states.get(eid, {})
            hist = []
            if st:
                ts_str = url.split("/api/history/period/")[1].split("?")[0]
                try:
                    start_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    lc = datetime.fromisoformat(st["last_changed"].replace("Z", "+00:00"))
                    if lc >= start_dt:
                        hist.append({"entity_id": eid, "state": "on", "last_changed": st.get("last_changed")})
                except Exception:
                    pass
                hist.append({"entity_id": eid, "state": st.get("state"), "last_changed": st.get("last_changed")})
            r = R()
            r.status_code = 200
            r.json = lambda: [hist]
            return r

        eid = url.rsplit("/", 1)[1]
        r = R()
        if eid in self.states:
            r.status_code = 200
            st = self.states[eid]
            r.json = lambda: st
        else:
            r.status_code = 404
            r.json = lambda: {}
        return r

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, json))

        class R:
            status_code = 200
        return R()


REMOTE_OK = {
    "binary_sensor.workday_sensor": {"state": "on"},
    "input_boolean.dnd_mode": {"state": "off"},
    "person.user": {"state": "home"},
    "binary_sensor.office_motion_sensor_occupancy": {"state": "off", "last_changed": "2026-11-10T08:50:00+00:00"},
}
CONDS = ["binary_sensor.workday_sensor=on", "input_boolean.dnd_mode=off", "person.user=home",
         "binary_sensor.office_motion_sensor_occupancy=on~30"]


def remote(states):
    s = FakeRemoteSession(states)
    return RemoteTTS("http://100.64.0.1:8123", "TOKEN", "tts.google_cloud",
                     "media_player.speaker", CONDS, "09:00-18:00",
                     voice="el-GR-Chirp3-HD-Laomedeia", session=s), s


def test_remote_tts_conditions():
    now = datetime(2026, 11, 10, 11, 0, tzinfo=TZ)  # 09:00 UTC; motion off since 08:50 UTC (10')
    r, s = remote(dict(REMOTE_OK))
    assert r.check_conditions(now) == (True, [])
    r.speak("γεια")
    url, body = s.posts[-1]
    assert url.endswith("/api/services/tts/speak")
    assert body["entity_id"] == "tts.google_cloud" and body["options"] == {"voice": "el-GR-Chirp3-HD-Laomedeia"}
    ok, failed = r.check_conditions(datetime(2026, 11, 10, 11, 40, tzinfo=TZ))  # motion 50' ago
    assert not ok and failed == ["binary_sensor.office_motion_sensor_occupancy=on~30"]
    ok, failed = r.check_conditions(datetime(2026, 11, 10, 19, 0, tzinfo=TZ))
    assert not ok and failed[0].startswith("work_hours")
    r2, _ = remote({**REMOTE_OK, "input_boolean.dnd_mode": {"state": "on"}})
    assert r2.check_conditions(now)[0] is False
    r3, _ = remote({k: v for k, v in REMOTE_OK.items() if k != "person.user"})
    assert r3.check_conditions(now)[1] == ["person.user=home (unavailable)"]
    assert "TOKEN" not in repr(r)


def test_notifier_defers_morning_tts_until_conditions():
    class HA:
        def __init__(self):
            self.calls = []

        def persistent_notification(self, *a):
            self.calls.append("pn")

        def notify(self, t, *a):
            self.calls.append(t)
    states = {**REMOTE_OK, "person.user": {"state": "not_home"}}
    r, s = remote(states)
    ha = HA()
    n = Notifier(ha, ["notify.mobile_app_phone"], r)
    now = datetime(2026, 11, 10, 10, 31, tzinfo=TZ)
    ok = n.notify("report", "t", "m", tts="Καλημέρα", now=now, defer_tts=True)
    assert ok == ["persistent", "notify.mobile_app_phone"] and n.pending_tts
    states["person.user"] = {"state": "home"}
    states["binary_sensor.office_motion_sensor_occupancy"] = {"state": "on"}
    assert n.retry_pending(now.replace(hour=12)) is True and n.pending_tts is None
    assert len(s.posts) == 1
    # micro-actions are never deferred
    states["person.user"] = {"state": "not_home"}
    n.notify("pause", "t", "m", tts="x", now=now)
    assert n.pending_tts is None
