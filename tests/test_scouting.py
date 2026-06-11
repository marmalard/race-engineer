"""Tests for the scouting report orchestrator and pace context."""

from unittest.mock import MagicMock, patch

import pytest

import core.benchmark.iracing_api as iracing_api_module
from core.benchmark.iracing_api import RecentRace
from core.coaching.prompts.scouting import build_scouting_prompt
from core.coaching.scouting import (
    PaceContext,
    _build_pace_context,
    _filter_races,
    _name_matches,
    _try_fetch_pace_context,
)


def _make_race(**kwargs) -> RecentRace:
    """Create a RecentRace with sensible defaults, overridable by kwargs."""
    defaults = dict(
        session_id=1,
        series_name="Test Series",
        track_name="Road America",
        track_id=18,
        car_name="BMW M4 GT4",
        car_id=72,
        start_position=5,
        finish_position=3,
        incidents=2,
        best_lap_time=141.456,
        best_qual_lap_time=140.234,
        strength_of_field=1850,
        field_size=20,
        session_start_time="2026-02-20T19:00:00Z",
        irating_new=1600,
        irating_old=1550,
    )
    defaults.update(kwargs)
    return RecentRace(**defaults)


class TestNameMatches:
    def test_query_in_api_name(self) -> None:
        assert _name_matches("Road America", "road america")

    def test_api_name_in_query(self) -> None:
        assert _name_matches("Road America", "road america full course")

    def test_partial_match(self) -> None:
        assert _name_matches("Circuit de Spa-Francorchamps", "spa")

    def test_no_match(self) -> None:
        assert not _name_matches("Road America", "monza")

    def test_case_insensitive(self) -> None:
        assert _name_matches("BMW M4 GT4", "bmw m4 gt4")


class TestFilterRaces:
    def test_car_and_track_match(self) -> None:
        races = [
            _make_race(track_name="Road America", car_name="BMW M4 GT4"),
            _make_race(track_name="Spa", car_name="BMW M4 GT4"),
        ]
        result = _filter_races(races, "BMW M4 GT4", "Road America")
        assert len(result) == 1
        assert result[0].track_name == "Road America"

    def test_track_only_fallback(self) -> None:
        races = [
            _make_race(track_name="Road America", car_name="Porsche 911 GT3 Cup"),
        ]
        result = _filter_races(races, "BMW M4 GT4", "Road America")
        assert len(result) == 1  # Falls back to track-only match

    def test_no_match(self) -> None:
        races = [
            _make_race(track_name="Monza", car_name="MX-5"),
        ]
        result = _filter_races(races, "BMW M4 GT4", "Road America")
        assert len(result) == 0

    def test_multiple_matches(self) -> None:
        races = [
            _make_race(track_name="Road America", car_name="BMW M4 GT4", best_lap_time=142.0),
            _make_race(track_name="Road America", car_name="BMW M4 GT4", best_lap_time=141.0),
        ]
        result = _filter_races(races, "BMW M4 GT4", "Road America")
        assert len(result) == 2


class TestBuildPaceContext:
    def test_basic_context(self) -> None:
        races = [
            _make_race(best_lap_time=141.0, best_qual_lap_time=140.0, finish_position=3),
            _make_race(best_lap_time=142.0, best_qual_lap_time=141.0, finish_position=5),
        ]
        ctx = _build_pace_context(races)
        assert ctx.race_count == 2
        assert ctx.driver_best_lap == pytest.approx(141.0)
        assert ctx.driver_best_qual == pytest.approx(140.0)
        assert ctx.avg_finish_position == pytest.approx(4.0)

    def test_skips_zero_lap_times(self) -> None:
        races = [
            _make_race(best_lap_time=0, best_qual_lap_time=0),
        ]
        ctx = _build_pace_context(races)
        assert ctx.driver_best_lap is None
        assert ctx.driver_best_qual is None

    def test_race_dicts_format(self) -> None:
        races = [_make_race(best_lap_time=141.456)]
        ctx = _build_pace_context(races)
        assert len(ctx.matching_races) == 1
        assert ctx.matching_races[0]["series"] == "Test Series"
        assert "2:21" in ctx.matching_races[0]["best_lap"]


class TestTryFetchPaceContext:
    def test_returns_none_without_credentials(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = _try_fetch_pace_context("BMW M4 GT4", "Road America")
        assert result is None

    def test_returns_none_with_partial_credentials(self) -> None:
        env = {"IRACING_CLIENT_ID": "id", "IRACING_CLIENT_SECRET": "secret"}
        with patch.dict("os.environ", env, clear=True):
            result = _try_fetch_pace_context("BMW M4 GT4", "Road America")
        assert result is None

    def test_returns_none_on_api_error(self) -> None:
        env = {
            "IRACING_CLIENT_ID": "id",
            "IRACING_CLIENT_SECRET": "secret",
            "IRACING_USERNAME": "user",
            "IRACING_PASSWORD": "pass",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch.object(iracing_api_module, "LiveIRacingAPI") as MockAPI:
            mock_api = MagicMock()
            mock_api.__enter__ = MagicMock(return_value=mock_api)
            mock_api.__exit__ = MagicMock(return_value=False)
            mock_api.get_member_recent_races.side_effect = RuntimeError("API down")
            MockAPI.return_value = mock_api

            result = _try_fetch_pace_context("BMW M4 GT4", "Road America")
        assert result is None

    def test_returns_empty_context_when_no_matches(self) -> None:
        env = {
            "IRACING_CLIENT_ID": "id",
            "IRACING_CLIENT_SECRET": "secret",
            "IRACING_USERNAME": "user",
            "IRACING_PASSWORD": "pass",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch.object(iracing_api_module, "LiveIRacingAPI") as MockAPI:
            mock_api = MagicMock()
            mock_api.__enter__ = MagicMock(return_value=mock_api)
            mock_api.__exit__ = MagicMock(return_value=False)
            mock_api.get_member_recent_races.return_value = [
                _make_race(track_name="Monza", car_name="MX-5"),
            ]
            MockAPI.return_value = mock_api

            result = _try_fetch_pace_context("BMW M4 GT4", "Road America")
        assert result is not None
        assert result.race_count == 0


class TestBuildScoutingPromptWithPaceContext:
    def test_prompt_without_pace_context(self) -> None:
        prompt = build_scouting_prompt("BMW M4 GT4", "Road America")
        assert "DRIVER'S OWN RACE HISTORY" not in prompt
        assert "BMW M4 GT4" in prompt
        assert "Road America" in prompt

    def test_prompt_with_pace_context(self) -> None:
        ctx = PaceContext(
            matching_races=[{"series": "Test", "best_lap": "2:21.456"}],
            driver_best_lap=141.456,
            driver_best_qual=140.234,
            avg_finish_position=3.0,
            avg_sof=1850,
            race_count=1,
        )
        prompt = build_scouting_prompt(
            "BMW M4 GT4", "Road America", pace_context=ctx
        )
        assert "DRIVER'S OWN RACE HISTORY" in prompt
        assert "2:21" in prompt
        assert "1 recent race" in prompt

    def test_prompt_with_empty_pace_context(self) -> None:
        ctx = PaceContext(race_count=0)
        prompt = build_scouting_prompt(
            "BMW M4 GT4", "Road America", pace_context=ctx
        )
        assert "DRIVER'S OWN RACE HISTORY" not in prompt
