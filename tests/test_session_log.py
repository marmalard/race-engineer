"""Tests for the live-session JSONL event log."""

import json

from core.live.session_log import SessionLog


def test_events_append_as_json_lines(tmp_path):
    path = tmp_path / "session.jsonl"
    log = SessionLog(path)
    log.log("connect", track="Spa", car="BMW M2 Racing (G87)")
    log.log("prompt", text="La Source — brake later.", lap_dist_m=6904.0)
    log.close()

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(ln) for ln in lines)
    assert first["event"] == "connect"
    assert first["track"] == "Spa"
    assert "t" in first  # ISO timestamp present on every event
    assert second["event"] == "prompt"
    assert second["lap_dist_m"] == 6904.0


def test_parent_directory_created(tmp_path):
    path = tmp_path / "live_sessions" / "spa.jsonl"
    log = SessionLog(path)
    log.log("connect")
    log.close()
    assert path.exists()


def test_log_survives_unserializable_values(tmp_path):
    """A weird value (e.g. numpy scalar) must not crash the live loop."""
    path = tmp_path / "session.jsonl"
    log = SessionLog(path)

    class Odd:
        def __str__(self):
            return "odd"

    log.log("lap", value=Odd())  # falls back to str()
    log.close()
    assert json.loads(path.read_text(encoding="utf-8"))["value"] == "odd"


def test_events_flushed_immediately(tmp_path):
    """A sim crash must not lose the session so far — no close() needed."""
    path = tmp_path / "session.jsonl"
    log = SessionLog(path)
    log.log("connect")
    # Read WITHOUT closing: the line must already be on disk.
    assert "connect" in path.read_text(encoding="utf-8")
    log.close()
