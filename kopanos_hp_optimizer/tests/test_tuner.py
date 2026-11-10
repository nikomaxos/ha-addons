import copy

import pytest

from optimizer import tuner as T
from optimizer.const import MAX_HZ, PUMP_DUTY, QUIET3, RAMP_MULT, SAFE_DEFAULTS, STEP_INTERVAL, zone_for

GOOD = {"comfort_within_03_pct": 95.0, "max_starts_per_hour_room": 2, "eeprom_max_daily": 8,
        "error_h62_h75": False, "defrosts_tout_gt7": 0}


def day(kph, **over):
    return {**GOOD, "kwh_per_hdd_heat": kph, **over}


@pytest.mark.parametrize("t,z", [(15, "≥12"), (12, "≥12"), (11.99, "7–12"), (7, "7–12"), (6.9, "3–7"),
                                 (3, "3–7"), (2.9, "<3"), (-5, "<3"), (None, None)])
def test_zones(t, z):
    assert zone_for(t) == z


def test_immediate_failures():
    assert T.immediate_failures(GOOD) == []
    assert T.immediate_failures({**GOOD, "error_h62_h75": True}) == ["h62_h75"]
    assert T.immediate_failures({**GOOD, "defrosts_tout_gt7": 1}) == ["defrost_tout_gt7"]
    # absolute comfort/starts/eeprom values are NOT immediate failures any more (HA watchdog owns them)
    assert T.immediate_failures({**GOOD, "comfort_within_03_pct": 10, "max_starts_per_hour_room": 9,
                                 "eeprom_max_daily": 40}) == []


def test_non_inferiority_relative():
    ctl = [dict(GOOD) for _ in range(3)]
    assert T.non_inferiority_failures([dict(GOOD)] * 3, ctl) == []
    # comfort: exactly control - 5 passes, below fails
    assert T.non_inferiority_failures([{**GOOD, "comfort_within_03_pct": 90.0}] * 3, ctl) == []
    assert T.non_inferiority_failures([{**GOOD, "comfort_within_03_pct": 89.9}] * 3, ctl) == ["comfort"]
    # starts/h room: control + 1 passes, more fails
    assert T.non_inferiority_failures([{**GOOD, "max_starts_per_hour_room": 3}] * 3, ctl) == []
    assert T.non_inferiority_failures([{**GOOD, "max_starts_per_hour_room": 4}] * 3, ctl) == ["starts_per_hour_room"]
    # eeprom: trial <= control
    assert T.non_inferiority_failures([{**GOOD, "eeprom_max_daily": 9}] * 3, ctl) == ["eeprom"]
    # relative: a "bad" absolute value is fine when control is equally bad
    bad = {**GOOD, "comfort_within_03_pct": 60.0, "max_starts_per_hour_room": 5, "eeprom_max_daily": 20}
    assert T.non_inferiority_failures([bad] * 3, [bad] * 3) == []


def test_non_inferiority_unknowns():
    unk = {**GOOD, "comfort_within_03_pct": None}
    assert T.non_inferiority_failures([unk] * 3, [unk] * 3) == []          # both unknown -> skip
    assert T.non_inferiority_failures([unk] * 3, [GOOD] * 3) == ["comfort"]  # trial unknown -> fail
    assert T.non_inferiority_failures([GOOD] * 3, [unk] * 3) == []          # control unknown -> skip
    # mean over known values only
    assert T.non_inferiority_failures([GOOD, unk, GOOD], [GOOD] * 3) == []


def test_non_inferiority_rejects_despite_gain():
    st = T.new_state()
    for i in range(20):
        params, arm = T.plan_day(st, "3–7")
        d = day(1.5, comfort_within_03_pct=80.0) if arm == "trial" else day(2.0)
        dec = T.record_day(st, "3–7", arm, params, d, True, f"d{i}")
        if dec:
            break
    assert dec and not dec["accepted"] and dec["reason"] == "non_inferiority:comfort"
    assert st["zones"]["3–7"]["incumbent"] == dict(SAFE_DEFAULTS)


def test_day_records_store_metrics():
    st = T.new_state()
    p, arm = T.plan_day(st, "7–12")
    T.record_day(st, "7–12", arm, p, day(2.0), True, "d0")
    rec = st["zones"]["7–12"]["trial"]["trial_days"][0]
    for m in T.REC_METRICS:
        assert rec[m] == GOOD[m]


def run_trial(st, zone, trial_kph, control_kph, date0=0):
    """Feed days following the plan until a decision is produced."""
    for i in range(20):
        params, arm = T.plan_day(st, zone)
        kph = trial_kph if arm == "trial" else control_kph
        dec = T.record_day(st, zone, arm, params, day(kph), True, f"d{date0 + i}")
        if dec:
            return dec, i + 1
    raise AssertionError("no decision")


def test_one_param_at_a_time_and_alternation():
    st = T.new_state()
    p, arm = T.plan_day(st, "7–12")
    assert arm == "trial"
    diff = {k for k in p if p[k] != SAFE_DEFAULTS[k]}
    assert diff == {RAMP_MULT} and p[RAMP_MULT] == 2.5
    T.record_day(st, "7–12", arm, p, day(2.0), True, "d0")
    p2, arm2 = T.plan_day(st, "7–12")
    assert arm2 == "control" and p2 == dict(SAFE_DEFAULTS)
    # other zones untouched
    assert st["zones"]["<3"]["trial"] is None


def test_accept_then_continue_same_direction():
    st = T.new_state()
    dec, ndays = run_trial(st, "3–7", trial_kph=1.8, control_kph=2.0)
    assert dec["accepted"] and dec["param"] == RAMP_MULT and dec["to"] == 2.5
    assert ndays == 6  # 3 trial + 3 control
    assert st["zones"]["3–7"]["incumbent"][RAMP_MULT] == 2.5
    assert st["zones"]["3–7"]["trial"]["value"] == 3.0


def test_no_gain_tries_down_then_next_param():
    st = T.new_state()
    dec, _ = run_trial(st, "≥12", trial_kph=2.0, control_kph=2.0)
    assert not dec["accepted"]
    assert st["zones"]["≥12"]["trial"]["value"] == 1.5  # downward once
    dec2, _ = run_trial(st, "≥12", trial_kph=2.1, control_kph=2.0, date0=100)
    assert not dec2["accepted"]
    z = st["zones"]["≥12"]
    assert z["incumbent"][RAMP_MULT] == 2.0
    assert z["trial"]["param"] == MAX_HZ  # moved on to next parameter


def test_unsafe_day_immediate_rollback():
    st = T.new_state()
    p, arm = T.plan_day(st, "<3")
    dec = T.record_day(st, "<3", arm, p, day(1.0, defrosts_tout_gt7=1), True, "d0")
    assert dec and not dec["accepted"] and dec["reason"].startswith("rollback_unsafe")
    assert st["zones"]["<3"]["incumbent"] == dict(SAFE_DEFAULTS)


def test_invalid_days_not_counted_and_stale_plans_ignored():
    st = T.new_state()
    p, arm = T.plan_day(st, "7–12")
    assert T.record_day(st, "7–12", arm, p, day(1.0), False, "d0") is None
    assert st["zones"]["7–12"]["trial"]["trial_days"] == []
    stale = {**p, RAMP_MULT: 1.0}
    assert T.record_day(st, "7–12", "trial", stale, day(1.0), True, "d1") is None


def test_full_ladder_terminates():
    st = T.new_state()
    for i in range(400):
        params, arm = T.plan_day(st, "7–12")
        if arm == "incumbent":
            break
        T.record_day(st, "7–12", arm, params, day(2.0), True, f"d{i}")
    else:
        raise AssertionError("tuner never finished")
    z = st["zones"]["7–12"]
    assert z["param_idx"] == 5 and z["incumbent"] == dict(SAFE_DEFAULTS)
    for k, v in z["incumbent"].items():
        assert v in T.LADDERS[k]


def test_manual_rollback_trials():
    st = T.new_state()
    T.plan_day(st, "7–12")
    out = T.rollback_trials(st, "d0")
    assert out and out[0]["reason"] == "manual_rollback"
    assert st["zones"]["7–12"]["incumbent"] == dict(SAFE_DEFAULTS)


def test_ladders_within_contract_limits():
    from optimizer.const import ALLOWLIST
    for eid, lad in T.LADDERS.items():
        spec = ALLOWLIST[eid]
        assert all(spec.minimum <= v <= spec.maximum for v in lad)
        assert SAFE_DEFAULTS[eid] in lad
    assert T.LADDERS[MAX_HZ][0] == 19.0 and T.LADDERS[MAX_HZ][-1] == 24.0
    assert T.LADDERS[RAMP_MULT][0] == 1.0 and T.LADDERS[RAMP_MULT][-1] == 3.0
    assert T.LADDERS[STEP_INTERVAL][0] == 30.0 and T.LADDERS[STEP_INTERVAL][-1] == 60.0
    assert 20.0 not in T.LADDERS[STEP_INTERVAL] and 25.0 not in T.LADDERS[STEP_INTERVAL]
    assert T.LADDERS[QUIET3][0] == 5.5 and T.LADDERS[QUIET3][-1] == 7.2
    assert T.LADDERS[PUMP_DUTY][0] == 105.0 and T.LADDERS[PUMP_DUTY][-1] == 150.0
    # snap doesn't unnecessarily alter valid values between rungs
    assert T._neighbor(MAX_HZ, 21.4, 1) == 22.0
    assert T._neighbor(MAX_HZ, 21.4, -1) == 21.0
