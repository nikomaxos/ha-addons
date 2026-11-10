from datetime import date, datetime, timedelta

import pytest

from conftest import FakeSession
from optimizer.config import Options
from optimizer.const import (AB_TODAY, AUTOTUNE_ENABLED, E, HEARTBEAT, MAX_HZ, QUIET3, RAMP_MULT, STEP_INTERVAL,
                             TZ, ULH_ENABLED, ULH_PHASE, WATCHDOG_REASON)
from optimizer.ha_client import HAClient
from optimizer.notifier import Notifier
from optimizer.reporter import Reporter
from optimizer.scheduler import Optimizer, Runner, due_jobs, forecast_temp, last_cycle_end
from optimizer.storage import Store

HELPER_STATES = {ULH_ENABLED: "off", ULH_PHASE: "off", MAX_HZ: "22.0", RAMP_MULT: "2.0", STEP_INTERVAL: "30.0",
                 QUIET3: "6.0", AUTOTUNE_ENABLED: "off", HEARTBEAT: "2026-11-10 09:00:00", AB_TODAY: "NA",
                 E["freq"]: "20", E["heat_power"]: "800", E["t_out"]: "10"}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make(tmp_path, mode="observe", history=None, now=datetime(2026, 11, 10, 10, 31, tzinfo=TZ)):
    sess = FakeSession(states=dict(HELPER_STATES), history=history or {})
    ha = HAClient("http://supervisor/core/api", "tok", session=sess)
    store = Store(str(tmp_path / "opt.db"))
    opts = Options(mode=mode, notify_targets=["notify.mobile_app_phone"], llm_provider="none")
    notifier = Notifier(ha, opts.notify_targets, None, event_cb=store.event)
    clock = Clock(now)
    opt = Optimizer(opts, ha, store, notifier, Reporter(), now_fn=clock)
    return opt, sess, clock


def helper_posts(sess):
    return [(u, j) for u, j in sess.posts if "/services/input_" in u]


def test_pure_helpers():
    now = datetime(2026, 11, 10, 9, 0, tzinfo=TZ)
    assert last_cycle_end(now, "10:30") == datetime(2026, 11, 9, 10, 30, tzinfo=TZ)
    assert last_cycle_end(now.replace(hour=11), "10:30") == datetime(2026, 11, 10, 10, 30, tzinfo=TZ)
    assert due_jobs(now, None, None, None, "10:30") == ["heartbeat", "health", "report"]
    assert due_jobs(now, now - timedelta(minutes=4), now - timedelta(hours=1), "2026-11-09", "10:30") == []
    assert due_jobs(now, now - timedelta(minutes=5), now - timedelta(hours=6), "2026-11-09", "10:30") == ["heartbeat", "health"]
    fc = [{"datetime": "2026-11-10T10:00:00+00:00", "temperature": 14, "templow": 6},
          {"datetime": "2026-11-11T10:00:00+00:00", "temperature": 12, "templow": 4}]
    assert forecast_temp(fc, date(2026, 11, 10), date(2026, 11, 11)) == pytest.approx((10 + 4) / 2)
    assert forecast_temp([], date(2026, 11, 10), date(2026, 11, 11)) is None


def test_observe_mode_writes_only_heartbeat(tmp_path, real_history):
    opt, sess, clock = make(tmp_path, "observe", real_history)
    opt.heartbeat()
    res = opt.close_cycle()
    opt.health()
    opt.rollback()  # strict: no restores in observe
    hp = helper_posts(sess)
    assert hp and all(j["entity_id"] == HEARTBEAT for _, j in hp)
    assert res["cycle_date"] == "2026-11-10"
    assert res["kpi"]["kwh"] == pytest.approx(16.656, rel=0.05)  # Baseline Analyst 09/11 10:30 → 10/11 10:30
    # notifications went to persistent + mobile, nothing else
    other = [u for u, _ in sess.posts if "/services/input_" not in u]
    assert all(u.endswith(("/persistent_notification/create", "/notify/mobile_app_phone")) for u in other)
    assert opt.close_cycle() is None  # idempotent
    assert opt.store.get("last_closed") == "2026-11-10"


def test_ab_test_plans_and_writes_only_ab_helpers(tmp_path, real_history):
    opt, sess, clock = make(tmp_path, "ab_test", real_history)
    opt.close_cycle()
    hp = helper_posts(sess)
    ents = {j["entity_id"] for _, j in hp}
    assert ents <= {ULH_ENABLED, AB_TODAY}
    plan = opt.store.plan("2026-11-11")
    assert plan["assignment"] in ("ON", "OFF") and plan["pair_id"]
    assert sess.states[AB_TODAY] == plan["assignment"]
    assert sess.states[ULH_ENABLED] == ("on" if plan["assignment"] == "ON" else "off")


def test_external_change_pauses_and_excludes_day(tmp_path, real_history):
    opt, sess, clock = make(tmp_path, "ab_test", real_history)
    opt.store.save_plan("2026-11-10", "ON", "P-x", None, None, {ULH_ENABLED: True, AB_TODAY: "ON"})
    sess.states[ULH_ENABLED] = "off"  # e.g. HA watchdog tripped / user switched off
    sess.states[AB_TODAY] = "ON"
    n_before = len(helper_posts(sess))
    res = opt.close_cycle()
    assert "manual_change" in res["exclusions"] and res["valid"] is False
    assert opt.paused is True
    assert len(helper_posts(sess)) == n_before  # paused before planning: no writes
    assert opt.store.plan("2026-11-11")["assignment"] == "PAUSED"


def test_watchdog_trip_does_not_pause_and_continues(tmp_path, real_history):
    opt, sess, clock = make(tmp_path, "ab_test", real_history)
    opt.store.save_plan("2026-11-10", "ON", "P-x", None, None, {ULH_ENABLED: True, AB_TODAY: "ON"})
    sess.states[ULH_ENABLED] = "off"
    sess.states[WATCHDOG_REASON] = "low_flow"
    sess.states[AB_TODAY] = "ON"
    res = opt.close_cycle()
    assert "watchdog:low_flow" in res["exclusions"] and res["valid"] is False
    assert "manual_change" not in res["exclusions"]
    assert opt.paused is False
    # next cycle is planned normally without being paused
    assert opt.store.plan("2026-11-11")["assignment"] in ("ON", "OFF")


def test_autotune_off_never_writes_ulh_even_on_off_day(tmp_path, real_history):
    opt, sess, clock = make(tmp_path, "autotune", real_history)
    from optimizer.experiment import weekly_off_weekday
    nd = date(2026, 11, 11)
    iso = nd.isocalendar()
    off_day = weekly_off_weekday(iso[0], iso[1], opt.opts.ab_seed)
    # Adjust clock or seed so that nd is exactly the weekly off day
    while nd.weekday() != off_day:
        opt.opts.ab_seed += 1
        off_day = weekly_off_weekday(iso[0], iso[1], opt.opts.ab_seed)
    sess.states[AUTOTUNE_ENABLED] = "off"
    sess.states[ULH_ENABLED] = "off"
    opt.close_cycle()
    hp = helper_posts(sess)
    # Must NOT touch ULH_ENABLED
    assert not any(j["entity_id"] == ULH_ENABLED for _, j in hp)
    assert opt.store.plan("2026-11-11")["assignment"] == "NA"


def test_autotune_requires_consent_and_writes_params(tmp_path, real_history):
    opt, sess, clock = make(tmp_path, "autotune", real_history)
    # pick a date that is not the weekly OFF day
    from optimizer.experiment import weekly_off_weekday
    nd = date(2026, 11, 11)
    iso = nd.isocalendar()
    if nd.weekday() == weekly_off_weekday(iso[0], iso[1], opt.opts.ab_seed):
        opt.opts.ab_seed += 1
    opt.close_cycle()
    assert helper_posts(sess) == [] or all(j["entity_id"] == HEARTBEAT for _, j in helper_posts(sess))
    assert opt.store.plan("2026-11-11")["assignment"] == "NA"
    # user gives consent
    sess.states[AUTOTUNE_ENABLED] = "on"
    clock.t += timedelta(days=1)
    opt.close_cycle()
    plan = opt.store.plan("2026-11-12")
    if plan["assignment"] == "ON":
        assert plan["arm"] == "trial"
        assert float(sess.states[RAMP_MULT]) == 2.5
        assert sess.states[ULH_ENABLED] == "on"
    ents = {j["entity_id"] for _, j in helper_posts(sess)}
    assert ULH_PHASE not in ents and AUTOTUNE_ENABLED not in ents


def test_rollback_restores_first_values_and_pauses(tmp_path):
    opt, sess, clock = make(tmp_path, "autotune")
    assert opt.apply(RAMP_MULT, 2.5, "t1")
    assert opt.apply(RAMP_MULT, 3.0, "t2")
    assert opt.apply(ULH_ENABLED, True, "t3")
    assert not opt.apply("input_number.hp_target_room_temp", 30, "evil")
    r = opt.rollback()
    assert r["restored"] == {RAMP_MULT: 2.0, ULH_ENABLED: False}
    assert sess.states[RAMP_MULT] == "2.0" and sess.states[ULH_ENABLED] == "off"
    assert opt.paused
    # paused: further non-restore writes rejected
    assert not opt.apply(RAMP_MULT, 2.5, "after pause")
    rej = [c for c in opt.store.changes() if not c["ok"]]
    assert any("not in allowlist" in c["error"] for c in rej)


def test_runner_tick_handles_errors(tmp_path):
    opt, sess, clock = make(tmp_path, "observe")

    def boom(*a, **k):
        raise RuntimeError("history down")
    opt.ha.history = boom
    r = Runner(opt)
    jobs = r.tick()
    assert jobs == ["heartbeat", "health", "report"]
    kinds = [e["kind"] for e in opt.store.events()]
    assert "job_error" in kinds
    assert opt.store.get("report_retry_after")
