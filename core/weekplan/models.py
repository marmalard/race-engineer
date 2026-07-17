# core/weekplan/models.py
"""Dataclasses for the week plan (v3 arc §3 — the unifying artifact).

Every section is optional; a missing section is a warning, never an
exception. The plan always exists once generated.
"""

from dataclasses import dataclass, field

PRACTICE_MINUTES = 20          # v1 fixed time box
SR_COMFORT = 2.5               # at/above = "even a bad night" sentence
REFRESH_MIN_INTERVAL_S = 3600.0   # hourly throttle on the watcher tick
REFRESH_MAX_AGE_S = 86400.0       # filled plans still refresh daily


@dataclass
class PlanSlot:
    start_utc: str              # ISO 8601
    fits_window: bool


@dataclass
class RaceHalf:
    series_name: str
    season_id: int
    race_week: int              # target week number within the season
    track_id: str
    track_name: str
    config_name: str
    car: str                    # user's most-practiced car at this track
    slots: list[PlanSlot] = field(default_factory=list)
    race_time_limit: int | None = None    # minutes (None = lap-limited)
    race_lap_limit: int | None = None
    standing_start: bool = False
    # curve verdict — None until backfilled post-flip
    implied_ir_lo: int | None = None
    implied_ir_hi: int | None = None
    sof_median: int | None = None
    splits_median: int | None = None
    prep_sessions: int = 0
    prep_best_lap_s: float | None = None


@dataclass
class PracticeHalf:
    kind: str                   # 'prescription' | 'race_combo'
    minutes: int = PRACTICE_MINUTES
    combo: str = ""             # human combo name (both kinds)
    # prescription kind
    fault: str | None = None    # FaultKind.value
    skill_line: str = ""
    transfer_line: str = ""
    # race_combo kind — goal seeded from the latest diagnosis
    goal_label: str = ""
    goal_fault: str = ""        # FAULT_LABELS human name
    goal_time_lost_s: float | None = None
    # both kinds
    ttp_line: str = ""          # time-to-pace sentence, "" when no data


@dataclass
class SRCheck:
    license_class: str          # e.g. "Class C"
    safety_rating: float
    comfortable: bool           # safety_rating >= SR_COMFORT


@dataclass
class WeekPlan:
    week_start: str             # ISO date of the target Tuesday
    created_at: str             # ISO UTC — set once, preserved on refresh
    updated_at: str             # ISO UTC — bumped every refresh
    race: RaceHalf | None = None
    practice: PracticeHalf | None = None
    sr: SRCheck | None = None
    curve_filled: bool = False
    warnings: list[str] = field(default_factory=list)
