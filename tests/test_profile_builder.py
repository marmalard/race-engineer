"""Builder integration: temp stores -> DriverProfile (the only I/O path)."""

from core.coaching.debrief import RegionDiagnosis
from core.profile.builder import load_profile
from core.race.race_store import RaceStore
from core.telemetry.loss_regions import LossRegion
from core.track.track_db import DiagnosisContext, TrackDB

# Reuse the synthetic narrative helpers from the racecraft tests.
from tests.test_profile_racecraft import _attr, _lap1, _narr


def test_load_profile_assembles_both_layers(tmp_path):
    race_store = RaceStore(tmp_path / "races.db")
    for i in range(3):
        race_store.save_race(
            _narr(lap1=_lap1(), attribution=_attr(), subsession_id=i + 1),
            ibt_file_path=f"{i}.ibt",
        )
    track_db = TrackDB(tmp_path / "tracks.db")
    track_db.record_session(
        session_id="s1", track_id="525", car="M2", session_type="practice",
        session_date="2026-07-01", best_lap_time=100.0, lap_count=5,
        ibt_file_path="p.ibt",
    )
    track_db.record_laps("s1", [(i + 1, 100.0 + i * 0.1, True) for i in range(5)])

    profile = load_profile(race_store, track_db, cust_id=100)
    assert profile.cust_id == 100
    assert profile.driver_name == "D"
    assert profile.races_captured == 3
    assert profile.racecraft.starts.enough_data
    assert profile.combos_tracked == 1
    assert profile.readiness[0].track_id == "525"


def test_load_profile_empty_stores(tmp_path):
    profile = load_profile(
        RaceStore(tmp_path / "r.db"), TrackDB(tmp_path / "t.db"), cust_id=1
    )
    assert profile.races_captured == 0
    assert profile.readiness == []
    assert not profile.racecraft.starts.enough_data


def test_load_profile_store_failure_degrades_to_empty(tmp_path):
    class ExplodingStore:
        def get_narratives(self, cust_id):
            raise RuntimeError("boom")

    profile = load_profile(
        ExplodingStore(), TrackDB(tmp_path / "t.db"), cust_id=1
    )
    assert profile.races_captured == 0        # degraded, not raised


def test_load_profile_track_db_failure_still_returns_racecraft(tmp_path):
    race_store = RaceStore(tmp_path / "races.db")
    race_store.save_race(_narr(lap1=_lap1()), ibt_file_path="a.ibt")

    class ExplodingTrackDB:
        def list_session_history(self):
            raise RuntimeError("boom")

    profile = load_profile(race_store, ExplodingTrackDB(), cust_id=100)
    assert profile.races_captured == 1        # race layer intact
    assert profile.readiness == []            # pace layer degraded


def _seed_diagnosed_sessions(track_db, n):
    for i in range(1, n + 1):
        track_db.record_session(
            session_id=f"s{i}", track_id="523", car="M2",
            session_type="practice",
            session_date=f"2026-07-{i:02d} 10-00-00",
            best_lap_time=150.0, lap_count=5, ibt_file_path="",
        )
        track_db.record_region_diagnoses(
            f"s{i}",
            DiagnosisContext(driver_lap_number=2, driver_lap_time=150.0,
                             reference_source="personal_best",
                             reference_lap_time=148.0, total_time_delta_s=2.0),
            [RegionDiagnosis(
                region=LossRegion(100.0, 250.0, 0.8),
                label="Eau Rouge", braking_delta_m=None,
                min_speed_delta_ms=-3.0, throttle_delta_m=None,
                driver_min_speed_ms=30.0, reference_min_speed_ms=33.0,
                brake_release_delta_m=None, exit_speed_delta_ms=0.0,
            )],
        )


def test_profile_includes_technique_and_ttp(tmp_path):
    track_db = TrackDB(tmp_path / "t.db")
    store = RaceStore(tmp_path / "r.db")
    _seed_diagnosed_sessions(track_db, 6)
    p = load_profile(store, track_db, cust_id=1)
    assert p.technique.enough_data
    assert p.technique.dominant == "lift"   # -3.0 m/s min-speed deficit
    assert p.technique.sessions_diagnosed == 6
    # No lap rows recorded -> time_to_pace stays empty but present
    assert p.time_to_pace.sample_sessions == 0


def test_diagnosis_load_failure_degrades_to_empty(tmp_path, monkeypatch):
    track_db = TrackDB(tmp_path / "t.db")
    store = RaceStore(tmp_path / "r.db")

    def _boom(self):
        raise RuntimeError("db locked")

    monkeypatch.setattr(TrackDB, "list_region_diagnoses", _boom)
    p = load_profile(store, track_db, cust_id=1)
    assert p.technique.sessions_diagnosed == 0
    assert not p.technique.enough_data
