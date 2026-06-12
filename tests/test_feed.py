"""Tests for the in-memory nudge feed and its stdlib web server."""

import json
import urllib.request

from core.live.feed import NudgeFeed, render_page, start_web_display


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
