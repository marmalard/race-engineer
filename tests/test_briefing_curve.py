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


from core.briefing.curve import build_curve, place_on_curve, smoothed_medians

# Synthetic field: pace improves 0.5s per 250 iR from 90.0s @ 1000 iR.
# 6 points per bin so every bin clears MIN_BIN_N=5.
def _points():
    pts = []
    for i, ir_base in enumerate([1000, 1250, 1500, 1750]):
        lap = 90.0 - 0.5 * i
        for j in range(6):
            pts.append((ir_base + j * 10, lap + (j % 3) * 0.01))
    return pts


class TestBuildCurve:
    def test_bins_have_medians_and_counts(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        assert len(curve.bins) == 4
        assert curve.bins[0].n == 6
        assert abs(curve.bins[0].median_lap_s - 90.0) < 0.02
        assert curve.bins[-1].median_lap_s < curve.bins[0].median_lap_s

    def test_invalid_points_filtered(self):
        pts = _points() + [(0, 89.0), (1500, -1.0), (1500, 0.0)]
        curve = build_curve(pts, subsessions_used=10, capped=False)
        assert curve.points == _points()  # invalid rows dropped

    def test_sparse_bins_merge_into_neighbor(self):
        # 3 points at 2000+ (below MIN_BIN_N) merge into the last full bin
        pts = _points() + [(2100, 88.0), (2110, 88.0), (2120, 88.0)]
        curve = build_curve(pts, subsessions_used=10, capped=False)
        assert curve.bins[-1].n == 9  # 6 + 3 merged
        assert curve.bins[-1].ir_hi >= 2120

    def test_leading_sparse_bin_merges_forward(self):
        # 3 points in the lowest bin (below MIN_BIN_N) merge forward into
        # the next bin - covers the forward-merge branch the trailing test misses
        pts = [(500, 91.0), (510, 91.0), (520, 91.0)] + [
            (1000 + j * 10, 90.0) for j in range(6)
        ]
        curve = build_curve(pts, subsessions_used=5, capped=False)
        assert len(curve.bins) == 1
        assert curve.bins[0].n == 9
        assert curve.bins[0].ir_lo == 500

    def test_empty_and_tiny_input(self):
        assert build_curve([], subsessions_used=0, capped=False).bins == []
        tiny = build_curve([(1500, 90.0)] * 3, subsessions_used=1, capped=False)
        assert len(tiny.bins) == 1
        assert tiny.bins[0].n == 3


class TestSmoothedMedians:
    def test_window_zero_is_identity(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        raw = {b.ir_center: b.median_lap_s for b in curve.bins}
        for ir, val in smoothed_medians(curve, window=0):
            assert abs(val - raw[ir]) < 1e-9

    def test_thin_bin_leans_on_heavy_neighbor(self):
        # 30 laps at 90.0 (1000-1249 iR) next to 5 outlier laps at 95.0
        # (1250-1499 iR): the thin bin's smoothed display value is pulled
        # hard toward the heavy neighbor; the raw median (verdict math)
        # is untouched
        pts = [(1000 + i, 90.0) for i in range(30)] + [
            (1300 + i, 95.0) for i in range(5)
        ]
        curve = build_curve(pts, subsessions_used=5, capped=False)
        assert len(curve.bins) == 2
        sm = dict(smoothed_medians(curve, window=1))
        heavy, thin = curve.bins[0], curve.bins[1]
        assert sm[thin.ir_center] < 91.0  # pulled from 95 toward 90
        assert sm[heavy.ir_center] < 91.0
        assert thin.median_lap_s == 95.0  # verdict math untouched

    def test_empty_curve(self):
        assert smoothed_medians(build_curve([], 0, False)) == []


class TestPlaceOnCurve:
    def test_faster_lap_implies_higher_irating(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        # 89.0s sits between the 1250 bin (89.5) and the 1500 bin (89.0)
        p = place_on_curve(curve, lap_s=89.0, user_ir=1200)
        assert p.implied_ir_lo is not None
        assert p.implied_ir_lo > 1200
        assert p.delta_to_own_band_s is not None
        assert p.delta_to_own_band_s < 0  # faster than own-band median

    def test_lap_faster_than_whole_field_clamps_to_top(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        p = place_on_curve(curve, lap_s=80.0, user_ir=1500)
        assert p.implied_ir_hi is not None
        assert p.implied_ir_hi >= curve.bins[-1].ir_center

    def test_unusable_curve_returns_none_fields(self):
        empty = build_curve([], subsessions_used=0, capped=False)
        p = place_on_curve(empty, lap_s=90.0, user_ir=1500)
        assert p.implied_ir_lo is None and p.delta_to_own_band_s is None

    def test_no_user_ir_still_gives_implied_band(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        p = place_on_curve(curve, lap_s=89.0, user_ir=None)
        assert p.implied_ir_lo is not None
        assert p.delta_to_own_band_s is None
