"""Storage adapter: TimescaleDB/PostgreSQL in production, SQLite in demo.

Same schema, same queries, different driver — this is the point. A capstone
that only runs on a laptop with SQLite is not 'production-shaped'; a
capstone that cannot run at all without Docker is not usable. So:
  - GRIDPULSE_DATABASE_URL set + psycopg installed -> Postgres/Timescale
  - otherwise -> local SQLite file (demo.db), with identical tables.
In Postgres, readings become a hypertable (see sql/schema.sql). In SQLite
they are a plain table with an index — the SQL in this file is kept
portable on purpose (no Postgres-only syntax in the Python path).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime


class Store:
    def __init__(self, path: str = "demo.db"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS readings (ts TEXT, topic TEXT, value REAL, "
            "unit TEXT, quality TEXT, source TEXT)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts_topic ON readings(ts, topic)")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS commands (ts TEXT, topic TEXT, requested_kw REAL, "
            "allowed_kw REAL, reason TEXT)")
        self.conn.commit()

    def insert(self, ts: datetime, topic: str, value: float, unit: str,
               quality: str = "good", source: str = "edge") -> None:
        self.conn.execute("INSERT INTO readings VALUES (?,?,?,?,?,?)",
                          (ts.isoformat(), topic, value, unit, quality, source))

    def commit(self) -> None:
        self.conn.commit()

    def daily_kwh(self, topic_prefix: str) -> list[dict]:
        """Sum of 15-min energy steps per day for topics under a prefix."""
        cur = self.conn.execute(
            "SELECT substr(ts,1,10) d, SUM(value) FROM readings "
            "WHERE topic LIKE ? AND unit='kWh' GROUP BY d ORDER BY d",
            (topic_prefix + "%",))
        return [{"date": d, "kwh": round(v, 1)} for d, v in cur.fetchall()]

    def peak_kw(self, topic: str) -> float:
        cur = self.conn.execute(
            "SELECT MAX(value) FROM readings WHERE topic=? AND unit='kW'", (topic,))
        v = cur.fetchone()[0]
        return float(v) if v is not None else 0.0

    def log_command(self, ts: datetime, topic: str, requested: float, allowed: float, reason: str) -> None:
        self.conn.execute("INSERT INTO commands VALUES (?,?,?,?,?)",
                          (ts.isoformat(), topic, requested, allowed, reason))
        self.conn.commit()
