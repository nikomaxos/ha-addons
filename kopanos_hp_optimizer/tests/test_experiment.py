import random
from datetime import date

import pytest

from optimizer.experiment import (day_exclusions, fit_effect, pair_exclusion, pair_schedule, t95, valid_pair_days,
                                  weekly_off_weekday)
from optimizer.scheduler import ab_assignment


def test_t_table():
    assert t95(1) == 6.314 and t95(30) == 1.697 and t95(10_000) == 1.645
    assert 1.684 > t95(50) > 1.671
    assert t95(0) == float("inf")


def test_pair_schedule_balanced_and_reproducible():
    s1 = pair_schedule(date(2026, 11, 14), 7, seed=42)
    s2 = pair_schedule(date(2026, 11, 14), 7, seed=42)
    assert s1 == s2 and len(s1) == 14
    for i in range(7):
        a, b = s1[2 * i], s1[2 * i + 1]
        assert {a[1], b[1]} == {"ON", "OFF"} and a[2] == b[2] == i
    firsts = [s1[2 * i][1] for i in range(7)]
    assert len(set(pair_schedule(date(2026, 11, 14), 50, seed=1)[::2][j][1] for j in range(50))) == 2  # not constant
    assert firsts  # silence


def test_ab_assignment_pairs():
    start = date(2026, 11, 14)
    seen = {}
    for i in range(20):
        a, pid = ab_assignment(start, 7, date.fromordinal(start.toordinal() + i))
        seen.setdefault(pid, []).append(a)
    assert all(sorted(v) == ["OFF", "ON"] for v in seen.values())
    assert ab_assignment(start, 7, date(2026, 11, 20)) == ab_assignment(start, 7, date(2026, 11, 20))
    with pytest.raises(ValueError):
        ab_assignment(start, 7, date(2026, 11, 1))


def test_weekly_off_day():
    d = weekly_off_weekday(2026, 50, 1)
    assert 0 <= d <= 6 and d == weekly_off_weekday(2026, 50, 1)


def test_exclusions():
    good = {"home_ratio": 0.0, "errors": [], "power_coverage": 1.0, "low_flow_minutes_room": 0, "kwh_per_hdd": 2.0}
    assert day_exclusions(good) == []                       # away exclusion is opt-in
    assert day_exclusions(good, away_exclusion=True) == ["away"]
    assert "manual_change" in day_exclusions(good, manual_change=True)
    assert any(r.startswith("fault") for r in day_exclusions({**good, "errors": ["H75"]}))
    assert "data_gap" in day_exclusions({**good, "power_coverage": 0.5})
    assert "low_flow" in day_exclusions({**good, "low_flow_minutes_room": 6})
    assert "hdd_too_low" in day_exclusions({**good, "kwh_per_hdd": None})
    assert pair_exclusion(10, 6.5) is None
    assert pair_exclusion(10, 5.9) == "hdd_pair_diff>40%"
    assert pair_exclusion(None, 5) == "hdd_missing"


def _synthetic(n_pairs, effect, seed=3, noise=0.6):
    rng = random.Random(seed)
    days = []
    for p in range(n_pairs):
        first = rng.choice(("ON", "OFF"))
        hdd0 = rng.uniform(4, 12)
        for j, a in enumerate((first, "OFF" if first == "ON" else "ON")):
            hdd = hdd0 * rng.uniform(0.85, 1.15)
            solar = rng.uniform(0, 1)
            boiler = rng.choice((0.0, 1.0, 2.5))
            kwh = 3 + 1.6 * hdd - 2.0 * solar + 1.0 * boiler + (effect if a == "ON" else 0) + rng.gauss(0, noise)
            days.append({"pair": p, "assignment": a, "valid": True, "hdd": hdd, "kwh": kwh,
                         "solar": solar, "boiler": boiler})
    return days


def test_fit_recovers_effect_and_confirms():
    days = _synthetic(14, effect=-1.5)
    vd, n = valid_pair_days(days)
    r = fit_effect(vd, n)
    assert n == 14 and r["n_days"] == 28
    assert abs(r["effect_kwh"] - (-1.5)) < 3 * r["se"]
    assert r["ci_low"] < r["effect_kwh"] < r["ci_high"]
    assert r["confirmed"] is True and r["effect_pct"] < 0
    assert r["ci_low_pct"] < r["effect_pct"] < r["ci_high_pct"]
    assert set(r["covariates"]) == {"hdd", "solar", "boiler"}


def test_fit_no_effect_not_confirmed():
    r = fit_effect(*valid_pair_days(_synthetic(10, effect=0.0, seed=9)))
    assert r["confirmed"] is False and r["ci_low"] < 0 < r["ci_high"]


def test_invalid_days_drop_whole_pair_and_hdd_rule():
    days = _synthetic(5, effect=-1)
    days[0]["valid"] = False                 # pair 0 dropped
    days[2]["hdd"], days[3]["hdd"] = 10, 5   # pair 1 dropped (>40 %)
    vd, n = valid_pair_days(days)
    assert n == 3 and len(vd) == 6


def test_fit_edge_cases():
    assert fit_effect([])["reason"] == "too_few_days"
    same = [{"assignment": "ON", "kwh": 10, "hdd": 5}] * 6
    assert fit_effect(same)["reason"] == "no_contrast"
    # constant covariates are dropped instead of crashing
    d = [{"assignment": a, "kwh": 10 + (i % 3), "hdd": 5 + i, "solar": 0.5, "boiler": 0}
         for i, a in enumerate(["ON", "OFF"] * 4)]
    r = fit_effect(d)
    assert r["covariates"] == ["hdd"] and r["effect_kwh"] is not None
