"""Pure lap-boundary state machine for live telemetry.

Fed one sample dict per sim tick, it decides when a lap completes and
whether the completed lap is worth analyzing. It owns no pyirsdk and no
I/O, so the whole risk surface (pits, resets, tows, out/in-laps) is
unit-testable against synthetic tick streams.

Validity here is deliberately coarse: suppress non-positive (pre-green) laps,
laps that touched pit road, laps too short to be real, and discard the buffer
on a backward Lap jump (reset/tow). Finer validity (distance coverage,
distance jumps) is left to
`Normalizer.normalize_lap`, whose `is_valid` flag the consumer checks
downstream — this keeps the state machine simple and its responsibility
single.
"""

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from core.live.lap_buffer import LapBuffer


class DiscardReason(str, Enum):
    """Why a lap the driver was working on was thrown away."""

    RESET = "reset"   # backward Lap jump: reset / tow
    PIT = "pit"       # a pit-touched lap that closed


@dataclass
class CompletedLap:
    """A lap that crossed the start/finish line and passed coarse gating."""

    lap_number: int
    dataframe: pd.DataFrame


class LapBoundaryTracker:
    """Accumulates ticks and emits CompletedLap on valid lap boundaries."""

    def __init__(self, min_lap_samples: int = 100) -> None:
        self.min_lap_samples = min_lap_samples
        self._buffer = LapBuffer()
        self._current_lap: int | None = None
        self._touched_pit = False

    def feed(self, sample: dict) -> CompletedLap | None:
        """Process one tick. Returns a CompletedLap iff this tick closed a
        valid lap, else None."""
        lap = int(sample["Lap"])

        # First tick of the session: start tracking, no boundary yet.
        if self._current_lap is None:
            self._start_lap(lap, sample)
            return None

        # Lap unchanged: keep buffering this lap.
        if lap == self._current_lap:
            if sample.get("OnPitRoad"):
                self._touched_pit = True
            self._buffer.add(sample)
            return None

        # Lap went backward (reset / tow): discard and restart cleanly.
        if lap < self._current_lap:
            self._start_lap(lap, sample)
            return None

        # Lap incremented: the buffered lap is complete. Decide whether to
        # emit it, then start the new lap with this tick.
        completed = self._close_current_lap()
        self._start_lap(lap, sample)
        return completed

    def _start_lap(self, lap: int, first_sample: dict) -> None:
        self._buffer.clear()
        self._current_lap = lap
        self._touched_pit = bool(first_sample.get("OnPitRoad"))
        self._buffer.add(first_sample)

    def _close_current_lap(self) -> CompletedLap | None:
        if self._current_lap is None or self._current_lap < 1:
            return None
        if self._touched_pit:
            return None
        if len(self._buffer) < self.min_lap_samples:
            return None
        return CompletedLap(
            lap_number=self._current_lap,
            dataframe=self._buffer.to_dataframe(),
        )
