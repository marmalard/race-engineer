"""Tests for the Phase 4 Data API plumbing (pre-race briefing endpoints).

Parse functions are tested with inline dict payloads modeled on real
recorded responses from the 2026-07-13 spike (data/api_spike/, gitignored).
No live API calls here — client methods use a fake HTTP client.
"""

import pytest

from core.benchmark.iracing_api import (
    CareerStats,
    IRatingPoint,
    LiveIRacingAPI,
    MemberLicense,
    MemberProfile,
    RaceGuideSession,
    RaceWeek,
    RegisteredDriver,
    SeasonSchedule,
    SeriesResultRow,
    SpectatorSubsession,
    StubIRacingAPI,
    _TokenData,
    _rating_or_none,
    parse_chart_data,
    parse_member_career,
    parse_member_profile,
    parse_race_guide,
    parse_reg_drivers,
    parse_season_schedules,
    parse_series_results,
    parse_spectator_subsessions,
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

    def test_official_session_flag_parsed(self):
        row = parse_series_results([SEARCH_SERIES_ROW])[0]
        assert row.official_session is True

    def test_no_valid_lap_sentinel_becomes_zero(self):
        # The API reports -1 when no valid lap exists; pace math doing
        # min() over split best-laps must never see the sentinel.
        dirty = dict(SEARCH_SERIES_ROW)
        dirty["event_best_lap_time"] = -1
        dirty["event_average_lap"] = -1
        row = parse_series_results([dirty])[0]
        assert row.event_best_lap_time == 0.0
        assert row.event_average_lap == 0.0

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


# ---------------------------------------------------------------------------
# Registered drivers roster — /data/session/reg_drivers_list
# ---------------------------------------------------------------------------

# Modeled on data/api_spike/reg_drivers_live_87170269.json (anonymized)
REG_DRIVERS_PAYLOAD = {
    "subscribed": True,
    "subsession_id": 87170269,
    "success": True,
    "entries": [
        {
            "cust_id": 414541,
            "display_name": "Driver B",
            "car_id": 213,
            "car_name": "EURO NASCAR V8GP",
            "car_class_id": 4104,
            "car_class_name": "EURO NASCAR V8GP",
            "reg_status": "reg_joined",
            "license": {
                "category_id": 5,
                "category": "sports_car",
                "category_name": "Sports Car",
                "license_level": 17,
                "safety_rating": 1.19,
                "cpi": 26.174011,
                "irating": 1467,
                "tt_rating": 1350,
                "mpr_num_races": 18,
                "group_name": "Class A",
                "group_id": 5,
            },
            "session_id": 315364678,
            "subsession_id": 87170269,
            "event_type": 5,
        },
    ],
}


class TestRatingOrNone:
    def test_unrated_minus_one_is_none(self):
        assert _rating_or_none(-1) is None

    def test_normal_value_passes(self):
        assert _rating_or_none(1467) == 1467

    def test_none_passes_through(self):
        assert _rating_or_none(None) is None

    def test_zero_passes(self):
        assert _rating_or_none(0) == 0


class TestParseRegDrivers:
    def test_parses_entry(self):
        drivers = parse_reg_drivers(REG_DRIVERS_PAYLOAD)
        assert len(drivers) == 1
        d = drivers[0]
        assert isinstance(d, RegisteredDriver)
        assert d.cust_id == 414541
        assert d.display_name == "Driver B"
        assert d.car_id == 213
        assert d.car_name == "EURO NASCAR V8GP"
        assert d.reg_status == "reg_joined"
        assert d.irating == 1467
        assert d.safety_rating == pytest.approx(1.19)
        assert d.cpi == pytest.approx(26.174011)
        assert d.license_level == 17
        assert d.group_name == "Class A"
        assert d.mpr_num_races == 18

    def test_unrated_driver_irating_none(self):
        payload = {
            "entries": [{
                "cust_id": 1,
                "display_name": "Driver C",
                "license": {"irating": -1, "safety_rating": 2.5},
            }],
        }
        d = parse_reg_drivers(payload)[0]
        assert d.irating is None
        assert d.safety_rating == pytest.approx(2.5)

    def test_missing_license_block_tolerated(self):
        payload = {"entries": [{"cust_id": 1, "display_name": "Driver C"}]}
        d = parse_reg_drivers(payload)[0]
        assert d.irating is None
        assert d.safety_rating is None
        assert d.cpi is None
        assert d.group_name == ""

    def test_empty_entries(self):
        """Pre-launch and post-completion: success true, entries empty."""
        payload = {"subscribed": True, "entries": [], "success": True}
        assert parse_reg_drivers(payload) == []

    def test_non_dict_payload(self):
        assert parse_reg_drivers(None) == []


# ---------------------------------------------------------------------------
# Spectator subsession discovery — /data/season/spectator_subsessionids_detail
# ---------------------------------------------------------------------------

# Modeled on data/api_spike/spectator_subsession_detail.json
SPECTATOR_PAYLOAD = {
    "success": True,
    "season_ids": [6404, 6265],
    "event_types": [5],
    "subsessions": [
        {
            "subsession_id": 87170269,
            "session_id": 315364678,
            "season_id": 6404,
            "start_time": "2026-07-13T14:15:00Z",
            "race_week_num": 3,
            "event_type": 5,
        },
        {
            "subsession_id": 87170000,
            "session_id": 315363545,
            "season_id": 6265,
            "start_time": "2026-07-13T14:00:00Z",
            "race_week_num": 3,
            "event_type": 5,
        },
    ],
}


class TestParseSpectatorSubsessions:
    def test_parses_rows(self):
        subs = parse_spectator_subsessions(SPECTATOR_PAYLOAD)
        assert len(subs) == 2
        first = subs[0]
        assert isinstance(first, SpectatorSubsession)
        assert first.subsession_id == 87170269
        assert first.session_id == 315364678
        assert first.season_id == 6404
        assert first.start_time == "2026-07-13T14:15:00Z"
        assert first.race_week_num == 3
        assert first.event_type == 5

    def test_empty_and_malformed(self):
        assert parse_spectator_subsessions({"success": True}) == []
        assert parse_spectator_subsessions(None) == []


class TestGetRegDriversAndSpectator:
    def test_get_reg_drivers_passes_subsession_id(self):
        api = _api_with_fake_client({
            "/data/session/reg_drivers_list": {"link": "https://s3.example/reg"},
            "s3.example/reg": REG_DRIVERS_PAYLOAD,
        })
        drivers = api.get_reg_drivers(87170269)
        assert len(drivers) == 1
        assert api._client.params[0] == {"subsession_id": 87170269}

    def test_get_spectator_subsessions_passes_event_types(self):
        api = _api_with_fake_client({
            "/data/season/spectator_subsessionids_detail":
                {"link": "https://s3.example/spec"},
            "s3.example/spec": SPECTATOR_PAYLOAD,
        })
        subs = api.get_spectator_subsessions()
        assert len(subs) == 2
        assert api._client.params[0] == {"event_types": 5}


class TestStubRoster:
    def test_returns_empty(self):
        stub = StubIRacingAPI()
        assert stub.get_reg_drivers(87170269) == []
        assert stub.get_spectator_subsessions() == []


# ---------------------------------------------------------------------------
# Series seasons / calendar — /data/series/seasons?include_series=true
# ---------------------------------------------------------------------------

# Modeled on data/api_spike/series_seasons.json — trimmed hard: the real
# payload is ~7 MB per season list; the parser must keep only the briefing
# slice and drop everything else (weather blobs, liveries, etc.).
SEASON_PAYLOAD = {
    "season_id": 6265,
    "season_name": "Global Mazda MX-5 Cup by Fanatec - 2026 Season 3",
    "active": True,
    "series_id": 139,
    # series_name is NOT present at season top level (only in schedules)
    "series_name": None,
    "race_week": 3,
    "max_weeks": 12,
    "fixed_setup": True,
    "reg_user_count": 320,
    "schedules": [
        {
            "season_id": 6265,
            "race_week_num": 0,
            "series_id": 139,
            "series_name": "Global Mazda MX-5 Cup by Fanatec",
            "start_date": "2026-06-16",
            "start_type": "Standing",
            "race_lap_limit": None,
            "race_time_limit": 12,
            "qual_attached": True,
            "car_restrictions": [
                {
                    "car_id": 67,
                    "max_dry_tire_sets": 0,
                    "max_pct_fuel_fill": 100,
                    "power_adjust_pct": 0,
                    "weight_penalty_kg": 0,
                },
            ],
            "track": {
                "category": "road",
                "category_id": 2,
                "config_name": "Full Course",
                "track_id": 166,
                "track_name": "Okayama International Circuit",
            },
            "weather": {"skies": 2},  # large blob in reality; must be dropped
        },
        {
            "season_id": 6265,
            "race_week_num": 3,
            "series_id": 139,
            "series_name": "Global Mazda MX-5 Cup by Fanatec",
            "start_date": "2026-07-07",
            "start_type": "Rolling",
            "race_lap_limit": 14,
            "race_time_limit": None,
            "car_restrictions": [],
            "track": {
                "config_name": "Summit Point Raceway",
                "track_id": 9,
                "track_name": "Summit Point Raceway",
            },
        },
    ],
}


class TestParseSeasonSchedules:
    def test_parses_season_slice(self):
        seasons = parse_season_schedules([SEASON_PAYLOAD])
        assert len(seasons) == 1
        s = seasons[0]
        assert isinstance(s, SeasonSchedule)
        assert s.series_id == 139
        assert s.season_id == 6265
        assert s.season_name == (
            "Global Mazda MX-5 Cup by Fanatec - 2026 Season 3"
        )
        # series_name comes from the schedules (not season top level)
        assert s.series_name == "Global Mazda MX-5 Cup by Fanatec"
        assert s.race_week == 3
        assert s.max_weeks == 12
        assert len(s.weeks) == 2

    def test_parses_week_race_format(self):
        s = parse_season_schedules([SEASON_PAYLOAD])[0]
        wk0 = s.weeks[0]
        assert isinstance(wk0, RaceWeek)
        assert wk0.race_week_num == 0
        assert wk0.track_id == 166
        assert wk0.track_name == "Okayama International Circuit"
        assert wk0.config_name == "Full Course"
        assert wk0.start_date == "2026-06-16"
        assert wk0.race_time_limit == 12
        assert wk0.race_lap_limit is None
        assert wk0.start_type == "Standing"
        assert wk0.standing_start is True
        assert wk0.max_pct_fuel_fill == 100

    def test_lap_limited_rolling_week(self):
        s = parse_season_schedules([SEASON_PAYLOAD])[0]
        wk3 = s.weeks[1]
        assert wk3.race_lap_limit == 14
        assert wk3.race_time_limit is None
        assert wk3.standing_start is False
        assert wk3.max_pct_fuel_fill is None  # no car_restrictions entry

    def test_accepts_seasons_wrapper_dict(self):
        seasons = parse_season_schedules({"seasons": [SEASON_PAYLOAD]})
        assert len(seasons) == 1

    def test_empty_and_malformed(self):
        assert parse_season_schedules([]) == []
        assert parse_season_schedules(None) == []
        assert parse_season_schedules({"success": True}) == []

    def test_season_without_schedules(self):
        bare = {"season_id": 1, "series_id": 2, "race_week": 0}
        s = parse_season_schedules([bare])[0]
        assert s.weeks == []
        assert s.series_name == ""


class TestGetSeriesSeasons:
    def test_calls_endpoint_with_include_series(self):
        api = _api_with_fake_client({
            "/data/series/seasons": {"link": "https://s3.example/seasons"},
            "s3.example/seasons": [SEASON_PAYLOAD],
        })
        seasons = api.get_series_seasons()
        assert len(seasons) == 1
        assert api._client.params[0] == {"include_series": True}


class TestStubSeriesSeasons:
    def test_returns_empty(self):
        assert StubIRacingAPI().get_series_seasons() == []


# ---------------------------------------------------------------------------
# Opponent primitives — member profile / chart_data / career
# ---------------------------------------------------------------------------

# Modeled on data/api_spike/member_profile_1523425.json (anonymized)
MEMBER_PROFILE_PAYLOAD = {
    "success": True,
    "cust_id": 1523425,
    "member_info": {
        "cust_id": 1523425,
        "display_name": "Driver D",
        "member_since": "2025-11-02",
        "last_login": "2026-07-13T01:12:00Z",
        "licenses": [
            {
                "category_id": 1,
                "category": "oval",
                "category_name": "Oval",
                "license_level": 2,
                "safety_rating": 2.45,
                "cpi": 9.808207,
                "irating": 1321,
                "tt_rating": 1350,
                "mpr_num_races": 1,
                "group_name": "Rookie",
                "group_id": 1,
            },
            {
                "category_id": 5,
                "category": "sports_car",
                "category_name": "Sports Car",
                "license_level": 10,
                "safety_rating": 3.1,
                "cpi": 35.2,
                "irating": -1,  # unrated in this category
                "group_name": "Class C",
                "group_id": 3,
            },
        ],
    },
    "license_history": [],
    "recent_awards": [],
    "activity": {},
    "follow_counts": {},
}

# Modeled on data/api_spike/chart_data_1523425.json
CHART_DATA_PAYLOAD = {
    "blackout": False,
    "category_id": 5,
    "chart_type": 1,
    "success": True,
    "cust_id": 1523425,
    "data": [
        {"when": "2026-07-04", "value": 1380},
        {"when": "2026-07-07", "value": 1360},
        {"when": "2026-07-13", "value": 1528},
    ],
}

# Modeled on data/api_spike/member_career_1523425.json
MEMBER_CAREER_PAYLOAD = {
    "cust_id": 1523425,
    "stats": [
        {
            "category_id": 5,
            "category": "Sports Car",
            "starts": 23,
            "wins": 6,
            "top5": 11,
            "poles": 4,
            "avg_start_position": 7,
            "avg_finish_position": 6,
            "laps": 165,
            "laps_led": 48,
            "avg_incidents": 6.3043,
            "avg_points": 44,
            "win_percentage": 26.09,
            "top5_percentage": 47.83,
            "laps_led_percentage": 29.09,
            "poles_percentage": 17.39,
        },
        {
            "category_id": 3,
            "category": "Dirt Oval",
            "starts": 0,
            "wins": 0,
            "top5": 0,
            "poles": 0,
            "avg_start_position": 0,
            "avg_finish_position": 0,
            "laps": 0,
            "laps_led": 0,
            "avg_incidents": 0,
            "win_percentage": 0,
        },
    ],
}


class TestParseMemberProfile:
    def test_parses_profile(self):
        profile = parse_member_profile(MEMBER_PROFILE_PAYLOAD)
        assert isinstance(profile, MemberProfile)
        assert profile.cust_id == 1523425
        assert profile.display_name == "Driver D"
        assert len(profile.licenses) == 2

    def test_parses_license_fields(self):
        profile = parse_member_profile(MEMBER_PROFILE_PAYLOAD)
        oval = profile.licenses[0]
        assert isinstance(oval, MemberLicense)
        assert oval.category_id == 1
        assert oval.category == "oval"
        assert oval.irating == 1321
        assert oval.safety_rating == pytest.approx(2.45)
        assert oval.cpi == pytest.approx(9.808207)
        assert oval.license_level == 2
        assert oval.group_name == "Rookie"

    def test_unrated_category_irating_none(self):
        profile = parse_member_profile(MEMBER_PROFILE_PAYLOAD)
        sports = profile.licenses[1]
        assert sports.irating is None
        assert sports.group_name == "Class C"

    def test_license_lookup_by_category(self):
        profile = parse_member_profile(MEMBER_PROFILE_PAYLOAD)
        assert profile.license_for_category(5).group_name == "Class C"
        assert profile.license_for_category(99) is None

    def test_malformed_returns_none(self):
        assert parse_member_profile(None) is None
        assert parse_member_profile({}) is None
        assert parse_member_profile({"success": True}) is None


class TestParseChartData:
    def test_parses_points(self):
        points = parse_chart_data(CHART_DATA_PAYLOAD)
        assert len(points) == 3
        assert isinstance(points[0], IRatingPoint)
        assert points[0].when == "2026-07-04"
        assert points[0].value == 1380
        assert points[-1].value == 1528

    def test_empty_and_malformed(self):
        assert parse_chart_data({"success": True, "data": []}) == []
        assert parse_chart_data({"success": True}) == []
        assert parse_chart_data(None) == []


class TestParseMemberCareer:
    def test_parses_category_stats(self):
        stats = parse_member_career(MEMBER_CAREER_PAYLOAD)
        assert len(stats) == 2
        sports = stats[0]
        assert isinstance(sports, CareerStats)
        assert sports.category_id == 5
        assert sports.category == "Sports Car"
        assert sports.starts == 23
        assert sports.wins == 6
        assert sports.top5 == 11
        assert sports.win_percentage == pytest.approx(26.09)
        assert sports.avg_incidents == pytest.approx(6.3043)
        assert sports.avg_start_position == 7
        assert sports.avg_finish_position == 6
        assert sports.laps == 165
        assert sports.laps_led == 48

    def test_empty_and_malformed(self):
        assert parse_member_career({"cust_id": 1, "stats": []}) == []
        assert parse_member_career({"cust_id": 1}) == []
        assert parse_member_career(None) == []


class TestOpponentClientMethods:
    def test_get_member_profile_passes_cust_id(self):
        api = _api_with_fake_client({
            "/data/member/profile": {"link": "https://s3.example/prof"},
            "s3.example/prof": MEMBER_PROFILE_PAYLOAD,
        })
        profile = api.get_member_profile(1523425)
        assert profile.display_name == "Driver D"
        assert api._client.params[0] == {"cust_id": 1523425}

    def test_get_member_chart_data_defaults(self):
        api = _api_with_fake_client({
            "/data/member/chart_data": {"link": "https://s3.example/chart"},
            "s3.example/chart": CHART_DATA_PAYLOAD,
        })
        points = api.get_member_chart_data(1523425)
        assert len(points) == 3
        # sports_car iRating by default: category_id 5, chart_type 1
        assert api._client.params[0] == {
            "cust_id": 1523425, "category_id": 5, "chart_type": 1,
        }

    def test_get_member_career_passes_cust_id(self):
        api = _api_with_fake_client({
            "/data/stats/member_career": {"link": "https://s3.example/career"},
            "s3.example/career": MEMBER_CAREER_PAYLOAD,
        })
        stats = api.get_member_career(1523425)
        assert stats[0].starts == 23
        assert api._client.params[0] == {"cust_id": 1523425}


class TestStubOpponentMethods:
    def test_graceful_empties(self):
        stub = StubIRacingAPI()
        assert stub.get_member_profile(1523425) is None
        assert stub.get_member_chart_data(1523425) == []
        assert stub.get_member_career(1523425) == []


class TestNullListKeys:
    def test_present_but_null_list_keys_return_empty(self):
        # A payload with the list key present but null must not raise -
        # these parsers sit on the briefing's live network path.
        assert parse_race_guide({"sessions": None}) == []
        assert parse_reg_drivers({"entries": None}) == []
        assert parse_spectator_subsessions({"subsessions": None}) == []
        assert parse_season_schedules({"seasons": None}) == []
        assert parse_chart_data({"data": None}) == []
        assert parse_member_career({"stats": None}) == []

    def test_null_schedules_within_season_tolerated(self):
        seasons = parse_season_schedules(
            [{"series_id": 571, "season_id": 6266, "schedules": None}]
        )
        assert seasons[0].weeks == []
