"""Unit tests, stdlib only:  PYTHONPATH=src python3 -m unittest discover -s tests -v"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gridpulse.analytics import enpi, fit_baseline, mv_savings, peak_and_demand_charge
from gridpulse.bms_safety import BessState, check_command
from gridpulse.carbon import scope2
from gridpulse.edge import EdgeGateway
from gridpulse.models import Reading
from gridpulse.optimizer import greedy_peak_shave
from gridpulse.validation import Validator, energy_balance_check


def R(value, unit="kW"):
    return Reading("gridpulse/test/x/power_kw", datetime(2026, 10, 20, tzinfo=timezone.utc), value, unit)


class TestValidation(unittest.TestCase):
    def test_negative_power_is_bad(self):
        self.assertEqual(Validator().validate(R(-5)).quality, "bad")

    def test_flatline_is_suspect(self):
        v = Validator(flatline_limit=3)
        for _ in range(3):
            out = v.validate(R(100))
        self.assertEqual(out.quality, "suspect")

    def test_energy_balance(self):
        r = energy_balance_check({"a": 90, "b": 10}, 100)
        self.assertTrue(r["within_tolerance"])


class TestSafety(unittest.TestCase):
    def test_low_soc_blocks_discharge(self):
        d = check_command(100, BessState(soc_pct=5, temp_c=30))
        self.assertEqual(d.allowed_kw, 0.0)

    def test_fault_blocks_all(self):
        d = check_command(-100, BessState(soc_pct=50, temp_c=30, fault=True))
        self.assertFalse(d.allowed)

    def test_edge_command_is_gated(self):
        e = EdgeGateway("test", buffer_path="/tmp/gp-test-buffer.jsonl")
        out = e.execute_command(500)  # above max: must be clamped, not passed through
        self.assertLessEqual(out["allowed_kw"], 200)


class TestAnalyticsCarbonOptimizer(unittest.TestCase):
    def test_enpi_zero_denominator_is_not_zero(self):
        self.assertIsNone(enpi(100, 0, "kWh/unit")["enpi"])

    def test_baseline_and_mv(self):
        daily = [{"kwh": 1000 + i * 10, "cdd": 5 + (i % 3) * 1.7, "production": 100 + i * i} for i in range(10)]
        b = fit_baseline(daily)
        self.assertIn("r_squared", b)
        mv = mv_savings(b, 900, 5.0, 100)
        self.assertIn("savings_kwh", mv)

    def test_peak_charge(self):
        p = peak_and_demand_charge([100, 500, 200], 20)
        self.assertEqual(p["peak_kw"], 500)
        self.assertEqual(p["demand_charge"], 10000)

    def test_carbon_dual_reporting(self):
        c = scope2(1000)
        self.assertIn("location_based_tco2e", c)
        self.assertIn("market_based_tco2e", c)

    def test_peak_shave_reduces_peak(self):
        plan = greedy_peak_shave([100, 300, 100], 200, bess_max_kw=200, soc_kwh=200)
        self.assertLessEqual(plan["shaved_peak_kw"], 300)
        self.assertGreaterEqual(plan["peak_reduction_kw"], 0)


if __name__ == "__main__":
    unittest.main()
