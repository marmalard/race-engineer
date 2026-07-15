"""Tests for the watcher's race-capture processor."""

from pathlib import Path

import pytest

from core.race.race_store import RaceStore
from core.track.track_db import TrackDB
from core.watcher.race_processor import (
    RaceReport,
    classify_ibt,
    decide_capture,
    process_race_ibt,
)


def test_classify_race():
    assert classify_ibt({"EventType": "Race", "SubSessionID": 12345}) == "race"


def test_classify_practice_is_lap():
    assert classify_ibt({"EventType": "Practice", "SubSessionID": 12345}) == "lap"


def test_classify_race_without_subsession_is_lap():
    assert classify_ibt({"EventType": "Race", "SubSessionID": 0}) == "lap"


def test_classify_missing_fields_is_lap():
    assert classify_ibt({}) == "lap"


def test_decide_full_when_results_ready():
    assert decide_capture(results_ready=True, have_creds=True, file_age_s=1.0) == "full"


def test_decide_defer_when_young_with_creds():
    assert decide_capture(results_ready=False, have_creds=True,
                          file_age_s=10.0, grace_s=300.0) == "defer"


def test_decide_partial_when_old():
    assert decide_capture(results_ready=False, have_creds=True,
                          file_age_s=600.0, grace_s=300.0) == "partial"


def test_decide_partial_when_no_creds():
    assert decide_capture(results_ready=False, have_creds=False,
                          file_age_s=1.0) == "partial"


def test_race_report_defaults():
    r = RaceReport(path=Path("x"))
    assert not r.captured and not r.partial and not r.deferred and r.error is None


FIXTURE_IBT = Path("tests/fixtures/race/race.ibt")
FIXTURE_CACHE = Path("tests/fixtures/race/cache")
needs_fixture = pytest.mark.skipif(
    not FIXTURE_IBT.exists() or not FIXTURE_CACHE.exists(),
    reason="race fixtures not recorded (scripts/record_race_fixture.py)",
)


class _ExplodingAPI:
    """Serves entirely from recorded cache; any network call is a bug."""

    def __getattr__(self, name):
        raise AssertionError(f"network call attempted: {name}")

    def close(self):
        pass


@needs_fixture
def test_process_race_full_capture_from_cache(tmp_path):
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")
    report = process_race_ibt(
        FIXTURE_IBT, _ExplodingAPI(), race_store, track_db,
        now=1000.0, file_mtime=1000.0, cache_dir=FIXTURE_CACHE,
    )
    assert report.error is None
    assert report.captured and not report.partial and not report.deferred
    assert report.subsession_id == 86748877
    # Oulton MX-5 fixture: gridded P7, finished P4 (adjust if the recorded
    # fixture differs — TDD will reveal the real values).
    assert report.start_position == 7
    assert report.finish_position == 4
    assert len(race_store.list_races()) == 1
    assert str(FIXTURE_IBT) in track_db.processed_ibt_paths()


@needs_fixture
def test_process_race_idempotent(tmp_path):
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")
    for _ in range(2):
        process_race_ibt(
            FIXTURE_IBT, _ExplodingAPI(), race_store, track_db,
            now=1000.0, file_mtime=1000.0, cache_dir=FIXTURE_CACHE,
        )
    assert len(race_store.list_races()) == 1  # INSERT OR REPLACE, no duplicate


@needs_fixture
def test_process_race_partial_when_no_results(tmp_path):
    """api=None + empty cache -> partial narrative persisted (file old)."""
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")
    report = process_race_ibt(
        FIXTURE_IBT, None, race_store, track_db,
        now=10_000.0, file_mtime=0.0, cache_dir=tmp_path / "emptycache",
    )
    assert report.error is None
    assert report.captured and report.partial
    assert len(race_store.list_races()) == 1


@needs_fixture
def test_process_race_defers_when_young_and_not_ready(tmp_path):
    """Creds present but results empty + young file -> defer, save nothing."""
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")

    class EmptyAPI:
        def get_subsession_results(self, *a):
            return {}  # not ready yet

        def close(self):
            pass

    report = process_race_ibt(
        FIXTURE_IBT, EmptyAPI(), race_store, track_db,
        now=100.0, file_mtime=99.0, cache_dir=tmp_path / "c", grace_s=300.0,
    )
    assert report.deferred and not report.captured
    assert race_store.list_races() == []
    assert track_db.processed_ibt_paths() == set()  # not marked -> retries


def test_process_race_skips_pre_race_chunk(tmp_path, monkeypatch):
    """A practice/quali chunk from the race server is reported for lap-path
    rerouting: nothing captured, nothing marked processed HERE — the CLI
    hands the file to process_ibt, whose history row marks it."""
    from core.race.ingest import NotRaceChunkError

    def fake_ingest(*args, **kwargs):
        raise NotRaceChunkError(
            "not the race", subsession_id=777,
            segment_types=["Practice", "Lone Qualify"],
        )

    monkeypatch.setattr("core.watcher.race_processor.ingest_race", fake_ingest)
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")
    report = process_race_ibt(
        Path("chunk.ibt"), None, race_store, track_db,
        now=1000.0, file_mtime=0.0,
    )
    assert report.non_race_segment == "Practice / Lone Qualify"
    assert report.error is None
    assert not report.captured and not report.deferred
    assert report.subsession_id == 777
    assert race_store.list_races() == []
    assert track_db.processed_ibt_paths() == set()
