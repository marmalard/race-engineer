"""Tests for the track database CRUD operations."""

import json
import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile

from core.track.models import (
    Corner,
    CornerType,
    Track,
    TrackCharacter,
    TrackType,
)
from core.track.track_db import TrackDB


@pytest.fixture
def db(tmp_path: Path) -> TrackDB:
    """Create a fresh TrackDB in a temporary directory."""
    return TrackDB(tmp_path / "test_tracks.db")


@pytest.fixture
def sample_track() -> Track:
    return Track(
        track_id="spa_2024",
        name="Circuit de Spa-Francorchamps",
        config="Grand Prix",
        length_meters=6929.0,
        track_type=TrackType.ROAD,
        character=TrackCharacter.MIXED,
        notes="Classic circuit",
    )


@pytest.fixture
def sample_corners() -> list[Corner]:
    return [
        Corner(
            corner_id=None,
            track_id="spa_2024",
            corner_number=1,
            name="La Source",
            distance_start_meters=100.0,
            distance_end_meters=300.0,
            corner_type=CornerType.HAIRPIN,
            notes="Tight hairpin after start/finish",
        ),
        Corner(
            corner_id=None,
            track_id="spa_2024",
            corner_number=2,
            name="Eau Rouge",
            distance_start_meters=500.0,
            distance_end_meters=800.0,
            corner_type=CornerType.KINK,
            notes="Flat-out uphill",
        ),
    ]


class TestTrackDBInit:
    def test_database_creates_tables(self, db: TrackDB):
        """Tables should be created on init."""
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()

        table_names = {t[0] for t in tables}
        assert "tracks" in table_names
        assert "corners" in table_names
        assert "sessions" in table_names
        assert "laps" in table_names

    def test_database_idempotent_init(self, tmp_path: Path):
        """Creating TrackDB twice on same path should not error."""
        db_path = tmp_path / "test.db"
        db1 = TrackDB(db_path)
        db2 = TrackDB(db_path)
        assert db2.list_tracks() == []


class TestTrackCRUD:
    def test_upsert_and_get_track(self, db: TrackDB, sample_track: Track):
        """Should insert and retrieve a track."""
        db.upsert_track(sample_track)
        result = db.get_track("spa_2024")
        assert result is not None
        assert result.name == "Circuit de Spa-Francorchamps"
        assert result.track_type == TrackType.ROAD
        assert result.character == TrackCharacter.MIXED
        assert result.length_meters == 6929.0

    def test_upsert_updates_existing(self, db: TrackDB, sample_track: Track):
        """Upserting with same track_id should update, not duplicate."""
        db.upsert_track(sample_track)

        updated = Track(
            track_id="spa_2024",
            name="Spa Updated",
            config="Grand Prix 2025",
            length_meters=6930.0,
            track_type=TrackType.ROAD,
            character=TrackCharacter.MOMENTUM,
        )
        db.upsert_track(updated)

        result = db.get_track("spa_2024")
        assert result.name == "Spa Updated"
        assert result.config == "Grand Prix 2025"
        assert result.character == TrackCharacter.MOMENTUM

        # Should still be only 1 track
        assert len(db.list_tracks()) == 1

    def test_get_nonexistent_track(self, db: TrackDB):
        """Getting a track that doesn't exist should return None."""
        assert db.get_track("nonexistent") is None

    def test_list_tracks_empty(self, db: TrackDB):
        """list_tracks on empty DB should return empty list."""
        assert db.list_tracks() == []

    def test_list_tracks_multiple(self, db: TrackDB, sample_track: Track):
        """list_tracks should return all tracks ordered by name."""
        db.upsert_track(sample_track)
        db.upsert_track(
            Track(
                track_id="bathurst",
                name="Mount Panorama Circuit",
                config=None,
                length_meters=6144.0,
                track_type=TrackType.ROAD,
                character=TrackCharacter.POINT_AND_SHOOT,
            )
        )

        tracks = db.list_tracks()
        assert len(tracks) == 2
        # Should be ordered by name
        assert tracks[0].name == "Circuit de Spa-Francorchamps"
        assert tracks[1].name == "Mount Panorama Circuit"

    def test_track_with_null_optional_fields(self, db: TrackDB):
        """Track with None for optional fields should store and retrieve."""
        track = Track(
            track_id="minimal",
            name="Minimal Track",
            config=None,
            length_meters=1000.0,
            track_type=TrackType.ROAD,
            character=None,
        )
        db.upsert_track(track)
        result = db.get_track("minimal")
        assert result.config is None
        assert result.character is None


class TestCornerCRUD:
    def test_upsert_and_get_corners(
        self, db: TrackDB, sample_track: Track, sample_corners: list[Corner]
    ):
        """Should store and retrieve corners for a track."""
        db.upsert_track(sample_track)
        db.upsert_corners("spa_2024", sample_corners)

        corners = db.get_corners("spa_2024")
        assert len(corners) == 2
        assert corners[0].name == "La Source"
        assert corners[0].corner_type == CornerType.HAIRPIN
        assert corners[1].name == "Eau Rouge"
        assert corners[1].corner_number == 2

    def test_upsert_corners_replaces_all(
        self, db: TrackDB, sample_track: Track, sample_corners: list[Corner]
    ):
        """Upserting corners should replace all existing corners."""
        db.upsert_track(sample_track)
        db.upsert_corners("spa_2024", sample_corners)
        assert len(db.get_corners("spa_2024")) == 2

        # Replace with a single corner
        new_corners = [
            Corner(
                corner_id=None,
                track_id="spa_2024",
                corner_number=1,
                name="New Turn 1",
                distance_start_meters=50.0,
                distance_end_meters=200.0,
                corner_type=None,
                notes=None,
            )
        ]
        db.upsert_corners("spa_2024", new_corners)

        corners = db.get_corners("spa_2024")
        assert len(corners) == 1
        assert corners[0].name == "New Turn 1"

    def test_get_corners_empty(self, db: TrackDB, sample_track: Track):
        """Track with no corners should return empty list."""
        db.upsert_track(sample_track)
        assert db.get_corners("spa_2024") == []

    def test_get_track_includes_corners(
        self, db: TrackDB, sample_track: Track, sample_corners: list[Corner]
    ):
        """get_track should include corners in the returned Track object."""
        db.upsert_track(sample_track)
        db.upsert_corners("spa_2024", sample_corners)

        track = db.get_track("spa_2024")
        assert len(track.corners) == 2
        assert track.corners[0].name == "La Source"

    def test_corners_ordered_by_number(
        self, db: TrackDB, sample_track: Track
    ):
        """Corners should be returned ordered by corner_number."""
        db.upsert_track(sample_track)
        corners = [
            Corner(None, "spa_2024", 3, "Turn 3", 700.0, 900.0, None, None),
            Corner(None, "spa_2024", 1, "Turn 1", 100.0, 300.0, None, None),
            Corner(None, "spa_2024", 2, "Turn 2", 400.0, 600.0, None, None),
        ]
        db.upsert_corners("spa_2024", corners)

        result = db.get_corners("spa_2024")
        numbers = [c.corner_number for c in result]
        assert numbers == [1, 2, 3]


class TestPopulateFromDetection:
    def test_populate_creates_corners(self, db: TrackDB, sample_track: Track):
        """populate_from_detection should create corners from segments."""
        from core.telemetry.corner_detector import CornerSegment, SegmentType

        db.upsert_track(sample_track)

        segments = [
            CornerSegment(
                segment_type=SegmentType.CORNER,
                corner_number=1,
                distance_start=100.0,
                distance_end=300.0,
                apex_distance=200.0,
                apex_speed=30.0,
                entry_speed=60.0,
                exit_speed=50.0,
                braking_distance=100.0,
                throttle_application_distance=250.0,
            ),
        ]
        db.populate_from_detection("spa_2024", segments)

        corners = db.get_corners("spa_2024")
        assert len(corners) == 1
        assert corners[0].distance_start_meters == 100.0

    def test_populate_does_not_overwrite(self, db: TrackDB, sample_track: Track):
        """populate_from_detection should not overwrite existing corners."""
        from core.telemetry.corner_detector import CornerSegment, SegmentType

        db.upsert_track(sample_track)

        # First: manual corners
        manual_corners = [
            Corner(None, "spa_2024", 1, "La Source", 100.0, 300.0, CornerType.HAIRPIN, None),
        ]
        db.upsert_corners("spa_2024", manual_corners)

        # Then: attempt to populate from detection (should be skipped)
        segments = [
            CornerSegment(
                SegmentType.CORNER, 1, 50.0, 200.0, 100.0, 20.0, 50.0, 40.0, 50.0, 180.0
            ),
            CornerSegment(
                SegmentType.CORNER, 2, 500.0, 700.0, 600.0, 25.0, 55.0, 45.0, 500.0, 680.0
            ),
        ]
        db.populate_from_detection("spa_2024", segments)

        # Should still have original manual corner
        corners = db.get_corners("spa_2024")
        assert len(corners) == 1
        assert corners[0].name == "La Source"
