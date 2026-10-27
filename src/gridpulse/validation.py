"""Validation: raw -> validated. This is the trust boundary of the whole EMS.

Rules (in order):
  1. Missing is honest, zero is a claim. Never turn a gap into 0 kWh.
  2. Energy (kWh) must never decrease between successive cumulative reads,
     except after a documented meter reset.
  3. Power (kW) must be within [0, rated_kw * 1.2] for a known asset.
  4. A flatline (identical value for >= N consecutive reads on a varying
     load) is suspect, not good.
  5. Suspect data is quarantined for billing/M&V, but may still feed live
     dashboards labelled as best-effort.

validate() returns a new Reading with quality set; it never mutates history
silently. Callers that need an audit trail should store both raw and
validated rows (see storage.py).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .models import Reading


@dataclass
class Validator:
    rated_kw: float = 10000.0
    flatline_limit: int = 12  # consecutive identical reads -> suspect
    _history: deque = field(default_factory=lambda: deque(maxlen=64))
    _last_cumulative: float | None = None

    def validate(self, r: Reading) -> Reading:
        quality = "good"
        if r.value is None:
            quality = "missing"
        elif r.unit == "kW" and not (0 <= r.value <= self.rated_kw * 1.2):
            quality = "bad"
        elif r.unit == "kWh" and self._last_cumulative is not None \
                and r.value < self._last_cumulative - 1e-9:
            quality = "suspect"  # possible reset or wiring error: investigate, don't auto-fix
        # Flatline check on the raw value stream.
        self._history.append(r.value)
        if len(self._history) >= self.flatline_limit and \
                len(set(self._history)) == 1 and r.unit == "kW" and r.value != 0:
            quality = "suspect"
        if r.unit == "kWh":
            self._last_cumulative = r.value
        return Reading(topic=r.topic, ts=r.ts, value=r.value, unit=r.unit,
                       quality=quality, source=r.source, schema=r.schema)


def energy_balance_check(submeter_kwh: dict[str, float], incomer_kwh: float,
                         tolerance_pct: float = 5.0) -> dict:
    """Sum of submeters should approximate the incomer. A large gap means
    an unmetered load, a wrong CT ratio, or a broken meter — all common,
    all worth an alert, none worth silently adjusting away."""
    total = sum(submeter_kwh.values())
    gap_pct = 0.0 if incomer_kwh == 0 else abs(total - incomer_kwh) / incomer_kwh * 100
    return {"submeter_total_kwh": total, "incomer_kwh": incomer_kwh,
            "gap_pct": round(gap_pct, 2),
            "within_tolerance": gap_pct <= tolerance_pct}
