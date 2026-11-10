"""Constants: entity map, STRICT helper allowlist, zones, defaults.

The allowlist is the ONLY set of Home Assistant entities this add-on may ever write.
It is defined here, immutable, and mirrors hp_optimizer_contract.md v1 exactly (9 helpers).
The add-on NEVER writes to panasonic_heat_pump_* / HeishaMon entities.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Athens")
ADDON_SLUG = "kopanos_hp_optimizer"
VERSION = "0.2.1"
DB_PATH = "/data/optimizer.db"
OPTIONS_PATH = "/data/options.json"
INGRESS_PORT = 8010
HDD_BASE_C = 18.0

# ---------------------------------------------------------------- helper allowlist


@dataclass(frozen=True)
class HelperSpec:
    entity_id: str
    kind: str  # "bool" | "select" | "number" | "datetime" | "text"
    default: object = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    options: Tuple[str, ...] = ()
    # bool helpers the add-on may only switch OFF (consent switches owned by the user)
    off_only: bool = False


HEARTBEAT = "input_datetime.hp_optimizer_heartbeat"
ULH_ENABLED = "input_boolean.hp_ultra_low_hz_enabled"
ULH_PHASE = "input_select.hp_ultra_low_phase"
MAX_HZ = "input_number.hp_ultra_low_max_hz"
RAMP_MULT = "input_number.hp_ramp_multiplier"
STEP_INTERVAL = "input_number.hp_ramp_step_interval_min"
QUIET3 = "input_number.hp_quiet3_threshold"
PUMP_DUTY = "input_number.hp_space_heat_pump_duty"
AUTOTUNE_ENABLED = "input_boolean.hp_optimizer_autotune_enabled"
AB_TODAY = "input_text.hp_optimizer_ab_today"

PHASES = ("off", "fixes", "quiet", "ramp", "tuned")

WATCHDOG_REASON = "input_text.hp_ultra_low_watchdog_reason"
WATCHDOG_AUTOMATION = "automation.a_th_watchdog_asphaleias_ultra_low_hz_optimizer"
THERMAL_BATTERY_STATUS = "sensor.hp_thermal_battery_status"

_ALLOW = {
    ULH_ENABLED: HelperSpec(ULH_ENABLED, "bool", default=False),
    MAX_HZ: HelperSpec(MAX_HZ, "number", default=22.0, minimum=19.0, maximum=24.0, step=1.0),
    RAMP_MULT: HelperSpec(RAMP_MULT, "number", default=2.0, minimum=1.0, maximum=3.0, step=0.25),
    STEP_INTERVAL: HelperSpec(STEP_INTERVAL, "number", default=30.0, minimum=30.0, maximum=60.0, step=5.0),
    QUIET3: HelperSpec(QUIET3, "number", default=6.0, minimum=5.5, maximum=7.2, step=0.1),
    PUMP_DUTY: HelperSpec(PUMP_DUTY, "number", default=150.0, minimum=95.0, maximum=150.0, step=1.0),
    AUTOTUNE_ENABLED: HelperSpec(AUTOTUNE_ENABLED, "bool", default=False, off_only=True),
    HEARTBEAT: HelperSpec(HEARTBEAT, "datetime"),
    AB_TODAY: HelperSpec(AB_TODAY, "text", default="NA", options=("ON", "OFF", "NA")),
    ULH_PHASE: HelperSpec(ULH_PHASE, "select", default="fixes", options=PHASES),
}
ALLOWLIST: Mapping[str, HelperSpec] = MappingProxyType(_ALLOW)
assert len(ALLOWLIST) == 10, "contract defines 10 writable helpers"

TUNABLE_PARAMS = (RAMP_MULT, MAX_HZ, STEP_INTERVAL, QUIET3, PUMP_DUTY)
SAFE_DEFAULTS = MappingProxyType({MAX_HZ: 22.0, RAMP_MULT: 2.0, STEP_INTERVAL: 30.0, QUIET3: 6.0, PUMP_DUTY: 150.0})

MODES = ("observe", "campaign", "ab_test", "autotune")

# Which helpers each mode may write (heartbeat always). observe = heartbeat ONLY.
MODE_WRITABLE: Mapping[str, frozenset] = MappingProxyType({
    "observe": frozenset({HEARTBEAT}),
    "campaign": frozenset({HEARTBEAT, ULH_ENABLED, ULH_PHASE, AB_TODAY, MAX_HZ, RAMP_MULT, STEP_INTERVAL, QUIET3, PUMP_DUTY, AUTOTUNE_ENABLED}),
    "ab_test": frozenset({HEARTBEAT, ULH_ENABLED, AB_TODAY, AUTOTUNE_ENABLED}),
    "autotune": frozenset({HEARTBEAT, ULH_ENABLED, AB_TODAY, AUTOTUNE_ENABLED, *TUNABLE_PARAMS}),
})

# Read-only service calls (return_response) that are permitted.
READONLY_SERVICES = frozenset({("weather", "get_forecasts")})

# ---------------------------------------------------------------- sensors (read-only)
E = MappingProxyType({
    "heat_power": "sensor.panasonic_heat_pump_main_heat_power_consumption",   # W
    "dhw_power": "sensor.panasonic_heat_pump_main_dhw_power_consumption",     # W
    "heat_prod": "sensor.panasonic_heat_pump_main_heat_power_production",     # W
    "dhw_prod": "sensor.panasonic_heat_pump_main_dhw_power_production",       # W
    "freq": "sensor.panasonic_heat_pump_main_compressor_freq",                # Hz
    "t_out": "sensor.panasonic_heat_pump_main_outside_temp",                  # °C
    "ops_counter": "sensor.panasonic_heat_pump_main_operations_counter",      # TOP12
    "flow": "sensor.panasonic_heat_pump_main_pump_flow",                      # L/min
    "error": "sensor.panasonic_heat_pump_main_error",
    "valve": "sensor.panasonic_heat_pump_main_threeway_valve_state",          # Room/Tank
    "room": "sensor.hp_room_temp_precision",                                  # primary comfort sensor
    "room_alt": "sensor.hp_room_temp_average",                                # fallback when primary unknown
    "target": "input_number.hp_target_room_temp",
    "eeprom": "input_number.hp_eeprom_writes_today",
    "defrost": "binary_sensor.hp_defrost_active",
    "price": "input_number.electricity_price_kwh",
    "person": "",
    "outlet": "sensor.panasonic_heat_pump_main_main_outlet_temp",            # °C (watchdog frost rule)
    "t_eff": "sensor.hp_effective_outdoor_temp",                             # °C (watchdog frost rule)
    "weather": "weather.forecast_home",
})

# ---------------------------------------------------------------- zones
ZONES = ("≥12", "7–12", "3–7", "<3")


def zone_for(t_out: Optional[float]) -> Optional[str]:
    if t_out is None:
        return None
    if t_out >= 12:
        return "≥12"
    if t_out >= 7:
        return "7–12"
    if t_out >= 3:
        return "3–7"
    return "<3"
