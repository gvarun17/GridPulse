"""BMS safety plane — LOCAL, deterministic, and never overridable by the EMS.

The EMS (optimisation plane) may *request* a charge/discharge power.
The BMS (safety plane) *decides* what is actually allowed, based on:
  state of charge, cell temperature, power limits, and fault state.
If the cloud, the optimiser, or the network dies, this module must still
run on the edge gateway / battery controller and keep the battery safe.

A rejected command is not an error to retry blindly — it is the system
working. Log it, clamp it, and tell the operator why.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BessState:
    soc_pct: float          # 0-100
    temp_c: float
    fault: bool = False
    capacity_kwh: float = 400.0


@dataclass
class SafetyDecision:
    allowed_kw: float
    allowed: bool
    reason: str


def check_command(requested_kw: float, state: BessState,
                  max_kw: float = 200.0) -> SafetyDecision:
    """requested_kw: + = discharge to site, - = charge from grid/solar.
    Returns the clamped, safe power actually permitted."""
    if state.fault:
        return SafetyDecision(0.0, False, "BMS fault: all commands blocked")
    if state.temp_c > 55:
        return SafetyDecision(0.0, False, "Cell temperature > 55C: blocked")
    if requested_kw > 0 and state.soc_pct <= 10:
        return SafetyDecision(0.0, False, "SoC <= 10%: discharge blocked (reserve)")
    if requested_kw < 0 and state.soc_pct >= 90:
        return SafetyDecision(0.0, False, "SoC >= 90%: charge blocked")
    if state.temp_c > 45:
        max_kw *= 0.5  # derate in heat, a real BMS behaviour
    allowed = max(-max_kw, min(max_kw, requested_kw))
    # Never let one command cross the SoC guardrails in a single 15-min step
    # (simplified energy check: 0.25 h * power must stay within 10-90%).
    if requested_kw > 0:
        allowed = min(allowed, max(0.0, (state.soc_pct - 10) / 100 * state.capacity_kwh / 0.25))
    if requested_kw < 0:
        allowed = max(allowed, -max(0.0, (90 - state.soc_pct) / 100 * state.capacity_kwh / 0.25))
    return SafetyDecision(allowed, True,
                          "OK" if allowed == requested_kw else f"Clamped to {allowed:.1f} kW by BMS limits")
