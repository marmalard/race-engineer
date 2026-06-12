"""Tests for LapBuffer — accumulating live ticks into a DataFrame the
Normalizer can consume."""

import numpy as np
import pandas as pd

from core.live.lap_buffer import LapBuffer, SAMPLE_CHANNELS
from core.telemetry.normalizer import NormalizedLap, Normalizer


def _tick(lapdist: float, session_time: float, speed: float = 50.0) -> dict:
    """A full live sample dict with all channels plus some extras the
    buffer should ignore."""
    return {
        "LapDist": lapdist,
        "Speed": speed,
        "Throttle": 1.0,
        "Brake": 0.0,
        "SteeringWheelAngle": 0.0,
        "RPM": 6000.0,
        "Gear": 4,
        "Lat": 50.0,
        "Lon": 5.0,
        "SessionTime": session_time,
        "LapCurrentLapTime": session_time,
        # Extra channels the buffer is not responsible for storing:
        "Lap": 3,
        "OnPitRoad": False,
        "PlayerTrackSurface": 3,
    }


def test_buffer_starts_empty():
    buf = LapBuffer()
    assert len(buf) == 0


def test_add_increments_length():
    buf = LapBuffer()
    buf.add(_tick(0.0, 0.0))
    buf.add(_tick(1.0, 0.02))
    assert len(buf) == 2


def test_to_dataframe_has_exactly_sample_channels():
    buf = LapBuffer()
    buf.add(_tick(0.0, 0.0))
    df = buf.to_dataframe()
    assert list(df.columns) == SAMPLE_CHANNELS
    # Extras like Lap / OnPitRoad are NOT columns
    assert "OnPitRoad" not in df.columns


def test_clear_empties_buffer():
    buf = LapBuffer()
    buf.add(_tick(0.0, 0.0))
    buf.clear()
    assert len(buf) == 0
    assert len(buf.to_dataframe()) == 0


def test_dataframe_feeds_normalizer():
    """A buffered lap must be consumable by the real Normalizer."""
    buf = LapBuffer()
    track_length = 1000.0
    # Build a plausible single lap: distance 0..999, time rising
    for i in range(1000):
        buf.add(_tick(float(i), i * 0.02, speed=50.0))
    df = buf.to_dataframe()
    nlap = Normalizer().normalize_lap(df, lap_number=3, track_length_m=track_length)
    assert isinstance(nlap, NormalizedLap)
    assert nlap.is_valid
    assert nlap.distance[1] - nlap.distance[0] == 1.0
    assert np.all(nlap.speed >= 0)
