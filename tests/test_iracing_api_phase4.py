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
    SeriesResultRow,
    StubIRacingAPI,
    _TokenData,
    parse_race_guide,
    parse_series_results,
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


# ---------------------------------------------------------------------------
# Series results search — /data/results/search_series
# ---------------------------------------------------------------------------

# Modeled on data/api_spike/search_series_571_wk3.json (names anonymized)
SEARCH_SERIES_ROW = {
    "session_id": 314670231,
    "subsession_id": 87005528,
    "start_time": "2026-07-07T00:15:00Z",
    "end_time": "2026-07-07T00:41:33Z",
    "license_category_id": 5,
    "license_category": "Sports Car",
    "num_drivers": 12,
    "num_cautions": 0,
    "num_caution_laps": 0,
    "num_lead_changes": 0,
    "event_average_lap": 814347,
    "event_best_lap_time": 803891,
    "event_laps_complete": 9,
    "driver_changes": False,
    "winner_group_id": 125274,
    "winner_name": "Driver A",
    "winner_ai": False,
    "track": {
        "config_name": "Summit Point Raceway",
        "track_id": 9,
        "track_name": "Summit Point Raceway",
    },
    "official_session": True,
    "season_id": 6266,
    "season_year": 2026,
    "season_quarter": 3,
    "event_type": 5,
    "event_type_name": "Race",
    "series_id": 571,
    "series_name": "BMW M2 Cup",
    "series_short_name": "BMW M2 Cup",
    "race_week_num": 3,
    "event_strength_of_field": 2542,
}


class TestParseSeriesResults:
    def test_parses_row(self):
        rows = parse_series_results([SEARCH_SERIES_ROW])
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, SeriesResultRow)
        assert row.subsession_id == 87005528
        assert row.session_id == 314670231  # timeslot / split-group key
        assert row.start_time == "2026-07-07T00:15:00Z"
        assert row.strength_of_field == 2542
        assert row.num_drivers == 12
        assert row.track_id == 9
        assert row.track_name == "Summit Point Raceway"
        assert row.series_id == 571
        assert row.season_id == 6266
        assert row.race_week_num == 3
        assert row.num_cautions == 0
        assert row.num_lead_changes == 0
        assert row.winner_name == "Driver A"
        assert row.winner_cust_id == 125274

    def test_lap_times_converted_to_seconds(self):
        row = parse_series_results([SEARCH_SERIES_ROW])[0]
        assert row.event_best_lap_time == pytest.approx(80.3891)
        assert row.event_average_lap == pytest.approx(81.4347)

    def test_missing_track_and_winner_tolerated(self):
        bare = {"subsession_id": 1, "session_id": 2}
        row = parse_series_results([bare])[0]
        assert row.track_id == 0
        assert row.track_name == ""
        assert row.winner_name == ""
        assert row.winner_cust_id == 0
        assert row.event_best_lap_time == 0.0

    def test_empty_input(self):
        assert parse_series_results([]) == []
        assert parse_series_results(None) == []


class TestSearchSeriesResults:
    def _chunked_api(self, head_payload, chunks=None):
        routes = {
            "/data/results/search_series": {"link": "https://s3.example/search"},
            "s3.example/search": head_payload,
        }
        if chunks:
            routes.update(chunks)
        return _api_with_fake_client(routes)

    def test_normalizes_nested_chunk_info(self):
        """search_series nests chunk_info under data (one level deeper
        than lap_chart_data / lap_data) — the client must normalize."""
        head = {
            "data": {
                "success": True,
                "chunk_info": {
                    "base_download_url": "https://s3.example/",
                    "chunk_file_names": ["chunk-0.json"],
                },
            }
        }
        api = self._chunked_api(
            head, {"chunk-0.json": [SEARCH_SERIES_ROW]}
        )
        rows = api.search_series_results(
            season_year=2026, season_quarter=3,
            series_id=571, race_week_num=3,
        )
        assert len(rows) == 1
        assert rows[0].subsession_id == 87005528

    def test_top_level_chunk_info_also_handled(self):
        head = {
            "success": True,
            "chunk_info": {
                "base_download_url": "https://s3.example/",
                "chunk_file_names": ["chunk-0.json"],
            },
        }
        api = self._chunked_api(
            head, {"chunk-0.json": [SEARCH_SERIES_ROW]}
        )
        rows = api.search_series_results(season_id=6266, race_week_num=3)
        assert len(rows) == 1

    def test_empty_but_success_returns_empty_list(self):
        """No results yet is not an error — and callers must never
        disk-cache this emptiness (race-capture _cached_fetch lesson)."""
        head = {"data": {"success": True, "chunk_info": None}}
        api = self._chunked_api(head)
        assert api.search_series_results(season_id=6266) == []

    def test_passes_params(self):
        head = {"data": {"success": True}}
        api = self._chunked_api(head)
        api.search_series_results(
            season_year=2026, season_quarter=3, series_id=571,
            race_week_num=3, official_only=True, event_types=5,
        )
        params = api._client.params[0]
        assert params["season_year"] == 2026
        assert params["season_quarter"] == 3
        assert params["series_id"] == 571
        assert params["race_week_num"] == 3
        assert params["official_only"] is True
        assert params["event_types"] == 5

    def test_omits_unset_params(self):
        head = {"data": {"success": True}}
        api = self._chunked_api(head)
        api.search_series_results(season_id=6266)
        params = api._client.params[0]
        assert params["season_id"] == 6266
        assert "season_year" not in params
        assert "series_id" not in params
        assert "race_week_num" not in params


class TestStubSearchSeries:
    def test_returns_empty(self):
        assert StubIRacingAPI().search_series_results(season_id=6266) == []
