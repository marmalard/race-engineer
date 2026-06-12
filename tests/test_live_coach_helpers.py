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


def test_session_meta_uses_directory_name_for_slug_and_display_for_message():
    """Lovely seeding needs TrackName (directory string); the message uses
    TrackDisplayName."""
    class _FakeIR:
        def __getitem__(self, key):
            assert key == "WeekendInfo"
            return {
                "TrackID": 523,
                "TrackLength": "7.00 km",
                "TrackName": "spa 2024 up",
                "TrackDisplayName": "Circuit de Spa-Francorchamps",
            }
    track_id, track_length_m, track_dir, track_display = live_coach._session_meta(_FakeIR())
    assert track_id == "523"
    assert track_length_m == 7000.0
    assert track_dir == "spa 2024 up"
    assert track_display == "Circuit de Spa-Francorchamps"
