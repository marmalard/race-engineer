"""Tests for the LapBoundaryTracker state machine.

Fed one sample dict per tick, it emits a CompletedLap when a valid lap
boundary is crossed and suppresses pit / reset / tow / too-short laps.
No pyirsdk, no live sim — pure synthetic tick streams.
"""

from core.live.session_reader import CompletedLap, LapBoundaryTracker


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
    """Feed n ticks of one lap; return the list of emissions."""
    emissions = []
    for i in range(n):
        out = tracker.feed(
            _tick(lap_num, float(i), t0 + i * 0.02, on_pit=on_pit)
        )
        emissions.append(out)
    return emissions


def test_no_emission_during_a_lap():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    emissions = _drive_lap(tracker, lap_num=1)
    assert all(e is None for e in emissions)


def test_lap_completes_on_increment():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=1, n=300, t0=0.0)
    # First tick of lap 2 closes lap 1
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert isinstance(out, CompletedLap)
    assert out.lap_number == 1
    assert len(out.dataframe) == 300


def test_out_lap_then_flying_lap():
    """Lap 1 is the out-lap; lap 2 flying. Both should emit (the consumer
    decides validity downstream), but the out-lap with a pit sample must
    be suppressed."""
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Lap 1 = out-lap, started in pit (first 50 ticks on pit road)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i < 50)))
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert out is None  # lap 1 touched pit road → suppressed


def test_clean_flying_lap_after_pit_lap_emits():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Lap 1 = pit lap (suppressed)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i < 50)))
    tracker.feed(_tick(2, 0.0, 6.0))  # closes lap 1 (suppressed)
    # Lap 2 = clean flying lap
    for i in range(1, 300):
        tracker.feed(_tick(2, float(i), 6.0 + i * 0.02))
    out = tracker.feed(_tick(3, 0.0, 12.0))  # closes lap 2
    assert isinstance(out, CompletedLap)
    assert out.lap_number == 2


def test_in_lap_to_pit_suppressed():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Lap 1 dives into pit near the end
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i > 250)))
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert out is None


def test_reset_lap_backward_discards_buffer():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=5, n=150, t0=0.0)
    # Sim reset: Lap jumps backward to 1, no completed lap emitted
    out = tracker.feed(_tick(1, 0.0, 0.0))
    assert out is None
    # And the new lap accumulates cleanly afterward
    for i in range(1, 300):
        tracker.feed(_tick(1, float(i), i * 0.02))
    closed = tracker.feed(_tick(2, 0.0, 6.0))
    assert isinstance(closed, CompletedLap)
    assert closed.lap_number == 1


def test_too_short_lap_suppressed():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Only 40 ticks before the lap flips — too short to be a real lap
    for i in range(40):
        tracker.feed(_tick(1, float(i), i * 0.02))
    out = tracker.feed(_tick(2, 0.0, 1.0))
    assert out is None


def test_lap_zero_is_not_emitted():
    """iRacing reports Lap 0 pre-green; it is never a real flying lap."""
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Drive a full, clean, non-pit Lap 0 (>= min_lap_samples ticks)
    for i in range(300):
        tracker.feed(_tick(0, float(i), i * 0.02))
    # Crossing to Lap 1 must NOT emit the garbage Lap 0
    out = tracker.feed(_tick(1, 0.0, 6.0))
    assert out is None
    # ...but the real Lap 1 that follows emits normally
    for i in range(1, 300):
        tracker.feed(_tick(1, float(i), 6.0 + i * 0.02))
    closed = tracker.feed(_tick(2, 0.0, 12.0))
    assert isinstance(closed, CompletedLap)
    assert closed.lap_number == 1


def test_emitted_dataframe_is_normalizer_shaped():
    from core.live.lap_buffer import SAMPLE_CHANNELS
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=1, n=300)
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert list(out.dataframe.columns) == SAMPLE_CHANNELS
