"""Tests for distance normalizer.

Requires a real IBT file in tests/fixtures/.
"""

import numpy as np
import pytest

from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer, NormalizedLap


@pytest.fixture
def parser() -> IBTParser:
    return IBTParser()


@pytest.fixture
def parsed_ibt(parser, sample_ibt_path):
    return parser.parse(sample_ibt_path)


@pytest.fixture
def normalizer() -> Normalizer:
    return Normalizer(distance_interval=1.0)


@pytest.fixture
def normalized_lap(parser, parsed_ibt, normalizer) -> NormalizedLap:
    """Get a single normalized lap from the sample file."""
    laps = parser.get_laps(parsed_ibt)
    if not laps:
        pytest.skip("No valid laps in sample IBT file")

    track_length_m = parsed_ibt.session.track_length_km * 1000
    lap_df = laps[0]
    lap_number = int(lap_df["Lap"].iloc[0])
    nlap = normalizer.normalize_lap(lap_df, lap_number, track_length_m)

    if not nlap.is_valid:
        pytest.skip("First lap is not valid for normalization")
    return nlap


class TestNormalizer:
    def test_output_distance_is_uniform(self, normalized_lap):
        """Distance array should have consistent 1m intervals."""
        diffs = np.diff(normalized_lap.distance)
        assert np.allclose(diffs, 1.0), "Distance intervals should be 1 meter"

    def test_all_channels_same_length(self, normalized_lap):
        """All channels should have the same length as the distance array."""
        n = len(normalized_lap.distance)
        assert len(normalized_lap.speed) == n
        assert len(normalized_lap.throttle) == n
        assert len(normalized_lap.brake) == n
        assert len(normalized_lap.elapsed_time) == n
        assert len(normalized_lap.steering) == n
        assert len(normalized_lap.gear) == n

    def test_speed_non_negative(self, normalized_lap):
        """Speed should be non-negative after normalization."""
        assert np.all(normalized_lap.speed >= 0)

    def test_throttle_brake_bounds(self, normalized_lap):
        """Throttle and brake should remain in [0, 1] after interpolation."""
        assert np.all(normalized_lap.throttle >= 0.0)
        assert np.all(normalized_lap.throttle <= 1.0)
        assert np.all(normalized_lap.brake >= 0.0)
        assert np.all(normalized_lap.brake <= 1.0)

    def test_elapsed_time_monotonic(self, normalized_lap):
        """Elapsed time should strictly increase with distance."""
        diffs = np.diff(normalized_lap.elapsed_time)
        assert np.all(diffs >= 0), "Elapsed time should be non-decreasing"

    def test_elapsed_time_starts_near_zero(self, normalized_lap):
        """Elapsed time should start at or very close to zero."""
        assert normalized_lap.elapsed_time[0] < 1.0

    def test_lap_time_positive(self, normalized_lap):
        """Lap time should be positive and reasonable."""
        assert normalized_lap.lap_time > 10.0  # At least 10 seconds
        assert normalized_lap.lap_time < 600.0  # Less than 10 minutes

    def test_distance_covers_track(self, normalized_lap):
        """Distance should cover most of the track length."""
        coverage = normalized_lap.distance[-1] / normalized_lap.track_length
        assert coverage > 0.85, f"Only covers {coverage:.0%} of track"

    def test_sample_count_reasonable(self, normalized_lap):
        """Sample count should be approximately track_length / interval."""
        expected = int(normalized_lap.track_length)
        actual = len(normalized_lap.distance)
        assert abs(actual - expected) < expected * 0.15


class TestNormalizerSession:
    def test_normalize_session(self, parser, parsed_ibt, normalizer):
        """normalize_session should return valid normalized laps."""
        laps = parser.get_laps(parsed_ibt)
        if not laps:
            pytest.skip("No valid laps")

        track_length_m = parsed_ibt.session.track_length_km * 1000
        lap_numbers = [int(df["Lap"].iloc[0]) for df in laps]

        normalized = normalizer.normalize_session(laps, lap_numbers, track_length_m)
        assert len(normalized) > 0
        for nlap in normalized:
            assert nlap.is_valid
            assert len(nlap.distance) > 0
