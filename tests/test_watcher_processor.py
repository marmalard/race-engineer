"""End-to-end tests for the watcher's per-file pipeline.

Uses the real sample IBT fixture (skips gracefully when absent),
with throwaway tmp databases.
"""

import numpy as np
import pytest

from core.benchmark.reference_store import ReferenceStore
from core.telemetry.normalizer import NormalizedLap
from core.track.track_db import TrackDB
from core.watcher.processor import SessionReport, process_ibt


@pytest.fixture
def dbs(tmp_path):
    return TrackDB(tmp_path / "tracks.db"), ReferenceStore(tmp_path / "refs.db")


def test_corrupt_file_returns_error_report(tmp_path, dbs):
    track_db, ref_store = dbs
    bad = tmp_path / "bad.ibt"
    bad.write_bytes(b"not an ibt file")
    report = process_ibt(bad, track_db, ref_store)
    assert isinstance(report, SessionReport)
    assert report.error is not None
    # A failed file must NOT be marked processed (it retries next scan)
    assert track_db.processed_ibt_paths() == set()


def test_process_records_promotes_and_reports(sample_ibt_path, dbs):
    track_db, ref_store = dbs
    report = process_ibt(sample_ibt_path, track_db, ref_store)

    assert report.error is None
    assert report.valid_laps >= 1
    assert report.best_lap_time is not None and report.best_lap_time > 0
    # Session recorded -> path is now deduped
    assert str(sample_ibt_path) in track_db.processed_ibt_paths()
    # First session at this combo -> PB promoted
    assert report.promoted
    metas = ref_store.list_all()
    assert len(metas) == 1
    assert metas[0].source == "personal_best"
    assert metas[0].lap_time == pytest.approx(report.best_lap_time)
    # First-ever reference is the lap itself -> baseline wording, no debrief
    assert report.debrief_text is None


def test_rerun_does_not_repromote(sample_ibt_path, dbs):
    track_db, ref_store = dbs
    process_ibt(sample_ibt_path, track_db, ref_store)
    second = process_ibt(sample_ibt_path, track_db, ref_store)
    assert second.error is None
    assert not second.promoted  # equal time is not strictly faster


def test_debrief_against_preseeded_faster_reference(sample_ibt_path, dbs):
    track_db, ref_store = dbs
    # Pre-seed a faster synthetic g61 reference for the same combo.
    from core.telemetry.ibt_parser import IBTParser

    session = IBTParser().parse(sample_ibt_path).session
    n = int(session.track_length_km * 1000)
    z = np.zeros(n)
    fast = NormalizedLap(
        lap_number=0, lap_time=1.0, track_length=float(n),
        distance=np.arange(n, dtype=float), speed=np.full(n, 80.0),
        throttle=np.ones(n), brake=z, steering=z, gear=np.full(n, 5),
        rpm=np.full(n, 7000.0), lat=z, lon=z,
        elapsed_time=np.cumsum(np.full(n, 1.0 / 80.0)), is_valid=True,
    )
    ref_store.save(str(session.track_id), session.car_name, fast,
                   source="g61", driver_name="Synthetic")

    report = process_ibt(sample_ibt_path, track_db, ref_store)
    assert report.error is None
    assert report.debrief_text is not None
    assert "Lap" in report.debrief_text
    # PB still promoted alongside (separate source row, g61 untouched)
    sources = {m.source for m in ref_store.list_all()}
    assert sources == {"g61", "personal_best"}
