"""Carbon accounting: GHG Protocol Scope 2, dual reporting.

Location-based = average grid intensity where consumption occurs.
Market-based   = contractual instruments (RECs / PPAs / supplier factor);
                 falls back to the residual mix where no instrument is held.
Both must be reported in parallel. Reporting only market-based lets a site
claim 'zero' on paper while its physical grid draw is unchanged.

Scope 1 in this capstone is gas/diesel where present; the demo sites are
electricity-dominated, so Scope 1 is modelled as a small explicit input,
not invented from electricity data.
"""
from __future__ import annotations

from .models import EMISSION_FACTORS


def scope2(kwh: float, location_factor: float = 0.71,
           market_factor: float | None = None, renewable_kwh: float = 0.0) -> dict:
    """market_factor=None means no contractual instrument: use residual mix.
    renewable_kwh covered by retired RECs is counted at 0 in market-based."""
    loc = kwh * location_factor
    if market_factor is None:
        market_factor = EMISSION_FACTORS["india-residual-2025-illustrative"]["market_kg_co2e_per_kwh"]
    market = (kwh - renewable_kwh) * market_factor
    return {
        "kwh": kwh,
        "location_based_tco2e": round(loc / 1000, 3),
        "market_based_tco2e": round(market / 1000, 3),
        "location_factor_kg_per_kwh": location_factor,
        "market_factor_kg_per_kwh": market_factor,
        "renewable_kwh_with_recs": renewable_kwh,
        "factor_note": "ILLUSTRATIVE factors — replace with the issuing authority's "
                       "current edition and record it before any real ESG report.",
    }
