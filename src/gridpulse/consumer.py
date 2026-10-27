"""Live ingestion: MQTT -> Kafka -> TimescaleDB.

This closes the gap the seed loader was filling. The pipeline has three
stages, each independently restartable, and each does exactly one job:

  1. Publisher (publisher.py, or a real edge gateway) publishes a Reading
     as JSON to EMQX on its UNS topic, e.g.
     gridpulse/mumbai-tower/chiller-01/power_kw, QoS 1.
  2. Bridge (run_bridge, in this file) subscribes to gridpulse/# on MQTT
     and republishes every message, unchanged, to Kafka topic
     `ems.readings`. Kafka is the durable event log: if the database
     consumer is down, messages wait in Kafka instead of being lost, and
     a new consumer group can replay from the start.
  3. Consumer (run_consumer, in this file) reads `ems.readings`, validates
     each reading again (defence in depth: edge validation is never
     trusted blindly), skips `bad` readings, and inserts the rest into
     the TimescaleDB `readings` hypertable. Grafana queries that table,
     so dashboards fill themselves with no seed loader.

Semantics, stated honestly: this is at-least-once delivery. MQTT QoS 1
plus a Kafka commit after insert means a crash between insert and commit
can redeliver a row, and `readings` has no primary key to deduplicate on.
That is acceptable for a demo/ops dashboard (a duplicated 15-minute step
overstates that step's energy by one step); a production store would add
a (ts, topic) uniqueness constraint or an idempotency key. Do not run
the seed loader at the same time as the live publisher: both write grid
energy rows and the dashboards sum by topic, so they would double-count
in any time range where both are present.

Broker libraries (paho-mqtt, confluent-kafka, psycopg) are imported
lazily inside the run functions, so the pure functions in this module —
reading_from_payload() and insert_reading() — are testable with stdlib
only, and importing this module never requires a broker.

Usage (from the repo root, with the Docker stack running):
    python -m gridpulse.consumer --mode pipeline \
        --mqtt-host localhost --kafka localhost:9092 \
        --dsn postgresql://gridpulse:gridpulse@localhost:5432/gridpulse
Modes: bridge | consume | pipeline (both, in two threads; this is what
the docker-compose `consumer` service runs).
"""
from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime

from .models import Reading
from .validation import Validator

MQTT_TOPIC = "gridpulse/#"
KAFKA_TOPIC = "ems.readings"


def reading_from_payload(payload) -> Reading:
    """Parse one Kafka/MQTT message body into a Reading.

    Accepts bytes, str, or an already-decoded dict. The payload format is
    Reading.to_dict(): {topic, ts (ISO 8601), value, unit, quality,
    source, schema}. Raises ValueError/KeyError on malformed input —
    callers log and skip the message, never crash the consumer on it.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        payload = json.loads(payload)
    return Reading(
        topic=payload["topic"],
        ts=datetime.fromisoformat(payload["ts"]),
        value=float(payload["value"]),
        unit=payload["unit"],
        quality=payload.get("quality", "good"),
        source=payload.get("source", "edge"),
        schema=payload.get("schema", "energy.v2"),
    )


def insert_reading(cursor, reading: Reading) -> None:
    """Insert one validated reading. `cursor` only needs execute()."""
    cursor.execute(
        "INSERT INTO readings (ts, topic, value, unit, quality, source) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (reading.ts, reading.topic, reading.value, reading.unit,
         reading.quality, reading.source),
    )


def validate_reading(reading: Reading, validators: dict) -> Reading:
    """Re-validate with a per-topic Validator, as the store consumer."""
    validator = validators.setdefault(reading.topic, Validator())
    return validator.validate(reading)


def run_bridge(mqtt_host: str = "emqx", mqtt_port: int = 1883,
               kafka_bootstrap: str = "kafka:9092") -> None:
    """MQTT gridpulse/# -> Kafka ems.readings, message body unchanged."""
    import paho.mqtt.client as mqtt  # type: ignore
    from confluent_kafka import Producer  # type: ignore

    producer = Producer({"bootstrap.servers": kafka_bootstrap})

    def on_message(_client, _userdata, msg):
        # Key by topic so all readings for one asset stay ordered in Kafka.
        producer.produce(KAFKA_TOPIC, key=msg.topic.encode(), value=msg.payload)
        producer.poll(0)

    def on_connect(client, _userdata, _flags, reason_code, _props=None):
        if reason_code == 0:
            client.subscribe(MQTT_TOPIC, qos=1)
            print(f"bridge: subscribed to {MQTT_TOPIC} on {mqtt_host}")
        else:
            print(f"bridge: MQTT connect failed: {reason_code}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(mqtt_host, mqtt_port, keepalive=60)
    try:
        client.loop_forever()
    finally:
        producer.flush(10)


def run_consumer(kafka_bootstrap: str = "kafka:9092", dsn: str = "",
                 group_id: str = "gridpulse-timescale") -> None:
    """Kafka ems.readings -> validated insert into TimescaleDB."""
    import psycopg  # type: ignore
    from confluent_kafka import Consumer  # type: ignore

    consumer = Consumer({
        "bootstrap.servers": kafka_bootstrap,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([KAFKA_TOPIC])
    validators: dict = {}
    print(f"consumer: subscribed to {KAFKA_TOPIC}, group {group_id}")
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                while True:
                    msg = consumer.poll(1.0)
                    if msg is None:
                        continue
                    if msg.error():
                        print(f"consumer: Kafka error: {msg.error()}")
                        continue
                    try:
                        reading = validate_reading(
                            reading_from_payload(msg.value()), validators)
                    except (ValueError, KeyError, TypeError) as exc:
                        print(f"consumer: skipping malformed message: {exc}")
                        consumer.commit(msg)
                        continue
                    if reading.quality == "bad":
                        print(f"consumer: skipping bad reading {reading.topic}")
                        consumer.commit(msg)
                        continue
                    insert_reading(cur, reading)
                    conn.commit()
                    consumer.commit(msg)
    finally:
        consumer.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="pipeline",
                    choices=["bridge", "consume", "pipeline"])
    ap.add_argument("--mqtt-host", default="emqx")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--kafka", default="kafka:9092")
    ap.add_argument("--dsn", default="postgresql://gridpulse:gridpulse@timescaledb:5432/gridpulse")
    ap.add_argument("--group-id", default="gridpulse-timescale")
    args = ap.parse_args()
    if args.mode == "bridge":
        run_bridge(args.mqtt_host, args.mqtt_port, args.kafka)
    elif args.mode == "consume":
        run_consumer(args.kafka, args.dsn, args.group_id)
    else:
        bridge = threading.Thread(
            target=run_bridge, args=(args.mqtt_host, args.mqtt_port, args.kafka),
            daemon=True, name="bridge")
        bridge.start()
        # Consumer runs in the main thread so Ctrl+C stops the process.
        run_consumer(args.kafka, args.dsn, args.group_id)


if __name__ == "__main__":
    main()
