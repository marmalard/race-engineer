"""Tests for distance-offset alignment between laps from different sources."""

import numpy as np
import pytest

from core.telemetry.alignment import find_distance_offset, shift_lap
from core.telemetry.normalizer import NormalizedLap


def _make_lap(speed: np.ndarray, track_length: float = 1000.0) -> NormalizedLap:
    n = len(speed)
    distance = np.arange(n, dtype=float)
    # elapsed time consistent with speed: dt = ds / v
    dt = 1.0 / np.maximum(speed, 1.0)
    return NormalizedLap(
        lap_number=1,
        lap_time=float(dt.sum()),
        track_length=track_length,
        distance=distance,
        speed=speed,
        throttle=np.ones(n),
        brake=np.zeros(n),
        steering=np.zeros(n),
        gear=np.full(n, 4),
        rpm=np.full(n, 5000.0),
        lat=np.zeros(n),
        lon=np.zeros(n),
        elapsed_time=np.cumsum(dt),
        is_valid=True,
    )


def _speed_profile(n: int = 1000) -> np.ndarray:
    """Synthetic lap: two 'corners' (speed dips) on a fast lap."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 35.0 * np.exp(-((x - 250.0) ** 2) / (2 * 40.0**2))
    speed -= 25.0 * np.exp(-((x - 700.0) ** 2) / (2 * 30.0**2))
    return speed


def test_zero_offset_for_identical_laps():
    speed = _speed_profile()
    assert find_distance_offset(speed, speed) == 0


def test_recovers_known_shift():
    speed = _speed_profile()
    shifted = np.roll(speed, 12)  # comparison trace shifted 12m forward
    assert find_distance_offset(speed, shifted) == 12


def test_recovers_negative_shift():
    speed = _speed_profile()
    shifted = np.roll(speed, -8)
    assert find_distance_offset(speed, shifted) == -8


def test_offset_search_is_bounded():
    speed = _speed_profile()
    shifted = np.roll(speed, 300)  # beyond max_offset window
    offset = find_distance_offset(speed, shifted, max_offset_m=150)
    assert abs(offset) <= 150


def test_shift_lap_realigns_speed():
    lap = _make_lap(np.roll(_speed_profile(), 12))
    shifted = shift_lap(lap, -12)
    np.testing.assert_allclose(shifted.speed, _speed_profile())


def test_shift_lap_keeps_elapsed_time_monotonic():
    lap = _make_lap(_speed_profile())
    shifted = shift_lap(lap, 12)
    assert np.all(np.diff(shifted.elapsed_time) > 0)
    # total lap time preserved
    assert shifted.elapsed_time[-1] == pytest.approx(lap.elapsed_time[-1], abs=1e-6)


def test_shift_zero_is_identity():
    lap = _make_lap(_speed_profile())
    shifted = shift_lap(lap, 0)
    np.testing.assert_allclose(shifted.speed, lap.speed)
    np.testing.assert_allclose(shifted.elapsed_time, lap.elapsed_time)
