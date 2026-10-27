# GridPulse EMS — Capstone Project

A production-shaped Energy Management System, built from the tech stack in the
EMS research report: **edge gateway → MQTT / Unified Namespace → Kafka →
TimescaleDB + PostgreSQL (+ InfluxDB mirror) → Python analytics, forecasting
and optimisation → Grafana + FastAPI**, with a **separate BMS safety plane**
that always wins over EMS optimisation.

It covers **both** case scenarios from the report in one codebase, so you can
compare them directly:

| | Mumbai Tower (commercial high-rise) | Pune Plant (multi-plant pattern, 1 plant modelled) |
|---|---|---|
| Dominant loads | Chillers, AHUs, lighting, lifts | Furnace, compressors, motors, cooling |
| Key metric | kWh/m² | kWh/production unit |
| Demand charge | $18/kW-month (illustrative tariff) | $25/kW-month (illustrative tariff) |
| Forecasting driver | Weather + occupancy hours | Production plan + shift pattern |

## 1. What is real, what is simulated — read this first

**Real:** the architecture, the data model, validation rules, baseline maths,
carbon dual-reporting, peak/demand-charge maths, BMS interlocks, gated
commands, storage schema, Grafana provisioning, and the docker-compose
topology. If you replace `simulator.py` with real meter reads, the rest of
the pipeline is the same pipeline.

**Simulated (deliberately):** the meters themselves. `simulator.py` generates
15-minute profiles for both sites. This is the only fake part, and it is
labelled as such in every report output.

**Not verified / do not use for real claims:** tariff rates, emission
factors, and savings percentages in this repo are illustrative defaults.
Replace them with your utility tariff and the issuing authority's current
emission-factor edition before any real finance or ESG report.

## 2. Run it in 2 minutes (no Docker, no pip install)

```bash
cd ems-capstone
PYTHONPATH=src python3 -m gridpulse.cli --days 7
# outputs: demo-output/report.json, demo-output/report.md, demo-output/demo.db
```

Then try the fault-injection exercises — these are the point of the capstone:

```bash
PYTHONPATH=src python3 -m gridpulse.cli --days 7 --gap
# Day 3 loses 2 hours of data. Check: is the gap a zero, or a marked gap?

PYTHONPATH=src python3 -m gridpulse.cli --days 7 --drift
# Chiller-01 over-reads by 12% from day 4. Check: does the energy balance
# (submeters vs incomer) catch it? What would you do in production?
```

Run the tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 3. Stack map — every tool from the deep dive, where it lives

| Layer | Tool (production) | In this repo |
|---|---|---|
| Field protocols | Modbus TCP, BACnet/IP, OPC UA | `deploy/modbus_stub.py`, simulator profiles |
| Edge | Node-RED / Kepware / OpenEMS Edge pattern | `src/gridpulse/edge.py` (poll, buffer, normalize, gated control) |
| Transport / UNS | EMQX / HiveMQ, MQTT, Sparkplug B | `docker-compose.yml` (emqx), UNS topics in `models.py` |
| Streaming | Kafka (KRaft) + schema registry | `docker-compose.yml` (kafka), `ingestion.py` bridge description |
| Time-series storage | TimescaleDB, InfluxDB | `sql/schema.sql`, `docker-compose.yml`, `storage.py` |
| Relational storage | PostgreSQL | `sql/schema.sql`, `storage.py` (SQLite adapter in demo) |
| Analytics / M&V | Python, dbt-style metric definitions in code | `analytics.py` (EnPI, baseline OLS, M&V) |
| Forecasting | XGBoost (optional) + profile fallback | `forecasting.py` |
| Optimisation | OR-Tools MILP (optional) + greedy fallback | `optimizer.py` |
| Control / safety | BMS safety plane, OpenEMS-style cycle | `bms_safety.py`, `edge.execute_command()` |
| Apps | Grafana, FastAPI, static console | `grafana/`, `api.py`, `web/index.html` |
| Observability | Prometheus | `deploy/prometheus.yml` |
| Protocol translation | Node-RED | `docker-compose.yml` (node-red service) |

Why two fallbacks (profile forecast, greedy optimiser, SQLite store)?
Because a production system degrades gracefully. A missing XGBoost install
must never become a zero forecast, and a missing Timescale instance must
never mean no demo at all. The fallbacks are documented, not hidden.

## 4. Full stack with Docker (a machine with Docker required)

```bash
docker compose up -d
# Grafana:  http://localhost:3000  (admin / gridpulse)
# EMQX dashboard: http://localhost:18083 (admin / gridpulse)
# API: http://localhost:8000/health
# Node-RED: http://localhost:1880
# TimescaleDB: localhost:5432 (gridpulse / gridpulse)
```

Then: point the edge at EMQX (MQTT, TLS/mTLS in production — the compose
file uses plain MQTT for local teaching only, never for a real site),
bridge EMQX → Kafka topic `ems.readings`, and run the ingestion consumer
into TimescaleDB. The Grafana dashboard provisioned in `grafana/` queries
TimescaleDB for load and daily energy.

**Security note for real deployment:** enable TLS/mTLS, per-gateway
certificates, SSO, network segmentation (Purdue model, OT isolated from IT,
gateway initiates outbound only), and IEC 62443-aligned hardening. None of
that is in the local compose file on purpose — it is a teaching topology,
not a hardened deployment.

## 5. The closed loop, end to end

```
Measure (simulator / meters)
  -> Edge: validate, buffer to JSONL, publish to UNS topic
  -> Ingest: MQTT -> Kafka -> TimescaleDB (validated only for billing/M&V)
  -> Analyse: EnPI, baseline, benchmarking, anomaly flags
  -> Forecast: next-day hourly load profile
  -> Optimise: peak-shave plan (greedy / MILP)
  -> Gate: BMS safety check (SoC, temperature, fault, power limit)
  -> Act: gated command, logged with reason
  -> Verify: M&V vs weather/production-adjusted baseline, carbon report
  -> Loop: verified results become the next baseline
```

## 6. Capstone exercises (do these, in order)

1. **Meter health:** run `--gap`, then query `demo.db` for the missing
   intervals. Write the SQL that reports "% intervals validated" per site.
2. **Drift hunt:** run `--drift`, compute submeter-vs-incomer balance, and
   find which asset diverges and from which day.
3. **Peak economics:** change the demand charge in `models.py` to your local
   tariff and re-run. How much is a 150 kW shave worth per month?
4. **Safety first:** in a Python REPL, call `edge.execute_command(1000)` with
   SoC at 8%. What happens, and why is that the correct behaviour?
5. **Real meter swap:** replace one simulator asset with a CSV of real
   15-minute reads (same columns). What breaks first — validation, baseline,
   or forecasting? Fix it in the right layer, not in the dashboard.
6. **Multi-plant extension:** add a second plant site to `models.py` and
   `simulator.py` with a different product mix. Do not force a single
   kWh/unit across unlike products — that is the benchmarking trap.
7. **Production hardening:** add TLS to EMQX, a schema registry check in
   ingestion, and a continuous aggregate in `sql/schema.sql` for hourly
   rollups. Document each change in this README.

## 7. File map

```
src/gridpulse/
  models.py       UNS topics, sites, assets, tariffs, factor versions
  simulator.py    15-min profiles for both sites + gap/drift faults
  validation.py   raw -> validated, flatline/range/energy-balance checks
  bms_safety.py   safety plane: SoC/temp/fault/power interlocks
  edge.py         gateway: poll, buffer (JSONL), publish, gated commands
  ingestion.py    MQTT -> Kafka -> store, with buffer replay
  storage.py      Postgres/Timescale in prod, SQLite adapter in demo
  analytics.py    EnPI, OLS baseline, M&V, peak + demand charge
  carbon.py       Scope 2 dual reporting (location + market)
  forecasting.py  profile forecast + optional XGBoost
  optimizer.py    greedy peak shave + optional OR-Tools MILP note
  api.py          FastAPI: summary, daily, gated commands
  cli.py          offline demo: whole loop in one command
tests/            stdlib unittest: validation, safety, analytics, carbon, optimiser
sql/schema.sql    TimescaleDB hypertables + seed assets/tariffs
grafana/          provisioned datasources + EMS overview dashboard
deploy/           prometheus.yml, modbus_stub.py
web/index.html    lightweight demo console (Grafana is the ops dashboard)
```

## 8. Evaluation checklist (how to tell if your build is good)

- [ ] A 2-hour outage appears as a marked gap, not as zero consumption.
- [ ] A sensor drift is detectable from the energy balance, not just from a chart.
- [ ] An unsafe BESS command is clamped or rejected, with a reason logged.
- [ ] Savings are reported against a weather/production-adjusted baseline, with R² shown.
- [ ] Carbon is reported both location-based and market-based, with factor edition recorded.
- [ ] The system still produces a report if Kafka, XGBoost, or Timescale is unavailable (degraded, labelled mode).
- [ ] Raw interval data can be exported (CSV/Parquet) without vendor permission.
