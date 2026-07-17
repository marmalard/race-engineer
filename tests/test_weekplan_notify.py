# tests/test_weekplan_notify.py
"""Marker handshake between watcher (writer) and tray (consumer)."""

import json
from pathlib import Path

from core.weekplan.notify import (
    MARKER_RELPATH, TOAST_MESSAGE, TOAST_TITLE, consume_marker,
    write_marker,
)


class TestMarkerPath:
    def test_relative_path_pinned(self):
        # BOTH processes anchor this exact subpath (watcher: cwd,
        # tray: _ROOT). Moving it is a two-process change.
        assert MARKER_RELPATH == Path("data/run/weekplan_ready.json")


class TestHandshake:
    def test_write_then_consume(self, tmp_path):
        marker = tmp_path / "weekplan_ready.json"
        write_marker("2026-07-21", marker_path=marker)
        data = consume_marker(marker_path=marker)
        assert data is not None and data["week_start"] == "2026-07-21"
        assert "created_at" in data

    def test_consume_deletes_marker(self, tmp_path):
        marker = tmp_path / "weekplan_ready.json"
        write_marker("2026-07-21", marker_path=marker)
        consume_marker(marker_path=marker)
        assert not marker.exists()
        assert consume_marker(marker_path=marker) is None

    def test_absent_marker_is_none(self, tmp_path):
        assert consume_marker(marker_path=tmp_path / "nope.json") is None

    def test_corrupt_marker_deleted_and_none(self, tmp_path):
        marker = tmp_path / "weekplan_ready.json"
        marker.write_text("{not json", encoding="utf-8")
        assert consume_marker(marker_path=marker) is None
        assert not marker.exists()


class TestToastCopy:
    def test_exact_strings(self):
        assert TOAST_TITLE == "Race Engineer"
        assert TOAST_MESSAGE == (
            "Week plan's ready — the week flips Tuesday. "
            "Open Race Engineer."
        )
