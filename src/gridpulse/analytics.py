"""Analytics: EnPI, baseline, benchmarking, M&V — the ISO 50001 evidence layer.

Definitions (kept in code, not in a dashboard, so they are versioned):
  EnPI (building) = total kWh / floor area (m2) over the period.
  EnPI (plant)    = total kWh / production units over the period.
  Baseline        = ordinary-least-squares regression of daily kWh on
                    heating/cooling degree days + production (plant).
                    In production this is a dbt/SQL model; here it is the
                    same maths, readable in one file.
  M&V savings     = baseline-predicted kWh (adjusted for actual weather /
                    production) - actual kWh. Never: last-year kWh - this-year
                    kWh without adjustment — that conflates weather and
                    production changes with efficiency.
"""
from __future__ import annotations

import statistics
from datetime import date


def enpi(total_kwh: float, denominator: float, label: str) -> dict:
    if denominator == 0:
        return {"enpi": None, "unit": label, "note": "denominator is zero: EnPI undefined, not zero"}
    return {"enpi": round(total_kwh / denominator, 4), "unit": label}


def degree_days(temp_c: float, base: float = 24.0) -> tuple[float, float]:
    """Cooling degree days (CDD) / heating degree days (HDD) for one reading."""
    return (max(0.0, temp_c - base), max(0.0, base - temp_c))


def fit_baseline(daily: list[dict]) -> dict:
    """daily: [{kwh, cdd, production}]. Fits kwh ~ a + b*cdd + c*production
    by normal equations (stdlib only). Constant predictors (e.g. production
    = 0 for a building, which would be collinear with the intercept) are
    dropped and reported, instead of failing with a singular matrix.
    Returns coefficients and R-squared so baseline quality is visible."""
    n = len(daily)
    if n < 5:
        return {"error": "need >= 5 days to fit a baseline"}
    predictors = ["cdd", "production"]
    active = [p for p in predictors
              if len({d.get(p, 0.0) for d in daily}) > 1]
    dropped = [p for p in predictors if p not in active]
    m = 1 + len(active)
    X = [[1.0] + [d.get(p, 0.0) for p in active] for d in daily]
    y = [d["kwh"] for d in daily]
    XtX = [[sum(X[k][i] * X[k][j] for k in range(n)) for j in range(m)] for i in range(m)]
    XtY = [sum(X[k][i] * y[k] for k in range(n)) for i in range(m)]
    A = [row[:] + [XtY[i]] for i, row in enumerate(XtX)]
    for col in range(m):
        piv = max(range(col, m), key=lambda r: abs(A[r][col]))
        A[col], A[piv] = A[piv], A[col]
        if abs(A[col][col]) < 1e-12:
            return {"error": "singular baseline matrix (collinear inputs?)"}
        for r in range(m):
            if r != col:
                f = A[r][col] / A[col][col]
                for c in range(col, m + 1):
                    A[r][c] -= f * A[col][c]
    coef = [A[i][m] / A[i][i] for i in range(m)]
    by_name = dict(zip(active, coef[1:]))
    pred = [coef[0] + sum(by_name[p] * d.get(p, 0.0) for p in active) for d in daily]
    mean_y = statistics.mean(y)
    ss_tot = sum((v - mean_y) ** 2 for v in y)
    ss_res = sum((y[i] - pred[i]) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return {"intercept_kwh": round(coef[0], 2),
            "per_cdd_kwh": round(by_name.get("cdd", 0.0), 2),
            "per_production_unit_kwh": round(by_name.get("production", 0.0), 4),
            "r_squared": round(r2, 3), "n_days": n, "dropped_constant_predictors": dropped,
            "note": "R2 < 0.7 means the baseline does not explain the site well — do not claim savings from it."}


def mv_savings(baseline: dict, actual_kwh: float, cdd: float, production: float) -> dict:
    if "error" in baseline:
        return baseline
    predicted = baseline["intercept_kwh"] + baseline["per_cdd_kwh"] * cdd \
        + baseline["per_production_unit_kwh"] * production
    return {"predicted_kwh": round(predicted, 1), "actual_kwh": round(actual_kwh, 1),
            "savings_kwh": round(predicted - actual_kwh, 1),
            "savings_pct": round((predicted - actual_kwh) / predicted * 100, 2) if predicted else None}


def peak_and_demand_charge(grid_kw_series: list[float], demand_rate: float) -> dict:
    """15-min peak -> monthly demand charge. This is why peak shaving pays:
    one 15-minute spike can set the charge for the whole month."""
    peak = max(grid_kw_series) if grid_kw_series else 0.0
    return {"peak_kw": round(peak, 1), "demand_charge": round(peak * demand_rate, 2),
            "currency_note": "demand_rate is $/kW-month from the site tariff (models.py)"}
