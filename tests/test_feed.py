"""Tests for the in-memory nudge feed and its stdlib web server."""

import json
import urllib.request

from core.live.feed import NudgeFeed, format_transcript_line, render_page, start_web_display


def test_feed_newest_first():
    f = NudgeFeed()
    f.add("lap 1")
    f.add("lap 2")
    assert f.snapshot() == ["lap 2", "lap 1"]


def test_feed_caps_at_max():
    f = NudgeFeed(max_entries=3)
    for i in range(5):
        f.add(f"lap {i}")
    snap = f.snapshot()
    assert len(snap) == 3
    assert snap[0] == "lap 4"
    assert snap[-1] == "lap 2"


def test_snapshot_is_a_copy():
    f = NudgeFeed()
    f.add("a")
    snap = f.snapshot()
    snap.append("mutated")
    assert f.snapshot() == ["a"]


def test_render_page_has_feed_div_and_poll():
    page = render_page()
    assert 'id="feed"' in page
    assert "/feed" in page
    assert "Race Engineer" in page


def test_server_serves_feed_json():
    f = NudgeFeed()
    f.add("Lap 6 - carry it flat")
    server = start_web_display(f, host="127.0.0.1", port=0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/feed", timeout=5
        ) as r:
            data = json.loads(r.read())
        assert data["entries"] == ["Lap 6 - carry it flat"]
    finally:
        server.shutdown()


def test_server_serves_html_root():
    f = NudgeFeed()
    server = start_web_display(f, host="127.0.0.1", port=0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=5
        ) as r:
            body = r.read().decode("utf-8")
        assert 'id="feed"' in body
    finally:
        server.shutdown()


def test_server_unknown_path_404():
    f = NudgeFeed()
    server = start_web_display(f, host="127.0.0.1", port=0)
    try:
        port = server.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        server.shutdown()


def test_feed_route_does_not_overmatch():
    """/feedback is not the /feed route — it must 404, not return JSON."""
    f = NudgeFeed()
    server = start_web_display(f, host="127.0.0.1", port=0)
    try:
        port = server.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/feedback", timeout=5)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        server.shutdown()


def test_feed_route_accepts_query_string():
    """The poll uses a cache-busting query string; /feed?t=1 still serves JSON."""
    f = NudgeFeed()
    f.add("lap entry")
    server = start_web_display(f, host="127.0.0.1", port=0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/feed?t=123", timeout=5
        ) as r:
            data = json.loads(r.read())
        assert data["entries"] == ["lap entry"]
    finally:
        server.shutdown()


class TestFormatTranscriptLine:
    """Exact-string per event type (nudges precedent).

    Events without a 't' timestamp render '--:--:--' — used here so the
    expected strings are timezone-independent.
    """

    def test_connect_with_reference(self):
        line = format_transcript_line({
            "event": "connect", "track": "Okayama", "car": "MX-5",
            "reference": {"source": "g61", "lap_time": 98.412,
                          "driver": "R. Mott"},
        })
        assert line == (
            "--:--:--  \U0001f399 On air — Okayama · MX-5 · "
            "reference 1:38.412 loaded"
        )

    def test_connect_without_reference(self):
        line = format_transcript_line({
            "event": "connect", "track": "Okayama", "car": "MX-5",
            "reference": None,
        })
        assert line == (
            "--:--:--  \U0001f399 On air — Okayama · MX-5 · "
            "no reference — lap one sets the baseline"
        )

    def test_lap(self):
        line = format_transcript_line({
            "event": "lap", "lap": 5, "lap_time": 143.501,
            "delta": 2.5, "improved": False, "dirty": False,
        })
        assert line == "--:--:--  \U0001f3c1 Lap 5 — 2:23.501 (+2.5s)"

    def test_lap_dirty_gets_asterisk_clause(self):
        line = format_transcript_line({
            "event": "lap", "lap": 6, "lap_time": 142.900,
            "delta": 1.9, "dirty": True,
        })
        assert line == (
            "--:--:--  \U0001f3c1 Lap 6 — 2:22.900 (+1.9s) "
            "— track limits, won't count"
        )

    def test_baseline(self):
        line = format_transcript_line({
            "event": "baseline", "lap": 1, "lap_time": 145.2,
        })
        assert line == "--:--:--  \U0001f3c1 Lap 1 — 2:25.200, baseline set"

    def test_prompt(self):
        line = format_transcript_line({
            "event": "prompt", "text": "Coming up — carry it flat",
        })
        assert line == "--:--:--  \U0001f399 Coming up — carry it flat"

    def test_discard(self):
        line = format_transcript_line({
            "event": "discard", "reason": "reset",
            "speech": "Reset — scratch that lap.",
        })
        assert line == "--:--:--  ↩ Reset — scratch that lap."

    def test_invalid(self):
        line = format_transcript_line({
            "event": "invalid", "lap": 3,
            "speech": "That lap won't count — data's incomplete.",
        })
        assert line == (
            "--:--:--  ⚠ That lap won't count — data's incomplete."
        )

    def test_dirty_baseline_skipped(self):
        line = format_transcript_line({
            "event": "dirty_baseline_skipped",
            "speech": "That lap had track limits — I won't use it as the baseline. Give me a clean one.",
        })
        assert line == (
            "--:--:--  ⚠ That lap had track limits — I won't use it as "
            "the baseline. Give me a clean one."
        )

    def test_schedule_is_machinery_and_hidden(self):
        assert format_transcript_line({"event": "schedule"}) == ""

    def test_unknown_event_falls_back_to_name(self):
        assert format_transcript_line({"event": "mystery"}) == (
            "--:--:--  · mystery"
        )

    def test_timestamp_renders_as_local_clock(self):
        import re

        line = format_transcript_line({
            "event": "prompt", "text": "x",
            "t": "2026-07-15T18:30:00+00:00",
        })
        assert re.match(r"^\d{2}:\d{2}:\d{2}  ", line)
