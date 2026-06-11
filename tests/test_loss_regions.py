"""Tests for loss-region extraction from cumulative time-delta traces."""

import numpy as np
import pytest

from core.telemetry.loss_regions import LossRegion, find_loss_regions


def _delta_with_losses(n: int = 2000) -> np.ndarray:
    """Synthetic cumulative delta: flat, then two distinct loss ramps."""
    delta = np.zeros(n)
    # Loss 1: 0.40s lost between 400m and 500m
    delta[400:500] += np.linspace(0, 0.40, 100)
    delta[500:] += 0.40
    # Loss 2: 0.15s lost between 1200m and 1260m
    delta[1200:1260] += np.linspace(0, 0.15, 60)
    delta[1260:] += 0.15
    return delta


def test_finds_both_loss_regions():
    distance = np.arange(2000, dtype=float)
    regions = find_loss_regions(_delta_with_losses(), distance)
    assert len(regions) == 2


def test_regions_sorted_by_time_lost_descending():
    distance = np.arange(2000, dtype=float)
    regions = find_loss_regions(_delta_with_losses(), distance)
    assert regions[0].time_lost >= regions[1].time_lost
    assert regions[0].time_lost == pytest.approx(0.40, abs=0.05)


def test_region_bounds_cover_the_ramp():
    distance = np.arange(2000, dtype=float)
    regions = find_loss_regions(_delta_with_losses(), distance)
    biggest = regions[0]
    assert biggest.distance_start <= 410
    assert biggest.distance_end >= 490


def test_no_regions_on_flat_delta():
    distance = np.arange(2000, dtype=float)
    assert find_loss_regions(np.zeros(2000), distance) == []


def test_gains_are_not_loss_regions():
    distance = np.arange(2000, dtype=float)
    delta = np.zeros(2000)
    delta[400:500] -= np.linspace(0, 0.5, 100)  # driver GAINS time
    delta[500:] -= 0.5
    assert find_loss_regions(delta, distance) == []


def test_tiny_losses_filtered():
    distance = np.arange(2000, dtype=float)
    delta = np.zeros(2000)
    delta[400:420] += np.linspace(0, 0.02, 20)  # below min_loss
    delta[420:] += 0.02
    assert find_loss_regions(delta, distance, min_loss_s=0.05) == []


def test_nearby_regions_merge():
    distance = np.arange(2000, dtype=float)
    delta = np.zeros(2000)
    # Two ramps separated by a 20m flat gap -> should merge (chicane case)
    delta[400:440] += np.linspace(0, 0.2, 40)
    delta[440:] += 0.2
    delta[460:500] += np.linspace(0, 0.2, 40)
    delta[500:] += 0.2
    regions = find_loss_regions(delta, distance, merge_gap_m=30.0)
    assert len(regions) == 1
    assert regions[0].time_lost == pytest.approx(0.4, abs=0.05)
