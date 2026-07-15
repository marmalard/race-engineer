"""Briefing data models (pure data, no I/O).

BriefingData is the deterministic contract between ingest and render —
the same role RaceData/RaceNarrative play for the race debrief.
"""

from dataclasses import dataclass, field


@dataclass
class CurveBin:
    """One iRating bin of the field's pace curve."""

    ir_lo: int
    ir_hi: int
    median_lap_s: float
    n: int

    @property
    def ir_center(self) -> int:
        return (self.ir_lo + self.ir_hi) // 2


@dataclass
class PaceCurve:
    """Binned pace-vs-iRating curve for one series week."""

    bins: list[CurveBin]
    points: list[tuple[int, float]]  # raw (irating, best_lap_s) for the chart
    subsessions_used: int
    capped: bool  # True when HARVEST_CAP dropped older subsessions


@dataclass
class CurvePlacement:
    """The user's practice PB placed on the curve."""

    lap_s: float
    implied_ir_lo: int | None  # None when the curve is unusable
    implied_ir_hi: int | None
    delta_to_own_band_s: float | None  # lap - median at own iR (negative = faster)


@dataclass
class FieldStats:
    """SoF and field-size norms from the harvested week."""

    sof_p25: int
    sof_median: int
    sof_p75: int
    field_size_median: int
    splits_median: int  # splits per timeslot (session_id groups)


@dataclass
class ComboPrep:
    """Prep-ledger inputs from the user's own practice history."""

    car: str
    sessions: int
    representative_laps: int
    best_lap_s: float | None
    trend_s: float | None  # first-session best minus last (positive = improved)


@dataclass
class RaceSlot:
    start_utc: str  # ISO 8601
    fits_window: bool


@dataclass
class RaceFormat:
    track_name: str
    config_name: str
    race_time_limit: int | None  # minutes
    race_lap_limit: int | None
    standing_start: bool
    max_pct_fuel_fill: float | None


@dataclass
class BriefingData:
    series_name: str
    season_id: int
    race_week: int
    fmt: RaceFormat
    curve: PaceCurve | None = None
    placement: CurvePlacement | None = None
    field_stats: FieldStats | None = None
    prep: ComboPrep | None = None
    slots: list[RaceSlot] = field(default_factory=list)
    user_irating: int | None = None
    warnings: list[str] = field(default_factory=list)
