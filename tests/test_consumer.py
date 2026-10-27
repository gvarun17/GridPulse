"""Tests for the live pipeline's pure functions, stdlib only.

No broker, no database: reading_from_payload, insert_reading (against a
recording fake cursor), and publisher message formatting are all
checkable without MQTT, Kafka, or TimescaleDB.
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gridpulse.consumer import insert_reading, reading_from_payload
from gridpulse.publisher import messages_for_step


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))


class TestConsumer(unittest.TestCase):
    def test_payload_parses_from_json_bytes(self):
        body = (b'{"topic": "gridpulse/mumbai-tower/chiller-01/power_kw", '
                b'"ts": "2026-10-20T12:00:00+00:00", "value": 380.5, '
                b'"unit": "kW", "quality": "good", "source": "publisher"}')
        r = reading_from_payload(body)
        self.assertEqual(r.topic, "gridpulse/mumbai-tower/chiller-01/power_kw")
        self.assertEqual(r.value, 380.5)
        self.assertEqual(r.unit, "kW")

    def test_malformed_payload_raises(self):
        with self.assertRaises((ValueError, KeyError)):
            reading_from_payload(b'{"topic": "x"}')

    def test_insert_uses_timescale_columns(self):
        r = reading_from_payload({
            "topic": "gridpulse/mumbai-tower/grid-01/energy_kwh",
            "ts": "2026-10-20T12:00:00+00:00", "value": 250.0,
            "unit": "kWh", "quality": "good", "source": "publisher"})
        cur = FakeCursor()
        insert_reading(cur, r)
        sql, params = cur.calls[0]
        self.assertIn("INSERT INTO readings", sql)
        self.assertEqual(params[1], "gridpulse/mumbai-tower/grid-01/energy_kwh")
        self.assertEqual(params[2], 250.0)


class TestPublisher(unittest.TestCase):
    def test_step_publishes_power_and_energy_per_asset(self):
        ts = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        rows = [{"asset": "chiller-01", "power_kw": 380.0, "energy_kwh_step": 95.0},
                {"asset": "grid-01", "power_kw": 900.0, "energy_kwh_step": 225.0}]
        msgs = messages_for_step("mumbai-tower", rows, ts)
        topics = [t for t, _ in msgs]
        self.assertEqual(len(msgs), 4)
        self.assertIn("gridpulse/mumbai-tower/chiller-01/power_kw", topics)
        self.assertIn("gridpulse/mumbai-tower/grid-01/energy_kwh", topics)


if __name__ == "__main__":
    unittest.main()
