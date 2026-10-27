"""Offline demo: the whole EMS loop in one command, stdlib only.

  PYTHONPATH=src python3 -m gridpulse.cli --days 7 [--gap] [--drift]

Steps: simulate 2 sites -> edge-validate + buffer -> ingest to SQLite ->
daily totals, EnPI, baseline + M&V, peak + demand charge, carbon (dual),
profile forecast, greedy peak-shave plan, gated BESS commands -> report.

Outputs: demo.db (SQLite), edge-buffer.jsonl, report.json, report.md.
No Docker, no pip install, no network needed. That is deliberate: the
demo must run on a fresh laptop, and the docker stack (below) is the
separate 'production deployment' exercise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gridpulse.analytics import degree_days, enpi, fit_baseline, mv_savings, peak_and_demand_charge  # noqa: E402
from gridpulse.carbon import scope2  # noqa: E402
from gridpulse.edge import EdgeGateway  # noqa: E402
from gridpulse.forecasting import profile_forecast  # noqa: E402
from gridpulse.models import Reading, SITES, TARIFFS  # noqa: E402
from gridpulse.optimizer import greedy_peak_shave  # noqa: E402
from gridpulse.simulator import generate  # noqa: E402
from gridpulse.storage import Store  # noqa: E402


def run(site: str, days: int, gap: bool, drift: bool, outdir: str) -> dict:
    os.makedirs(outdir, exist_ok=True)
    start = datetime(2026, 10, 20, tzinfo=timezone.utc)
    rows = generate(site, start, days=days, gap=gap, drift=drift)
    edge = EdgeGateway(site, buffer_path=os.path.join(outdir, "edge-buffer.jsonl"))
    if os.path.exists(edge.buffer_path):
        os.remove(edge.buffer_path)
    store = Store(os.path.join(outdir, "demo.db"))
    grid_kw, grid_kwh_steps = [], []
    for r in rows:
        topic = f"gridpulse/{site}/{r['asset']}/power_kw" if r["kind"] != "grid" else f"gridpulse/{site}/grid-01/power_kw"
        edge.process(Reading(topic, r["ts"], r["power_kw"], "kW"))
        if r["asset"] == "grid-01":
            grid_kw.append(r["power_kw"])
            grid_kwh_steps.append(r["energy_kwh_step"])
    # Store validated energy steps for the grid meter (demo simplification:
    # in production, ingestion.py does this from the buffer for all points).
    for r in rows:
        if r["asset"] == "grid-01":
            store.insert(r["ts"], f"gridpulse/{site}/grid-01/energy_kwh", r["energy_kwh_step"], "kWh")
    store.commit()
    total_kwh = sum(grid_kwh_steps)
    # Daily baseline inputs: kwh + CDD from mean temp + production proxy
    daily_map: dict[str, dict] = {}
    seen_ts: set = set()
    for r in rows:
        if r["asset"] == "grid-01":
            d = r["ts"].date().isoformat()
            daily_map.setdefault(d, {"kwh": 0.0, "cdd": 0.0, "production": 0.0, "n": 0})
            daily_map[d]["kwh"] += r["energy_kwh_step"]
        # Temperature and production are per-timestamp values, not per
        # asset: count them once. (Grid rows carry a placeholder temp.)
        if r["ts"] not in seen_ts and r["asset"] != "grid-01":
            seen_ts.add(r["ts"])
            d = r["ts"].date().isoformat()
            daily_map.setdefault(d, {"kwh": 0.0, "cdd": 0.0, "production": 0.0, "n": 0})
            daily_map[d]["cdd"] += degree_days(r["temp_c"])[0] / 96
            daily_map[d]["production"] += r["production_units"]
    daily = [{"kwh": round(v["kwh"], 1), "cdd": round(v["cdd"], 2),
              "production": v["production"]} for v in daily_map.values()]
    baseline = fit_baseline(daily[:-1]) if len(daily) > 5 else {"error": "not enough days"}
    last = daily[-1] if daily else {"kwh": 0, "cdd": 0, "production": 0}
    mv = mv_savings(baseline, last["kwh"], last["cdd"], last["production"]) if "error" not in baseline else baseline
    tariff = TARIFFS[site]
    peak = peak_and_demand_charge(grid_kw, tariff["demand_charge_per_kw_month"])
    # Forecast: hourly grid profile from history, then shave to 90% of peak
    hist = [(r["ts"].weekday(), r["ts"].hour, r["power_kw"]) for r in rows if r["asset"] == "grid-01"]
    forecast = profile_forecast(hist)
    # Shave to 90% of the *forecast* peak: the plan must be computable
    # before the day happens, from the forecast, not from hindsight.
    plan = greedy_peak_shave(forecast, max(forecast) * 0.9 if forecast else 0)
    # Gated BESS commands for the first 4 shaving hours
    commands = []
    for p in plan["plan"][:4]:
        if p["bess_kw"] > 0:
            c = edge.execute_command(p["bess_kw"])
            commands.append({**p, **c})
            store.log_command(start, f"gridpulse/{site}/bess-01/cmd", c["requested_kw"], c["allowed_kw"], c["reason"])
    result = {
        "site": site, "days": days, "total_kwh": round(total_kwh, 1),
        "enpi_building_kwh_per_m2": enpi(total_kwh, 30000, "kWh/m2") if site == "mumbai-tower" else None,
        "enpi_plant_kwh_per_unit": enpi(total_kwh, sum(d["production"] for d in daily), "kWh/unit") if site == "pune-plant" else None,
        "peak": peak, "baseline": baseline, "mv_last_day": mv,
        "carbon": scope2(total_kwh),
        "forecast_next_day_kw": forecast,
        "peak_shave_plan": {"original_peak_kw": plan["original_peak_kw"],
                            "shaved_peak_kw": plan["shaved_peak_kw"],
                            "peak_reduction_kw": plan["peak_reduction_kw"]},
        "gated_bess_commands_sample": commands,
        "faults_injected": {"gap": gap, "drift": drift},
        "note": "Demo numbers are simulated. Replace simulator with real meters before any real claim.",
    }
    with open(os.path.join(outdir, "report.json"), "w") as f:
        json.dump(result, f, indent=2)
    with open(os.path.join(outdir, "report.md"), "w") as f:
        f.write(f"# GridPulse demo report — {site}\n\n")
        f.write(f"Total energy ({days} days): **{result['total_kwh']} kWh**\n\n")
        f.write(f"Peak: **{peak['peak_kw']} kW** — demand charge at tariff: **${peak['demand_charge']}**\n\n")
        f.write(f"Peak-shave plan: {plan['original_peak_kw']} -> {plan['shaved_peak_kw']} kW "
                f"({plan['peak_reduction_kw']} kW reduction)\n\n")
        f.write(f"Carbon (location-based): **{result['carbon']['location_based_tco2e']} tCO2e**; "
                f"market-based: **{result['carbon']['market_based_tco2e']} tCO2e**\n\n")
        f.write(f"Baseline: {baseline}\n\nM&V last day: {mv}\n")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--gap", action="store_true", help="inject a 2h comms gap on day 3")
    ap.add_argument("--drift", action="store_true", help="inject chiller-01 sensor drift from day 4")
    ap.add_argument("--site", default="mumbai-tower", choices=list(SITES))
    ap.add_argument("--outdir", default="demo-output")
    args = ap.parse_args()
    result = run(args.site, args.days, args.gap, args.drift, args.outdir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
