"""Thin, service-specific system-under-test wrappers.

Each adapter maps one real service's domain output into EvalPrediction —
the harness (harness.py, online/*) never imports from here and knows
nothing about any specific service, per docs/adr/0001-standalone-module.md.
"""
