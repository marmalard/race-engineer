"""Tests for core/briefing: models smoke + pure curve math."""

from core.briefing.models import BriefingData, RaceFormat


def test_briefing_data_defaults():
    b = BriefingData(
        series_name="M2 Cup",
        season_id=10,
        race_week=2,
        fmt=RaceFormat(
            track_name="Summit Point Raceway",
            config_name="Summit Point Raceway",
            race_time_limit=12,
            race_lap_limit=None,
            standing_start=True,
            max_pct_fuel_fill=None,
        ),
    )
    assert b.curve is None and b.placement is None and b.prep is None
    assert b.slots == [] and b.warnings == []
