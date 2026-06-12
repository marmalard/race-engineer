"""Tests for the pure helpers in scripts/live_coach.py."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "live_coach", Path(__file__).resolve().parent.parent / "scripts" / "live_coach.py"
)
live_coach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_coach)


def test_parse_track_length_standard():
    assert live_coach._parse_track_length_km({"TrackLength": "7.00 km"}) == 7.0


def test_parse_track_length_missing():
    assert live_coach._parse_track_length_km({}) == 0.0


def test_parse_track_length_malformed():
    assert live_coach._parse_track_length_km({"TrackLength": "garbage"}) == 0.0
