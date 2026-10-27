"""FastAPI application layer (production path; requires fastapi + uvicorn).

Endpoints (all read from the validated store, never from raw meters):
  GET /health
  GET /sites
  GET /sites/{site}/summary?db=demo.db   -> totals, peak, demand charge, carbon
  GET /sites/{site}/daily                -> daily kWh series for charts
  POST /sites/{site}/commands            -> gated BESS command (BMS decides)

Run:  uvicorn gridpulse.api:app --reload   (PYTHONPATH=src)
The offline demo does not need this service; Grafana + report.json cover
the demo. This API is the 'workflow app' layer for targets, actions, and
M&V reports in the full stack.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from fastapi import FastAPI  # type: ignore
except ImportError:  # pragma: no cover - demo mode has no fastapi
    FastAPI = None  # type: ignore

from gridpulse.carbon import scope2  # noqa: E402
from gridpulse.edge import EdgeGateway  # noqa: E402
from gridpulse.models import SITES, TARIFFS  # noqa: E402
from gridpulse.storage import Store  # noqa: E402

app = FastAPI(title="GridPulse EMS API") if FastAPI else None
_edges: dict[str, EdgeGateway] = {}


if app is not None:
    @app.get("/health")
    def health():
        return {"status": "ok", "service": "gridpulse-api"}

    @app.get("/sites")
    def sites():
        return {"sites": list(SITES.keys())}

    @app.get("/sites/{site}/summary")
    def summary(site: str, db: str = "demo-output/demo.db"):
        store = Store(db) if os.path.exists(db) else Store(":memory:")
        daily = store.daily_kwh(f"gridpulse/{site}/grid-01")
        total = sum(d["kwh"] for d in daily)
        peak = store.peak_kw(f"gridpulse/{site}/grid-01/power_kw")
        return {"site": site, "total_kwh": round(total, 1), "peak_kw": peak,
                "demand_charge": round(peak * TARIFFS[site]["demand_charge_per_kw_month"], 2)
                if peak else 0.0,
                "carbon": scope2(total), "daily": daily}

    @app.post("/sites/{site}/commands")
    def command(site: str, requested_kw: float):
        edge = _edges.setdefault(site, EdgeGateway(site))
        result = edge.execute_command(requested_kw)
        return {"site": site, **result,
                "note": "BMS decision, not EMS request, is authoritative."}
