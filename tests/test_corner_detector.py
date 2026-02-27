"""Tests for corner detection.

Requires a real IBT file in tests/fixtures/.
"""

import pytest

from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer, NormalizedLap
from core.telemetry.corner_detector import CornerDetector, DetectionParams


@pytest.fixture
def parser() -> IBTParser:
    return IBTParser()


@pytest.fixture
def normalizer() -> Normalizer:
    return Normalizer(distance_interval=1.0)


@pytest.fixture
def normalized_lap(parser, normalizer, sample_ibt_path) -> NormalizedLap:
    ibt = parser.parse(sample_ibt_path)
    laps = parser.get_laps(ibt)
    if not laps:
        pytest.skip("No valid laps")

    track_length_m = ibt.session.track_length_km * 1000
    lap_df = laps[0]
    lap_number = int(lap_df["Lap"].iloc[0])
    nlap = normalizer.normalize_lap(lap_df, lap_number, track_length_m)
    if not nlap.is_valid:
        pytest.skip("Lap not valid for normalization")
    return nlap


@pytest.fixture
def detector() -> CornerDetector:
    return CornerDetector()


@pytest.fixture
def segmentation(detector, normalized_lap):
    return detector.detect(normalized_lap)


class TestCornerDetector:
    def test_detects_corners(self, segmentation):
        """Should detect at least one corner."""
        assert len(segmentation.corners) > 0

    def test_corner_count_reasonable(self, segmentation):
        """A road circuit should have between 3 and 30 corners."""
        count = len(segmentation.corners)
        assert 3 <= count <= 30, f"Detected {count} corners"

    def test_apex_speed_lower_than_entry(self, segmentation):
        """Every detected corner's apex speed should be < entry speed."""
        for corner in segmentation.corners:
            assert corner.apex_speed < corner.entry_speed, (
                f"Corner {corner.corner_number}: apex {corner.apex_speed:.1f} "
                f">= entry {corner.entry_speed:.1f}"
            )

    def test_braking_before_apex(self, segmentation):
        """Braking distance should be before (<=) apex distance."""
        for corner in segmentation.corners:
            assert corner.braking_distance <= corner.apex_distance, (
                f"Corner {corner.corner_number}: braking at {corner.braking_distance:.0f} "
                f"but apex at {corner.apex_distance:.0f}"
            )

    def test_exit_after_apex(self, segmentation):
        """Exit distance should be after (>=) apex distance."""
        for corner in segmentation.corners:
            assert corner.throttle_application_distance >= corner.apex_distance, (
                f"Corner {corner.corner_number}: exit at "
                f"{corner.throttle_application_distance:.0f} "
                f"but apex at {corner.apex_distance:.0f}"
            )

    def test_corners_sequentially_numbered(self, segmentation):
        """Corners should be numbered 1, 2, 3, ..."""
        numbers = [c.corner_number for c in segmentation.corners]
        assert numbers == list(range(1, len(numbers) + 1))

    def test_corners_in_distance_order(self, segmentation):
        """Corners should appear in order of increasing distance."""
        distances = [c.apex_distance for c in segmentation.corners]
        assert distances == sorted(distances)

    def test_no_overlapping_corners(self, segmentation):
        """Corner segments should not overlap."""
        for i in range(len(segmentation.corners) - 1):
            current = segmentation.corners[i]
            next_corner = segmentation.corners[i + 1]
            assert current.distance_end <= next_corner.distance_start, (
                f"Corner {current.corner_number} ends at {current.distance_end:.0f} "
                f"but corner {next_corner.corner_number} starts at "
                f"{next_corner.distance_start:.0f}"
            )


class TestDetectionParams:
    def test_for_track_type_road(self):
        """Road preset should create a valid detector."""
        det = CornerDetector.for_track_type("road")
        assert det.params.min_corner_speed_drop == 5.0

    def test_for_track_type_street(self):
        """Street preset should be more sensitive."""
        det = CornerDetector.for_track_type("street")
        assert det.params.min_corner_speed_drop < 5.0

    def test_for_track_type_oval(self):
        """Oval preset should have large min distance between corners."""
        det = CornerDetector.for_track_type("oval")
        assert det.params.min_corner_distance >= 200

    def test_custom_params(self):
        """Should accept custom params."""
        params = DetectionParams(min_corner_speed_drop=3.0)
        det = CornerDetector(params=params)
        assert det.params.min_corner_speed_drop == 3.0
