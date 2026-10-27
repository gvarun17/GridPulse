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

## 2. Setup and execution — step by step

There are two paths. **Path A is the verified, recommended start** — it runs
on any laptop with Python only, no Docker and no `pip install`. Path B is
the full production-shaped stack, and needs Docker.

### Prerequisites

- Python 3.10+ (tested here on Python 3.12). Check with `python3 --version`.
- Git.
- For Path B only: Docker and Docker Compose (`docker compose version`).

### Step 0 — Get the code (important: use the `dev` branch)

The capstone lives on the `dev` branch — PR #1 into `main` is still open,
so cloning the default branch alone will only give you the initial README.

```bash
git clone https://github.com/gvarun17/GridPulse.git
cd GridPulse
git checkout dev
git pull
ls
# You should see: README.md, docker-compose.yml, src/, tests/, sql/, grafana/, deploy/, web/
```

If you already have the local `ems-capstone/` folder from this project,
that folder *is* this repo content — just `cd` into it instead of cloning.

### Path A — Step 1: Run the offline demo (no install)

From the repo root, run:

```bash
PYTHONPATH=src python3 -m gridpulse.cli --days 7
```

`PYTHONPATH=src` is required — it tells Python where the `gridpulse`
package lives. Without it you will get `ModuleNotFoundError: No module
named 'gridpulse'`.

### Path A — Step 2: Check the outputs

The demo writes, all under `demo-output/`:

- `report.md` — human-readable summary. Read this first.
- `report.json` — the same results in machine-readable form.
- `demo.db` — SQLite database with the grid energy steps.
- `edge-buffer.jsonl` — the edge gateway's local buffer (one JSON reading
  per line, written *before* any publish attempt).

Expected Mumbai Tower result (7 days, default site):

- Total energy: **76,521.5 kWh**
- Peak: **1,073.1 kW**, demand charge **$19,316.52** at the illustrative tariff
- Forecast peak shaved: **983.4 → 885.1 kW**
- Carbon: **54.33 tCO2e** location-based, **62.75 tCO2e** market-based

If your numbers differ slightly, that is the simulator's random variation
only if you changed the seed — with the default seed they should match.

### Path A — Step 3: Run the second site

```bash
PYTHONPATH=src python3 -m gridpulse.cli --days 7 --site pune-plant --outdir demo-output-pune
```

Expected Pune Plant result: **177,206.9 kWh**, peak **1,282.1 kW**,
peak shave **140.8 kW** on the midday furnace spike, EnPI **4.12 kWh/unit**.
Compare the two reports: same pipeline, different dominant loads, different
EnPI denominator (kWh/m² vs kWh/unit).

### Path A — Step 4: Run the tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: `Ran 11 tests … OK`. The tests cover validation, BMS safety
interlocks, analytics, carbon dual-reporting, and peak shaving — all with
the standard library only, so they need no extra install.

### Path A — Step 5: Inspect the database (optional, but worth it)

```bash
sqlite3 demo-output/demo.db "SELECT date(substr(ts,1,10)), ROUND(SUM(value),1) FROM readings GROUP BY 1;"
# If sqlite3 is not installed, use Python instead:
python3 -c "
import sqlite3
db = sqlite3.connect('demo-output/demo.db')
for row in db.execute(\"SELECT substr(ts,1,10), ROUND(SUM(value),1) FROM readings GROUP BY 1\"):
    print(row)
"
```

### Path A — Step 6: Try the fault-injection exercises

These are the point of the capstone — a demo that never fails teaches
nothing about a real EMS:

```bash
PYTHONPATH=src python3 -m gridpulse.cli --days 7 --gap
# Day 3 loses 2 hours of data. Check: is the gap a zero, or a marked gap?

PYTHONPATH=src python3 -m gridpulse.cli --days 7 --drift
# Chiller-01 over-reads by 12% from day 4. Check: does the energy balance
# (submeters vs incomer) catch it? What would you do in production?
```

### Path B — Step 1: Install the full-stack dependencies (optional)

Only needed for the FastAPI service and the Docker API container:

```bash
pip install -r requirements.txt
```

The offline demo and the tests do **not** need this step.

### Path B — Step 2: Start the full stack with Docker

From the repo root:

```bash
docker compose up -d
docker compose ps
# All services should show as running / healthy after a minute or so.
```

Then open:

- Grafana: http://localhost:3000 — user `admin`, password `gridpulse`
- EMQX dashboard: http://localhost:18083 — user `admin`, password `gridpulse`
- Node-RED: http://localhost:1880
- Prometheus: http://localhost:9090
- TimescaleDB: `localhost:5432`, user `gridpulse`, password `gridpulse`, database `gridpulse`

Grafana is provisioned with TimescaleDB and InfluxDB datasources and three
dashboards in the `GridPulse` folder (http://localhost:3000, admin /
gridpulse):

- **GridPulse EMS Overview** — total grid energy, peak load, sites
  reporting, site load (kW), daily energy by site, top assets by energy,
  and carbon location- vs market-based (illustrative 0.71 / 0.82 kg/kWh).
- **GridPulse Site Detail** — pick a site from the dropdown: total energy,
  peak, 90% peak target, meter-health gauge (% good readings), load vs
  solar vs BESS, asset load, daily energy, and gated BESS commands.
- **GridPulse Peak & Carbon** — daily peak by site, demand charge per
  site (peak x the site's tariff from the `tariffs` table), daily carbon
  by method, and a monthly peak & demand-charge table.

All dashboards query the `readings` hypertable in TimescaleDB, so they
are empty until data lands there. There are two ways to fill it — pick
one, not both in an overlapping time range, or the dashboards will
double-count (they sum by topic, regardless of source).

**Live pipeline (recommended now):** `docker compose up -d` also starts
two new services, and no seed loader is needed:

- `publisher` — streams one simulated day for Mumbai Tower to EMQX on
  UNS topics (`gridpulse/mumbai-tower/<asset>/power_kw` and
  `/energy_kwh`), one 15-minute step every 5 seconds, looping to the
  next day. Published timestamps are publish time, so a simulated day
  appears as a time-compressed day curve in Grafana's recent time range.
- `consumer` — bridges EMQX `gridpulse/#` to Kafka topic `ems.readings`,
  then consumes that topic, re-validates each reading, skips `bad`
  readings, and inserts the rest into TimescaleDB. Code: `src/gridpulse/
  consumer.py` (bridge + consumer, `--mode bridge|consume|pipeline`) and
  `src/gridpulse/publisher.py`. Delivery is at-least-once: a crash
  between insert and Kafka commit can redeliver a row, and `readings`
  has no uniqueness constraint to deduplicate on.

Check it is flowing:

```bash
docker compose ps                          # publisher + consumer up
docker compose logs -f publisher consumer  # step published / subscribed lines
docker compose logs kafka | head -20       # ems.readings topic activity
```

Then open Grafana and use a recent time range (last 1–6 hours): the
curves build up live, one step every 5 seconds. To publish the other
site instead, change the publisher command in `docker-compose.yml` to
`--site pune-plant` and restart it. To check the message format with no
broker at all: `PYTHONPATH=src python3 -m gridpulse.publisher --dry-run`.

**Seed loader (offline / historical alternative):** if you are not
running the live pipeline, seed TimescaleDB from the simulator:

```bash
pip install "psycopg[binary]"
python3 tools/seed_timescale.py --days 7
docker compose restart grafana   # picks up the new dashboards/datasource uid
```

The seed data starts 2026-10-20, so set a dashboard time range covering
that week (the default last 7 days works only while that week is recent).
Re-running the loader is safe: it replaces only its own seeded rows
(`source = 'seed-timescale'`). The Site Detail commands panel stays empty
until commands are written to the `commands` table via the full-stack path.

### Path B — Step 3: Run the API (optional)

After running the offline demo once (so `demo-output/demo.db` exists):

```bash
PYTHONPATH=src uvicorn gridpulse.api:app --reload --port 8000
curl http://localhost:8000/health
curl http://localhost:8000/sites
curl "http://localhost:8000/sites/mumbai-tower/summary"
```

Note: the API summary's total/daily figures come from the demo database.
Its `peak_kw` field reads power-kW rows, which the offline CLI stores only
as energy steps — so for peak, trust `demo-output/report.json`, not the
API's peak field, until power rows are ingested via the full stack.

### Path B — Step 4: Stop the stack

```bash
docker compose down
# Add -v only if you want to delete the Docker volumes/data as well:
# docker compose down -v
```

### Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'gridpulse'` | Run from the repo root with `PYTHONPATH=src` in front of the command. |
| `python3: command not found` / old Python | Install Python 3.10+ and use `python3`, not `python`. |
| Only an initial `# GridPulse` README after cloning | You are on `main`. Run `git checkout dev`. |
| `docker: command not found` | Path B is unavailable on that machine — use Path A, which is the verified path. |
| A Grafana panel is empty in Docker mode | Check `docker compose ps` first: if publisher + consumer are running, check their logs and use a recent time range; if they are not running, run `python3 tools/seed_timescale.py --days 7` (see the dashboards section above). Empty panels mean no data has arrived yet, not necessarily a broken dashboard. |
| Baseline R² is low in the demo report | Expected. Simulated days are near-identical, so weather/production explain almost nothing. The code reports R² and warns not to claim savings from a weak baseline — that warning is part of the lesson. |

### What to do after it runs

Work through §6 (Capstone exercises) in order: meter health, drift hunt,
peak economics, the BMS safety check, a real-meter CSV swap, a second plant
site, and production hardening (TLS, schema registry, hourly rollups).

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
grafana/          provisioned datasources + 3 dashboards (overview, site detail, peak & carbon)
tools/seed_timescale.py  seeds TimescaleDB readings so the dashboards show data
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
