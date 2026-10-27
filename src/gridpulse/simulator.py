"""Site simulator: the 'field' in this capstone.

Generates realistic 15-minute load profiles for both sites, plus:
  - a solar curve (daytime bell) and a BESS state of charge,
  - a weather-driven HVAC component (hotter -> more cooling),
  - a production-driven plant component (shift pattern),
  - OPTIONAL faults for testing validation: --gap (drop 2h of data) and
    --drift (chiller-01 slowly over-reads by 12% after day 3).

This is intentionally a *model*, not a Modbus server, so the offline demo
runs with stdlib only. In docker mode, edge.py polls the same profiles
through a Modbus TCP stub (see deploy/modbus_stub.py) — same numbers,
real protocol on the wire.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from .models import SITES


def _hour_profile(hour: int, kind: str) -> float:
    """Base load fraction (0-1) by hour for a load kind."""
    if kind == "hvac":  # offices: ramps 07:00, peaks midday, off at night
        return 0.15 + 0.75 * math.exp(-((hour - 14) ** 2) / 18) if 6 <= hour <= 22 else 0.15
    if kind == "process":  # plant: 3 shifts, dip at shift change, midday furnace spike
        if hour in (13, 14):
            return 1.15
        return 0.9 if hour not in (6, 22) else 0.55
    if kind == "lighting":
        return 0.9 if 7 <= hour <= 20 else 0.25
    return 0.7


def generate(site: str, start: datetime, days: int = 7, seed: int = 42,
             gap: bool = False, drift: bool = False) -> list[dict]:
    """Return rows: {ts, site, asset, kind, power_kw, energy_kwh_step,
    temp_c, production_units}. energy step = power * 0.25 h."""
    rng = random.Random(seed)
    assets = SITES[site]
    rows: list[dict] = []
    for d in range(days):
        for step in range(96):  # 15-min steps
            ts = start + timedelta(days=d, minutes=15 * step)
            hour = ts.hour + ts.minute / 60
            temp = 28 + 6 * math.sin((hour - 9) / 24 * 2 * math.pi) + rng.uniform(-1, 1)
            for a in assets:
                base_kind = "hvac" if a.kind in ("chiller", "ahu", "cooling") else \
                    "process" if a.kind in ("furnace", "compressor", "motor") else a.kind
                frac = _hour_profile(ts.hour, base_kind)
                if a.kind == "solar":
                    power = a.rated_kw * max(0.0, math.sin((hour - 6) / 12 * math.pi)) \
                        if 6 <= hour <= 18 else 0.0
                elif a.kind == "bess":
                    # Simple demo dispatch: discharge 17:00-21:00, charge 01:00-05:00
                    power = -80 if 1 <= ts.hour < 5 else (100 if 17 <= ts.hour < 21 else 0.0)
                elif a.kind == "grid":
                    continue  # computed below as sum of loads minus solar/bess
                else:
                    heat = 1 + max(0.0, temp - 28) * 0.03 if a.kind in ("chiller", "cooling") else 1.0
                    power = a.rated_kw * frac * heat * rng.uniform(0.92, 1.08)
                    if drift and a.asset_id == "chiller-01" and d >= 3:
                        power *= 1.12
                if gap and d == 2 and 10 <= ts.hour < 12 and a.kind != "grid":
                    continue  # 2-hour communications outage on day 3
                rows.append({"ts": ts, "site": site, "asset": a.asset_id, "kind": a.kind,
                             "power_kw": round(power, 2),
                             "energy_kwh_step": round(abs(power) * 0.25, 3),
                             "temp_c": round(temp, 1),
                             "production_units": 100 if site == "pune-plant" and 6 <= ts.hour < 22 else 0})
    # Grid = sum of consuming loads - solar - bess discharge (bess power is
    # signed: + discharge reduces grid, - charge increases grid).
    by_ts: dict[datetime, float] = {}
    for r in rows:
        sign = -1 if r["kind"] == "solar" else (1 if r["kind"] == "bess" and r["power_kw"] < 0 else -1 if r["kind"] == "bess" else 1)
        by_ts[r["ts"]] = by_ts.get(r["ts"], 0.0) + sign * r["power_kw"] if r["kind"] != "bess" \
            else by_ts.get(r["ts"], 0.0) - r["power_kw"]
    # Recompute cleanly: grid = loads - solar - bess_discharge + bess_charge
    by_ts = {}
    for r in rows:
        if r["kind"] == "solar":
            by_ts[r["ts"]] = by_ts.get(r["ts"], 0.0) - r["power_kw"]
        elif r["kind"] == "bess":
            by_ts[r["ts"]] = by_ts.get(r["ts"], 0.0) - r["power_kw"]
        else:
            by_ts[r["ts"]] = by_ts.get(r["ts"], 0.0) + r["power_kw"]
    for ts, kw in sorted(by_ts.items()):
        rows.append({"ts": ts, "site": site, "asset": "grid-01", "kind": "grid",
                     "power_kw": round(max(0.0, kw), 2),
                     "energy_kwh_step": round(max(0.0, kw) * 0.25, 3),
                     "temp_c": 30.0, "production_units": 0})
    return sorted(rows, key=lambda r: (r["ts"], r["asset"]))


if __name__ == "__main__":
    rows = generate("mumbai-tower", datetime(2026, 10, 20, tzinfo=timezone.utc), days=1)
    print(f"{len(rows)} rows, first: {rows[0]}")
