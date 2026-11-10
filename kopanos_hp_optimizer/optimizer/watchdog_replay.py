"""Offline replay of the HA automation `hp_ultra_low_hz_watchdog` (packages/heat_pump_boiler.yaml §19)
over recorded history: how many times WOULD each trigger have fired (assuming the switch was on)?

Semantics mirror the YAML templates (raw HA states, `for:` durations, last_changed-based timers).
binary_sensor.hp_compressor_running is derived from the compressor frequency exactly like its template
(number -> on if > 0 else off; non-number -> unavailable).
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .const import E, TZ
from .kpi import compressor_runs, ffill, segments, to_float

Series = Sequence[Tuple[datetime, Any]]

FLOW = E["flow"]
FREQ = E["freq"]
VALVE = E["valve"]
ROOM_AVG = "sensor.hp_room_temp_average"
TARGET = E["target"]
EEPROM = E["eeprom"]
ERROR = E["error"]
T_EFF = "sensor.hp_effective_outdoor_temp"
OUTLET = "sensor.panasonic_heat_pump_main_main_outlet_temp"
DEFROST = E["defrost"]
RUNNING = "binary_sensor.hp_compressor_running"
WATCHDOG_ENTITIES = [FLOW, FREQ, VALVE, ROOM_AVG, TARGET, EEPROM, ERROR, T_EFF, OUTLET, DEFROST, E["t_out"]]


class Timeline:
    """Raw state + HA-style last_changed lookup for one entity."""

    def __init__(self, series: Series):
        pts = sorted(series or [], key=lambda p: p[0])
        self.t: List[datetime] = []
        self.v: List[Any] = []
        self.lc: List[datetime] = []  # last_changed at each point
        prev = object()
        for ts, raw in pts:
            raw = None if raw is None else str(raw)
            if self.v and raw == self.v[-1]:
                continue  # attribute-only update: last_changed unchanged
            self.t.append(ts)
            self.v.append(raw)
            self.lc.append(ts)
            prev = raw
        del prev

    def at(self, ts: datetime) -> Tuple[Optional[str], Optional[datetime]]:
        i = bisect.bisect_right(self.t, ts) - 1
        if i < 0:
            return None, None
        return self.v[i], self.lc[i]

    @property
    def changes(self) -> List[datetime]:
        return self.t


def _num(s: Optional[str]) -> Optional[float]:
    return to_float(s)


def derive_running(freq: Series) -> List[Tuple[datetime, str]]:
    out = []
    for ts, raw in freq:
        f = _num(raw)
        out.append((ts, "unavailable" if f is None else ("on" if f > 0 else "off")))
    return out


def _run_for(cond: Callable[[datetime], bool], points: Iterable[datetime], start: datetime, end: datetime,
             hold: timedelta) -> List[datetime]:
    """Fire times of a template trigger with `for: hold` (re-armed when the condition turns false)."""
    pts = sorted({p for p in points if start <= p <= end} | {start, end})
    fires: List[datetime] = []
    since: Optional[datetime] = None
    fired = False
    for i, t in enumerate(pts):
        c = cond(t)
        if c and since is None:
            # already true at window start = carried over from before the window: not a new trigger
            since, fired = t, (i == 0)
        elif not c:
            since, fired = None, False
        nxt = pts[i + 1] if i + 1 < len(pts) else end
        if since is not None and not fired and since + hold <= nxt and since + hold <= end:
            fires.append(max(since + hold, t))
            fired = True
    return fires


def replay(history: Dict[str, Series], start: datetime, end: datetime, starts_limit: int = 3) -> Dict[str, Any]:
    tl = {e: Timeline(history.get(e, [])) for e in WATCHDOG_ENTITIES}
    tl[RUNNING] = Timeline(history.get(RUNNING) or derive_running(history.get(FREQ, [])))
    S = lambda e, t: tl[e].at(t)[0]  # noqa: E731
    res: Dict[str, Dict[str, Any]] = {}

    # 1) low_flow -------------------------------------------------------------------
    def low_flow(t):
        f, c = _num(S(FLOW, t)), _num(S(FREQ, t)) or 0.0
        return f is not None and f < 11.0 and c > 0.0 and S(VALVE, t) != "Tank"
    pts = tl[FLOW].changes + tl[FREQ].changes + tl[VALVE].changes
    res["low_flow"] = {"fires": _run_for(low_flow, pts, start, end, timedelta(minutes=5))}

    # 2) starts_1h — (a) as implemented: history_stats count of ->on transitions incl. unavailable->on,
    #                    +1 if on at window start; numeric_state above 3 (fires on crossing)
    run_t = tl[RUNNING]
    ons = [run_t.t[i] for i in range(len(run_t.t)) if run_t.v[i] == "on"]

    def count_1h(t):
        w0 = t - timedelta(minutes=60)
        n = bisect.bisect_right(ons, t) - bisect.bisect_right(ons, w0)
        st0, _ = run_t.at(w0)
        return n + (1 if st0 == "on" else 0)
    pts = sorted(set(ons) | {o + timedelta(minutes=60, seconds=1) for o in ons} | set(run_t.t))
    fires, above = [], False
    for t in pts:
        if not (start <= t <= end):
            continue
        a = count_1h(t) > starts_limit
        if a and not above:
            fires.append(t)
        above = a
    res["starts_1h_as_implemented"] = {"fires": fires,
                                       "note": "all starts incl. Tank, unavailable->on glitches, +1 if running at window start"}
    #    (b) intent: real starts (glitches ≤10' bridged), Room mode only, no +1
    fsegs = segments(history.get(FREQ, []), start - timedelta(hours=2), end)
    vsegs = ffill(segments(history.get(VALVE, []), start - timedelta(hours=2), end,
                           parse=lambda s: 1.0 if s == "Tank" else (0.0 if s == "Room" else None)))
    vstart = [s[0] for s in vsegs]

    def valve_at(t):
        i = bisect.bisect_right(vstart, t) - 1
        return vsegs[i][2] if i >= 0 else None
    real = [r[0] for r in compressor_runs(fsegs) if r[2]]
    room_starts = [t for t in real if valve_at(t) != 1.0]
    fires_b, above = [], False
    for t in sorted(set(room_starts) | {x + timedelta(minutes=60, seconds=1) for x in room_starts}):
        n = bisect.bisect_right(room_starts, t) - bisect.bisect_right(room_starts, t - timedelta(minutes=60))
        a = n > starts_limit
        if a and not above and start <= t <= end:
            fires_b.append(t)
        above = a
    res["starts_1h_room_real"] = {"fires": fires_b, "note": "real starts (gaps ≤10' bridged), Room only"}
    res["_glitch_on_transitions"] = len([t for t in ons if start <= t <= end]) - len([t for t in real if start <= t <= end])

    # 3) cold_room ----------------------------------------------------------------------
    def cold(t):
        tg = _num(S(TARGET, t))
        tg = 23.0 if tg is None else tg
        r = _num(S(ROOM_AVG, t))
        return r is not None and r <= tg - 1.2
    pts = tl[ROOM_AVG].changes + tl[TARGET].changes
    res["cold_room"] = {"fires": _run_for(cold, pts, start, end, timedelta(minutes=45))}

    # 4) eeprom_high (budget 12 eco / 18 comfort; history of the dynamic attribute not replayed) ---------
    for budget in (12, 18):
        def ee(t, b=budget):
            v = _num(S(EEPROM, t))
            return int(v or 0) >= b
        res[f"eeprom_high_{budget}"] = {"fires": _run_for(ee, tl[EEPROM].changes, start, end, timedelta(0))}

    # 5) error_code ---------------------------------------------------------------------
    def err(t):
        e = S(ERROR, t) or ""
        return "H62" in e or "H75" in e
    res["error_code"] = {"fires": _run_for(err, tl[ERROR].changes, start, end, timedelta(0))}

    # 6) frost_water_risk -------------------------------------------------------------------
    teff = tl[T_EFF] if tl[T_EFF].t else tl[E["t_out"]]

    def frost(t):
        to = _num(teff.at(t)[0])
        to = 10.0 if to is None else to
        out = _num(S(OUTLET, t))
        comp = _num(S(FREQ, t)) or 0.0
        rs, rlc = run_t.at(t)
        run_s = (t - rlc).total_seconds() if rs == "on" and rlc else 0
        ds, dlc = tl[DEFROST].at(t)
        defr_ok = ds is None or (ds != "on" and (t - dlc).total_seconds() >= 600)
        vs, vlc = tl[VALVE].at(t)
        room_ok = vs is None or (vs != "Tank" and (t - vlc).total_seconds() >= 600)
        return to <= 5.0 and out is not None and out < 27.0 and comp > 0.0 and run_s >= 900 and defr_ok and room_ok
    pts = (teff.changes + tl[OUTLET].changes + tl[FREQ].changes
           + [x + timedelta(seconds=900) for x in run_t.t] + [x + timedelta(seconds=600) for x in tl[DEFROST].t]
           + [x + timedelta(seconds=600) for x in tl[VALVE].t])
    res["frost_water_risk"] = {"fires": _run_for(frost, pts, start, end, timedelta(minutes=2)),
                               "t_out_source": T_EFF if tl[T_EFF].t else E["t_out"]}
    mins = [v for v in (_num(x) for x in teff.v) if v is not None]
    res["_t_out_min"] = min(mins) if mins else None
    return res


def summarize(res: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in res.items():
        if k.startswith("_"):
            out[k] = v
            continue
        per_day: Dict[str, int] = defaultdict(int)
        for t in v["fires"]:
            per_day[t.astimezone(TZ).date().isoformat()] += 1
        out[k] = {"count": len(v["fires"]), "per_day": dict(sorted(per_day.items())),
                  "first": [t.astimezone(TZ).strftime("%m-%d %H:%M") for t in v["fires"][:5]],
                  **{kk: vv for kk, vv in v.items() if kk != "fires"}}
    return out
