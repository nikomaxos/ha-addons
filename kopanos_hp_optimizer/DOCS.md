# Kopanos HP Optimizer

Μόνιμη υπηρεσία βελτιστοποίησης της αντλίας θερμότητας (Panasonic T-CAP / HeishaMon) για όλο τον χειμώνα.

## Τι κάνει
- **KPI ανά κύκλο 24ώρου** (κλείσιμο στις `report_hour`, Europe/Athens): kWh (θέρμανση/ΖΝΧ), €, βαθμοημέρες (βάση 18 °C),
  kWh/HDD, εκκινήσεις (TOP12 + Hz), max εκκινήσεις/ώρα, διάρκειες ON/OFF, κατανομή Hz, max Hz μετά την εκκίνηση,
  COP, εγγραφές EEPROM, αποψύξεις, άνεση ±0,3 °C, ελάχιστη ροή.
- **A/B (mode `ab_test`)**: τυχαία σειρά ON/OFF ανά ζεύγος ημερών, OLS `kWh ~ HDD + ηλιοφάνεια + μπόιλερ + ON`, 90% CI.
- **Autotune (mode `autotune`)**: ανά ζώνη T_out (≥12 / 7–12 / 3–7 / <3), μία παράμετρος τη φορά, ≥3 έγκυρες μέρες ανά τιμή,
  αυστηρά κριτήρια αποδοχής, άμεσο rollback σε μη ασφαλή μέρα, μία μέρα OFF/εβδομάδα. Απαιτεί και
  `input_boolean.hp_optimizer_autotune_enabled = on` (συγκατάθεση χρήστη — το add-on μπορεί μόνο να το κλείσει).
- **Heartbeat** κάθε 5' στο `input_datetime.hp_optimizer_heartbeat` (το HA επαναφέρει defaults αν σιωπήσει >30').

## Ασφάλεια
- Το add-on **ποτέ** δεν γράφει στην αντλία. Γράφει **μόνο** στους 9 helpers του συμβολαίου (allowlist, clamp στα όρια).
- `observe` (default): μόνο μέτρηση/αναφορά/heartbeat — **καμία** άλλη εγγραφή.
- Εξωτερική αλλαγή helper (χρήστης ή watchdog του HA) ⇒ η μέρα εξαιρείται και το add-on μπαίνει σε **παύση**.
- Ingress μόνο (καμία θύρα host). Τα tokens (`remote_ha_token`, `anthropic_api_key`) είναι τύπου `password` και δεν καταγράφονται.

## Οντότητες (MQTT discovery)
`sensor.hp_opt_mode, _phase, _ab_today, _zone, _effect_pct, _kwh_per_hdd_7d, _last_cycle_kwh, _last_cycle_cost,
_last_action, _last_report` · `binary_sensor.hp_opt_online` · `button.hp_opt_pause, _rollback, _run_report_now`.

## Ειδοποιήσεις
persistent_notification + `notify_targets`. Προαιρετικό TTS σε δεύτερο HA (`remote_*`): μόνο εντός `remote_work_hours`
και όταν ισχύουν **όλες** οι `remote_conditions` (`entity=state1|state2`, `entity!=state`, `entity=on~30` = on ή αλλαγή
μέσα σε 30'). Η πρωινή αναφορά κρατιέται έως 24 ώρες μέχρι να ικανοποιηθούν οι συνθήκες.

## LLM
`llm_provider`: `brain_openai` (OpenAI-compatible endpoint του Antigravity Brain), `anthropic`, `none`.
Το LLM **μόνο διατυπώνει** την περίληψη· ο πίνακας είναι πάντα ντετερμινιστικός και κάθε κείμενο με αριθμό
που δεν υπάρχει στα δεδομένα απορρίπτεται (fallback σε template).
