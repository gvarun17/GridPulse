-- GridPulse production schema (TimescaleDB / PostgreSQL).
-- Run automatically on first timescaledb start via docker-compose.
-- The Python demo uses the same table shapes in SQLite (storage.py);
-- this file adds hypertables, compression, and retention for production.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS readings (
  ts TIMESTAMPTZ NOT NULL,
  topic TEXT NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  unit TEXT NOT NULL,
  quality TEXT NOT NULL DEFAULT 'good',
  source TEXT
);
SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_readings_topic_ts ON readings (topic, ts DESC);

CREATE TABLE IF NOT EXISTS assets (
  site TEXT, area TEXT, asset_id TEXT, kind TEXT, rated_kw DOUBLE PRECISION,
  PRIMARY KEY (site, asset_id)
);
CREATE TABLE IF NOT EXISTS tariffs (
  site TEXT PRIMARY KEY, demand_charge_per_kw_month DOUBLE PRECISION,
  energy_per_kwh DOUBLE PRECISION, peak_window TEXT
);
CREATE TABLE IF NOT EXISTS emission_factors (
  factor_id TEXT PRIMARY KEY, location_kg_per_kwh DOUBLE PRECISION,
  market_kg_per_kwh DOUBLE PRECISION, source TEXT, edition TEXT
);
CREATE TABLE IF NOT EXISTS commands (
  ts TIMESTAMPTZ NOT NULL, topic TEXT, requested_kw DOUBLE PRECISION,
  allowed_kw DOUBLE PRECISION, reason TEXT
);
-- Retention: raw 90 days, then downsampled aggregates are the long-term record.
-- (Continuous aggregates are created by the platform team in production;
--  the demo keeps raw rows in SQLite so students can inspect them.)
INSERT INTO assets VALUES
  ('mumbai-tower','hvac','chiller-01','chiller',420),
  ('mumbai-tower','hvac','chiller-02','chiller',420),
  ('pune-plant','line-2','compressor-01','compressor',220),
  ('pune-plant','line-2','furnace-01','furnace',650)
ON CONFLICT DO NOTHING;
INSERT INTO tariffs VALUES
  ('mumbai-tower', 18.0, 0.12, '09:00-21:00'),
  ('pune-plant', 25.0, 0.10, '08:00-22:00')
ON CONFLICT DO NOTHING;
