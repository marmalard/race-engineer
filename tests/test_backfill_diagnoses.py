"""Back-fill: re-debrief recorded history vs the CURRENT reference.

Pure-logic tests need no IBT; the end-to-end test uses the sample fixture
(skips gracefully when absent, like the processor tests).
"""

import dataclasses

import pytest

from core.benchmark.reference_store import ReferenceStore
from core.track.track_db import TrackDB
from scripts.backfill_diagnoses import backfill


@pytest.fixture
def dbs(tmp_path):
    return TrackDB(tmp_path / "tracks.db"), ReferenceStore(tmp_path / "refs.db")


def _record(db, session_id, session_type="practice", path="C:/nope/missing.ibt"):
    db.record_session(
        session_id=session_id, track_id="523", car="BMW M2",
        session_type=session_type, session_date="2026-07-01 10-00-00",
        best_lap_time=150.0, lap_count=5, ibt_file_path=path,
    )


def test_race_sessions_skipped(dbs):
    track_db, ref_store = dbs
    _record(track_db, "r1", session_type="Race")
    counts = backfill(track_db, ref_store)
    assert counts["skipped_race"] == 1
    assert counts["recorded"] == 0


def test_missing_files_skipped(dbs):
    track_db, ref_store = dbs
    _record(track_db, "p1")  # path does not exist
    counts = backfill(track_db, ref_store)
    assert counts["skipped_missing"] == 1
    assert counts["recorded"] == 0
    assert track_db.list_region_diagnoses() == []


def test_backfill_end_to_end(sample_ibt_path, dbs):
    from core.watcher.processor import parse_best_lap

    track_db, ref_store = dbs
    parsed = parse_best_lap(sample_ibt_path)
    assert parsed.best is not None
    track_id = str(parsed.session.track_id)
    car = parsed.session.car_name
    # The recorded session row must match the IBT's combo for the
    # reference lookup (record_session is INSERT OR REPLACE — idempotent).
    track_db.record_session(
        session_id="s1", track_id=track_id, car=car,
        session_type="practice", session_date="2026-07-01 10-00-00",
        best_lap_time=parsed.best.lap_time, lap_count=2,
        ibt_file_path=str(sample_ibt_path),
    )
    # No reference yet -> skipped, nothing written
    counts = backfill(track_db, ref_store)
    assert counts["skipped_no_ref"] == 1
    assert track_db.list_region_diagnoses() == []

    factor = 0.95
    faster = dataclasses.replace(
        parsed.best,
        lap_time=parsed.best.lap_time * factor,
        elapsed_time=parsed.best.elapsed_time * factor,
    )
    ref_store.save(track_id, car, faster, source="personal_best")

    # Dry run writes nothing
    counts = backfill(track_db, ref_store, dry_run=True)
    assert counts["recorded"] == 1
    assert track_db.list_region_diagnoses() == []

    # Real run writes rows; ReferenceStore untouched
    refs_before = ref_store.list_all()
    counts = backfill(track_db, ref_store)
    assert counts["recorded"] == 1
    rows = track_db.list_region_diagnoses()
    assert len(rows) >= 1
    assert rows[0].reference_source == "personal_best"
    assert ref_store.list_all() == refs_before

    # Idempotent rerun: same row count
    backfill(track_db, ref_store)
    assert len(track_db.list_region_diagnoses()) == len(rows)
