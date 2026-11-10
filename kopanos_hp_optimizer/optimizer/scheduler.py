"""Orchestration: cycle close (report_hour Europe/Athens), health (6h), heartbeat (5'), A/B + autotune
planning, pause / resume / rollback. All helper writes go through HAClient.set_helper()."""
from __future__ import annotations

import logging
import random
import threading
from datetime import date, datetime, time, timedelta
from statistics import mean
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import tuner as T
from .const import (AB_TODAY, ALLOWLIST, AUTOTUNE_ENABLED, E, HEARTBEAT, MAX_HZ, THERMAL_BATTERY_STATUS,
                    TUNABLE_PARAMS, TZ, ULH_ENABLED, ULH_PHASE, WATCHDOG_AUTOMATION, WATCHDOG_REASON, zone_for)
from .experiment import day_exclusions, fit_effect, valid_pair_days, weekly_off_weekday
from .ha_client import WriteRejected
from .kpi import compute_kpis, needed_entities, to_float

log = logging.getLogger(__name__)
HEARTBEAT_EVERY = timedelta(minutes=5)
HEALTH_EVERY = timedelta(hours=6)


# ---------------------------------------------------------------- pure helpers (tested)
def last_cycle_end(now: datetime, report_hour: str) -> datetime:
    hh, mm = (int(x) for x in report_hour.split(":"))
    local = now.astimezone(TZ)
    end = datetime.combine(local.date(), time(hh, mm), TZ)
    if end > local:
        end -= timedelta(days=1)
    return end


def due_jobs(now: datetime, last_hb: Optional[datetime], last_health: Optional[datetime],
             last_closed: Optional[str], report_hour: str) -> List[str]:
    jobs = []
    if last_hb is None or now - last_hb >= HEARTBEAT_EVERY:
        jobs.append("heartbeat")
    if last_health is None or now - last_health >= HEALTH_EVERY:
        jobs.append("health")
    if last_closed != last_cycle_end(now, report_hour).date().isoformat():
        jobs.append("report")
    return jobs


def ab_assignment(start: date, seed: int, d: date) -> Tuple[str, str]:
    """Randomized order within each consecutive pair of days. Returns (ON|OFF, pair_id)."""
    idx = (d - start).days
    if idx < 0:
        raise ValueError("date before A/B start")
    pair = idx // 2
    first = random.Random(f"{seed}-{pair}").choice(("ON", "OFF"))
    a = first if idx % 2 == 0 else ("OFF" if first == "ON" else "ON")
    return a, f"P{start.isoformat()}-{pair}"


def helper_value(entity_id: str, state: Optional[dict]) -> Any:
    if not state:
        return None
    s = state.get("state")
    if s in (None, "unknown", "unavailable"):
        return None
    kind = ALLOWLIST[entity_id].kind if entity_id in ALLOWLIST else "text"
    if kind == "bool":
        return s == "on"
    if kind == "number":
        return to_float(s)
    return s


def same_value(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def forecast_temp(forecast: List[dict], start_day: date, end_day: date) -> Optional[float]:
    """Heuristic zone temperature for the next cycle: mean(start-day high+low)/2 and end-day low."""
    by_day: Dict[date, dict] = {}
    for f in forecast or []:
        try:
            d = datetime.fromisoformat(str(f["datetime"]).replace("Z", "+00:00")).astimezone(TZ).date()
        except Exception:  # noqa: BLE001
            continue
        by_day.setdefault(d, f)
    vals = []
    s = by_day.get(start_day)
    if s and s.get("temperature") is not None and s.get("templow") is not None:
        vals.append((float(s["temperature"]) + float(s["templow"])) / 2)
    e = by_day.get(end_day)
    if e and e.get("templow") is not None:
        vals.append(float(e["templow"]))
    return round(mean(vals), 2) if vals else None


# ---------------------------------------------------------------- optimizer
class Optimizer:
    def __init__(self, opts: Any, ha: Any, store: Any, notifier: Any, reporter: Any, mqtt: Any = None,
                 now_fn: Callable[[], datetime] = lambda: datetime.now(TZ)):
        self.opts, self.ha, self.store, self.notifier, self.reporter = opts, ha, store, notifier, reporter
        self.mqtt = mqtt
        self.now = now_fn
        self.lock = threading.RLock()

    # -- state -------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.opts.mode

    @property
    def paused(self) -> bool:
        return bool(self.store.get("paused", False))

    def tuner_state(self) -> Dict[str, Any]:
        st = self.store.get("tuner_state")
        return st if st else T.new_state()

    def _pub(self, key: str, state: Any, attrs: Optional[dict] = None) -> None:
        if self.mqtt:
            try:
                self.mqtt.publish(key, state, attrs)
            except Exception as e:  # noqa: BLE001
                log.warning("mqtt publish %s: %s", key, type(e).__name__)

    def _event(self, kind: str, msg: str) -> None:
        log.info("%s: %s", kind, msg)
        self.store.event(kind, msg)

    def _read(self, eid: str) -> Any:
        try:
            return helper_value(eid, self.ha.get_state(eid))
        except Exception:  # noqa: BLE001
            return None

    # -- writes -----------------------------------------------------------------
    def apply(self, eid: str, value: Any, reason: str, restore: bool = False) -> bool:
        old = None if eid == HEARTBEAT else self._read(eid)
        try:
            norm = self.ha.set_helper(eid, value, mode=self.mode, paused=self.paused, restore=restore)
        except WriteRejected as e:
            self.store.log_change(eid, old, value if not isinstance(value, datetime) else value.isoformat(),
                                  reason, self.mode, False, str(e))
            self._event("write_rejected", f"{eid}: {e}")
            return False
        except Exception as e:  # noqa: BLE001
            self.store.log_change(eid, old, str(value), reason, self.mode, False, type(e).__name__)
            self._event("write_error", f"{eid}: {type(e).__name__}")
            return False
        if eid != HEARTBEAT:
            if not same_value(old, norm):
                self.store.log_change(eid, old, norm, reason, self.mode, True)
                txt = f"{eid.split('.', 1)[1]} {old} → {norm} ({reason})"
                self.store.put("last_action", {"text": txt, "ts": self.now().isoformat()})
                self._pub("last_action", txt[:255], {"timestamp": self.now().isoformat(), "reason": reason})
        return True

    # -- jobs -------------------------------------------------------------------
    def heartbeat(self) -> None:
        now = self.now()
        with self.lock:
            if self.apply(HEARTBEAT, now, "heartbeat"):
                self.store.put("last_heartbeat", now.isoformat())
        if self.mqtt:
            self.mqtt.online()
        try:
            self.notifier.retry_pending(now)
        except Exception:  # noqa: BLE001
            pass

    def health(self) -> List[str]:
        issues: List[str] = []
        if not self.ha.ping():
            issues.append("HA API unreachable")
        else:
            for eid in ALLOWLIST:
                try:
                    if self.ha.get_state(eid) is None:
                        issues.append(f"missing helper {eid}")
                except Exception:  # noqa: BLE001
                    issues.append(f"read error {eid}")
            for key in ("freq", "heat_power", "t_out"):
                st = self.ha.get_state(E[key])
                if not st or st.get("state") in ("unknown", "unavailable"):
                    issues.append(f"sensor unavailable {E[key]}")
        if self.mqtt and not self.mqtt.connected:
            issues.append("MQTT disconnected")
        prev = self.store.get("health_issues", [])
        self.store.put("health_issues", issues)
        self.store.put("last_health", self.now().isoformat())
        if issues != prev:
            if issues:
                self.notifier.notify("health", "⚠️ HP Optimizer · Έλεγχος υγείας", "\n".join(f"- {i}" for i in issues))
            elif prev:
                self.notifier.notify("health", "✅ HP Optimizer · Υγεία OK", "Όλα τα προβλήματα επιλύθηκαν.")
        return issues

    # -- pause / resume / rollback ----------------------------------------------------
    def pause(self, reason: str, notify: bool = True) -> None:
        with self.lock:
            self.store.put("paused", True)
            self.store.put("pause_reason", reason)
            self._event("pause", reason)
            self._pub("last_action", f"Παύση: {reason}"[:255], {"timestamp": self.now().isoformat()})
        if notify:
            self.notifier.notify("pause", "⏸️ HP Optimizer σε παύση", f"Αιτία: {reason}. Καμία αλλαγή helper μέχρι συνέχιση.")

    def resume(self) -> None:
        with self.lock:
            self.store.put("paused", False)
            self.store.put("pause_reason", "")
            self._event("resume", "resumed by user")
        self.notifier.notify("pause", "▶️ HP Optimizer συνεχίζει", "Η βελτιστοποίηση συνεχίζει από τον επόμενο κύκλο.")

    def rollback(self) -> Dict[str, Any]:
        with self.lock:
            restored, skipped = {}, {}
            for eid, old in self.store.first_old_values().items():
                if eid == HEARTBEAT or eid not in ALLOWLIST or old is None:
                    continue
                if ALLOWLIST[eid].off_only and old is True:
                    skipped[eid] = "consent switch: only OFF allowed"
                    continue
                if self.apply(eid, old, "rollback", restore=True):
                    restored[eid] = old
                else:
                    skipped[eid] = "rejected"
            st = self.tuner_state()
            T.rollback_trials(st, self.now().date().isoformat())
            self.store.put("tuner_state", st)
        self.pause("rollback", notify=False)
        msg = ("Επαναφορά: " + (", ".join(f"{k.split('.', 1)[1]}={v}" for k, v in restored.items()) or "τίποτα προς επαναφορά")
               + (f"\nΠαραλείφθηκαν: {skipped}" if skipped else "") + "\nΤο add-on είναι σε παύση.")
        self.notifier.notify("rollback", "↩️ HP Optimizer · Rollback", msg)
        return {"restored": restored, "skipped": skipped}

    # -- cycle close ------------------------------------------------------------------
    def _detect_external_change(self, plan: Optional[dict]) -> List[str]:
        if not plan or not plan.get("applied") or self.mode == "observe":
            return []
        diffs = []
        for eid, want in plan["applied"].items():
            cur = self._read(eid)
            if cur is not None and not same_value(cur, want):
                diffs.append(f"{eid}={cur} (αναμενόταν {want})")
        return diffs

    def _detect_watchdog_trip(self, plan: Optional[dict]) -> Optional[str]:
        if not plan or not plan.get("applied") or self.mode == "observe":
            return None
        want_ulh = plan["applied"].get(ULH_ENABLED)
        if want_ulh is True and self._read(ULH_ENABLED) is False:
            try:
                reason = str(self._read(WATCHDOG_REASON) or "").strip()
                if reason and reason.lower() not in ("none", "unknown", "unavailable", "idle", "off", "ok", ""):
                    return reason
            except Exception:
                pass
            try:
                st = self.ha.get_state(WATCHDOG_AUTOMATION) or {}
                lt = (st.get("attributes") or {}).get("last_triggered")
                if lt:
                    return f"safety_trip_{str(lt)[:19]}"
            except Exception:
                pass
            return None
        return None

    def _eeprom_budget(self) -> float:
        try:
            st = self.ha.get_state(THERMAL_BATTERY_STATUS) or {}
            attrs = (st.get("attributes") or {}) if isinstance(st, dict) else {}
            val = attrs.get("eeprom_budget_max") or attrs.get("budget_max")
            if val is not None:
                return float(val)
        except Exception:
            pass
        return 16.0

    def _history(self, start: datetime, end: datetime) -> Dict[str, list]:
        em = {"person": self.opts.person_entity} if self.opts.person_entity else None
        hist = self.ha.history(needed_entities(em), start, end)
        try:
            w = self.ha.history([E["weather"]], start, end, attributes=True)
            hist[E["weather"]] = [(t, (a or {}).get("cloud_coverage")) for t, a in w.get(E["weather"], [])]
        except Exception as e:  # noqa: BLE001
            self._event("history_warning", f"weather: {type(e).__name__}")
        return hist

    def _baseline(self, exclude_date: str) -> Dict[str, Any]:
        rows = [c for c in self.store.cycles(30)
                if c["cycle_date"] != exclude_date and c["valid"] and c["assignment"] in (None, "NA", "OFF", "PAUSED")][:7]
        if not rows:
            return {}
        out: Dict[str, Any] = {}
        for key in ("kwh_per_hdd", "kwh", "cost_eur", "starts", "max_hz_after_start_mean", "low_hz_ratio_pct",
                    "comfort_within_03_pct"):
            vals = [c["kpi"].get(key) for c in rows if c["kpi"].get(key) is not None]
            out[key] = round(mean(vals), 3) if vals else None
        out["n"] = len(rows)
        return out

    def _ab_result(self) -> Dict[str, Any]:
        days = []
        for c in self.store.cycles(400):
            if c["assignment"] in ("ON", "OFF") and c["pair_id"]:
                k = c["kpi"]
                days.append({"pair": c["pair_id"], "assignment": c["assignment"], "valid": c["valid"],
                             "hdd": k.get("hdd"), "kwh": k.get("kwh"), "solar": k.get("solar_index"),
                             "boiler": k.get("kwh_boiler")})
        vd, n = valid_pair_days(days)
        return fit_effect(vd, n)

    def kwh_per_hdd_7d(self) -> Optional[float]:
        rows = [c for c in self.store.cycles(7) if c["valid"]]
        kwh = sum(c["kpi"].get("kwh_heat") or 0 for c in rows)
        hdd = sum(c["kpi"].get("hdd") or 0 for c in rows)
        return round(kwh / hdd, 3) if hdd >= 1 else None

    def close_cycle(self, force: bool = False, notify: bool = True) -> Optional[Dict[str, Any]]:
        with self.lock:
            now = self.now()
            end = last_cycle_end(now, self.opts.report_hour)
            start = end - timedelta(days=1)
            cdate = end.date().isoformat()
            if self.store.has_cycle(cdate) and not force:
                self.store.put("last_closed", cdate)
                return None
            max_hz = self._read(MAX_HZ) or 22.0
            em = {"person": self.opts.person_entity} if self.opts.person_entity else None
            kpi = compute_kpis(self._history(start, end), start, end, max_hz=max_hz, entity_map=em)
            plan = self.store.plan(cdate)
            ext = self._detect_external_change(plan)
            watchdog_trip = self._detect_watchdog_trip(plan)
            if watchdog_trip:
                ext = [d for d in ext if not d.startswith(f"{ULH_ENABLED}=")]
            excl = day_exclusions(kpi, bool(ext), self.opts.away_exclusion)
            if watchdog_trip:
                excl.append(f"watchdog:{watchdog_trip}")
            valid = not excl
            zone = zone_for(kpi.get("t_out_mean"))
            self.store.save_cycle(cdate, start.isoformat(), end.isoformat(), kpi, mode=self.mode,
                                  assignment=(plan or {}).get("assignment"), pair_id=(plan or {}).get("pair_id"),
                                  arm=(plan or {}).get("arm"), zone=zone, applied=(plan or {}).get("applied"),
                                  valid=valid, exclusions=excl)
            self.store.put("last_closed", cdate)
            if ext:
                self.pause("εξωτερική αλλαγή helper: " + "; ".join(ext), notify=True)
            elif watchdog_trip:
                self.notifier.notify("watchdog", "⚠️ HP Optimizer · Watchdog Trip",
                                     f"Η ασφάλεια έκλεισε το Ultra-Low Hz ({watchdog_trip}). Η μέρα εξαιρείται, η βελτιστοποίηση συνεχίζει κανονικά.")
            ab = self._ab_result() if self.mode != "observe" else None
            if ab is not None:
                self.store.put("ab_result", ab)
            decision = None
            if plan and plan.get("arm") in ("trial", "control", "incumbent") and plan.get("zone"):
                st = self.tuner_state()
                if plan["zone"] == zone:
                    params = {k: v for k, v in (plan.get("applied") or {}).items() if k in TUNABLE_PARAMS}
                    decision = T.record_day(st, zone, plan["arm"], params, kpi, valid, cdate,
                                            eeprom_budget=self._eeprom_budget())
                    self.store.put("tuner_state", st)
                    if decision:
                        self._event("tuner", str(decision))
                else:
                    self._event("tuner", f"zone mismatch: planned {plan['zone']} actual {zone} — day not used")
            action, next_text = self._plan_next(end, kpi)
            if decision:
                verdict = "αποδεκτή" if decision["accepted"] else "απορρίφθηκε"
                action = (f"{decision['param'].split('.', 1)[1]} {decision['from']} → {decision['to']} {verdict} "
                          f"({decision['reason']}) · " + action)
            rep = self.reporter.build(cycle_date=cdate, mode=self.mode, assignment=(plan or {}).get("assignment"),
                                      zone=zone, action=action, kpi=kpi, baseline=self._baseline(cdate), ab=ab,
                                      next_text=next_text, exclusions=excl, max_hz=max_hz,
                                      eeprom_budget_max=int(self._eeprom_budget()))
            self.store.put("last_report", rep)
            self.store.put("zone", zone)
            self.publish_status()
        if notify:
            self.notifier.notify("report", rep["title"], rep["markdown"], tts=rep["tts"], defer_tts=True)
        return {"cycle_date": cdate, "kpi": kpi, "valid": valid, "exclusions": excl, "report": rep}

    def _plan_next(self, cycle_start: datetime, kpi: Dict[str, Any]) -> Tuple[str, str]:
        """Plan + apply helpers for the cycle [cycle_start, cycle_start+1d). Returns (action, next_text)."""
        nd = (cycle_start + timedelta(days=1)).date()
        key = nd.isoformat()
        if self.paused:
            self.store.save_plan(key, "PAUSED", None, None, None, None)
            return "Καμία (παύση)", "παύση μέχρι συνέχιση"
        if self.mode == "observe":
            self.store.save_plan(key, "NA", None, None, None, None)
            return "Καμία (observe)", "συνέχεια παρατήρησης"
        if self.mode == "ab_test":
            if self.store.get("ab_mode") != "ab_test" or not self.store.get("ab_start"):
                self.store.put("ab_start", key)
            self.store.put("ab_mode", "ab_test")
            a, pair = ab_assignment(date.fromisoformat(self.store.get("ab_start")), self.opts.ab_seed, nd)
            ok1 = self.apply(ULH_ENABLED, a == "ON", f"A/B {a}")
            ok2 = self.apply(AB_TODAY, a, f"A/B {a}")
            self.store.save_plan(key, a, pair, None, None, {ULH_ENABLED: a == "ON", AB_TODAY: a})
            self._pub("ab_today", a)
            return (f"A/B: σήμερα {a}" + ("" if ok1 and ok2 else " (κάποια εγγραφή απέτυχε)")), f"μέρα {a} (ζεύγος {pair.rsplit('-', 1)[1]})"
        # autotune
        self.store.put("ab_mode", "autotune")
        if self._read(AUTOTUNE_ENABLED) is not True:
            self.store.save_plan(key, "NA", None, None, None, None)
            return "Καμία (διακόπτης autotune off)", "αναμονή συγκατάθεσης (input_boolean.hp_optimizer_autotune_enabled)"

        iso = nd.isocalendar()
        pair = f"W{iso[0]}-{iso[1]}"
        off_day = weekly_off_weekday(iso[0], iso[1], self.opts.ab_seed)
        if nd.weekday() == off_day:
            self.apply(ULH_ENABLED, False, "autotune weekly OFF control day")
            self.apply(AB_TODAY, "OFF", "autotune weekly OFF control day")
            self.store.save_plan(key, "OFF", pair, None, None, {ULH_ENABLED: False, AB_TODAY: "OFF"})
            return "Εβδομαδιαία μέρα ελέγχου OFF", "μέρα OFF (έλεγχος)"

        prev = nd - timedelta(days=1)
        prev_plan = self.store.plan(prev.isoformat())
        prev_iso = prev.isocalendar()
        prev_off_day = weekly_off_weekday(prev_iso[0], prev_iso[1], self.opts.ab_seed)
        if prev.weekday() == prev_off_day or (prev_plan and prev_plan.get("assignment") == "OFF"):
            pair_id = f"W{prev_iso[0]}-{prev_iso[1]}"
        else:
            pair_id = None
        t_fc = forecast_temp(self.ha.daily_forecast(E["weather"]), cycle_start.date(), nd)
        zone = zone_for(t_fc if t_fc is not None else kpi.get("t_out_mean")) or "7–12"
        st = self.tuner_state()
        params, arm = T.plan_day(st, zone)
        self.store.put("tuner_state", st)
        oks = [self.apply(eid, v, f"autotune {zone} {arm}") for eid, v in params.items()]
        oks.append(self.apply(ULH_ENABLED, True, f"autotune {zone}"))
        oks.append(self.apply(AB_TODAY, "ON", f"autotune {zone}"))
        applied = {**params, ULH_ENABLED: True, AB_TODAY: "ON"}
        self.store.save_plan(key, "ON", pair_id, arm, zone, applied)
        self.store.put("zone_planned", zone)
        p = ", ".join(f"{k.split('.', 1)[1]}={v}" for k, v in params.items())
        return (f"Autotune ζώνη {zone} ({arm}): {p}" + ("" if all(oks) else " (κάποια εγγραφή απέτυχε)")), f"ζώνη {zone}, {arm}"

    # -- status ---------------------------------------------------------------------------
    def publish_status(self) -> Dict[str, Any]:
        ab = self.store.get("ab_result") or {}
        rep = self.store.get("last_report") or {}
        last = (self.store.cycles(1) or [None])[0]
        la = self.store.get("last_action") or {}
        st = {
            "mode": self.mode + (" (paused)" if self.paused else ""),
            "phase": self._read(ULH_PHASE),
            "ab_today": self._read(AB_TODAY),
            "zone": self.store.get("zone"),
            "effect_pct": ab.get("effect_pct"),
            "kwh_per_hdd_7d": self.kwh_per_hdd_7d(),
            "last_cycle_kwh": last["kpi"].get("kwh") if last else None,
            "last_cycle_cost": last["kpi"].get("cost_eur") if last else None,
            "last_action": la.get("text"),
            "last_report": rep.get("short"),
        }
        self._pub("mode", st["mode"], {"paused": self.paused, "pause_reason": self.store.get("pause_reason", "")})
        self._pub("phase", st["phase"])
        self._pub("ab_today", st["ab_today"])
        self._pub("zone", st["zone"])
        self._pub("effect_pct", st["effect_pct"], {"ci_low": ab.get("ci_low_pct"), "ci_high": ab.get("ci_high_pct"),
                                                   "n_pairs": ab.get("n_pairs"), "confirmed": ab.get("confirmed")})
        self._pub("kwh_per_hdd_7d", st["kwh_per_hdd_7d"])
        self._pub("last_cycle_kwh", st["last_cycle_kwh"])
        self._pub("last_cycle_cost", st["last_cycle_cost"])
        self._pub("last_action", st["last_action"], {"timestamp": la.get("ts")})
        self._pub("last_report", st["last_report"], {"markdown": rep.get("markdown"), "title": rep.get("title")})
        return st

    # -- commands (MQTT buttons / web) ---------------------------------------------------------
    def command(self, name: str) -> Any:
        if name == "pause":
            return self.pause("κουμπί Pause")
        if name == "resume":
            return self.resume()
        if name == "rollback":
            return self.rollback()
        if name == "run_report_now":
            return self.close_cycle(force=True)
        raise ValueError(name)


class Runner(threading.Thread):
    def __init__(self, opt: Optimizer, interval: float = 20.0):
        super().__init__(daemon=True, name="hp-optimizer-scheduler")
        self.opt = opt
        self.interval = interval
        self.stop_evt = threading.Event()

    def _dt(self, key: str) -> Optional[datetime]:
        v = self.opt.store.get(key)
        return datetime.fromisoformat(v) if v else None

    def tick(self) -> List[str]:
        now = self.opt.now()
        jobs = due_jobs(now, self._dt("last_heartbeat_attempt"), self._dt("last_health"),
                        self.opt.store.get("last_closed"), self.opt.opts.report_hour)
        for job in jobs:
            try:
                if job == "heartbeat":
                    self.opt.store.put("last_heartbeat_attempt", now.isoformat())
                    self.opt.heartbeat()
                elif job == "health":
                    self.opt.health()
                elif job == "report":
                    self.opt.close_cycle()
            except Exception as e:  # noqa: BLE001
                log.exception("job %s failed", job)
                self.opt.store.event("job_error", f"{job}: {type(e).__name__}: {str(e)[:300]}")
                if job == "health":
                    self.opt.store.put("last_health", now.isoformat())
                if job == "report":  # avoid hot loop; retry after 30 min
                    self.opt.store.put("report_retry_after", (now + timedelta(minutes=30)).isoformat())
        return jobs

    def run(self) -> None:
        while not self.stop_evt.is_set():
            retry = self._dt("report_retry_after")
            if retry and self.opt.now() < retry:
                # only heartbeat/health while waiting for report retry
                try:
                    now = self.opt.now()
                    if (self._dt("last_heartbeat_attempt") is None
                            or now - self._dt("last_heartbeat_attempt") >= HEARTBEAT_EVERY):
                        self.opt.store.put("last_heartbeat_attempt", now.isoformat())
                        self.opt.heartbeat()
                    if (self._dt("last_health") is None
                            or now - self._dt("last_health") >= HEALTH_EVERY):
                        self.opt.health()
                except Exception:  # noqa: BLE001
                    log.exception("heartbeat/health failed")
            else:
                self.tick()
            self.stop_evt.wait(self.interval)
