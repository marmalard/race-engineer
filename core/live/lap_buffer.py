"""Accumulate live telemetry ticks into a DataFrame the Normalizer consumes.

The live reader hands us one sample dict per sim tick. We store only the
channels `Normalizer.normalize_lap` reads, in the same column shape that
`IBTParser.get_laps()` produces — so the entire offline analysis pipeline
runs on live data unchanged.
"""

import pandas as pd

# Exactly the channels Normalizer.normalize_lap reads (see normalizer.py).
# Order is fixed so the produced DataFrame is deterministic.
SAMPLE_CHANNELS = [
    "LapDist",
    "Speed",
    "Throttle",
    "Brake",
    "SteeringWheelAngle",
    "RPM",
    "Gear",
    "Lat",
    "Lon",
    "SessionTime",
    "LapCurrentLapTime",
]


class LapBuffer:
    """Accumulates per-tick sample dicts for a single lap."""

    def __init__(self) -> None:
        self._rows: list[dict] = []

    def add(self, sample: dict) -> None:
        """Append one tick, keeping only the channels the Normalizer needs."""
        self._rows.append({ch: sample[ch] for ch in SAMPLE_CHANNELS})

    def to_dataframe(self) -> pd.DataFrame:
        """Build the lap DataFrame in normalizer-ready column order."""
        return pd.DataFrame(self._rows, columns=SAMPLE_CHANNELS)

    def clear(self) -> None:
        """Discard all buffered ticks."""
        self._rows = []

    def __len__(self) -> int:
        return len(self._rows)
