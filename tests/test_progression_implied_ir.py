"""Weighted roll-up of per-combo implied-iR bands."""

from core.progression.implied_ir import aggregate_implied_ir
from core.progression.models import ComboImplied, DriverImpliedIR


def _combo(lo, hi, weight, car="M2"):
    return ComboImplied(
        track_id="525", track_name="Spa", car=car, series_name="S",
        lap_s=160.0, implied_lo=lo, implied_hi=hi, weight=weight,
    )


class TestAggregate:
    def test_empty_returns_none(self):
        assert aggregate_implied_ir([]) is None

    def test_single_combo_passes_through(self):
        out = aggregate_implied_ir([_combo(1400, 1650, 10.0)])
        assert out == DriverImpliedIR(lo=1400, hi=1650, combo_count=1)

    def test_weighted_mean_of_midpoints(self):
        # midpoints 1525 (w=30) and 1275 (w=10) -> 1462.5; half-width 125
        out = aggregate_implied_ir([
            _combo(1400, 1650, 30.0), _combo(1150, 1400, 10.0, car="F4")])
        assert out.combo_count == 2
        assert out.lo == 1338  # round(1462.5 - 125)
        assert out.hi == 1588  # round(1462.5 + 125)

    def test_lo_clamped_to_zero(self):
        out = aggregate_implied_ir([_combo(0, 150, 5.0)])
        assert out.lo >= 0

    def test_zero_total_weight_falls_back_to_unweighted(self):
        out = aggregate_implied_ir([_combo(1000, 1250, 0.0)])
        assert out == DriverImpliedIR(lo=1000, hi=1250, combo_count=1)
