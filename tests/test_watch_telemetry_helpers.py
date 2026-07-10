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


def test_process_candidate_routes_race_to_race_processor(monkeypatch, tmp_path):
    """A race IBT goes to process_race_ibt; a lap IBT goes to process_ibt.
    Proves races never hit the PB-promoting lap path."""
    import scripts.watch_telemetry as wt
    from core.watcher.scanner import IbtCandidate

    called = {"race": 0, "lap": 0}

    class _FakeSession:
        event = "Race"

        def __init__(self):
            self.raw = {"WeekendInfo": {"EventType": _FakeSession.event,
                                        "SubSessionID": 42}}

    monkeypatch.setattr(
        wt.IBTParser, "parse_session_only",
        lambda self, p: _FakeSession(),
    )
    monkeypatch.setattr(
        wt, "process_race_ibt",
        lambda *a, **k: called.__setitem__("race", called["race"] + 1)
        or wt.RaceReport(path=Path("r")),
    )
    monkeypatch.setattr(
        wt, "process_ibt",
        lambda *a, **k: called.__setitem__("lap", called["lap"] + 1)
        or wt.SessionReport(path=Path("l")),
    )

    cand = IbtCandidate(path=tmp_path / "x.ibt", mtime=0.0)

    _FakeSession.event = "Race"
    wt._process_candidate(cand, api=None, track_db=None, ref_store=None,
                          race_store=None, now=1.0)
    assert called == {"race": 1, "lap": 0}

    _FakeSession.event = "Practice"
    wt._process_candidate(cand, api=None, track_db=None, ref_store=None,
                          race_store=None, now=1.0)
    assert called == {"race": 1, "lap": 1}
