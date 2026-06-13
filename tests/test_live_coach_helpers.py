"""Tests for the pure helpers in scripts/live_coach.py."""

import importlib.util
from pathlib import Path

from core.track.models import Corner
from core.track.track_db import TrackDB

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


def test_load_corners_creates_track_row_then_seeds(tmp_path, monkeypatch):
    """A live session at a track not in the DB must create the row and seed
    names, so loss regions get corner names instead of bare distances."""
    db_path = tmp_path / "tracks.db"
    monkeypatch.setattr(live_coach, "DB_PATH", db_path)

    seeded = {}

    def fake_seed(db, track_id, ibt_track_name, track_length_m):
        db.upsert_corners(track_id, [Corner(
            corner_id=None, track_id=track_id, corner_number=1,
            name="Big Bend", distance_start_meters=100.0,
            distance_end_meters=200.0, corner_type=None,
        )])
        seeded["slug_input"] = ibt_track_name
        return 1

    monkeypatch.setattr(live_coach, "seed_track_from_lovely", fake_seed)

    corners = live_coach._load_corners(
        track_id="999", track_dir="oran gp", track_length_m=2600.0,
        track_display="Oran Park Grand Prix",
    )

    # The track row was created from the live session metadata...
    row = TrackDB(db_path).get_track("999")
    assert row is not None
    assert row.name == "Oran Park Grand Prix"
    # ...lovely seeding ran with the directory string (not the pretty name)...
    assert seeded["slug_input"] == "oran gp"
    # ...producing named corners rather than a distance fallback.
    assert [c.name for c in corners] == ["Big Bend"]


def test_load_corners_empty_track_id_returns_empty(monkeypatch, tmp_path):
    """No track ID -> no DB work, no crash, empty corner list."""
    monkeypatch.setattr(live_coach, "DB_PATH", tmp_path / "tracks.db")
    assert live_coach._load_corners(
        track_id="", track_dir="", track_length_m=0.0, track_display="x"
    ) == []
