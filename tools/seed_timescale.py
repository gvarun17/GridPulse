"""Seed TimescaleDB with simulator data so the Grafana dashboards show
real-looking series in the Docker stack.

Why this exists: the dashboards query the `readings` hypertable, but the
full MQTT -> Kafka -> Timescale ingestion consumer is a deployment
exercise, not a running service in this repo. This loader fills that gap
for demo purposes, using the exact same simulator and topic names as the
offline demo, so dashboard queries need no changes.

Usage (TimescaleDB running via docker compose, from the repo root):
    pip install "psycopg[binary]"
    python3 tools/seed_timescale.py --days 7
    # or with an explicit DSN:
    GRIDPULSE_DSN="postgresql://gridpulse:gridpulse@localhost:5432/gridpulse" \
        python3 tools/seed_timescale.py --days 7

Behaviour: for each site, deletes prior rows with source='seed-timescale'
for that site, then inserts power_kw and energy_kwh rows for every asset
(including grid-01). Re-running is therefore idempotent for seeded data
and does not touch rows from any other source.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gridpulse.models import SITES  # noqa: E402
from gridpulse.simulator import generate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dsn", default=os.environ.get(
        "GRIDPULSE_DSN", "postgresql://gridpulse:gridpulse@localhost:5432/gridpulse"))
    args = ap.parse_args()
    try:
        import psycopg  # type: ignore
    except ImportError:
        print("psycopg is not installed. Run: pip install \"psycopg[binary]\"")
        raise SystemExit(1)
    start = datetime(2026, 10, 20, tzinfo=timezone.utc)
    total = 0
    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            for site in SITES:
                cur.execute("DELETE FROM readings WHERE source = 'seed-timescale' "
                            "AND topic LIKE %s", (f"gridpulse/{site}/%",))
                rows = []
                for r in generate(site, start, days=args.days):
                    prefix = f"gridpulse/{site}/{r['asset']}"
                    rows.append((r["ts"], f"{prefix}/power_kw", r["power_kw"], "kW", "good", "seed-timescale"))
                    rows.append((r["ts"], f"{prefix}/energy_kwh", r["energy_kwh_step"], "kWh", "good", "seed-timescale"))
                cur.executemany(
                    "INSERT INTO readings (ts, topic, value, unit, quality, source) "
                    "VALUES (%s, %s, %s, %s, %s, %s)", rows)
                total += len(rows)
                print(f"{site}: {len(rows)} rows seeded")
        conn.commit()
    print(f"Done: {total} rows. Open Grafana and set the dashboard time range to cover 2026-10-20 onwards (or use the time picker).")


if __name__ == "__main__":
    main()
