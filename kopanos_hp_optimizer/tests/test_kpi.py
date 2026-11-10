from datetime import datetime, timedelta

import pytest

from optimizer.const import E, TZ
from optimizer.kpi import compressor_runs, compute_kpis, cycle_window, segments

S = datetime(2026, 11, 5, 0, 0, tzinfo=TZ)
END = S + timedelta(days=1)


def at(h, m=0):
    return S + timedelta(hours=h, minutes=m)


def base_history(**over):
    h = {
        E["heat_power"]: [(S, "1000")],
        E["dhw_power"]: [(S, "0")],
        E["heat_prod"]: [(S, "5000")],
        E["dhw_prod"]: [(S, "0")],
        E["price"]: [(S, "0.2")],
        E["t_out"]: [(S, "8")],
        E["freq"]: [(S, "0")],
        E["flow"]: [(S, "20")],
        E["valve"]: [(S, "Room")],
        E["room"]: [(S, "23.5")],
        E["target"]: [(S, "23.5")],
        E["eeprom"]: [(S, "0")],
        E["defrost"]: [(S, "off")],
        E["error"]: [(S, "No error")],
    }
    h.update(over)
    return h


def test_energy_cost_hdd_cop():
    k = compute_kpis(base_history(), S, END)
    assert k["kwh"] == pytest.approx(24.0)
    assert k["cost_eur"] == pytest.approx(4.8)
    assert k["hdd"] == pytest.approx(10.0)
    assert k["kwh_per_hdd"] == pytest.approx(2.4)
    assert k["cop"] == pytest.approx(5.0)
    assert k["power_coverage"] == 1.0


def test_price_change_and_unknown_power():
    h = base_history(**{E["price"]: [(S, "0.1"), (at(12), "0.3")],
                        E["heat_power"]: [(S, "1000"), (at(6), "unavailable"), (at(12), "1000")]})
    k = compute_kpis(h, S, END)
    assert k["kwh"] == pytest.approx(18.0)
    assert k["cost_eur"] == pytest.approx(6 * 0.1 + 12 * 0.3)
    assert k["power_coverage"] == pytest.approx(0.75)


def test_starts_runs_bins_peaks():
    freq = [(S - timedelta(minutes=30), "20"),  # running at window start: not a start
            (at(1), "0"),
            (at(2), "35"), (at(2, 10), "20"), (at(3), "0"),   # start 1, peak 35
            (at(4), "22"), (at(4, 5), "unknown"), (at(4, 8), "22"), (at(5), "0"),  # gap 3' bridged -> 1 start
            (at(6), "30"), (at(6, 20), "0"),
            (at(6, 40), "30"), (at(6, 50), "0"),
            (at(6, 55), "30"), (at(7), "0")]  # 3 starts within 60'
    k = compute_kpis(base_history(**{E["freq"]: freq}), S, END)
    assert k["starts_freq"] == 5
    assert k["max_starts_per_hour"] == 3
    assert k["max_hz_after_start_mean"] == pytest.approx((35 + 22 + 30 + 30 + 30) / 5)
    assert k["hz_bins_pct"]["20–22"] > 0
    assert sum(k["hz_bins_pct"].values()) == pytest.approx(100, abs=0.5)


def test_long_gap_breaks_run():
    freq = [(S, "0"), (at(1), "25"), (at(2), "unavailable"), (at(3), "25"), (at(4), "0")]
    runs = compressor_runs(segments(freq, S, END))
    assert len(runs) == 2
    assert runs[0][2] is True and runs[1][2] is False  # after a long gap, the restart is not counted


def test_counter_starts_preferred():
    h = base_history(**{E["ops_counter"]: [(S, "100"), (at(5), "101"), (at(9), "unknown"), (at(10), "103")]})
    k = compute_kpis(h, S, END)
    assert k["starts_counter"] == 3 and k["starts"] == 3


def test_eeprom_across_midnight_reset():
    s = datetime(2026, 11, 4, 10, 30, tzinfo=TZ)
    e = s + timedelta(days=1)
    h = base_history(**{E["eeprom"]: [(s - timedelta(hours=1), "5"), (s + timedelta(hours=2), "8"),
                                      (datetime(2026, 11, 5, 0, 0, tzinfo=TZ), "0"),
                                      (datetime(2026, 11, 5, 6, 0, tzinfo=TZ), "4")]})
    k = compute_kpis(h, s, e)
    assert k["eeprom_writes"] == 7      # 3 before midnight + 4 after
    assert k["eeprom_max_daily"] == 8


def test_comfort_flow_defrost_errors():
    h = base_history(**{
        E["room"]: [(S, "23.5"), (at(12), "unknown"), (at(18), "22.0")],
        E["room_alt"]: [(S, "23.4"), (at(12), "23.0")],
        E["freq"]: [(S, "25")],
        E["flow"]: [(S, "20"), (at(3), "9"), (at(3, 30), "20"), (at(8), "4"), (at(8, 20), "20")],
        E["valve"]: [(S, "Room"), (at(8), "Tank"), (at(8, 10), "unknown"), (at(8, 11), "Tank"), (at(8, 30), "Room")],
        E["defrost"]: [(S, "off"), (at(2), "on"), (at(2, 10), "off"), (at(5), "on"), (at(5, 6), "off")],
        E["error"]: [(S, "No error"), (at(20), "H62")],
    })
    k = compute_kpis(h, S, END)
    # 12h within (23.5 vs 23.5), 12–18 fallback 23.0 (dev -0.5), 18–24 22.0 (dev -1.5 => cold)
    assert k["comfort_within_03_pct"] == pytest.approx(50.0)
    assert k["cold_minutes"] == pytest.approx(360)
    assert k["min_flow_running"] == 4
    assert k["min_flow_running_room"] == 9      # valve 'unknown' inside Tank is forward-filled
    assert k["low_flow_minutes_room"] == pytest.approx(30)
    assert k["defrosts"] == 2 and k["defrost_minutes"] == pytest.approx(16)
    assert k["errors"] == ["H62"] and k["error_h62_h75"] is True


def test_cycle_window():
    s, e = cycle_window(datetime(2026, 11, 12, 11, 0, tzinfo=TZ), "10:30")
    assert e == datetime(2026, 11, 12, 10, 30, tzinfo=TZ) and s == e - timedelta(days=1)


# ---------------------------------------------------------------- real history replay
BASE_MAP = {
    "kwh_heishamon_total": "kwh", "kwh_heishamon_heat": "kwh_heat", "kwh_heishamon_dhw": "kwh_dhw",
    "cost_heishamon_eur": "cost_eur", "t_out_mean_c": "t_out_mean", "hdd_18": "hdd",
    "kwh_per_hdd_heishamon": "kwh_per_hdd", "compressor_starts_counter": "starts_counter",
    "avg_duration_on_min": "on_minutes_mean", "avg_duration_off_min": "off_minutes_mean",
    "pct_active_le_22hz": "low_hz_ratio_pct", "avg_max_hz_per_start": "max_hz_after_start_mean",
    "cop_heishamon": "cop", "defrost_count": "defrosts", "min_flow_comp_on_all_l_min": "min_flow_running",
    "min_flow_comp_on_room_l_min": "min_flow_running_room",
}


def test_replay_matches_baseline_analyst_within_5pct(real_history, baseline_rows):
    """Cross-check vs the independent Baseline Analyst (recorder SQLite) — ±5 %."""
    assert len(baseline_rows) == 8
    for row in baseline_rows:
        s, e = datetime.fromisoformat(row["t_start_iso"]), datetime.fromisoformat(row["t_end_iso"])
        k = compute_kpis(real_history, s, e)
        for bk, kk in BASE_MAP.items():
            bv, kv = row[bk], k[kk]
            assert kv is not None, (row["interval"], kk)
            assert abs(kv - bv) <= max(0.05 * abs(bv), 0.02), (row["interval"], kk, bv, kv)
        # freq-derived starts: within ±1 of the TOP12 counter (Baseline Analyst counts +1 at window edge)
        assert abs(k["starts_freq"] - row["compressor_starts_counter"]) <= 1
        assert abs(k["starts_freq"] - row["compressor_starts_freq"]) <= max(1, 0.05 * row["compressor_starts_freq"])
        rp = row["room_deviation_precision"]
        if rp:
            assert k["comfort_within_03_pct"] == pytest.approx(rp["pct_within_03"], abs=1.0)
        # EEPROM: baseline reports max of the daily counter
        assert k["eeprom_max_daily"] == row["max_eeprom_writes_today"]


def test_replay_starts_freq_equals_counter(real_history):
    for day in range(3, 10):
        s = datetime(2026, 11, day, tzinfo=TZ)
        k = compute_kpis(real_history, s, s + timedelta(days=1))
        assert k["starts_freq"] == k["starts_counter"]
