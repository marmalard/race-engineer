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


@dataclass
class TickResult:
    """The outcome of one fed tick: a completed lap, a discard reason, or
    neither (still buffering). At most one of the two is ever set."""

    completed: CompletedLap | None = None
    discarded: DiscardReason | None = None


class LapBoundaryTracker:
    """Accumulates ticks and emits a TickResult on each fed tick."""

    def __init__(self, min_lap_samples: int = 100) -> None:
        self.min_lap_samples = min_lap_samples
        self._buffer = LapBuffer()
        self._current_lap: int | None = None
        self._touched_pit = False

    def feed(self, sample: dict) -> TickResult:
        """Process one tick. Returns a TickResult describing whether this tick
        closed a valid lap, discarded an in-progress lap, or neither."""
        # pyirsdk can hand back a list (whole-buffer churn) or None for a
        # scalar var around session transitions — one such tick crashed the
        # coach mid-session (2026-07-12). Ignore the tick; the next clean
        # one re-syncs. bool is excluded: True would masquerade as lap 1.
        lap_raw = sample.get("Lap")
        if not isinstance(lap_raw, (int, float)) or isinstance(lap_raw, bool):
            return TickResult()
        lap = int(lap_raw)

        # First tick of the session: start tracking, no boundary yet.
        if self._current_lap is None:
            self._start_lap(lap, sample)
            return TickResult()

        # Lap unchanged: keep buffering this lap.
        if lap == self._current_lap:
            if sample.get("OnPitRoad"):
                self._touched_pit = True
            self._buffer.add(sample)
            return TickResult()

        # Lap went backward (reset / tow): discard and restart cleanly. Only
        # announce it if a real attempt was in the buffer — garage/pit-box
        # resets with tiny buffers stay silent.
        if lap < self._current_lap:
            was_real = (
                self._current_lap >= 1
                and len(self._buffer) >= self.min_lap_samples
            )
            self._start_lap(lap, sample)
            return TickResult(
                discarded=DiscardReason.RESET if was_real else None
            )

        # Lap incremented: the buffered lap is complete. Capture the buffer
        # size BEFORE closing so the PIT check does not depend on whether
        # _close_current_lap happens to leave the buffer intact.
        buffer_size = len(self._buffer)
        completed = self._close_current_lap()
        discarded = None
        if (
            completed is None
            and self._touched_pit
            and self._current_lap is not None
            and self._current_lap >= 1
            and buffer_size >= self.min_lap_samples
        ):
            discarded = DiscardReason.PIT
        self._start_lap(lap, sample)
        return TickResult(completed=completed, discarded=discarded)

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
