"""Tests for the LapBoundaryTracker state machine.

Fed one sample dict per tick, it emits a CompletedLap when a valid lap
boundary is crossed and suppresses pit / reset / tow / too-short laps.
No pyirsdk, no live sim — pure synthetic tick streams.
"""

from core.live.session_reader import (
    CompletedLap,
    DiscardReason,
    LapBoundaryTracker,
)


def _tick(lap: int, lapdist: float, session_time: float,
          on_pit: bool = False, surface: int = 3) -> dict:
    return {
        "Lap": lap,
        "LapDist": lapdist,
        "Speed": 50.0,
        "Throttle": 1.0,
        "Brake": 0.0,
        "SteeringWheelAngle": 0.0,
        "RPM": 6000.0,
        "Gear": 4,
        "Lat": 50.0,
        "Lon": 5.0,
        "SessionTime": session_time,
        "LapCurrentLapTime": session_time,
        "OnPitRoad": on_pit,
        "PlayerTrackSurface": surface,
    }


def _drive_lap(tracker, lap_num, n=300, t0=0.0, on_pit=False):
    """Feed n ticks of one lap; return the list of TickResults."""
    results = []
    for i in range(n):
        out = tracker.feed(
            _tick(lap_num, float(i), t0 + i * 0.02, on_pit=on_pit)
        )
        results.append(out)
    return results


def test_no_emission_during_a_lap():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    results = _drive_lap(tracker, lap_num=1)
    assert all(r.completed is None for r in results)
    assert all(r.discarded is None for r in results)


def test_lap_completes_on_increment():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=1, n=300, t0=0.0)
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert isinstance(out.completed, CompletedLap)
    assert out.completed.lap_number == 1
    assert len(out.completed.dataframe) == 300
    assert out.discarded is None


def test_out_lap_then_flying_lap():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i < 50)))
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert out.completed is None  # lap 1 touched pit road → suppressed
    assert out.discarded is DiscardReason.PIT


def test_clean_flying_lap_after_pit_lap_emits():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i < 50)))
    tracker.feed(_tick(2, 0.0, 6.0))  # closes lap 1 (pit, suppressed)
    for i in range(1, 300):
        tracker.feed(_tick(2, float(i), 6.0 + i * 0.02))
    out = tracker.feed(_tick(3, 0.0, 12.0))  # closes lap 2
    assert isinstance(out.completed, CompletedLap)
    assert out.completed.lap_number == 2
    assert out.discarded is None


def test_in_lap_to_pit_suppressed():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i > 250)))
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert out.completed is None
    assert out.discarded is DiscardReason.PIT


def test_reset_lap_backward_discards_buffer():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=5, n=150, t0=0.0)
    # Sim reset: Lap jumps backward to 1. Real attempt was buffered → RESET.
    out = tracker.feed(_tick(1, 0.0, 0.0))
    assert out.completed is None
    assert out.discarded is DiscardReason.RESET
    # And the new lap accumulates cleanly afterward
    for i in range(1, 300):
        tracker.feed(_tick(1, float(i), i * 0.02))
    closed = tracker.feed(_tick(2, 0.0, 6.0))
    assert isinstance(closed.completed, CompletedLap)
    assert closed.completed.lap_number == 1


def test_reset_with_tiny_buffer_is_silent():
    """A backward jump with only a few buffered ticks (garage/pit-box reset)
    must not announce a discard."""
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(10):
        tracker.feed(_tick(3, float(i), i * 0.02))
    out = tracker.feed(_tick(1, 0.0, 0.0))
    assert out.completed is None
    assert out.discarded is None


def test_too_short_lap_suppressed():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(40):
        tracker.feed(_tick(1, float(i), i * 0.02))
    out = tracker.feed(_tick(2, 0.0, 1.0))
    assert out.completed is None
    assert out.discarded is None  # too-short is not announced


def test_lap_zero_is_not_emitted():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(300):
        tracker.feed(_tick(0, float(i), i * 0.02))
    out = tracker.feed(_tick(1, 0.0, 6.0))
    assert out.completed is None
    for i in range(1, 300):
        tracker.feed(_tick(1, float(i), 6.0 + i * 0.02))
    closed = tracker.feed(_tick(2, 0.0, 12.0))
    assert isinstance(closed.completed, CompletedLap)
    assert closed.completed.lap_number == 1


def test_emitted_dataframe_is_normalizer_shaped():
    from core.live.lap_buffer import SAMPLE_CHANNELS
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=1, n=300)
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert list(out.completed.dataframe.columns) == SAMPLE_CHANNELS


def test_pit_fragment_below_threshold_is_silent():
    """A short pit-touched fragment (below min_lap_samples) that closes must
    not announce PIT — same noise-gating as the tiny-buffer reset case."""
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(40):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=True))
    out = tracker.feed(_tick(2, 0.0, 1.0))
    assert out.completed is None
    assert out.discarded is None
