"""Tests for lap comparator.

Requires a real IBT file in tests/fixtures/ with at least 2 valid laps.
"""

import numpy as np
import pytest

from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer, NormalizedLap
from core.telemetry.corner_detector import CornerDetector, LapSegmentation
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
def session_data(parser, normalizer, sample_ibt_path):
    """Parse, normalize, and return session data."""
    ibt = parser.parse(sample_ibt_path)
    laps = parser.get_laps(ibt)
    track_length_m = ibt.session.track_length_km * 1000

    normalized: list[NormalizedLap] = []
    for lap_df in laps:
        lap_num = int(lap_df["Lap"].iloc[0])
        nlap = normalizer.normalize_lap(lap_df, lap_num, track_length_m)
        if nlap.is_valid:
            normalized.append(nlap)

    if len(normalized) < 1:
        pytest.skip("Need at least 1 valid normalized lap")

    return normalized


@pytest.fixture
def segmentation(detector, session_data) -> LapSegmentation:
    return detector.detect(session_data[0])


class TestLapComparatorSelfComparison:
    """Test comparing a lap to itself — should produce zero deltas."""

    def test_self_comparison_zero_total_delta(self, comparator, session_data, segmentation):
        """Comparing a lap to itself should yield zero total time delta."""
        lap = session_data[0]
        result = comparator.compare_laps(lap, lap, segmentation)
        assert abs(result.total_time_delta) < 0.001

    def test_self_comparison_zero_cumulative(self, comparator, session_data, segmentation):
        """Cumulative time delta should be zero everywhere."""
        lap = session_data[0]
        result = comparator.compare_laps(lap, lap, segmentation)
        assert np.allclose(result.cumulative_time_delta, 0.0, atol=0.001)

    def test_self_comparison_zero_speed_delta(self, comparator, session_data, segmentation):
        """Speed delta should be zero everywhere."""
        lap = session_data[0]
        result = comparator.compare_laps(lap, lap, segmentation)
        assert np.allclose(result.speed_delta, 0.0, atol=0.001)

    def test_self_comparison_corner_deltas_zero(self, comparator, session_data, segmentation):
        """Per-corner time deltas should all be zero."""
        lap = session_data[0]
        result = comparator.compare_laps(lap, lap, segmentation)
        for cd in result.corner_deltas:
            assert abs(cd.time_delta) < 0.001


class TestLapComparatorTwoLaps:
    """Test comparing two different laps."""

    def test_two_lap_comparison(self, comparator, session_data, segmentation):
        """Comparing two different laps should produce non-trivial results."""
        if len(session_data) < 2:
            pytest.skip("Need at least 2 normalized laps")

        result = comparator.compare_laps(session_data[0], session_data[1], segmentation)
        assert result.reference_time > 0
        assert result.comparison_time > 0
        assert len(result.cumulative_time_delta) > 0

    def test_total_delta_matches_lap_times(self, comparator, session_data, segmentation):
        """Total time delta should equal the difference in lap times."""
        if len(session_data) < 2:
            pytest.skip("Need at least 2 normalized laps")

        ref, comp = session_data[0], session_data[1]
        result = comparator.compare_laps(ref, comp, segmentation)
        expected_delta = comp.lap_time - ref.lap_time
        assert abs(result.total_time_delta - expected_delta) < 0.01

    def test_cumulative_delta_final_matches_total(self, comparator, session_data, segmentation):
        """Last value of cumulative delta should approximate the total delta."""
        if len(session_data) < 2:
            pytest.skip("Need at least 2 normalized laps")

        result = comparator.compare_laps(session_data[0], session_data[1], segmentation)
        final_cum = result.cumulative_time_delta[-1]
        assert abs(final_cum - result.total_time_delta) < 1.0


class TestTheoreticalBest:
    def test_theoretical_best_leq_actual(self, comparator, session_data, segmentation):
        """Theoretical best should be <= actual best lap time."""
        tb = comparator.theoretical_best(session_data, segmentation)
        assert tb.theoretical_time <= tb.actual_best_time + 0.01

    def test_gap_non_negative(self, comparator, session_data, segmentation):
        """Gap to theoretical should be non-negative."""
        tb = comparator.theoretical_best(session_data, segmentation)
        assert tb.gap_to_theoretical >= -0.01


class TestConsistencyAnalysis:
    def test_consistency_returns_results(self, comparator, session_data, segmentation):
        """Should return analysis for detected corners."""
        results = comparator.consistency_analysis(session_data, segmentation)
        # May be empty if we only have 1 lap (need >=2 for std)
        if len(session_data) >= 2:
            assert len(results) > 0

    def test_consistency_cv_non_negative(self, comparator, session_data, segmentation):
        """Coefficient of variation should be non-negative."""
        results = comparator.consistency_analysis(session_data, segmentation)
        for r in results:
            assert r.coefficient_of_variation >= 0
