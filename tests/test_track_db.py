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


def test_record_session_and_processed_paths(tmp_path):
    db = TrackDB(tmp_path / "t.db")
    db.record_session(
        session_id="bmwm2g87_spa 2026-07-05 16-32-53",
        track_id="525", car="BMW M2 Racing (G87)", session_type="Practice",
        session_date="2026-07-05T16:32:53", best_lap_time=161.384,
        lap_count=16, ibt_file_path="C:/tel/bmwm2g87_spa.ibt",
    )
    assert db.processed_ibt_paths() == {"C:/tel/bmwm2g87_spa.ibt"}


def test_record_session_is_idempotent(tmp_path):
    db = TrackDB(tmp_path / "t.db")
    for best in (161.384, 160.9):  # rerun with updated data replaces
        db.record_session(
            session_id="s1", track_id="525", car="M2", session_type="Practice",
            session_date="2026-07-05T16:32:53", best_lap_time=best,
            lap_count=16, ibt_file_path="C:/tel/a.ibt",
        )
    assert db.processed_ibt_paths() == {"C:/tel/a.ibt"}  # one row, not two


def test_record_laps_replaces_on_rerun(tmp_path):
    db = TrackDB(tmp_path / "t.db")
    db.record_session(
        session_id="s1", track_id="525", car="M2", session_type="Practice",
        session_date="d", best_lap_time=100.0, lap_count=2,
        ibt_file_path="p",
    )
    db.record_laps("s1", [(1, 101.0, True), (2, 100.0, True)])
    db.record_laps("s1", [(1, 101.0, True), (2, 100.0, True), (3, 99.5, True)])
    conn = db._get_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM laps WHERE session_id = 's1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 3  # replaced, not appended to 5


def test_processed_paths_empty_on_fresh_db(tmp_path):
    assert TrackDB(tmp_path / "t.db").processed_ibt_paths() == set()


def test_list_session_history_and_laps_roundtrip(tmp_path):
    from core.track.track_db import LapRow, SessionRow, TrackDB

    db = TrackDB(tmp_path / "t.db")
    db.record_session(
        session_id="s1", track_id="525", car="M2",
        session_type="practice", session_date="2026-07-01 10-00-00",
        best_lap_time=100.5, lap_count=3, ibt_file_path="x.ibt",
    )
    db.record_laps("s1", [(1, 101.0, True), (2, 100.5, True), (3, 130.0, False)])
    db.record_session(
        session_id="s2", track_id="525", car="M2",
        session_type="Race", session_date="2026-07-02 10-00-00",
        best_lap_time=99.9, lap_count=1, ibt_file_path="y.ibt",
    )

    sessions = db.list_session_history()
    assert [s.session_id for s in sessions] == ["s1", "s2"]  # date order
    s1 = sessions[0]
    assert isinstance(s1, SessionRow)
    assert (s1.track_id, s1.car, s1.session_type) == ("525", "M2", "practice")
    assert s1.best_lap_time == 100.5 and s1.lap_count == 3
    assert s1.session_date == "2026-07-01 10-00-00"

    laps = db.get_session_laps("s1")
    assert [(l.lap_number, l.lap_time, l.is_valid) for l in laps] == [
        (1, 101.0, True), (2, 100.5, True), (3, 130.0, False),
    ]
    assert isinstance(laps[0], LapRow)
    assert db.get_session_laps("nope") == []


# ---------------------------------------------------------------------------
# Region diagnoses
# ---------------------------------------------------------------------------

from core.coaching.debrief import RegionDiagnosis
from core.telemetry.loss_regions import LossRegion
from core.track.track_db import DiagnosisContext, DiagnosisRow


def _diag(label="Eau Rouge", time_lost=1.2, braking=-12.0, release=None):
    """A RegionDiagnosis as build_debrief produces it (absolutes default None)."""
    return RegionDiagnosis(
        region=LossRegion(distance_start=100.0, distance_end=250.0,
                          time_lost=time_lost),
        label=label,
        braking_delta_m=braking,
        min_speed_delta_ms=-2.5,
        throttle_delta_m=15.0,
        driver_min_speed_ms=30.0,
        reference_min_speed_ms=32.5,
        brake_release_delta_m=release,
        exit_speed_delta_ms=-1.0,
    )


def _ctx():
    return DiagnosisContext(
        driver_lap_number=3,
        driver_lap_time=150.5,
        reference_source="personal_best",
        reference_lap_time=148.2,
        total_time_delta_s=2.3,
    )


def _record_session(db, session_id="sess1", track_id="523",
                    session_type="practice", date="2026-07-01 10-00-00"):
    db.record_session(
        session_id=session_id, track_id=track_id, car="BMW M2",
        session_type=session_type, session_date=date,
        best_lap_time=150.5, lap_count=8, ibt_file_path=f"C:/t/{session_id}.ibt",
    )


class TestRegionDiagnoses:
    def test_round_trip_all_fields(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db)
        db.record_region_diagnoses(
            "sess1", _ctx(), [_diag(), _diag(label="Pouhon", time_lost=0.4,
                                          braking=None, release=-8.0)],
        )
        rows = db.list_region_diagnoses()
        assert len(rows) == 2
        r = rows[0]
        assert isinstance(r, DiagnosisRow)
        assert r.session_id == "sess1"
        assert r.region_rank == 1
        assert r.label == "Eau Rouge"
        assert r.distance_start_m == 100.0
        assert r.distance_end_m == 250.0
        assert r.time_lost_s == 1.2
        assert r.braking_delta_m == -12.0
        assert r.min_speed_delta_ms == -2.5
        assert r.throttle_delta_m == 15.0
        assert r.brake_release_delta_m is None
        assert r.exit_speed_delta_ms == -1.0
        assert r.driver_min_speed_ms == 30.0
        assert r.reference_min_speed_ms == 32.5
        assert r.driver_lap_number == 3
        assert r.driver_lap_time == 150.5
        assert r.reference_source == "personal_best"
        assert r.reference_lap_time == 148.2
        assert r.total_time_delta_s == 2.3
        # NULL round-trip on the second row
        assert rows[1].braking_delta_m is None
        assert rows[1].brake_release_delta_m == -8.0
        assert rows[1].region_rank == 2

    def test_session_context_joined(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db)
        db.record_region_diagnoses("sess1", _ctx(), [_diag()])
        r = db.list_region_diagnoses()[0]
        assert r.track_id == "523"
        assert r.car == "BMW M2"
        assert r.session_type == "practice"
        assert r.session_date == "2026-07-01 10-00-00"

    def test_rerun_is_idempotent(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db)
        db.record_region_diagnoses("sess1", _ctx(), [_diag(), _diag()])
        db.record_region_diagnoses("sess1", _ctx(), [_diag()])
        assert len(db.list_region_diagnoses()) == 1

    def test_empty_list_clears(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db)
        db.record_region_diagnoses("sess1", _ctx(), [_diag()])
        db.record_region_diagnoses("sess1", _ctx(), [])
        assert db.list_region_diagnoses() == []

    def test_ordered_by_date_then_rank(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db, "b", date="2026-07-02 10-00-00")
        _record_session(db, "a", date="2026-07-01 10-00-00")
        db.record_region_diagnoses("b", _ctx(), [_diag(label="B1")])
        db.record_region_diagnoses("a", _ctx(), [_diag(label="A1"),
                                                 _diag(label="A2")])
        labels = [r.label for r in db.list_region_diagnoses()]
        assert labels == ["A1", "A2", "B1"]


def test_session_row_carries_ibt_file_path(tmp_path):
    db = TrackDB(tmp_path / "t.db")
    _record_session(db)
    row = db.list_session_history()[0]
    assert row.ibt_file_path == "C:/t/sess1.ibt"
