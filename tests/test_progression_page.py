"""Page-level pure helpers + nav registration for the Progression page."""

from app.navigation import NAV_SPEC
from app.pages.progression import _lap_axis_ticks, _week_band_series
from core.progression.models import ComboImplied


class TestNavRegistration:
    def test_progression_first_in_practice_group(self):
        practice = dict(NAV_SPEC)["Practice"]
        assert practice[0].title == "Progression"
        assert practice[0].url_path == "progression"


class TestLapAxisTicks:
    def test_five_formatted_ticks_spanning_range(self):
        vals, texts = _lap_axis_ticks([90.0, 95.0, 100.0])
        assert len(vals) == 5 and len(texts) == 5
        assert vals[0] == 90.0 and vals[-1] == 100.0
        assert texts[0] == "1:30.000"

    def test_flat_series_still_renders(self):
        vals, texts = _lap_axis_ticks([100.0])
        assert len(vals) == 5


class TestWeekBandSeries:
    def test_aggregates_each_week(self):
        history = [
            ("2026-07-07", [ComboImplied("525", "Spa", "M2", "S", 160.0,
                                         1300, 1550, 10.0)]),
            ("2026-07-14", [ComboImplied("525", "Spa", "M2", "S", 159.5,
                                         1400, 1650, 12.0)]),
        ]
        weeks, los, his = _week_band_series(history)
        assert weeks == ["2026-07-07", "2026-07-14"]
        assert los == [1300, 1400]
        assert his == [1550, 1650]

    def test_empty_history(self):
        assert _week_band_series([]) == ([], [], [])
