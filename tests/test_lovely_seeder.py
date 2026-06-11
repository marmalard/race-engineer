"""Tests for lovely-track-data corner seeding."""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.track.lovely_seeder import (
    lovely_track_slug,
    parse_lovely_corners,
    seed_track_from_lovely,
)
from core.track.models import Track, TrackType
from core.track.track_db import TrackDB

# Real JSON shape: top-level key is "turn" (not "turns"),
# plus "name", "trackId", "country", "length", "pitentry", "pitexit", "straight".
SAMPLE_LOVELY_JSON = {
    "name": "Spa Grand Prix Pits",
    "trackId": "spa 2024 up",
    "country": "BE",
    "length": 6930,
    "pitentry": 0.971,
    "pitexit": 0.065,
    "turn": [
        {"start": 0.046, "end": 0.077, "name": "La Source"},
        {"start": 0.138, "end": 0.155, "name": "Eau Rouge"},
        {"start": 0.156, "end": 0.19,  "name": "Raidillon"},
    ],
    "straight": [
        {"start": 0.24, "marker": 0.28, "end": 0.32, "name": "Kemmel Straight"}
    ],
}


def test_slug_from_ibt_track_name():
    assert lovely_track_slug("spa 2024 up") == "spa-2024-up"
    assert lovely_track_slug("roadamerica full") == "roadamerica-full"
    assert lovely_track_slug("monza combinedchicanes") == "monza-combinedchicanes"


def test_parse_corners_converts_fractions_to_meters():
    corners = parse_lovely_corners(
        SAMPLE_LOVELY_JSON, track_id="523", track_length_m=6930.0
    )
    assert len(corners) == 3
    eau_rouge = corners[1]
    assert eau_rouge.name == "Eau Rouge"
    assert eau_rouge.distance_start_meters == pytest.approx(0.138 * 6930, abs=1.0)
    assert eau_rouge.distance_end_meters == pytest.approx(0.155 * 6930, abs=1.0)
    assert eau_rouge.track_id == "523"


def test_corners_numbered_sequentially_by_position():
    corners = parse_lovely_corners(
        SAMPLE_LOVELY_JSON, track_id="523", track_length_m=6930.0
    )
    assert [c.corner_number for c in corners] == [1, 2, 3]


def test_parse_corners_ignores_straights():
    """The "straight" list in the JSON must not produce Corner rows."""
    corners = parse_lovely_corners(
        SAMPLE_LOVELY_JSON, track_id="523", track_length_m=6930.0
    )
    names = [c.name for c in corners]
    assert "Kemmel Straight" not in names


def test_seed_track_upserts_into_db(tmp_path: Path):
    db = TrackDB(tmp_path / "tracks.db")
    db.upsert_track(
        Track(
            track_id="523",
            name="Spa",
            config="Grand Prix",
            length_meters=6930.0,
            track_type=TrackType.ROAD,
            character=None,
        )
    )
    with patch(
        "core.track.lovely_seeder._fetch_lovely_json",
        return_value=SAMPLE_LOVELY_JSON,
    ):
        count = seed_track_from_lovely(
            db, track_id="523", ibt_track_name="spa 2024 up", track_length_m=6930.0
        )
    assert count == 3
    names = [c.name for c in db.get_corners("523")]
    assert "Eau Rouge" in names


def test_seed_missing_track_returns_zero(tmp_path: Path):
    db = TrackDB(tmp_path / "tracks.db")
    with patch("core.track.lovely_seeder._fetch_lovely_json", return_value=None):
        count = seed_track_from_lovely(
            db,
            track_id="999",
            ibt_track_name="notreal track",
            track_length_m=1000.0,
        )
    assert count == 0


def test_malformed_entries_do_not_create_numbering_gaps():
    data = {
        "turn": [
            {"start": 0.01, "end": 0.02},  # malformed: no name
            {"start": 0.10, "end": 0.12, "name": "First Real"},
            {"start": 0.50, "name": "No End"},  # malformed: no end
            {"start": 0.80, "end": 0.85, "name": "Second Real"},
        ]
    }
    corners = parse_lovely_corners(data, track_id="1", track_length_m=1000.0)
    assert [c.corner_number for c in corners] == [1, 2]
    assert [c.name for c in corners] == ["First Real", "Second Real"]


def test_seed_without_track_row_returns_zero(tmp_path: Path):
    db = TrackDB(tmp_path / "tracks.db")  # no upsert_track call
    with patch("core.track.lovely_seeder._fetch_lovely_json",
               return_value=SAMPLE_LOVELY_JSON):
        count = seed_track_from_lovely(db, track_id="523",
                                       ibt_track_name="spa 2024 up",
                                       track_length_m=6930.0)
    assert count == 0
