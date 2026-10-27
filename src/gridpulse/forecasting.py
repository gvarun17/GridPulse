"""Forecasting: profile first, ML second.

Level 1 (always on, explainable): day-of-week x hour profile from history.
Level 2 (if xgboost is installed): gradient boosting on hour, day-of-week,
lagged load, temperature, and production flag. If xgboost is absent, the
profile forecast is returned and the caller is told so — a missing library
must never silently become a zero forecast.

Forecasts feed the optimiser; they never directly write to equipment.
"""
from __future__ import annotations

import statistics
from collections import defaultdict


def profile_forecast(history_kw: list[tuple[int, int, float]], horizon_hours: int = 24) -> list[float]:
    """history_kw: [(weekday 0-6, hour, kw)]. Returns next-24h profile by
    (weekday, hour) median. Callers pass the *next* day's weekday."""
    by_key: dict[tuple[int, int], list[float]] = defaultdict(list)
    for wd, h, kw in history_kw:
        by_key[(wd, h)].append(kw)
    medians = {k: statistics.median(v) for k, v in by_key.items()}
    overall = statistics.median([kw for _, _, kw in history_kw]) if history_kw else 0.0
    # Next day = weekday of last history day + 1 (demo simplification, documented)
    next_wd = (history_kw[-1][0] + 1) % 7 if history_kw else 0
    return [round(medians.get((next_wd, h), overall), 1) for h in range(horizon_hours)]


def xgboost_forecast(features, target):
    """Optional ML path. Returns (model_or_None, note). Kept separate so the
    core demo has zero heavy dependencies."""
    try:
        import xgboost as xgb  # type: ignore
    except ImportError:
        return None, "xgboost not installed: using profile forecast (see profile_forecast)"
    model = xgb.XGBRegressor(n_estimators=200, max_depth=5, learning_rate=0.05)
    model.fit(features, target)
    return model, "xgboost model trained"
