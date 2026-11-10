# Changelog

## 0.2.0
- Autonomous Phase I campaign progression (`fixes` -> `quiet` -> `ramp` -> `tuned`) with daily 24h KPI safety checks (H62/H75, watchdog trips, minimum flow, EEPROM writes budget, comfort).
- Dynamic tuning of `input_number.hp_ramp_multiplier` upon entering `tuned` based on room start frequency and comfort.
- Autonomous seamless transition to Phase II (`autotune` / `ab_test`) upon completing the `tuned` cycle.
- Restored `input_select.hp_ultra_low_phase` to helper allowlist with dedicated `campaign` mode.

## 0.1.0
- Initial release: KPI engine, A/B experiment (OLS, 90% CI), per-zone tuner, scheduler (cycle close at report_hour,
  health 6h, heartbeat 5'), MQTT discovery (hp_opt_*), notifier (+ remote TTS interface), reporter (+ LLM wording
  with deterministic fallback), ingress dashboard, SQLite storage. Default mode: observe.
