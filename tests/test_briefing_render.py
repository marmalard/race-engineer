"""Exact-string verdict tests (nudges/profile precedent) + markdown shape."""

from core.briefing.models import (
    BriefingData,
    ComboPrep,
    CurvePlacement,
    FieldStats,
    RaceFormat,
    RaceSlot,
)
from core.briefing.render import render_briefing, verdict_line


def _fmt():
    return RaceFormat(
        track_name="Summit Point Raceway", config_name="",
        race_time_limit=12, race_lap_limit=None,
        standing_start=True, max_pct_fuel_fill=None,
    )


class TestVerdictLine:
    def test_over_curve(self):
        p = CurvePlacement(
            lap_s=82.18, implied_ir_lo=1400, implied_ir_hi=1650,
            delta_to_own_band_s=-0.15,
        )
        assert verdict_line(p, user_ir=1300) == (
            "Your 1:22.180 runs like a 1,400-1,650 iR driver in this "
            "series this week - your pace is worth more iRating than you "
            "have. Racing is how you collect it."
        )

    def test_under_curve(self):
        p = CurvePlacement(
            lap_s=83.40, implied_ir_lo=1000, implied_ir_hi=1250,
            delta_to_own_band_s=0.42,
        )
        assert verdict_line(p, user_ir=1400) == (
            "The median at your rating runs 0.4s quicker this week - "
            "mid-pack is a strong result here, and practice has a clear "
            "target."
        )

    def test_on_curve(self):
        p = CurvePlacement(
            lap_s=82.5, implied_ir_lo=1300, implied_ir_hi=1550,
            delta_to_own_band_s=0.03,
        )
        assert verdict_line(p, user_ir=1400) == (
            "You're right on the pace for your rating - a clean race "
            "converts it to a solid finish."
        )

    def test_no_placement_invites(self):
        assert verdict_line(None, user_ir=1400) == (
            "Run a practice session at this combo and I'll place you on "
            "this week's curve."
        )

    def test_no_user_ir_reports_band_only(self):
        p = CurvePlacement(
            lap_s=82.18, implied_ir_lo=1400, implied_ir_hi=1650,
            delta_to_own_band_s=None,
        )
        assert verdict_line(p, user_ir=None) == (
            "Your 1:22.180 runs like a 1,400-1,650 iR driver in this "
            "series this week."
        )


class TestRenderBriefing:
    def test_full_render_contains_sections(self):
        data = BriefingData(
            series_name="M2 Cup", season_id=100, race_week=2, fmt=_fmt(),
            placement=CurvePlacement(
                lap_s=82.18, implied_ir_lo=1400, implied_ir_hi=1650,
                delta_to_own_band_s=-0.15,
            ),
            field_stats=FieldStats(
                sof_p25=1200, sof_median=1400, sof_p75=1600,
                field_size_median=14, splits_median=1,
            ),
            prep=ComboPrep(
                car="BMW M2 CS Racing", sessions=3,
                representative_laps=28, best_lap_s=82.18, trend_s=0.4,
            ),
            slots=[RaceSlot(start_utc="2026-07-16T00:15:00+00:00",
                            fits_window=True)],
            user_irating=1300,
        )
        md = render_briefing(data)
        assert "# Race Briefing - M2 Cup" in md
        assert "Summit Point Raceway" in md
        assert "12 minutes" in md
        assert "standing start" in md
        assert "SoF ~1,400 (typ. 1,200-1,600)" in md
        assert "worth more iRating" in md
        assert "28 representative laps" in md
        assert "fits your usual window" in md

    def test_warning_and_empty_sections_render(self):
        data = BriefingData(
            series_name="M2 Cup", season_id=100, race_week=2, fmt=_fmt(),
            warnings=["Couldn't fetch this week's field data - briefing "
                      "is format-and-history only."],
        )
        md = render_briefing(data)
        assert "Couldn't fetch" in md
        assert "Run a practice session" in md  # invitation verdict


class TestVerdictLineBoundary:
    def test_under_curve_exact_boundary(self):
        # delta exactly +ON_CURVE_BAND_S routes under-curve (inclusive >=),
        # symmetric with the over-curve boundary at -0.15
        p = CurvePlacement(
            lap_s=82.5, implied_ir_lo=1300, implied_ir_hi=1550,
            delta_to_own_band_s=0.15,
        )
        assert verdict_line(p, user_ir=1400).startswith(
            "The median at your rating runs"
        )
