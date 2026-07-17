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


def test_race_report_block_survives_cp1252_stdout():
    """The detached watcher's stdout is a cp1252-encoded file on Windows;
    a report line with a non-cp1252 char (the old P4->P2 arrow, U+2192)
    killed the daemon on 2026-07-12. Report blocks must encode cleanly."""
    from pathlib import Path as _P
    from core.watcher.race_processor import RaceReport
    report = RaceReport(
        path=_P("race.ibt"), subsession_id=86748877, track="Summit Point",
        car="BMW M2", start_position=4, finish_position=2, captured=True,
    )
    block = watch_telemetry._format_race_report(report)
    block.encode("cp1252")  # must not raise
    assert "P4" in block and "P2" in block


def test_format_race_report_pre_race_chunk_cp1252_safe():
    from pathlib import Path as _P
    from core.watcher.race_processor import RaceReport
    report = RaceReport(
        path=_P("chunk.ibt"), subsession_id=777,
        non_race_segment="Lone Qualify",
    )
    block = watch_telemetry._format_race_report(report)
    block.encode("cp1252")  # must not raise
    assert "Lone Qualify" in block


def test_process_candidate_reroutes_pre_race_chunk(monkeypatch):
    """A race-classified chunk that turns out to lack the race segment must
    be handed to the lap path with its real segment type — quali laps are
    pace data (founder, 2026-07-15), and the lap path's history row is what
    marks the file processed."""
    from types import SimpleNamespace

    from core.watcher.processor import SessionReport
    from core.watcher.race_processor import RaceReport

    class _Session:
        raw = {"WeekendInfo": {"EventType": "Race", "SubSessionID": 777}}

    monkeypatch.setattr(
        watch_telemetry.IBTParser, "parse_session_only",
        lambda self, path: _Session(),
    )

    def fake_race(path, api, race_store, track_db, *, now, file_mtime):
        return RaceReport(path=path, subsession_id=777,
                          non_race_segment="Lone Qualify")

    calls = {}

    def fake_lap(path, track_db, ref_store, session_type_override=None):
        calls["lap"] = (path, session_type_override)
        return SessionReport(path=path)

    monkeypatch.setattr(watch_telemetry, "process_race_ibt", fake_race)
    monkeypatch.setattr(watch_telemetry, "process_ibt", fake_lap)

    cand = SimpleNamespace(path=Path("chunk.ibt"), mtime=0.0)
    block = watch_telemetry._process_candidate(
        cand, None, object(), object(), object(), 1000.0
    )
    assert calls["lap"] == (Path("chunk.ibt"), "Lone Qualify")
    assert "Lone Qualify" in block


def test_format_report_mentions_diagnoses_recorded():
    from core.watcher.processor import SessionReport

    r = SessionReport(path=Path("x.ibt"), track="Spa", car="M2",
                      laps_found=5, valid_laps=4, best_lap_time=150.0,
                      diagnoses_recorded=3)
    assert "3 region diagnoses recorded" in watch_telemetry._format_report(r)


def test_format_report_silent_when_no_diagnoses():
    from core.watcher.processor import SessionReport

    r = SessionReport(path=Path("x.ibt"), track="Spa", car="M2",
                      laps_found=5, valid_laps=4, best_lap_time=150.0)
    assert "diagnoses" not in watch_telemetry._format_report(r)
