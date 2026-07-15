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
