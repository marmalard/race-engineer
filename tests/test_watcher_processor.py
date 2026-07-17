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
    # sample.ibt has incidents on every lap -> all dirty -> no PB promoted
    # (the cleanliness gate correctly blocks dirty laps from ReferenceStore).
    # Pin that assumption: if the fixture is ever swapped for a clean one,
    # this must fail loudly rather than silently flip to the else branch.
    assert report.best_lap_dirty, (
        "expected sample.ibt to have dirty laps — fixture changed?"
    )
    if report.best_lap_dirty:
        assert not report.promoted
        assert ref_store.list_all() == []
        assert report.dirty_note is not None
    else:
        # Clean session: PB promoted as before
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


def test_short_coverage_lap_not_promoted(tmp_path, dbs, monkeypatch):
    """A lap that stops short of the finish line (92.8%) must not become a PB.

    The normaliser accepts laps with >= 90% coverage as valid for analysis,
    but the watcher's covers_full_lap gate (>= 98%) must block them from
    entering the ReferenceStore. Without this gate a partial lap with an
    implausibly fast recorded time permanently blocks real promotion.
    """
    import pandas as pd
    import core.watcher.processor as proc_mod

    track_length = 7004.0                     # Spa Endurance approximate
    n = int(track_length * 0.928)             # 92.8% -> ~6499 metres

    z = np.zeros(n)
    short_lap = NormalizedLap(
        lap_number=1, lap_time=153.5,         # "fast" because only 92.8% driven
        track_length=track_length,
        distance=np.arange(n, dtype=float),   # distance[-1] ~6498, far below 98%
        speed=np.full(n, 43.0), throttle=z, brake=z, steering=z,
        gear=np.ones(n), rpm=np.full(n, 5000.0),
        lat=z, lon=z,
        elapsed_time=np.linspace(0, 153.5, n),
        is_valid=True,
    )

    # Minimal IBT session stub — no real file needed.
    from unittest.mock import MagicMock
    mock_session = MagicMock()
    mock_session.track_id = "525"
    mock_session.track_name = "Circuit de Spa-Francorchamps"
    mock_session.track_directory = "spa 2024 combined"
    mock_session.track_length_km = track_length / 1000.0
    mock_session.car_name = "BMW M2 Racing (G87)"
    mock_session.driver_name = "Test Driver"
    mock_session.session_type = "practice"

    mock_ibt = MagicMock()
    mock_ibt.session = mock_session

    mock_df = pd.DataFrame({"Lap": [1]})

    monkeypatch.setattr(proc_mod.IBTParser, "parse", lambda self, p: mock_ibt)
    monkeypatch.setattr(proc_mod.IBTParser, "get_laps", lambda self, ibt: [mock_df])
    monkeypatch.setattr(
        proc_mod.Normalizer, "normalize_session",
        lambda *a, **kw: [short_lap],
    )

    track_db, ref_store = dbs
    fake_path = tmp_path / "fake_spa.ibt"
    fake_path.write_bytes(b"")   # content irrelevant; parse is mocked

    report = process_ibt(fake_path, track_db, ref_store)

    assert report.error is None, f"Unexpected error: {report.error}"
    assert not report.promoted, "Stop-short partial lap must not be promoted to personal_best"
    assert ref_store.list_all() == [], "ReferenceStore must remain empty"


def _mk_lap(lap_number, lap_time, track_length):
    """Plausible, full-coverage NormalizedLap for promotion tests."""
    n = int(track_length)
    z = np.zeros(n)
    return NormalizedLap(
        lap_number=lap_number, lap_time=lap_time, track_length=track_length,
        distance=np.arange(n, dtype=float),
        speed=np.full(n, track_length / lap_time), throttle=z, brake=z,
        steering=z, gear=np.ones(n), rpm=np.full(n, 5000.0), lat=z, lon=z,
        elapsed_time=np.linspace(0, lap_time, n), is_valid=True,
    )


def _mk_lap_df(lap_number, incident_counts):
    """Raw per-lap frame the cleanliness check reads (Lap col for keying)."""
    import pandas as pd
    n = len(incident_counts)
    return pd.DataFrame({
        "Lap": [lap_number] * n,
        "LapDist": [float(i * 100) for i in range(n)],
        "PlayerCarMyIncidentCount": incident_counts,
    })


def _run_with(monkeypatch, tmp_path, dbs, lap_dfs, nlaps, track_length=4000.0):
    import core.watcher.processor as proc_mod
    from unittest.mock import MagicMock

    mock_session = MagicMock()
    mock_session.track_id = "525"
    mock_session.track_name = "Spa"
    mock_session.track_directory = "spa 2024 combined"
    mock_session.track_length_km = track_length / 1000.0
    mock_session.car_name = "M2"
    mock_session.driver_name = "Test Driver"
    mock_session.session_type = "practice"
    mock_ibt = MagicMock()
    mock_ibt.session = mock_session

    monkeypatch.setattr(proc_mod.IBTParser, "parse", lambda self, p: mock_ibt)
    monkeypatch.setattr(proc_mod.IBTParser, "get_laps", lambda self, ibt: lap_dfs)
    monkeypatch.setattr(
        proc_mod.Normalizer, "normalize_session", lambda *a, **kw: nlaps,
    )
    track_db, ref_store = dbs
    fake = tmp_path / "fake.ibt"
    fake.write_bytes(b"")
    return process_ibt(fake, track_db, ref_store), ref_store


def test_fastest_dirty_lap_not_promoted_clean_one_is(tmp_path, dbs, monkeypatch):
    """Coach the dirty lap (it stays report.best) but promote the clean one."""
    lap_dfs = [
        _mk_lap_df(1, [0, 0, 1, 1]),   # dirty (fast)
        _mk_lap_df(2, [1, 1, 1, 1]),   # clean (slower)
    ]
    nlaps = [_mk_lap(1, 100.0, 4000.0), _mk_lap(2, 102.0, 4000.0)]
    report, ref_store = _run_with(monkeypatch, tmp_path, dbs, lap_dfs, nlaps)

    assert report.error is None
    assert report.best_lap_time == 100.0          # coached/reported best unchanged
    assert report.best_lap_dirty
    assert report.dirty_note is not None
    assert report.promoted
    metas = ref_store.list_all()
    assert len(metas) == 1
    assert metas[0].lap_time == pytest.approx(102.0)   # the CLEAN lap


def test_all_dirty_nothing_promoted(tmp_path, dbs, monkeypatch):
    lap_dfs = [_mk_lap_df(1, [0, 0, 2, 2])]
    nlaps = [_mk_lap(1, 100.0, 4000.0)]
    report, ref_store = _run_with(monkeypatch, tmp_path, dbs, lap_dfs, nlaps)

    assert report.error is None
    assert not report.promoted
    assert report.best_lap_dirty
    assert "no clean lap" in (report.dirty_note or "")
    assert ref_store.list_all() == []


def test_all_clean_behavior_unchanged(tmp_path, dbs, monkeypatch):
    lap_dfs = [_mk_lap_df(1, [3, 3, 3, 3])]
    nlaps = [_mk_lap(1, 100.0, 4000.0)]
    report, ref_store = _run_with(monkeypatch, tmp_path, dbs, lap_dfs, nlaps)

    assert report.error is None
    assert report.promoted and not report.best_lap_dirty
    assert report.dirty_note is None


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
    # PB promoted alongside only when a clean lap exists; sample.ibt laps are
    # all dirty so only g61 remains (dirty best is still debriefed, not promoted)
    sources = {m.source for m in ref_store.list_all()}
    assert "g61" in sources  # pre-seeded reference untouched


def test_no_reference_records_no_diagnoses(sample_ibt_path, dbs):
    track_db, ref_store = dbs
    report = process_ibt(sample_ibt_path, track_db, ref_store)
    assert report.error is None
    assert report.diagnoses_recorded == 0
    assert track_db.list_region_diagnoses() == []


def test_process_persists_diagnoses_when_reference_exists(sample_ibt_path, dbs):
    """With a faster stored reference, the debrief runs and its region
    diagnoses land in tracks.db with the comparison context."""
    import dataclasses

    from core.watcher.processor import parse_best_lap

    track_db, ref_store = dbs
    parsed = parse_best_lap(sample_ibt_path)
    assert parsed.best is not None
    # Uniformly 5% faster copy of the fixture's own best lap: identical
    # speed trace (alignment offset 0) but every metre costs less time,
    # so the driver "loses" everywhere -> loss regions exist.
    factor = 0.95
    faster = dataclasses.replace(
        parsed.best,
        lap_time=parsed.best.lap_time * factor,
        elapsed_time=parsed.best.elapsed_time * factor,
    )
    ref_store.save(
        str(parsed.session.track_id), parsed.session.car_name, faster,
        source="personal_best", driver_name="Ref Driver",
    )

    report = process_ibt(sample_ibt_path, track_db, ref_store)
    assert report.error is None
    assert report.debrief_text is not None
    assert report.diagnoses_recorded >= 1
    rows = track_db.list_region_diagnoses()
    assert len(rows) == report.diagnoses_recorded
    r0 = rows[0]
    assert r0.region_rank == 1
    assert r0.reference_source == "personal_best"
    assert r0.driver_lap_time == pytest.approx(parsed.best.lap_time)
    assert r0.reference_lap_time == pytest.approx(faster.lap_time)
    assert r0.time_lost_s > 0
