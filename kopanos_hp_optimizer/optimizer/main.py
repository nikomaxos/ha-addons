"""Entry point: wires options, HA client, storage, notifier, reporter, MQTT, scheduler and web."""
from __future__ import annotations

import logging
import os
import sys

import uvicorn

from .config import load_options
from .const import DB_PATH, INGRESS_PORT, VERSION
from .ha_client import HAClient
from .mqtt_entities import MqttBridge, fetch_mqtt_service
from .notifier import Notifier, RemoteTTS
from .reporter import Reporter, make_provider
from .scheduler import Optimizer, Runner
from .storage import Store
from .web import create_app


def main() -> None:
    opts = load_options()
    logging.basicConfig(level=getattr(logging, opts.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    log = logging.getLogger("hp_optimizer")
    log.info("Kopanos HP Optimizer %s starting, options=%s", VERSION, opts.redacted())
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        log.error("SUPERVISOR_TOKEN missing")
    store = Store(os.environ.get("HPO_DB_PATH", DB_PATH))
    ha = HAClient("http://supervisor/core/api", token)
    remote = RemoteTTS(opts.remote_ha_url, opts.remote_ha_token, opts.remote_tts_entity, opts.remote_media_player,
                       opts.remote_conditions, work_hours=opts.remote_work_hours, voice=opts.remote_tts_voice,
                       language=opts.remote_tts_language)
    notifier = Notifier(ha, opts.notify_targets, remote, event_cb=store.event)
    reporter = Reporter(make_provider(opts), event_cb=store.event)
    opt = Optimizer(opts, ha, store, notifier, reporter)

    mqtt_cfg = fetch_mqtt_service(token)
    if mqtt_cfg:
        bridge = MqttBridge(mqtt_cfg, on_command=lambda name: _safe_command(opt, name, log))
        opt.mqtt = bridge
        bridge.start()
    else:
        store.event("mqtt", "MQTT service unavailable — hp_opt_* entities disabled")

    runner = Runner(opt)
    runner.start()

    try:  # uvicorn handles SIGTERM/SIGINT and returns
        uvicorn.run(create_app(opt), host="0.0.0.0", port=INGRESS_PORT, log_level="warning", access_log=False)
    finally:
        runner.stop_evt.set()
        if opt.mqtt:
            opt.mqtt.stop()


def _safe_command(opt: Optimizer, name: str, log: logging.Logger) -> None:
    try:
        opt.command(name)
        opt.publish_status()
    except Exception as e:  # noqa: BLE001
        log.exception("command %s failed", name)
        opt.store.event("command_error", f"{name}: {type(e).__name__}")


if __name__ == "__main__":
    main()
