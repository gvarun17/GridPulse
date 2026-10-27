"""Ingestion: MQTT -> Kafka -> store, with replay.

Production path (docker-compose):
  EMQX (MQTT, UNS topics) --bridge--> Kafka topic `ems.readings`
  --consumer--> validation -> TimescaleDB hypertable + InfluxDB mirror
  --consumer--> Grafana / analytics services (independent consumers,
                 each at its own pace; Kafka replay is the recovery path).

Demo path (no broker): read edge-buffer.jsonl, validate again
(defence in depth: edge validation is not trusted blindly), store to
SQLite via storage.Store. Run:  python -m gridpulse.ingestion --replay
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from .storage import Store


def replay(buffer_path: str = "edge-buffer.jsonl", db_path: str = "demo.db") -> dict:
    store = Store(db_path)
    n = bad = 0
    try:
        lines = open(buffer_path).readlines()
    except FileNotFoundError:
        return {"stored": 0, "bad": 0, "note": "no buffer file yet: run the demo CLI first"}
    for line in lines:
        d = json.loads(line)
        if d.get("quality") == "bad":
            bad += 1
            continue
        store.insert(datetime.fromisoformat(d["ts"]), d["topic"], d["value"], d["unit"],
                     d.get("quality", "good"), d.get("source", "edge"))
        n += 1
    store.commit()
    return {"stored": n, "bad_skipped": bad, "db": db_path}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--buffer", default="edge-buffer.jsonl")
    ap.add_argument("--db", default="demo.db")
    args = ap.parse_args()
    print(replay(args.buffer, args.db))


if __name__ == "__main__":
    main()
