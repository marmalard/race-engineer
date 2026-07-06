"""Tests for the debrief orchestrator (reference-lap delta analysis)."""

import numpy as np
import pytest

from core.coaching.debrief import DebriefAnalysis, RegionDiagnosis, build_debrief
from core.telemetry.normalizer import NormalizedLap
from core.track.models import Corner


def _lap(speed: np.ndarray, brake: np.ndarray | None = None,
         throttle: np.ndarray | None = None) -> NormalizedLap:
    n = len(speed)
    dt = 1.0 / np.maximum(speed, 1.0)
    return NormalizedLap(
        lap_number=1, lap_time=float(dt.sum()), track_length=float(n),
        distance=np.arange(n, dtype=float),
        speed=speed,
        throttle=throttle if throttle is not None else np.ones(n),
        brake=brake if brake is not None else np.zeros(n),
        steering=np.zeros(n), gear=np.full(n, 4), rpm=np.full(n, 6000.0),
        lat=np.zeros(n), lon=np.zeros(n),
        elapsed_time=np.cumsum(dt), is_valid=True,
    )


def _reference(n: int = 2000) -> NormalizedLap:
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 35.0 * np.exp(-((x - 500.0) ** 2) / (2 * 50.0**2))  # corner at 500m
    brake = np.where((x > 380) & (x < 480), 0.8, 0.0)
    throttle = np.where((x > 380) & (x < 560), 0.0, 1.0)
    return _lap(speed, brake, throttle)


def _slower_driver(n: int = 2000) -> NormalizedLap:
    """Same lap but over-slows the corner and brakes 30m earlier."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 42.0 * np.exp(-((x - 500.0) ** 2) / (2 * 55.0**2))  # deeper dip
    brake = np.where((x > 350) & (x < 480), 0.8, 0.0)  # brakes at 350 not 380
    throttle = np.where((x > 350) & (x < 580), 0.0, 1.0)
    return _lap(speed, brake, throttle)


CORNERS = [Corner(
    corner_id=None, track_id="t", corner_number=1, name="Test Hairpin",
    distance_start_meters=420.0, distance_end_meters=580.0, corner_type=None,
)]


def test_debrief_finds_the_loss_region():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    assert isinstance(result, DebriefAnalysis)
    assert len(result.diagnoses) >= 1
    top = result.diagnoses[0]
    assert 350 <= top.region.distance_start <= 550


def test_diagnosis_labeled_with_corner_name():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    assert result.diagnoses[0].label == "Test Hairpin"


def test_braking_delta_detects_early_braking():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    # Driver brakes ~30m earlier than reference -> negative delta
    assert top.braking_delta_m == pytest.approx(-30.0, abs=10.0)


def test_min_speed_delta_detects_overslowing():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    # Driver min speed ~18 m/s vs reference ~25 m/s -> negative delta
    assert top.min_speed_delta_ms < -3.0


def test_total_delta_positive_for_slower_driver():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    assert result.total_time_delta > 0


def test_identical_laps_produce_no_diagnoses():
    result = build_debrief(_reference(), _reference(), CORNERS)
    assert result.diagnoses == []
    assert result.total_time_delta == pytest.approx(0.0, abs=0.01)


def test_top_n_limits_diagnoses():
    result = build_debrief(_slower_driver(), _reference(), CORNERS, top_n=1)
    assert len(result.diagnoses) <= 1


def _early_release_driver(n: int = 2000) -> NormalizedLap:
    """Brakes at the reference point but releases the brakes ~30m earlier."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 40.0 * np.exp(-((x - 500.0) ** 2) / (2 * 52.0**2))  # slower than ref
    brake = np.where((x > 380) & (x < 450), 0.8, 0.0)  # releases at 450 not 480
    throttle = np.where((x > 380) & (x < 560), 0.0, 1.0)
    return _lap(speed, brake, throttle)


def _straightline_brake_reference(n: int = 2000) -> NormalizedLap:
    """Reference that does NOT trail-brake: brakes done 90m before the apex."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 35.0 * np.exp(-((x - 500.0) ** 2) / (2 * 50.0**2))
    brake = np.where((x > 380) & (x < 410), 0.8, 0.0)  # release 90m before apex
    throttle = np.where((x > 380) & (x < 560), 0.0, 1.0)
    return _lap(speed, brake, throttle)


def _slow_exit_driver(n: int = 2000) -> NormalizedLap:
    """Matches the reference into the corner but recovers speed slowly on exit."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 35.0 * np.exp(-((x - 500.0) ** 2) / (2 * 50.0**2))
    speed = speed - np.where(x >= 500.0, 4.0 * np.exp(-(x - 500.0) / 300.0), 0.0)
    brake = np.where((x > 380) & (x < 480), 0.8, 0.0)
    throttle = np.where((x > 380) & (x < 600), 0.0, 1.0)
    return _lap(speed, brake, throttle)


def test_release_delta_when_driver_releases_early():
    """Driver gives up the brakes ~30m before the reference -> negative delta."""
    result = build_debrief(_early_release_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    assert top.brake_release_delta_m is not None
    assert top.brake_release_delta_m == pytest.approx(-30.0, abs=3.0)


def test_release_delta_none_when_reference_does_not_trail():
    """Reference brakes in a straight line -> trail coaching is meaningless
    here, so the release delta must be None (the trail guard)."""
    result = build_debrief(
        _early_release_driver(), _straightline_brake_reference(), CORNERS
    )
    top = result.diagnoses[0]
    assert top.brake_release_delta_m is None


def test_exit_speed_delta_negative_when_slower_on_exit():
    result = build_debrief(_slow_exit_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    assert top.exit_speed_delta_ms < -1.0


def test_reference_brake_onset_recorded():
    """The reference's brake-onset distance is exposed for the prompt
    scheduler's trigger anchor."""
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    assert top.reference_brake_onset_m == pytest.approx(380.0, abs=15.0)
