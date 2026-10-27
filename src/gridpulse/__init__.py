"""GridPulse EMS — a production-shaped, runnable Energy Management System capstone.

Design rule, repeated everywhere in this codebase:
  safety (BMS) is local and always wins;
  optimisation (EMS) is advisory until it passes a gateway interlock.
"""
__version__ = "0.1.0"
