"""Randomized paired A/B experiment + OLS effect estimation with 90% CI.

Model:  kWh_day = a + b*HDD + c*solar + d*kWh_boiler + effect*ON  (OLS, numpy)
A result is *confirmed* only if the whole 90% CI is below 0.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# one-sided 0.95 Student-t quantiles (=> two-sided 90% CI)
_T95 = {1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015, 6: 1.943, 7: 1.895, 8: 1.860, 9: 1.833,
        10: 1.812, 11: 1.796, 12: 1.782, 13: 1.771, 14: 1.761, 15: 1.753, 16: 1.746, 17: 1.740,
        18: 1.734, 19: 1.729, 20: 1.725, 21: 1.721, 22: 1.717, 23: 1.714, 24: 1.711, 25: 1.708,
        26: 1.706, 27: 1.703, 28: 1.701, 29: 1.699, 30: 1.697, 40: 1.684, 60: 1.671, 120: 1.658}

HDD_PAIR_MAX_DIFF = 0.40
AWAY_HOME_RATIO_MIN = 0.5
MIN_POWER_COVERAGE = 0.9


def t95(df: int) -> float:
    if df <= 0:
        return float("inf")
    if df in _T95:
        return _T95[df]
    keys = sorted(_T95)
    if df > keys[-1]:
        return 1.645
    lo = max(k for k in keys if k < df)
    hi = min(k for k in keys if k > df)
    # interpolate in 1/df (standard for t tables)
    w = (1 / lo - 1 / df) / (1 / lo - 1 / hi)
    return _T95[lo] + w * (_T95[hi] - _T95[lo])


# ---------------------------------------------------------------- schedules
def pair_schedule(start: date, n_pairs: int, seed: int) -> List[Tuple[date, str, int]]:
    """Each consecutive pair of days gets a random ON/OFF order (reproducible by seed)."""
    out = []
    for i in range(n_pairs):
        first = random.Random(f"{seed}-{i}").choice(("ON", "OFF"))
        second = "OFF" if first == "ON" else "ON"
        d0 = start + timedelta(days=2 * i)
        out.append((d0, first, i))
        out.append((d0 + timedelta(days=1), second, i))
    return out


def weekly_off_weekday(iso_year: int, iso_week: int, seed: int) -> int:
    """Autotune: one random OFF control day per ISO week (0=Mon..6=Sun)."""
    return random.Random(f"{seed}-{iso_year}-{iso_week}").randrange(7)


# ---------------------------------------------------------------- exclusions
def day_exclusions(kpi: Dict[str, Any], manual_change: bool = False, away_exclusion: bool = False,
                   away_min: float = AWAY_HOME_RATIO_MIN) -> List[str]:
    """Reasons a day is excluded from the A/B comparison / tuning (empty list = valid).
    away_exclusion is opt-in: person.* tracking proved unreliable for this (e.g. continuously 'not_home' 03–06/11)."""
    reasons = []
    if manual_change:
        reasons.append("manual_change")
    hr = kpi.get("home_ratio")
    if away_exclusion and hr is not None and hr < away_min:
        reasons.append("away")
    if kpi.get("errors"):
        reasons.append("fault:" + ",".join(kpi["errors"]))
    if (kpi.get("power_coverage") or 0) < MIN_POWER_COVERAGE:
        reasons.append("data_gap")
    if (kpi.get("low_flow_minutes_room") or 0) >= 5:
        reasons.append("low_flow")
    if kpi.get("kwh_per_hdd") is None:
        reasons.append("hdd_too_low")
    return reasons


def pair_exclusion(hdd_a: Optional[float], hdd_b: Optional[float]) -> Optional[str]:
    if not hdd_a or not hdd_b:
        return "hdd_missing"
    if abs(hdd_a - hdd_b) / max(hdd_a, hdd_b) > HDD_PAIR_MAX_DIFF:
        return "hdd_pair_diff>40%"
    return None


def valid_pair_days(days: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """days: dicts with keys pair, assignment(ON/OFF), valid(bool), hdd, kwh, solar, boiler.
    Returns (days belonging to complete valid pairs, n_pairs)."""
    by_pair: Dict[Any, List[Dict[str, Any]]] = {}
    for d in days:
        if d.get("pair") is None or d.get("assignment") not in ("ON", "OFF"):
            continue
        by_pair.setdefault(d["pair"], []).append(d)
    out: List[Dict[str, Any]] = []
    n = 0
    for _, ds in sorted(by_pair.items(), key=lambda kv: str(kv[0])):
        if len(ds) != 2 or {x["assignment"] for x in ds} != {"ON", "OFF"}:
            continue
        if not all(x.get("valid") for x in ds):
            continue
        if pair_exclusion(ds[0].get("hdd"), ds[1].get("hdd")):
            continue
        out.extend(ds)
        n += 1
    return out, n


# ---------------------------------------------------------------- OLS
def fit_effect(days: Sequence[Dict[str, Any]], n_pairs: Optional[int] = None) -> Dict[str, Any]:
    """OLS kWh ~ HDD + solar + boiler + ON. Covariates with ~zero variance or missing are dropped."""
    rows = [d for d in days if (d.get("kwh_heat") is not None or d.get("kwh") is not None) and d.get("hdd") is not None
            and d.get("assignment") in ("ON", "OFF")]
    res: Dict[str, Any] = {"n_days": len(rows), "n_pairs": n_pairs if n_pairs is not None else len(rows) // 2,
                           "effect_kwh": None, "ci_low": None, "ci_high": None, "effect_pct": None,
                           "ci_low_pct": None, "ci_high_pct": None, "confirmed": False, "covariates": []}
    if len(rows) < 4:
        res["reason"] = "too_few_days"
        return res
    y = np.array([float(d["kwh_heat"] if d.get("kwh_heat") is not None else d["kwh"]) for d in rows])
    on = np.array([1.0 if d["assignment"] == "ON" else 0.0 for d in rows])
    if on.min() == on.max():
        res["reason"] = "no_contrast"
        return res
    cols = [np.ones(len(rows))]
    names = ["const"]
    for key in ("hdd", "solar", "boiler"):
        vals = [d.get(key) for d in rows]
        if any(v is None for v in vals):
            continue
        arr = np.array(vals, dtype=float)
        if arr.std() < 1e-9:
            continue
        cols.append(arr)
        names.append(key)
    cols.append(on)
    names.append("on")
    X = np.column_stack(cols)
    # drop covariates until full rank & enough dof
    while True:
        p = X.shape[1]
        if np.linalg.matrix_rank(X) == p and len(rows) - p >= 1:
            break
        if p <= 2:
            res["reason"] = "rank_deficient"
            return res
        if "solar" in names:
            drop = names.index("solar")
        else:
            drop = names.index(names[-2])  # drop last covariate before 'on'
        X = np.delete(X, drop, axis=1)
        names.pop(drop)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(rows) - X.shape[1]
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se = float(np.sqrt(max(cov[-1, -1], 0.0)))
    eff = float(beta[-1])
    t = t95(dof)
    lo, hi = eff - t * se, eff + t * se
    X_off = X.copy()
    X_off[:, -1] = 0.0
    base = float(np.mean(X_off @ beta))
    res.update({"effect_kwh": round(eff, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4), "se": round(se, 4),
                "dof": dof, "covariates": names[1:-1], "baseline_kwh": round(base, 3),
                "confirmed": (hi < 0 and dof >= 2)})
    if base > 0:
        res.update({"effect_pct": round(100 * eff / base, 2), "ci_low_pct": round(100 * lo / base, 2),
                    "ci_high_pct": round(100 * hi / base, 2)})
    return res
