"""KPI engine: computes per-window KPIs from Home Assistant history (step-function semantics).

History series format: list of (datetime_tzaware, raw_state). Each state holds until the next
change. The HA history API returns the state valid at window start as the first point.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .const import E, HDD_BASE_C, TZ

Seg = Tuple[datetime, datetime, Optional[float]]
BAD = {"unknown", "unavailable", "none", "", None}
HZ_BINS: Tuple[Tuple[str, float, float], ...] = (
    ("≤19", 0.0, 19.5), ("20–22", 19.5, 22.5), ("23–26", 22.5, 26.5),
    ("27–35", 26.5, 35.5), ("36–45", 35.5, 45.5), (">45", 45.5, 1e9),
)
RUN_GAP_BRIDGE = timedelta(minutes=10)
START_PEAK_WINDOW = timedelta(minutes=30)


def to_float(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, str) and v.strip().lower() in BAD):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def to_onoff(v: Any) -> Optional[float]:
    if isinstance(v, str):
        s = v.lower()
        if s == "on":
            return 1.0
        if s == "off":
            return 0.0
    return None


def bounded(lo: float, hi: float) -> Callable[[Any], Optional[float]]:
    """Parser that treats values outside the physical range [lo, hi] (e.g. HeishaMon -128 sentinel) as unknown."""
    def _p(v: Any) -> Optional[float]:
        f = to_float(v)
        return f if f is not None and lo <= f <= hi else None
    return _p


# physical plausibility limits (code review MAJOR 4)
P_TEMP = bounded(-40.0, 60.0)      # °C (outdoor / room)
P_FREQ = bounded(0.0, 120.0)       # Hz
P_FLOW = bounded(0.0, 60.0)        # L/min
P_POWER = bounded(0.0, 9500.0)     # W electrical consumption
P_PROD = bounded(0.0, 30000.0)     # W thermal production


def is_fault_code(state: Any) -> bool:
    """True for a real heat-pump error. H00 / 'No error' / unknown are normal states."""
    if state is None:
        return False
    s = str(state).strip()
    if not s or s.lower() in BAD or s.lower() in ("no error", "none"):
        return False
    if s.upper().startswith("H00") or "no error" in s.lower():
        return False
    return True


def segments(series: Sequence[Tuple[datetime, Any]], start: datetime, end: datetime,
             parse: Callable[[Any], Optional[float]] = to_float) -> List[Seg]:
    """Clip a step series to [start, end). Missing prefix => None segment."""
    pts = sorted(series or [], key=lambda p: p[0])
    out: List[Seg] = []
    cur_v: Optional[float] = None
    cur_t = start
    for ts, raw in pts:
        v = parse(raw)
        if ts <= start:
            cur_v = v
            continue
        if ts >= end:
            break
        if ts > cur_t:
            out.append((cur_t, ts, cur_v))
        cur_t, cur_v = ts, v
    if end > cur_t:
        out.append((cur_t, end, cur_v))
    return out


def ffill(segs: List[Seg]) -> List[Seg]:
    """Forward-fill unknown segments with the last known value (for discrete states like the 3-way valve)."""
    out: List[Seg] = []
    last: Optional[float] = None
    for a, b, v in segs:
        if v is None:
            v = last
        else:
            last = v
        out.append((a, b, v))
    return out


def _secs(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds()


def integrate(segs: List[Seg]) -> Tuple[float, float]:
    """Return (integral value*seconds over known, known seconds)."""
    tot = known = 0.0
    for a, b, v in segs:
        if v is not None:
            d = _secs(a, b)
            tot += v * d
            known += d
    return tot, known


def value_at(segs: List[Seg], starts: List[datetime], t: datetime) -> Optional[float]:
    i = bisect.bisect_right(starts, t) - 1
    if i < 0:
        return None
    a, b, v = segs[i]
    return v if a <= t < b else None


def align(named: Dict[str, List[Seg]], start: datetime, end: datetime) -> List[Tuple[datetime, datetime, Dict[str, Optional[float]]]]:
    """Union of breakpoints -> intervals with all values."""
    bps = {start, end}
    for segs in named.values():
        for a, b, _ in segs:
            bps.add(a)
            bps.add(b)
    times = sorted(t for t in bps if start <= t <= end)
    idx = {k: ([s[0] for s in v], v) for k, v in named.items()}
    out = []
    for a, b in zip(times, times[1:]):
        if b <= a:
            continue
        out.append((a, b, {k: value_at(segs, st, a) for k, (st, segs) in idx.items()}))
    return out


# ---------------------------------------------------------------- compressor runs
def compressor_runs(freq_segs: List[Seg]) -> List[Tuple[datetime, datetime, bool]]:
    """Return runs (t_on, t_off, starts_in_window). None gaps <= 10' are bridged."""
    runs: List[List[Any]] = []
    prev_known_zero = False
    last_state: Optional[bool] = None
    gap_start: Optional[datetime] = None
    for a, b, v in freq_segs:
        if v is None:
            if gap_start is None:
                gap_start = a
            continue
        running = v > 0
        if gap_start is not None:
            long_gap = (a - gap_start) > RUN_GAP_BRIDGE
            if long_gap:
                if last_state and runs:
                    runs[-1][1] = gap_start
                    runs[-1][3] = True  # closed
                last_state = None
                prev_known_zero = False
            gap_start = None
        if running:
            if last_state is True and runs and not runs[-1][3]:
                runs[-1][1] = b
            else:
                runs.append([a, b, prev_known_zero, False])
        else:
            if last_state is True and runs:
                runs[-1][3] = True
            prev_known_zero = True
        last_state = running
    return [(r[0], r[1], r[2]) for r in runs]


def effective_states(series: Sequence[Tuple[datetime, Any]], start: datetime, end: datetime) -> List[str]:
    """Raw states effective at any time inside [start, end)."""
    pts = sorted(series or [], key=lambda p: p[0])
    before = [str(r) for t, r in pts if t <= start][-1:]
    return before + [str(r) for t, r in pts if start < t < end]


def max_starts_per_hour(start_times: List[datetime]) -> int:
    st = sorted(start_times)
    best = j = 0
    for i, t in enumerate(st):
        while st[j] <= t - timedelta(minutes=60):
            j += 1
        best = max(best, i - j + 1)
    return best


def counter_increments(segs: List[Seg]) -> Optional[float]:
    vals = [v for _, _, v in segs if v is not None]
    if len(vals) < 1:
        return None
    inc = 0.0
    for x, y in zip(vals, vals[1:]):
        if y > x:
            inc += y - x
    return inc


def eeprom_writes(segs: List[Seg]) -> Optional[float]:
    """Writes in window for a daily-resetting counter (sum of positive increments)."""
    return counter_increments(segs)


def _daytime_windows(start: datetime, end: datetime, h0: int = 8, h1: int = 17):
    d = start.astimezone(TZ).date() - timedelta(days=1)
    last = end.astimezone(TZ).date()
    while d <= last:
        a = datetime.combine(d, time(h0), TZ)
        b = datetime.combine(d, time(h1), TZ)
        a, b = max(a, start), min(b, end)
        if b > a:
            yield a, b
        d += timedelta(days=1)


# ---------------------------------------------------------------- main entry
def compute_kpis(history: Dict[str, Sequence[Tuple[datetime, Any]]], start: datetime, end: datetime,
                 max_hz: float = 22.0, entity_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    em = dict(E)
    if entity_map:
        em.update(entity_map)
    H = lambda k: history.get(em[k], [])  # noqa: E731
    window_s = _secs(start, end)
    k: Dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat(), "hours": round(window_s / 3600, 3)}

    heat = segments(H("heat_power"), start, end, parse=P_POWER)
    dhw = segments(H("dhw_power"), start, end, parse=P_POWER)
    heat_p = segments(H("heat_prod"), start, end, parse=P_PROD)
    dhw_p = segments(H("dhw_prod"), start, end, parse=P_PROD)
    price = segments(H("price"), start, end)
    freq = segments(H("freq"), start, end, parse=P_FREQ)
    tout = segments(H("t_out"), start, end, parse=P_TEMP)

    # energy & cost ------------------------------------------------------
    heat_ws, heat_known = integrate(heat)
    dhw_ws, _ = integrate(dhw)
    hp_ws, _ = integrate(heat_p)
    dp_ws, _ = integrate(dhw_p)
    k["kwh_heat"] = round(heat_ws / 3.6e6, 3)
    k["kwh_dhw"] = round(dhw_ws / 3.6e6, 3)
    k["kwh"] = round((heat_ws + dhw_ws) / 3.6e6, 3)
    k["kwh_boiler"] = k["kwh_dhw"]
    k["power_coverage"] = round(heat_known / window_s, 4) if window_s else 0.0
    cost = 0.0
    last_price = None
    for a, b, vals in align({"h": heat, "d": dhw, "p": price}, start, end):
        p = vals["p"] if vals["p"] is not None else last_price
        if vals["p"] is not None:
            last_price = vals["p"]
        if p is None:
            continue
        w = (vals["h"] or 0.0) + (vals["d"] or 0.0)
        cost += w * _secs(a, b) / 3.6e6 * p
    k["cost_eur"] = round(cost, 3)
    cons = heat_ws + dhw_ws
    k["cop"] = round((hp_ws + dp_ws) / cons, 2) if cons > 0 else None
    k["cop_heat"] = round(hp_ws / heat_ws, 2) if heat_ws > 0 else None

    # outdoor / HDD -------------------------------------------------------
    t_ws, t_known = integrate(tout)
    tv = [v for _, _, v in tout if v is not None]
    k["t_out_mean"] = round(t_ws / t_known, 2) if t_known else None
    k["t_out_min"] = min(tv) if tv else None
    k["t_out_max"] = max(tv) if tv else None
    hdd_s = sum(max(0.0, HDD_BASE_C - v) * _secs(a, b) for a, b, v in tout if v is not None)
    # scale to full window if partially missing
    k["hdd"] = round(hdd_s / 86400 * (window_s / t_known), 3) if t_known else None
    ok_hdd = bool(k["hdd"] and k["hdd"] >= 0.5)
    k["kwh_per_hdd"] = round(k["kwh"] / k["hdd"], 3) if ok_hdd else None            # total (heat + DHW)
    k["kwh_per_hdd_heat"] = round(k["kwh_heat"] / k["hdd"], 3) if ok_hdd else None  # space heating only

    # compressor ------------------------------------------------------------
    runs = compressor_runs(freq)
    started = [r for r in runs if r[2] and r[0] >= start]
    k["starts_freq"] = len(started)
    ops = counter_increments(segments(H("ops_counter"), start, end))
    k["starts_counter"] = None if ops is None else int(round(ops))
    k["starts"] = k["starts_counter"] if k["starts_counter"] is not None else k["starts_freq"]
    k["max_starts_per_hour"] = max_starts_per_hour([r[0] for r in started])
    on_d = [_secs(a, b) / 60 for a, b, _ in runs]
    k["on_minutes_total"] = round(sum(on_d), 1)
    k["on_minutes_mean"] = round(sum(on_d) / len(on_d), 1) if on_d else None
    k["on_minutes_min"] = round(min(on_d), 1) if on_d else None
    off_d = [_secs(runs[i][1], runs[i + 1][0]) / 60 for i in range(len(runs) - 1)]
    k["off_minutes_mean"] = round(sum(off_d) / len(off_d), 1) if off_d else None
    run_s = 0.0
    bins = {name: 0.0 for name, _, _ in HZ_BINS}
    low_s = 0.0
    for a, b, v in freq:
        if v is None or v <= 0:
            continue
        d = _secs(a, b)
        run_s += d
        if v <= max_hz:
            low_s += d
        for name, lo, hi in HZ_BINS:
            if lo < v <= hi or (name == "≤19" and v <= hi):
                bins[name] += d
                break
    k["running_hours"] = round(run_s / 3600, 3)
    k["hz_bins_pct"] = {n: round(100 * s / run_s, 1) if run_s else 0.0 for n, s in bins.items()}
    k["low_hz_ratio_pct"] = round(100 * low_s / run_s, 1) if run_s else None
    peaks = []
    for a, _, _ in started:
        lim = a + START_PEAK_WINDOW
        vs = [v for s0, s1, v in freq if v is not None and s1 > a and s0 < lim]
        if vs:
            peaks.append(max(vs))
    k["max_hz_after_start_mean"] = round(sum(peaks) / len(peaks), 1) if peaks else None
    k["max_hz_after_start_max"] = max(peaks) if peaks else None
    fv = [v for _, _, v in freq if v is not None]
    k["max_hz"] = max(fv) if fv else None

    # flow while running ---------------------------------------------------
    flow = segments(H("flow"), start, end, parse=P_FLOW)
    valve = ffill(segments(H("valve"), start, end, parse=lambda s: 1.0 if s == "Tank" else (0.0 if s == "Room" else None)))
    min_flow = min_flow_room = None
    low_flow_s = low_flow_room_s = 0.0
    for a, b, vals in align({"f": freq, "q": flow, "v": valve}, start, end):
        if vals["f"] and vals["f"] > 0 and vals["q"] is not None:
            q = vals["q"]
            min_flow = q if min_flow is None else min(min_flow, q)
            room_mode = vals["v"] != 1.0  # Room or unknown => space heating circuit
            if room_mode:
                min_flow_room = q if min_flow_room is None else min(min_flow_room, q)
            if q < 11:
                low_flow_s += _secs(a, b)
                if room_mode:
                    low_flow_room_s += _secs(a, b)
    vst = [x[0] for x in valve]
    room_started = [r for r in started if value_at(valve, vst, r[0]) != 1.0]
    k["starts_room"] = len(room_started)
    k["max_starts_per_hour_room"] = max_starts_per_hour([r[0] for r in room_started])
    k["min_flow_running"] = min_flow
    k["min_flow_running_room"] = min_flow_room
    k["low_flow_minutes"] = round(low_flow_s / 60, 1)
    k["low_flow_minutes_room"] = round(low_flow_room_s / 60, 1)

    # comfort -------------------------------------------------------------------
    room_p = segments(H("room"), start, end)
    room_a = segments(H("room_alt"), start, end)
    room = [(a, b, v["p"] if v["p"] is not None else v["a"]) for a, b, v in align({"p": room_p, "a": room_a}, start, end)]
    target = segments(H("target"), start, end)
    within = known = cold = 0.0
    dev_ws = 0.0
    for a, b, vals in align({"r": room, "t": target}, start, end):
        r, t = vals["r"], vals["t"]
        if r is None or t is None:
            continue
        d = _secs(a, b)
        known += d
        dev_ws += (r - t) * d
        if abs(r - t) <= 0.3 + 1e-9:
            within += d
        if r <= t - 1.2:
            cold += d
    k["comfort_within_03_pct"] = round(100 * within / known, 1) if known else None
    k["comfort_mean_dev"] = round(dev_ws / known, 2) if known else None
    k["cold_minutes"] = round(cold / 60, 1)
    rv = [v for _, _, v in room if v is not None]
    k["room_min"] = min(rv) if rv else None

    # eeprom / defrost / errors / valve -------------------------------------------
    ee_segs = segments(H("eeprom"), start, end)
    ee = eeprom_writes(ee_segs)
    k["eeprom_writes"] = None if ee is None else int(round(ee))          # writes inside the window
    # ignore sub-minute carry-over states (e.g. yesterday's value lasting 0.4 s before the midnight reset)
    ee_vals = [v for a, b, v in ee_segs if v is not None and _secs(a, b) >= 60]
    k["eeprom_max_daily"] = int(round(max(ee_vals))) if ee_vals else None  # max of the daily counter (budget 12/18)
    dfr = segments(H("defrost"), start, end, parse=to_onoff)
    k["defrosts"] = sum(1 for (_, _, v0), (_, _, v1) in zip(dfr, dfr[1:]) if v0 == 0.0 and v1 == 1.0)
    tst = [x[0] for x in tout]
    onsets = [a1 for (_, _, v0), (a1, _, v1) in zip(dfr, dfr[1:]) if v0 == 0.0 and v1 == 1.0]
    k["defrosts_tout_gt7"] = sum(1 for t in onsets if (value_at(tout, tst, t) or -99) > 7)
    k["defrost_minutes"] = round(sum(_secs(a, b) for a, b, v in dfr if v == 1.0) / 60, 1)
    errs = sorted(e for e in set(effective_states(H("error"), start, end)) if is_fault_code(e))
    k["errors"] = errs
    k["error_h62_h75"] = any(("H62" in e or "H75" in e) for e in errs)
    k["tank_minutes"] = round(sum(_secs(a, b) for a, b, v in valve if v == 1.0) / 60, 1)

    # presence / solar ------------------------------------------------------------
    pers = segments(H("person"), start, end, parse=lambda s: None if s in BAD else (1.0 if s == "home" else 0.0))
    p_ws, p_known = integrate(pers)
    k["home_ratio"] = round(p_ws / p_known, 3) if p_known else None
    cloud = segments(H("weather"), start, end)
    sol_ws = sol_s = 0.0
    for a, b in _daytime_windows(start, end):
        for s0, s1, v in cloud:
            lo, hi = max(a, s0), min(b, s1)
            if hi > lo and v is not None:
                d = _secs(lo, hi)
                sol_ws += (1 - min(max(v, 0), 100) / 100) * d
                sol_s += d
    k["solar_index"] = round(sol_ws / sol_s, 3) if sol_s else None
    return k


def cycle_window(day_end_local: datetime, report_hour: str = "10:30") -> Tuple[datetime, datetime]:
    """Cycle that closes at report_hour on day_end_local's date: [D-1 hh:mm, D hh:mm) Europe/Athens."""
    hh, mm = (int(x) for x in report_hour.split(":"))
    d = day_end_local.astimezone(TZ).date()
    end = datetime.combine(d, time(hh, mm), TZ)
    return end - timedelta(days=1), end


def needed_entities(entity_map: Optional[Dict[str, str]] = None) -> List[str]:
    em = dict(E)
    if entity_map:
        em.update(entity_map)
    return [v for key, v in em.items() if key != "weather" and v]
