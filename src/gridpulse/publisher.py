"""Live publisher: simulator -> MQTT, in real time (time-compressed).

A real edge gateway would poll meters and publish each reading as it
arrives. This publisher stands in for that gateway in the Docker stack:
it generates one simulated day with simulator.generate(), then streams
it step by step to EMQX, one 15-minute step every --step-seconds seconds
(default 5, so a full simulated day streams in about 8 minutes), and
loops to the next day. Each row is published twice, once per point:

    gridpulse/<site>/<asset>/power_kw   (kW, signed for BESS/solar as in
                                         the simulator: + = discharge)
    gridpulse/<site>/<asset>/energy_kwh (kWh step = |power| * 0.25 h)

The published timestamp is the *publish* time, not the simulated
timestamp: Grafana's time axis is therefore real time, and a simulated
day appears as a compressed day curve. Energy totals per simulated day
are still correct, because every step of the day is published exactly
once per loop. Do not run this at the same time as the seed loader in
an overlapping time range (see consumer.py): dashboards sum by topic.

Usage:
    python -m gridpulse.publisher --mqtt-host localhost --dry-run
    python -m gridpulse.publisher --mqtt-host localhost --once
    python -m gridpulse.publisher --site pune-plant --step-seconds 10
--dry-run prints the first step's messages and publishes nothing, so
the message format is checkable with no broker at all.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import OrderedDict
from datetime import datetime, timezone

from .models import Reading
from .simulator import generate


def payload_for_row(site: str, row: dict, point: str, value: float,
                    unit: str, ts: datetime) -> tuple[str, str]:
    """Return (mqtt_topic, json_body) for one simulator row / point."""
    topic = f"gridpulse/{site}/{row['asset']}/{point}"
    body = json.dumps(Reading(topic, ts, value, unit,
                              quality="good", source="publisher").to_dict())
    return topic, body


def messages_for_step(site: str, rows: list[dict], ts: datetime) -> list[tuple[str, str]]:
    """All MQTT messages for one 15-minute step (power + energy per asset)."""
    messages = []
    for row in rows:
        messages.append(payload_for_row(site, row, "power_kw", row["power_kw"], "kW", ts))
        messages.append(payload_for_row(site, row, "energy_kwh", row["energy_kwh_step"], "kWh", ts))
    return messages


def stream(site: str, mqtt_host: str = "emqx", mqtt_port: int = 1883,
           step_seconds: float = 5.0, once: bool = False,
           dry_run: bool = False) -> None:
    client = None
    if not dry_run:
        import paho.mqtt.client as mqtt  # type: ignore
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.connect(mqtt_host, mqtt_port, keepalive=60)
        client.loop_start()
    day = 0
    while True:
        day += 1
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = generate(site, start, days=1)
        by_ts: "OrderedDict[datetime, list[dict]]" = OrderedDict()
        for row in rows:
            by_ts.setdefault(row["ts"], []).append(row)
        for step_ts in by_ts:
            now = datetime.now(timezone.utc)
            messages = messages_for_step(site, by_ts[step_ts], now)
            for topic, body in messages:
                if dry_run:
                    print(topic, body)
                else:
                    client.publish(topic, body, qos=1)
            if dry_run:
                print(f"dry-run: first step only ({len(messages)} messages)")
                return
            print(f"publisher: {site} step published at {now.isoformat()} "
                  f"({len(messages)} messages)")
            time.sleep(step_seconds)
        print(f"publisher: {site} day {day} complete, looping to next day")
        if once:
            break
    if client is not None:
        client.loop_stop()
        client.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="mumbai-tower")
    ap.add_argument("--mqtt-host", default="emqx")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--step-seconds", type=float, default=5.0)
    ap.add_argument("--once", action="store_true",
                    help="publish one simulated day, then exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the first step's messages, publish nothing")
    args = ap.parse_args()
    stream(args.site, args.mqtt_host, args.mqtt_port,
           args.step_seconds, args.once, args.dry_run)


if __name__ == "__main__":
    main()
