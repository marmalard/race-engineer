"""Lap-cleanliness detection: did the incident count rise during this lap?

A lap with a minor infraction usually has PERFECT telemetry — the
normalizer rightly accepts it. This module answers the different question
"does the TIME count?": any mid-lap rise in PlayerCarMyIncidentCount
(1x off-track, 2x loss of control, 4x contact) marks the lap dirty.

Detection only — no phrasing here (the 1x/2x/4x wording lives in
core/live/nudges.py) and no corner naming (consumers use
core.race.narrative.corner_name_at with their loaded corners).
Fail-open everywhere: cleanliness is an enhancement; a missing channel
must never break lap processing.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass
class IncidentMark:
    """One mid-lap incident-count increment."""

    distance_m: float   # LapDist at the tick the count rose
    delta: int          # how much iRacing added (1 / 2 / 4)


@dataclass
class LapCleanliness:
    clean: bool
    marks: list[IncidentMark]


def check_lap_cleanliness(df: pd.DataFrame) -> LapCleanliness:
    """Offline path: one per-lap DataFrame from IBTParser.get_laps().

    Needs PlayerCarMyIncidentCount + LapDist columns (both in
    CORE_CHANNELS). Missing columns or an empty frame -> clean
    (fail-open). Count DECREASES are ignored (session-reset artifacts)."""
    if (
        "PlayerCarMyIncidentCount" not in df.columns
        or "LapDist" not in df.columns
        or len(df) == 0
    ):
        return LapCleanliness(clean=True, marks=[])
    counts = df["PlayerCarMyIncidentCount"].astype(int).to_numpy()
    dists = df["LapDist"].astype(float).to_numpy()
    marks: list[IncidentMark] = []
    for i in range(1, len(counts)):
        delta = int(counts[i] - counts[i - 1])
        if delta > 0:
            marks.append(IncidentMark(distance_m=float(dists[i]), delta=delta))
    return LapCleanliness(clean=not marks, marks=marks)


class IncidentTracker:
    """Live path: pure per-tick state machine (no pyirsdk, no I/O).

    feed() one (incident_count, lap_dist_m) pair per tick; close_lap()
    returns the lap's marks and clears them (the count baseline carries
    over — the sim's counter is session-cumulative); reset() discards
    marks on a lap discard without losing the baseline. None inputs
    (tow / out-of-world ticks) are ignored entirely."""

    def __init__(self) -> None:
        self._last_count: int | None = None
        self._marks: list[IncidentMark] = []

    def feed(self, incident_count: "int | None", lap_dist_m: "float | None") -> None:
        if incident_count is None or lap_dist_m is None:
            return
        if self._last_count is not None:
            delta = int(incident_count) - self._last_count
            if delta > 0:
                self._marks.append(
                    IncidentMark(distance_m=float(lap_dist_m), delta=delta)
                )
        self._last_count = int(incident_count)

    def close_lap(self) -> list[IncidentMark]:
        marks, self._marks = self._marks, []
        return marks

    def reset(self) -> None:
        self._marks = []
