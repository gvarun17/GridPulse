"""Optimiser: given a forecast load curve, a peak target, and a BESS,
produce a dispatch plan. Then the BMS safety module (bms_safety.py) — not
this module — decides what is actually allowed.

Level 1 (greedy, stdlib): discharge the BESS whenever forecast grid load
exceeds the peak target, charge overnight when load is low.
Level 2 (if ortools is installed): MILP that minimises demand + energy
cost subject to SoC dynamics. The greedy plan is the fallback and the
sanity check for the MILP — if MILP ever beats greedy by an implausible
margin, suspect the model, not the physics.

Output is a *plan* (list of {hour, bess_kw, reason}), never a direct
device write. edge.py turns a plan into gated commands.
"""
from __future__ import annotations


def greedy_peak_shave(forecast_kw: list[float], peak_target_kw: float,
                      bess_max_kw: float = 200.0, soc_kwh: float = 200.0) -> dict:
    plan = []
    soc = soc_kwh
    shaved_peak = max(forecast_kw) if forecast_kw else 0.0
    for h, load in enumerate(forecast_kw):
        bess_kw = 0.0
        if load > peak_target_kw and soc > 0:
            need = min(load - peak_target_kw, bess_max_kw, soc / 1.0)
            bess_kw = need
            soc -= need  # 1-hour step simplification, documented in README
        elif load < peak_target_kw * 0.6 and soc < 400:
            bess_kw = -min(bess_max_kw, 400 - soc)
            soc -= bess_kw
        plan.append({"hour": h, "forecast_kw": load, "bess_kw": round(bess_kw, 1),
                     "grid_after_kw": round(load - bess_kw, 1),
                     "soc_after_kwh": round(soc, 1),
                     "reason": "peak shave" if bess_kw > 0 else ("charge" if bess_kw < 0 else "idle")})
    if plan:
        shaved_peak = max(p["grid_after_kw"] for p in plan)
    return {"plan": plan, "original_peak_kw": round(max(forecast_kw), 1) if forecast_kw else 0,
            "shaved_peak_kw": round(shaved_peak, 1),
            "peak_reduction_kw": round((max(forecast_kw) if forecast_kw else 0) - shaved_peak, 1)}
