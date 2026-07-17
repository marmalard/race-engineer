"""Dataclasses and thresholds for the driver profile.

Thresholds answer one question: at what sample does an aggregate stop
being noise and become a claim the engineer can say out loud? They are
judgment calls, kept as named constants for tuning.
"""

from dataclasses import dataclass, field

RACECRAFT_MIN_RACES = 3      # tendencies unlock at 3 races with the relevant data
READINESS_MIN_SESSIONS = 2   # per-combo readiness unlocks at 2 sessions...
READINESS_MIN_LAPS = 10      # ...and 10 valid laps
RECURRING_CORNER_MIN = 2     # a corner is "recurring trouble" at 2+ incidents
CONSISTENCY_WINDOW_SESSIONS = 3
CONSISTENCY_MIN_LAPS = 5
REPRESENTATIVE_FACTOR = 1.10  # a lap counts as clean only within 110% of the
                               # combo best — same 10% pace-threshold precedent
                               # as the coaching analyzer's disrupted-lap filter

TECHNIQUE_MIN_SESSIONS = 5   # diagnosed sessions before technique speaks
TECHNIQUE_TREND_WINDOW = 5   # recent sessions vs everything before
TTP_FACTOR = 1.01            # time-to-pace: within 101% of session best
TTP_MIN_LAPS = 5             # sessions with fewer valid laps don't count


@dataclass
class StartsTendency:
    """Lap-1/2 racecraft. Positive net = gained places."""

    mean_lap1_net: float | None = None
    mean_lap2_net: float | None = None
    races_lost_ground: int = 0
    sample: int = 0
    enough_data: bool = False


@dataclass
class PaceVsResultTendency:
    """The headline: do results match pace? Positive = finishing worse."""

    mean_positions_left: float | None = None    # positive = finishing worse than pace deserved
    mean_incident_time_lost_s: float | None = None
    mean_actual_position: float | None = None
    mean_deserved_position: float | None = None
    sample: int = 0
    enough_data: bool = False


@dataclass
class IncidentTendency:
    """Incident rate, timing, and recurring trouble corners."""

    mean_incident_points: float | None = None
    lap1_share: float | None = None            # fraction of events on lap 1 (None when no events)
    recurring_corners: list[tuple[str, int]] = field(default_factory=list)
    sample: int = 0
    enough_data: bool = False


@dataclass
class TrajectoryTendency:
    """Start->finish net (positive = gained) and late-race fade.

    DUAL POOL: sample/enough_data cover the position-complete races that
    feed mean_race_net; mean_stint_fade_s pools stint trends from ALL
    races (partial captures included) — gate the fade field on its own
    None-ness, not on enough_data.
    """

    mean_race_net: float | None = None
    mean_stint_fade_s: float | None = None      # positive = slower 2nd half
    sample: int = 0
    enough_data: bool = False


@dataclass
class RacecraftTendencies:
    starts: StartsTendency = field(default_factory=StartsTendency)
    pace_vs_result: PaceVsResultTendency = field(default_factory=PaceVsResultTendency)
    incidents: IncidentTendency = field(default_factory=IncidentTendency)
    trajectory: TrajectoryTendency = field(default_factory=TrajectoryTendency)


@dataclass
class ComboReadiness:
    """Practice-based confidence signals for one (track, car) combo."""

    track_id: str
    track_name: str
    car: str
    sessions: int = 0
    valid_laps: int = 0
    last_driven: str = ""
    best_lap: float | None = None
    pb_trend_s: float | None = None             # positive = getting faster
    consistency_s: float | None = None          # stdev, recent sessions
    enough_data: bool = False


@dataclass
class FaultAggregate:
    """Cross-session aggregate for one FaultKind."""

    kind: str                        # FaultKind.value
    occurrences: int                 # regions where this fault crossed threshold
    combos: int                      # distinct (track_id, car) it appears in
    mean_time_lost_s: float
    trend_time_lost_s: float | None  # recent mean minus earlier mean
                                     # (negative = shrinking = improving);
                                     # None until both pools are non-empty


@dataclass
class TechniqueTendencies:
    """What the persisted loss-region corpus says about technique."""

    dominant: str | None = None
    faults: list[FaultAggregate] = field(default_factory=list)
    recurring_corners: list[tuple[str, int]] = field(default_factory=list)
    sessions_diagnosed: int = 0
    enough_data: bool = False


@dataclass
class TimeToPace:
    """Warm-up habit: how many laps until the driver is on pace."""

    median_laps: float | None = None
    sample_sessions: int = 0
    trend_laps: float | None = None  # negative = reaching pace sooner
    enough_data: bool = False


@dataclass
class DriverProfile:
    cust_id: int = 0
    driver_name: str = ""
    races_captured: int = 0
    combos_tracked: int = 0
    racecraft: RacecraftTendencies = field(default_factory=RacecraftTendencies)
    readiness: list[ComboReadiness] = field(default_factory=list)
    technique: TechniqueTendencies = field(default_factory=TechniqueTendencies)
    time_to_pace: TimeToPace = field(default_factory=TimeToPace)
