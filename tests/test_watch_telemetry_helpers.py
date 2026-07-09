"""Tests for the pure helpers in scripts/watch_telemetry.py."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "watch_telemetry",
    Path(__file__).resolve().parent.parent / "scripts" / "watch_telemetry.py",
)
watch_telemetry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch_telemetry)


def test_gather_candidates_lists_only_ibt(tmp_path):
    (tmp_path / "a.ibt").write_bytes(b"x")
    (tmp_path / "b.txt").write_bytes(b"x")
    (tmp_path / "c.ibt").write_bytes(b"x")
    cands = watch_telemetry._gather_candidates(tmp_path)
    assert sorted(c.path.name for c in cands) == ["a.ibt", "c.ibt"]
    assert all(c.mtime > 0 for c in cands)


def test_gather_candidates_missing_folder_returns_none(tmp_path):
    assert watch_telemetry._gather_candidates(tmp_path / "nope") is None


def test_format_report_success():
    from core.watcher.processor import SessionReport

    r = SessionReport(path=Path("C:/tel/x.ibt"), track="Spa", car="M2",
                      laps_found=8, valid_laps=6, best_lap_time=161.384,
                      promoted=True, debrief_text="Lap 7  (2:41.384, +2.2s)")
    text = watch_telemetry._format_report(r)
    assert "Spa" in text and "M2" in text
    assert "2:41.384" in text
    assert "PB promoted" in text


def test_format_report_error():
    from core.watcher.processor import SessionReport

    r = SessionReport(path=Path("C:/tel/bad.ibt"), error="ValueError: nope")
    text = watch_telemetry._format_report(r)
    assert "bad.ibt" in text and "nope" in text
