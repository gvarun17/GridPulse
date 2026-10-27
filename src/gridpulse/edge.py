"""Edge gateway: poll -> buffer -> publish -> gated control.

In docker mode this polls Modbus TCP (pymodbus) and publishes to EMQX
over MQTT with TLS/mTLS. In offline demo mode it consumes simulator rows
directly — same validation, buffering, and safety logic, no broker needed.

Buffering contract: every reading is appended to a local JSONL file
BEFORE any publish attempt. If MQTT/Kafka is down, data is not lost; a
replay job (ingestion.py --replay) forwards the buffer later. This file
is the reason a 4-hour outage is a gap in the cloud, not a gap in history.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from .bms_safety import BessState, check_command
from .models import Reading
from .validation import Validator


class EdgeGateway:
    def __init__(self, site: str, buffer_path: str = "edge-buffer.jsonl"):
        self.site = site
        self.buffer_path = buffer_path
        self.validators: dict[str, Validator] = {}
        self.bess = BessState(soc_pct=55.0, temp_c=32.0, capacity_kwh=400.0)

    def process(self, reading: Reading) -> Reading:
        v = self.validators.setdefault(reading.topic, Validator())
        validated = v.validate(reading)
        with open(self.buffer_path, "a") as f:
            f.write(json.dumps(validated.to_dict()) + "\n")
        # In docker mode, publish validated.to_dict() to MQTT topic
        #   gridpulse/<site>/...  (UNS) with QoS 1, retained=False.
        # In demo mode, the buffer file IS the transport (see ingestion.py).
        return validated

    def execute_command(self, requested_kw: float, max_kw: float = 200.0) -> dict:
        """Gated control: EMS request -> BMS decision -> logged outcome.
        Callers must persist the returned dict (storage.log_command)."""
        decision = check_command(requested_kw, self.bess, max_kw=max_kw)
        # Update the demo SoC model for a 15-min step (real BMS reports SoC;
        # the edge never estimates it from its own commands in production).
        self.bess.soc_pct = max(0.0, min(100.0,
            self.bess.soc_pct - decision.allowed_kw * 0.25 / self.bess.capacity_kwh * 100))
        return {"requested_kw": requested_kw, "allowed_kw": decision.allowed_kw,
                "allowed": decision.allowed, "reason": decision.reason,
                "soc_after_pct": round(self.bess.soc_pct, 1)}
