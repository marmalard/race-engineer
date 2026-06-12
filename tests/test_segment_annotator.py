"""Tests for annotating loss regions with corner names."""

from core.telemetry.loss_regions import LossRegion
from core.track.models import Corner
from core.track.segment_annotator import annotate_region


def _corner(name: str, start: float, end: float) -> Corner:
    return Corner(
        corner_id=None, track_id="523", corner_number=1, name=name,
        distance_start_meters=start, distance_end_meters=end, corner_type=None,
    )


CORNERS = [
    _corner("La Source", 35.0, 175.0),
    _corner("Eau Rouge", 966.0, 1086.0),
    _corner("Raidillon", 1086.0, 1226.0),
]


def test_region_inside_corner_gets_name():
    region = LossRegion(distance_start=1000.0, distance_end=1080.0, time_lost=0.3)
    assert annotate_region(region, CORNERS, track_length=7004.0) == "Eau Rouge"


def test_region_spanning_corners_joins_names():
    region = LossRegion(distance_start=1000.0, distance_end=1200.0, time_lost=0.5)
    assert annotate_region(region, CORNERS, track_length=7004.0) == (
        "Eau Rouge / Raidillon"
    )


def test_region_near_corner_within_tolerance():
    # Braking zone starts 40m before the corner's DB start
    region = LossRegion(distance_start=930.0, distance_end=960.0, time_lost=0.2)
    assert annotate_region(region, CORNERS, track_length=7004.0,
                           tolerance_m=50.0) == "Eau Rouge"


def test_region_far_from_any_corner_falls_back_to_position():
    region = LossRegion(distance_start=4400.0, distance_end=4500.0, time_lost=0.2)
    label = annotate_region(region, CORNERS, track_length=7004.0)
    assert "4.4 km" in label


def test_no_corners_at_all_falls_back_to_position():
    region = LossRegion(distance_start=1000.0, distance_end=1080.0, time_lost=0.3)
    label = annotate_region(region, [], track_length=7004.0)
    assert "1.0 km" in label


def test_exit_bleed_region_attributed_to_preceding_corner():
    """A bad corner exit bleeds time down the following straight: the region
    starts past the corner's end (Raidillon exit onto Kemmel at Spa)."""
    region = LossRegion(distance_start=1300.0, distance_end=2300.0, time_lost=2.0)
    assert annotate_region(region, CORNERS, track_length=7004.0) == (
        "after Raidillon"
    )


def test_trailing_attribution_respects_window():
    # Nearest preceding corner ends 3+ km back: too far to blame the exit
    region = LossRegion(distance_start=4400.0, distance_end=4500.0, time_lost=0.2)
    label = annotate_region(region, CORNERS, track_length=7004.0,
                            trailing_window_m=300.0)
    assert "4.4 km" in label


def test_strict_overlap_beats_trailing_attribution():
    # Region inside Eau Rouge, with La Source ending well behind it
    region = LossRegion(distance_start=1000.0, distance_end=1080.0, time_lost=0.3)
    assert annotate_region(region, CORNERS, track_length=7004.0) == "Eau Rouge"
