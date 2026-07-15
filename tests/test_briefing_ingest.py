"""Briefing ingest: series ranking (pure) + harvest/build with fakes."""

from core.benchmark.iracing_api import RaceWeek, SeasonSchedule
from core.briefing.ingest import SeriesCandidate, rank_series_candidates
from core.track.track_db import SessionRow


def _season(season_id, series, week_num, track_id, track_name):
    return SeasonSchedule(
        series_id=season_id,
        series_name=series,
        season_id=season_id,
        season_name=f"{series} S3",
        race_week=week_num,
        max_weeks=12,
        weeks=[
            RaceWeek(
                race_week_num=week_num,
                track_id=track_id,
                track_name=track_name,
                config_name="",
                start_date="2026-07-14",
                race_time_limit=12,
                race_lap_limit=None,
                start_type="Standing",
                standing_start=True,
                max_pct_fuel_fill=None,
            )
        ],
    )


def _row(session_id, track_id, car, laps=10):
    return SessionRow(
        session_id=session_id,
        track_id=track_id,
        track_name="",
        car=car,
        session_type="Practice",
        session_date="2026-07-01 21-00-00",
        best_lap_time=90.0,
        lap_count=laps,
    )


class TestRankSeriesCandidates:
    def test_most_practiced_track_ranks_first(self):
        seasons = [
            _season(100, "M2 Cup", 2, 9, "Summit Point Raceway"),
            _season(200, "PCup", 2, 523, "Spa"),
        ]
        sessions = [
            _row("a", "9", "BMW M2"), _row("b", "9", "BMW M2"),
            _row("c", "9", "BMW M2"), _row("d", "523", "992 Cup"),
        ]
        ranked = rank_series_candidates(seasons, sessions)
        assert ranked[0].series_name == "M2 Cup"
        assert ranked[0].practice_sessions == 3
        assert ranked[1].practice_sessions == 1

    def test_unpracticed_series_still_listed(self):
        seasons = [_season(300, "FF1600", 4, 439, "Winton")]
        ranked = rank_series_candidates(seasons, [])
        assert ranked[0].practice_sessions == 0

    def test_current_week_missing_from_schedule_skipped(self):
        s = _season(400, "Odd", 9, 18, "Road America")
        s.weeks[0].race_week_num = 3  # schedule has no week 9 entry
        assert rank_series_candidates([s], []) == []


import json
from dataclasses import dataclass

from core.benchmark.iracing_api import RaceTimeDescriptor, SeriesResultRow
from core.briefing.ingest import build_briefing, harvest_field


def _series_row(subsession_id, session_id, sof, drivers, start="2026-07-15T01:15:00Z"):
    return SeriesResultRow(
        subsession_id=subsession_id, session_id=session_id, start_time=start,
        end_time=start, strength_of_field=sof, num_drivers=drivers,
        track_id=9, track_name="Summit Point Raceway",
        event_best_lap_time=82.0, event_average_lap=83.0,
        num_cautions=0, num_lead_changes=0, winner_name="", winner_cust_id=0,
        season_id=100, series_id=100, race_week_num=2, official_session=True,
    )


def _results_payload(laps_by_ir):
    """Minimal subsession-results payload parse_results understands."""
    return {
        "session_results": [{
            "simsession_number": 0,
            "results": [
                {
                    "cust_id": i, "display_name": f"D{i}",
                    "finish_position": i, "starting_position": i,
                    "laps_complete": 10, "incidents": 0,
                    "oldi_rating": ir, "newi_rating": ir,
                    "best_lap_time": int(lap * 10000),
                }
                for i, (ir, lap) in enumerate(laps_by_ir)
            ],
        }]
    }


class FakeAPI:
    def __init__(self, rows, payloads):
        self.rows = rows
        self.payloads = payloads  # subsession_id -> payload
        self.results_calls = []
        self.search_kwargs = None

    def search_series_results(self, **kwargs):
        self.search_kwargs = kwargs
        return self.rows

    def get_subsession_results(self, subsession_id):
        self.results_calls.append(subsession_id)
        return self.payloads[subsession_id]


class TestHarvestField:
    def test_points_and_field_stats(self, tmp_path):
        rows = [
            _series_row(1, 500, sof=1400, drivers=14),
            _series_row(2, 500, sof=1100, drivers=12),
            _series_row(3, 501, sof=1450, drivers=15),
        ]
        payloads = {
            1: _results_payload([(1400, 82.0)] * 6),
            2: _results_payload([(1100, 83.0)] * 6),
            3: _results_payload([(1450, 82.1)] * 6),
        }
        api = FakeAPI(rows, payloads)
        curve, stats = harvest_field(api, 100, 2, cache_dir=tmp_path)
        assert len(curve.points) == 18
        assert curve.subsessions_used == 3
        assert curve.capped is False
        assert stats.sof_median == 1400
        assert stats.field_size_median == 14
        assert stats.splits_median == 1  # session 500 has 2, 501 has 1 -> median 1.5 -> int 1

    def test_cache_hit_skips_api(self, tmp_path):
        rows = [_series_row(1, 500, sof=1400, drivers=14)]
        payloads = {1: _results_payload([(1400, 82.0)] * 6)}
        api = FakeAPI(rows, payloads)
        harvest_field(api, 100, 2, cache_dir=tmp_path)
        api2 = FakeAPI(rows, {})  # would KeyError on API hit
        harvest_field(api2, 100, 2, cache_dir=tmp_path)
        assert api2.results_calls == []

    def test_empty_week_returns_empty_curve(self, tmp_path):
        api = FakeAPI([], {})
        curve, stats = harvest_field(api, 100, 2, cache_dir=tmp_path)
        assert curve.points == [] and stats is None

    def test_other_season_rows_filtered_out(self, tmp_path):
        # search_series ignores season_id server-side (verified live
        # 2026-07-15: year+quarter returns the whole week across ALL
        # series) - harvest must filter to this season client-side
        from dataclasses import replace

        alien = replace(
            _series_row(9, 900, sof=2800, drivers=20), season_id=999
        )
        rows = [_series_row(1, 500, sof=1400, drivers=14), alien]
        api = FakeAPI(rows, {1: _results_payload([(1400, 82.0)] * 6)})
        curve, stats = harvest_field(api, 100, 2, cache_dir=tmp_path)
        assert curve.subsessions_used == 1
        assert stats.sof_median == 1400  # alien SoF 2800 excluded

    def test_year_quarter_forwarded_to_search(self, tmp_path):
        api = FakeAPI([], {})
        harvest_field(
            api, 100, 2, cache_dir=tmp_path,
            season_year=2026, season_quarter=3,
        )
        assert api.search_kwargs["season_year"] == 2026
        assert api.search_kwargs["season_quarter"] == 3
        assert api.search_kwargs["race_week_num"] == 2


class TestBuildBriefing:
    def test_full_assembly(self, tmp_path):
        from core.benchmark.iracing_api import RaceWeek, SeasonSchedule

        season = SeasonSchedule(
            series_id=100, series_name="M2 Cup", season_id=100,
            season_name="M2 Cup S3", race_week=2, max_weeks=12,
            weeks=[RaceWeek(
                race_week_num=2, track_id=9,
                track_name="Summit Point Raceway", config_name="",
                start_date="2026-07-14", race_time_limit=12,
                race_lap_limit=None, start_type="Standing",
                standing_start=True, max_pct_fuel_fill=None,
                race_time_descriptors=[RaceTimeDescriptor(
                    repeating=True, first_session_time="00:15",
                    repeat_minutes=120, day_offset=[0, 1, 2, 3, 4, 5, 6],
                )],
            )],
        )
        rows = [_series_row(1, 500, sof=1400, drivers=14)]
        payloads = {1: _results_payload(
            [(1200 + 50 * i, 83.0 - 0.05 * i) for i in range(12)]
        )}
        api = FakeAPI(rows, payloads)
        sessions = [SessionRow(
            session_id=f"s{i}", track_id="9", track_name="Summit",
            car="BMW M2 CS Racing", session_type="Practice",
            session_date=f"2026-07-0{i + 1} 21-00-00",
            best_lap_time=82.2 + 0.1 * i, lap_count=12,
        ) for i in range(3)]
        laps = {f"s{i}": [] for i in range(3)}

        data = build_briefing(
            api=api, season=season, sessions=sessions, laps=laps,
            car="BMW M2 CS Racing", user_irating=1300,
            now_utc=__import__("datetime").datetime(
                2026, 7, 15, 22, 0,
                tzinfo=__import__("datetime").timezone.utc,
            ),
            cache_dir=tmp_path,
        )
        assert data.series_name == "M2 Cup"
        assert data.fmt.race_time_limit == 12
        assert data.curve is not None and data.placement is not None
        assert data.prep is not None and data.prep.sessions == 3
        assert len(data.slots) > 0
        assert data.user_irating == 1300

    def test_api_failure_degrades_with_warning(self, tmp_path):
        from core.benchmark.iracing_api import RaceWeek, SeasonSchedule

        class ExplodingAPI:
            def search_series_results(self, **kwargs):
                raise RuntimeError("api down")

        season = SeasonSchedule(
            series_id=100, series_name="M2 Cup", season_id=100,
            season_name="M2 Cup S3", race_week=2, max_weeks=12,
            weeks=[RaceWeek(
                race_week_num=2, track_id=9,
                track_name="Summit Point Raceway", config_name="",
                start_date="2026-07-14", race_time_limit=12,
                race_lap_limit=None, start_type="Standing",
                standing_start=True, max_pct_fuel_fill=None,
            )],
        )
        data = build_briefing(
            api=ExplodingAPI(), season=season, sessions=[], laps={},
            car="BMW M2 CS Racing", user_irating=None,
            now_utc=__import__("datetime").datetime(
                2026, 7, 15, tzinfo=__import__("datetime").timezone.utc
            ),
            cache_dir=tmp_path,
        )
        assert data.curve is None
        assert any("field data" in w for w in data.warnings)
