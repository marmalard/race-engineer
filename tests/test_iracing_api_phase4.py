"""Tests for the Phase 4 Data API plumbing (pre-race briefing endpoints).

Parse functions are tested with inline dict payloads modeled on real
recorded responses from the 2026-07-13 spike (data/api_spike/, gitignored).
No live API calls here — client methods use a fake HTTP client.
"""

import time

import pytest

from core.benchmark.iracing_api import (
    LiveIRacingAPI,
    RaceGuideSession,
    StubIRacingAPI,
    _TokenData,
    parse_race_guide,
)


# ---------------------------------------------------------------------------
# Fake HTTP plumbing (same pattern as test_iracing_api.py chunked tests)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHTTPClient:
    """Serves canned responses keyed by URL substring; records params."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []
        self.params: list[dict | None] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        self.params.append(kwargs.get("params"))
        for key, payload in self.routes.items():
            if key in url:
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected URL: {url}")


def _api_with_fake_client(routes: dict) -> LiveIRacingAPI:
    api = LiveIRacingAPI("cid", "csecret", "user", "pass")
    api._client = _FakeHTTPClient(routes)
    api._token = _TokenData(access_token="tok", expires_at=9999999999.0)
    return api


# ---------------------------------------------------------------------------
# Race guide — /data/season/race_guide
# ---------------------------------------------------------------------------

# Modeled on data/api_spike/race_guide.json (imminent session, fully populated)
RACE_GUIDE_PAYLOAD = {
    "subscribed": False,
    "success": True,
    "block_begin_time": "2026-07-13T14:00:00Z",
    "block_end_time": "2026-07-13T17:00:00Z",
    "sessions": [
        {
            # Imminent session: session_id + entry_count populated
            "season_id": 6266,
            "start_time": "2026-07-13T14:15:00Z",
            "super_session": False,
            "series_id": 571,
            "race_week_num": 3,
            "end_time": "2026-07-13T14:41:00Z",
            "session_id": 315364654,
            "entry_count": 153,
        },
        {
            # Far-future session: no session_id, entry_count 0
            # (per findings: these only populate ~30 min before start)
            "season_id": 6314,
            "start_time": "2026-07-14T18:15:00Z",
            "super_session": False,
            "series_id": 520,
            "race_week_num": 3,
            "end_time": "2026-07-14T18:41:00Z",
            "entry_count": 0,
        },
    ],
}


class TestParseRaceGuide:
    def test_parses_populated_session(self):
        sessions = parse_race_guide(RACE_GUIDE_PAYLOAD)
        assert len(sessions) == 2
        first = sessions[0]
        assert isinstance(first, RaceGuideSession)
        assert first.series_id == 571
        assert first.season_id == 6266
        assert first.race_week_num == 3
        assert first.start_time == "2026-07-13T14:15:00Z"
        assert first.end_time == "2026-07-13T14:41:00Z"
        assert first.session_id == 315364654
        assert first.entry_count == 153
        assert first.super_session is False

    def test_tolerates_missing_session_id_and_zero_entries(self):
        sessions = parse_race_guide(RACE_GUIDE_PAYLOAD)
        future = sessions[1]
        assert future.session_id is None
        assert future.entry_count == 0

    def test_empty_sessions_returns_empty_list(self):
        assert parse_race_guide({"success": True, "sessions": []}) == []

    def test_missing_sessions_key_returns_empty_list(self):
        assert parse_race_guide({"success": True}) == []

    def test_non_dict_payload_returns_empty_list(self):
        assert parse_race_guide(None) == []
        assert parse_race_guide([]) == []


class TestGetRaceGuide:
    def test_calls_endpoint_and_parses(self):
        api = _api_with_fake_client({
            "/data/season/race_guide": {"link": "https://s3.example/guide"},
            "s3.example/guide": RACE_GUIDE_PAYLOAD,
        })
        sessions = api.get_race_guide()
        assert len(sessions) == 2
        assert sessions[0].entry_count == 153
        # No params when from_time omitted
        assert api._client.params[0] is None

    def test_passes_from_param(self):
        api = _api_with_fake_client({
            "/data/season/race_guide": {"link": "https://s3.example/guide"},
            "s3.example/guide": {"sessions": []},
        })
        api.get_race_guide(from_time="2026-07-14T18:00:00Z")
        assert api._client.params[0] == {"from": "2026-07-14T18:00:00Z"}


class TestStubRaceGuide:
    def test_returns_empty(self):
        assert StubIRacingAPI().get_race_guide() == []
