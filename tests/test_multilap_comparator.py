"""Tests for lap comparator with actual multi-lap data.

These tests use real IBT files with multiple valid laps so we can
test actual two-lap comparisons, theoretical best calculations,
and consistency analysis with real variance.
"""

import numpy as np
import pytest

from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer, NormalizedLap
from core.telemetry.corner_detector import CornerDetector
from core.telemetry.lap_comparator import LapComparator


@pytest.fixture
def parser() -> IBTParser:
    return IBTParser()


@pytest.fixture
def normalizer() -> Normalizer:
    return Normalizer(distance_interval=1.0)


@pytest.fixture
def detector() -> CornerDetector:
    return CornerDetector()


@pytest.fixture
def comparator() -> LapComparator:
    return LapComparator()


@pytest.fixture
def multilap_session(parser, normalizer, multilap_ibt_path):
    """Parse a real multi-lap IBT and return normalized laps + metadata."""
    ibt = parser.parse(multilap_ibt_path)
    laps = parser.get_laps(ibt)
    track_length_m = ibt.session.track_length_km * 1000

    normalized: list[NormalizedLap] = []
    for lap_df in laps:
        lap_num = int(lap_df["Lap"].iloc[0])
        nlap = normalizer.normalize_lap(lap_df, lap_num, track_length_m)
        if nlap.is_valid:
            normalized.append(nlap)

    if len(normalized) < 2:
        pytest.skip("Need at least 2 valid normalized laps")

    return normalized


@pytest.fixture
def segmentation(detector, multilap_session):
    """Detect corners using the best lap."""
    best = min(multilap_session, key=lambda l: l.lap_time)
    return detector.detect(best)


class TestTwoLapComparison:
    """Tests that require two different laps to compare."""

    def test_two_lap_comparison_produces_results(
        self, comparator, multilap_session, segmentation
    ):
        """Comparing two different laps should produce non-trivial results."""
        ref = multilap_session[0]
        comp = multilap_session[1]
        result = comparator.compare_laps(ref, comp, segmentation)

        assert result.reference_time > 0
        assert result.comparison_time > 0
        assert len(result.cumulative_time_delta) > 0
        assert len(result.speed_delta) > 0

    def test_total_delta_derived_from_cumulative(
        self, comparator, multilap_session, segmentation
    ):
        """Total time delta should equal the final cumulative delta value.

        We derive total_time_delta from the SessionTime-based cumulative
        trace (not from official lap times) so the per-distance delta
        chart and the headline number are always consistent.
        """
        ref = multilap_session[0]
        comp = multilap_session[1]
        result = comparator.compare_laps(ref, comp, segmentation)

        final_cum = float(result.cumulative_time_delta[-1])
        assert result.total_time_delta == pytest.approx(final_cum, abs=1e-9)

    def test_corner_deltas_have_all_fields(
        self, comparator, multilap_session, segmentation
    ):
        """Each corner delta should have non-None values for all fields."""
        ref = multilap_session[0]
        comp = multilap_session[1]
        result = comparator.compare_laps(ref, comp, segmentation)

        if not result.corner_deltas:
            pytest.skip("No corner deltas produced")

        for cd in result.corner_deltas:
            assert cd.time_delta is not None
            assert cd.braking_point_delta is not None
            assert cd.apex_speed_delta is not None
            assert cd.exit_speed_delta is not None
            assert cd.min_speed_delta is not None
            assert cd.throttle_application_delta is not None
            assert cd.entry_speed_delta is not None

    def test_speed_delta_matches_channels(
        self, comparator, multilap_session, segmentation
    ):
        """Speed delta should be comparison speed minus reference speed."""
        ref = multilap_session[0]
        comp = multilap_session[1]
        result = comparator.compare_laps(ref, comp, segmentation)

        min_len = min(len(ref.speed), len(comp.speed))
        expected = comp.speed[:min_len] - ref.speed[:min_len]
        assert np.allclose(result.speed_delta, expected, atol=0.001)

    def test_reverse_comparison_negates_delta(
        self, comparator, multilap_session, segmentation
    ):
        """Comparing B-to-A should negate the delta from A-to-B."""
        ref = multilap_session[0]
        comp = multilap_session[1]

        result_ab = comparator.compare_laps(ref, comp, segmentation)
        result_ba = comparator.compare_laps(comp, ref, segmentation)

        assert abs(result_ab.total_time_delta + result_ba.total_time_delta) < 0.01


class TestTheoreticalBestMultiLap:
    """Theoretical best tests with real multi-lap data."""

    def test_theoretical_best_leq_all_laps(
        self, comparator, multilap_session, segmentation
    ):
        """Theoretical best should be <= every actual lap time."""
        tb = comparator.theoretical_best(multilap_session, segmentation)

        for lap in multilap_session:
            assert tb.theoretical_time <= lap.lap_time + 0.5

    def test_theoretical_best_gap_positive(
        self, comparator, multilap_session, segmentation
    ):
        """Gap to theoretical should be non-negative."""
        tb = comparator.theoretical_best(multilap_session, segmentation)
        assert tb.gap_to_theoretical >= -0.01

    def test_best_corners_reference_valid_laps(
        self, comparator, multilap_session, segmentation
    ):
        """Every lap number in best_corners should be a real lap in the session."""
        tb = comparator.theoretical_best(multilap_session, segmentation)
        session_lap_nums = {l.lap_number for l in multilap_session}

        for corner_num, lap_num in tb.best_corners.items():
            assert lap_num in session_lap_nums, (
                f"Corner {corner_num} references lap {lap_num} "
                f"which is not in session laps {session_lap_nums}"
            )


class TestConsistencyMultiLap:
    """Consistency analysis with real multi-lap data."""

    def test_consistency_returns_results(
        self, comparator, multilap_session, segmentation
    ):
        """With multiple laps, should return consistency data per corner."""
        results = comparator.consistency_analysis(multilap_session, segmentation)
        assert len(results) > 0

    def test_consistency_cv_non_negative(
        self, comparator, multilap_session, segmentation
    ):
        """CV should always be non-negative."""
        results = comparator.consistency_analysis(multilap_session, segmentation)
        for r in results:
            assert r.coefficient_of_variation >= 0

    def test_consistency_best_leq_mean(
        self, comparator, multilap_session, segmentation
    ):
        """Best time through each corner should be <= mean."""
        results = comparator.consistency_analysis(multilap_session, segmentation)
        for r in results:
            assert r.best_time <= r.mean_time + 0.001

    def test_consistency_worst_geq_mean(
        self, comparator, multilap_session, segmentation
    ):
        """Worst time through each corner should be >= mean."""
        results = comparator.consistency_analysis(multilap_session, segmentation)
        for r in results:
            assert r.worst_time >= r.mean_time - 0.001

    def test_consistency_issue_flags(
        self, comparator, multilap_session, segmentation
    ):
        """Consistency and technique flags should be mutually exclusive."""
        results = comparator.consistency_analysis(multilap_session, segmentation)
        for r in results:
            # A corner cannot be both a consistency and technique issue
            assert not (r.is_consistency_issue and r.is_technique_issue)
