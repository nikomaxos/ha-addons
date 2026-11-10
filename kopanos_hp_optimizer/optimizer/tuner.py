"""Per-zone parameter tuner: one parameter at a time, ≥3 valid days per value, strict acceptance.

State is a plain JSON-serializable dict (persisted in /data/optimizer.db). Decisions are fully
deterministic — no LLM is involved.

Algorithm per T_out zone:
  * incumbent = current best parameter set (starts at SAFE_DEFAULTS)
  * tune parameters in order TUNABLE_PARAMS; for the active parameter try the next ladder value
    upwards first; while a trial is running, days alternate between trial and incumbent
    (concurrent control) until both have ≥ MIN_DAYS valid days
  * accept only if the trial is NON-INFERIOR to the concurrent control days of the same zone
    (relative criteria, see non_inferiority_failures) AND mean kWh/HDD improves by
    ≥ MIN_IMPROVEMENT; continue in the same direction. Otherwise rollback to incumbent; if the
    first upward step failed, try downward once; then move to the next parameter.
  * any trial day with an immediate failure (H62/H75 error, defrost while T_out > 7 °C)
    => immediate rollback of that trial.
  * absolute safety limits (low flow, starts/h, cold room, EEPROM budget, frost) are enforced
    only by the Home Assistant watchdog, never here.
"""
from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from .const import MAX_HZ, PUMP_DUTY, QUIET3, RAMP_MULT, SAFE_DEFAULTS, STEP_INTERVAL, TUNABLE_PARAMS, ZONES

LADDERS: Dict[str, Tuple[float, ...]] = {
    RAMP_MULT: (1.0, 1.5, 2.0, 2.5, 3.0),
    MAX_HZ: (19.0, 20.0, 21.0, 22.0, 23.0, 24.0),
    STEP_INTERVAL: (30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0),
    QUIET3: (5.5, 6.0, 6.4, 6.8, 7.2),
    PUMP_DUTY: (105.0, 112.0, 125.0, 150.0),
}
MIN_DAYS = 3
MIN_IMPROVEMENT = 0.01  # 1 % lower kWh/HDD

# relative (non-inferiority) acceptance criteria vs concurrent control days of the same zone
COMFORT_MARGIN_PCT = 5.0     # comfort_trial >= comfort_control - 5 points
STARTS_MARGIN = 1.0          # room starts/h: trial <= control + 1
EEPROM_MARGIN = 0.0          # eeprom_max_daily: trial <= control
# metrics stored per day record
REC_METRICS = ("comfort_within_03_pct", "max_starts_per_hour_room", "eeprom_max_daily")


def immediate_failures(day: Dict[str, Any]) -> List[str]:
    """Failures that roll back a trial immediately (single day is enough)."""
    f = []
    if day.get("error_h62_h75"):
        f.append("h62_h75")
    if (day.get("defrosts_tout_gt7") or 0) > 0:
        f.append("defrost_tout_gt7")
    return f


def _mean_known(days: List[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [d.get(key) for d in days if d.get(key) is not None]
    return mean(vals) if vals else None


def non_inferiority_failures(trial_days: List[Dict[str, Any]],
                             control_days: List[Dict[str, Any]],
                             eeprom_budget: float = 16.0) -> List[str]:
    """Compare means of trial vs control. Unknown on both sides => skipped;
    unknown trial with known control => failure; known trial with unknown control => skipped."""
    f = []
    rules = (("comfort_within_03_pct", "comfort", lambda t, c: t >= c - COMFORT_MARGIN_PCT),
             ("max_starts_per_hour_room", "starts_per_hour_room", lambda t, c: t <= c + STARTS_MARGIN),
             ("eeprom_max_daily", "eeprom", lambda t, c: t <= c + EEPROM_MARGIN))
    for key, name, ok in rules:
        t = _mean_known(trial_days, key)
        c = _mean_known(control_days, key)
        if c is None:
            continue
        if t is None or not ok(t, c):
            f.append(name)
    return f


def _neighbor(param: str, value: float, direction: int) -> Optional[float]:
    lad = LADDERS[param]
    for i, rung in enumerate(lad):
        if abs(rung - value) < 1e-4:
            j = i + direction
            return lad[j] if 0 <= j < len(lad) else None
    if direction > 0:
        higher = [x for x in lad if x > value + 1e-4]
        return higher[0] if higher else None
    if direction < 0:
        lower = [x for x in lad if x < value - 1e-4]
        return lower[-1] if lower else None
    return None


def new_zone_state() -> Dict[str, Any]:
    return {"incumbent": dict(SAFE_DEFAULTS), "param_idx": 0, "trial": None,
            "tried_down": False, "accepted_in_dir": False, "baseline_days": [], "log": []}


def new_state() -> Dict[str, Any]:
    return {"zones": {z: new_zone_state() for z in ZONES}}


def _trial_set(zs: Dict[str, Any]) -> Dict[str, float]:
    p = dict(zs["incumbent"])
    t = zs["trial"]
    if t:
        p[t["param"]] = t["value"]
    return p


def _start_next_trial(zs: Dict[str, Any]) -> None:
    while zs["param_idx"] < len(TUNABLE_PARAMS):
        param = TUNABLE_PARAMS[zs["param_idx"]]
        direction = -1 if zs["tried_down"] else 1
        nv = _neighbor(param, zs["incumbent"][param], direction)
        if nv is not None:
            zs["trial"] = {"param": param, "value": nv, "direction": direction, "trial_days": [], "control_days": []}
            return
        if direction == 1 and not zs["accepted_in_dir"]:
            zs["tried_down"] = True
            continue
        zs["param_idx"] += 1
        zs["tried_down"] = False
        zs["accepted_in_dir"] = False
    zs["trial"] = None


def plan_day(state: Dict[str, Any], zone: str) -> Tuple[Dict[str, float], str]:
    """Return (helper values for the day, arm) where arm in {'trial','control','incumbent'}."""
    zs = state["zones"][zone]
    if zs["trial"] is None and zs["param_idx"] < len(TUNABLE_PARAMS):
        _start_next_trial(zs)
    t = zs["trial"]
    if t is None:
        return dict(zs["incumbent"]), "incumbent"
    if len(t["trial_days"]) <= len(t["control_days"]):
        return _trial_set(zs), "trial"
    return dict(zs["incumbent"]), "control"


def _finish(zs: Dict[str, Any], accepted: bool, reason: str, date: str) -> Dict[str, Any]:
    t = zs["trial"]
    old = zs["incumbent"][t["param"]]
    entry = {"date": date, "param": t["param"], "from": old, "to": t["value"],
             "accepted": accepted, "reason": reason}
    zs["log"].append(entry)
    if accepted:
        zs["incumbent"][t["param"]] = t["value"]
        zs["accepted_in_dir"] = True
        nv = _neighbor(t["param"], t["value"], t["direction"])
        if nv is not None:
            zs["trial"] = {"param": t["param"], "value": nv, "direction": t["direction"],
                           "trial_days": [], "control_days": []}
            return entry
    else:
        if t["direction"] == 1 and not zs["accepted_in_dir"] and not zs["tried_down"]:
            zs["tried_down"] = True
            zs["trial"] = None
            _start_next_trial(zs)
            return entry
    zs["param_idx"] += 1
    zs["tried_down"] = False
    zs["accepted_in_dir"] = False
    zs["trial"] = None
    _start_next_trial(zs)
    return entry


def record_day(state: Dict[str, Any], zone: str, arm: str, applied: Dict[str, float],
               day: Dict[str, Any], valid: bool, date: str,
               eeprom_budget: float = 16.0) -> Optional[Dict[str, Any]]:
    """Feed a closed cycle. Returns a decision entry (accept / reject / rollback) or None."""
    zs = state["zones"][zone]
    t = zs["trial"]
    kph = day.get("kwh_per_hdd_heat") if day.get("kwh_per_hdd_heat") is not None else day.get("kwh_per_hdd")
    rec = {"date": date, "kwh_per_hdd": kph, "fail": immediate_failures(day)}
    for m in REC_METRICS:
        rec[m] = day.get(m)
    if t is None or arm == "incumbent":
        if valid and applied == zs["incumbent"]:
            zs["baseline_days"] = (zs["baseline_days"] + [rec])[-30:]
        return None
    if arm == "trial":
        if applied != _trial_set(zs):
            return None  # stale plan (state changed meanwhile)
        if rec["fail"]:
            return _finish(zs, False, "rollback_unsafe:" + ",".join(rec["fail"]), date)
        if valid:
            t["trial_days"].append(rec)
    elif arm == "control":
        if applied != zs["incumbent"]:
            return None
        if valid:
            t["control_days"].append(rec)
    if len(t["trial_days"]) >= MIN_DAYS and len(t["control_days"]) >= MIN_DAYS:
        ni = non_inferiority_failures(t["trial_days"], t["control_days"], eeprom_budget=eeprom_budget)
        if ni:
            return _finish(zs, False, "non_inferiority:" + ",".join(ni), date)
        tm = mean(d["kwh_per_hdd"] for d in t["trial_days"])
        cm = mean(d["kwh_per_hdd"] for d in t["control_days"])
        if tm <= cm * (1 - MIN_IMPROVEMENT):
            return _finish(zs, True, f"kwh_per_hdd {cm:.3f}->{tm:.3f}", date)
        return _finish(zs, False, f"no_gain {cm:.3f}->{tm:.3f}", date)
    return None


def rollback_trials(state: Dict[str, Any], date: str) -> List[Dict[str, Any]]:
    """Abort every active trial (treated as a rejection; incumbents kept). Used by the Rollback button."""
    out = []
    for zs in state["zones"].values():
        if zs["trial"]:
            out.append(_finish(zs, False, "manual_rollback", date))
    return out
