"""Core data model. Every point in the system is a Reading with a UNS topic.

UNS topic convention (ISA-95 style):
    <enterprise>/<site>/<area>/<asset>/<point>
e.g. gridpulse/mumbai-tower/hvac/chiller-01/power_kw
     gridpulse/pune-plant/line-2/compressor-01/energy_kwh

A point name without site/asset context is a bug, not a shortcut.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class Asset:
    site: str
    area: str
    asset_id: str
    kind: str  # chiller, ahu, compressor, furnace, bess, solar, grid, lighting
    rated_kw: float
    controllable: bool = False

    @property
    def uns_prefix(self) -> str:
        return f"gridpulse/{self.site}/{self.area}/{self.asset_id}"


@dataclass
class Reading:
    topic: str
    ts: datetime
    value: float
    unit: str
    quality: str = "good"  # good | suspect | bad | missing
    source: str = "simulator"
    schema: str = "energy.v2"

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "ts": self.ts.astimezone(timezone.utc).isoformat(),
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality,
            "source": self.source,
            "schema": self.schema,
        }


# Two realistic sites, deliberately different (see README §1).
# Mumbai Tower: HVAC-dominated commercial high-rise.
# Pune Plant: process-dominated manufacturing line.
SITES: dict[str, list[Asset]] = {
    "mumbai-tower": [
        Asset("mumbai-tower", "hvac", "chiller-01", "chiller", 420, True),
        Asset("mumbai-tower", "hvac", "chiller-02", "chiller", 420, True),
        Asset("mumbai-tower", "hvac", "ahu-01", "ahu", 55, True),
        Asset("mumbai-tower", "hvac", "ahu-02", "ahu", 55, True),
        Asset("mumbai-tower", "common", "lighting-01", "lighting", 90, True),
        Asset("mumbai-tower", "common", "lifts-01", "lifts", 60, False),
        Asset("mumbai-tower", "roof", "solar-01", "solar", 120, False),
        Asset("mumbai-tower", "roof", "bess-01", "bess", 200, True),
        Asset("mumbai-tower", "incomer", "grid-01", "grid", 1500, False),
    ],
    "pune-plant": [
        Asset("pune-plant", "line-2", "furnace-01", "furnace", 650, False),
        Asset("pune-plant", "line-2", "compressor-01", "compressor", 220, True),
        Asset("pune-plant", "line-2", "compressor-02", "compressor", 220, True),
        Asset("pune-plant", "line-2", "motor-01", "motor", 150, True),
        Asset("pune-plant", "utilities", "cooling-01", "cooling", 180, True),
        Asset("pune-plant", "roof", "solar-01", "solar", 250, False),
        Asset("pune-plant", "roof", "bess-01", "bess", 400, True),
        Asset("pune-plant", "incomer", "grid-01", "grid", 2000, False),
    ],
}

# Tariffs are inputs, not constants buried in code. Edit per site/utility.
# demand_charge: $/kW-month on the billing-month 15-min peak. energy: $/kWh.
TARIFFS: dict[str, dict] = {
    "mumbai-tower": {"demand_charge_per_kw_month": 18.0, "energy_per_kwh": 0.12,
                     "peak_window": "09:00-21:00"},
    "pune-plant": {"demand_charge_per_kw_month": 25.0, "energy_per_kwh": 0.10,
                   "peak_window": "08:00-22:00"},
}

# Emission factors, VERSIONED. Never hard-code a factor into a dashboard.
# Values below are illustrative defaults for the demo; replace with the
# issuing authority's current edition (India CEA / US EPA eGRID / UK DEFRA)
# and record the edition in every report. See carbon.py.
EMISSION_FACTORS: dict[str, dict] = {
    "india-grid-2025-illustrative": {"location_kg_co2e_per_kwh": 0.71,
                                     "source": "CEA-style grid average, ILLUSTRATIVE — replace before any real report"},
    "india-residual-2025-illustrative": {"market_kg_co2e_per_kwh": 0.82,
                                         "source": "Residual mix, ILLUSTRATIVE — replace before any real report"},
}
