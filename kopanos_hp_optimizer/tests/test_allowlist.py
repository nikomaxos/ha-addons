import math
from datetime import datetime

import pytest

from conftest import FakeSession
from optimizer.const import (AB_TODAY, ALLOWLIST, AUTOTUNE_ENABLED, HEARTBEAT, MAX_HZ, QUIET3, RAMP_MULT,
                             STEP_INTERVAL, TZ, ULH_ENABLED, ULH_PHASE)
from optimizer.ha_client import HAClient, WriteRejected, check_policy, validate_helper_value

CONTRACT = {
    "input_boolean.hp_ultra_low_hz_enabled", "input_number.hp_ultra_low_max_hz",
    "input_number.hp_ramp_multiplier", "input_number.hp_ramp_step_interval_min", "input_number.hp_quiet3_threshold",
    "input_boolean.hp_optimizer_autotune_enabled", "input_datetime.hp_optimizer_heartbeat",
    "input_text.hp_optimizer_ab_today", "input_select.hp_ultra_low_phase",
}
FORBIDDEN = [
    "select.panasonic_heat_pump_main_quiet_mode_level",
    "number.panasonic_heat_pump_main_z1_heat_curve_target_low_temp",
    "switch.panasonic_heat_pump_main_heatpump_state",
    "climate.panasonic_heat_pump_main_z1_temp",
    "input_number.hp_eeprom_writes_today",
    "input_number.hp_target_room_temp",
    "input_boolean.hp_empc_autopilot_enabled",
    "input_number.hp_ultra_low_max_hz ",
    "INPUT_NUMBER.HP_ULTRA_LOW_MAX_HZ",
    "",
    None,
]


def test_allowlist_is_exactly_contract():
    assert set(ALLOWLIST) == CONTRACT
    assert len(ALLOWLIST) == 9
    assert ULH_PHASE in ALLOWLIST
    with pytest.raises(TypeError):
        ALLOWLIST["x"] = None  # immutable


@pytest.mark.parametrize("eid", FORBIDDEN)
def test_forbidden_entities_rejected_and_never_posted(eid):
    s = FakeSession()
    ha = HAClient("http://x/api", "t", session=s)
    for mode in ("observe", "campaign", "ab_test", "autotune"):
        with pytest.raises(WriteRejected):
            ha.set_helper(eid, 22, mode=mode, paused=False)
        with pytest.raises(WriteRejected):
            ha.set_helper(eid, 22, mode=mode, paused=False, restore=True)
    assert s.posts == []


@pytest.mark.parametrize("eid,val,exp", [
    (MAX_HZ, 30, 24.0), (MAX_HZ, 10, 19.0), (MAX_HZ, 21.4, 21.0), (MAX_HZ, 21.6, 22.0),
    (RAMP_MULT, 2.1, 2.0), (RAMP_MULT, 2.2, 2.25), (RAMP_MULT, 9, 3.0), (RAMP_MULT, -1, 1.0),
    (STEP_INTERVAL, 47, 45.0), (STEP_INTERVAL, 5, 30.0), (STEP_INTERVAL, 600, 60.0),
    (QUIET3, 7.9, 7.2), (QUIET3, 6.04, 6.0), (QUIET3, 5.0, 5.5), (QUIET3, 6.4, 6.4),
])
def test_number_clamp_and_snap(eid, val, exp):
    _, srv, data, norm = validate_helper_value(eid, val)
    assert srv == "set_value" and norm == exp and data == {"entity_id": eid, "value": exp}


@pytest.mark.parametrize("val", [float("nan"), float("inf"), True, "22", None])
def test_number_bad_types(val):
    with pytest.raises(WriteRejected):
        validate_helper_value(MAX_HZ, val)


def test_select_text_bool_datetime():
    assert validate_helper_value(ULH_PHASE, "ramp")[2]["option"] == "ramp"
    with pytest.raises(WriteRejected):
        validate_helper_value(ULH_PHASE, "invalid_phase")
    assert validate_helper_value(AB_TODAY, "ON")[2]["value"] == "ON"
    with pytest.raises(WriteRejected):
        validate_helper_value(AB_TODAY, "on; drop")
    assert validate_helper_value(ULH_ENABLED, False)[1] == "turn_off"
    with pytest.raises(WriteRejected):
        validate_helper_value(ULH_ENABLED, 1)
    # consent switch: only OFF
    assert validate_helper_value(AUTOTUNE_ENABLED, False)[1] == "turn_off"
    with pytest.raises(WriteRejected):
        validate_helper_value(AUTOTUNE_ENABLED, True)
    dt = datetime(2026, 11, 10, 9, 0, tzinfo=TZ)
    assert validate_helper_value(HEARTBEAT, dt)[2]["datetime"] == "2026-11-10 09:00:00"
    with pytest.raises(WriteRejected):
        validate_helper_value(HEARTBEAT, "2026-11-10")


def test_mode_policy():
    # observe: heartbeat only
    check_policy(HEARTBEAT, None, "observe", paused=False)
    for eid in set(ALLOWLIST) - {HEARTBEAT}:
        with pytest.raises(WriteRejected):
            check_policy(eid, None, "observe", paused=False)
        with pytest.raises(WriteRejected):
            check_policy(eid, None, "observe", paused=False, restore=True)
    # campaign: writes phase, tunables, ulh, ab_today
    check_policy(ULH_PHASE, "quiet", "campaign", paused=False)
    check_policy(RAMP_MULT, 2.5, "campaign", paused=False)
    check_policy(ULH_ENABLED, True, "campaign", paused=False)
    check_policy(AB_TODAY, "ON", "campaign", paused=False)
    # ab_test: no tunables or phase
    check_policy(ULH_ENABLED, True, "ab_test", paused=False)
    check_policy(AB_TODAY, "ON", "ab_test", paused=False)
    for eid in (RAMP_MULT, MAX_HZ, STEP_INTERVAL, QUIET3, ULH_PHASE):
        with pytest.raises(WriteRejected):
            check_policy(eid, 2, "ab_test", paused=False)
    # autotune: tunables ok, phase never (user-owned)
    check_policy(RAMP_MULT, 2, "autotune", paused=False)
    with pytest.raises(WriteRejected):
        check_policy(ULH_PHASE, "tuned", "autotune", paused=False)
    # paused: heartbeat only, unless restore
    check_policy(HEARTBEAT, None, "autotune", paused=True)
    with pytest.raises(WriteRejected):
        check_policy(RAMP_MULT, 2, "autotune", paused=True)
    check_policy(RAMP_MULT, 2, "autotune", paused=True, restore=True)
    with pytest.raises(WriteRejected):
        check_policy(HEARTBEAT, None, "bogus", paused=False)


def test_set_helper_posts_only_derived_service():
    s = FakeSession()
    ha = HAClient("http://x/api", "t", session=s)
    assert ha.set_helper(MAX_HZ, 99, mode="autotune", paused=False) == 24.0
    assert s.posts == [("http://x/api/services/input_number/set_value", {"entity_id": MAX_HZ, "value": 24.0})]
    s.posts.clear()
    with pytest.raises(WriteRejected):
        ha.set_helper(MAX_HZ, 22, mode="observe", paused=False)
    assert s.posts == []


def test_low_level_post_guard():
    s = FakeSession()
    ha = HAClient("http://x/api", "t", session=s)
    with pytest.raises(WriteRejected):
        ha._post("switch", "turn_on", {"entity_id": "switch.panasonic_heat_pump_main_heatpump_state"})
    with pytest.raises(WriteRejected):
        ha._post("input_number", "set_value", {"entity_id": "input_number.hp_target_room_temp", "value": 30})
    with pytest.raises(WriteRejected):
        ha._post("mqtt", "publish", {"topic": "panasonic_heat_pump/commands/SetQuietMode", "payload": "3"})
    with pytest.raises(WriteRejected):
        ha.call_readonly_service("input_number", "set_value", {})
    assert s.posts == []


@pytest.mark.parametrize("target,ok", [
    ("notify.mobile_app_phone", True), ("notify.notify", True), ("light.turn_on", False),
    ("notify.../x", False), ("notify.Mobile", False), ("notify.a/b", False), ("", False),
])
def test_notify_target_validation(target, ok):
    s = FakeSession()
    ha = HAClient("http://x/api", "t", session=s)
    if ok:
        ha.notify(target, "t", "m")
        assert s.posts[-1][0].endswith("/services/notify/" + target.split(".", 1)[1])
    else:
        with pytest.raises(WriteRejected):
            ha.notify(target, "t", "m")
        assert s.posts == []


def test_token_not_in_repr():
    ha = HAClient("http://x/api", "SECRET-TOKEN")
    assert "SECRET" not in repr(ha)
