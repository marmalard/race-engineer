"""Data models for race ingestion and the race narrative.

RaceData bundles the raw ingested sources (IBT telemetry, roster,
API results); RaceNarrative is the deterministic engine's product and
the single source of truth for rendering, AI synthesis, and persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd


# --- Raw ingested data -------------------------------------------------

@dataclass
class RosterEntry:
    """One driver from the IBT session YAML roster."""

    car_idx: int
    cust_id: int
    display_name: str
    car_number: str
    irating: int
    license_string: str
    car_name: str


@dataclass
class ResultRow:
    """One driver's official result from the Data API."""

    cust_id: int
    display_name: str
    finish_position: int  # 1-based
    starting_position: int  # 1-based
    laps_complete: int
    incidents: int
    oldi_rating: int
    newi_rating: int
    best_lap_time: float  # seconds, -1.0 if none


@dataclass
class DriverLap:
    """One lap by one driver from the Data API lap_data endpoint."""

    cust_id: int
    lap_number: int
    lap_time: float  # seconds, -1.0 if no valid time
    lap_events: list[str] = field(default_factory=list)
    incident: bool = False


@dataclass
class LapChartRow:
    """One car's position at the end of one lap."""

    cust_id: int
    lap_number: int
    position: int


@dataclass
class RaceData:
    """Everything ingested for one race, pre-narrative.

    player_telemetry columns match IBTParser output for the extended
    race channel list. results/lap_chart/driver_laps are empty when the
    Data API was unavailable (partial-narrative mode).
    """

    subsession_id: int
    player_cust_id: int
    player_car_idx: int
    driver_name: str
    track_id: int
    track_name: str
    track_config: str
    track_directory: str  # lovely-track-data slug source
    track_length_m: float
    car_name: str
    series_name: str
    session_date: str
    sof: int
    player_telemetry: pd.DataFrame
    roster: list[RosterEntry] = field(default_factory=list)
    results: list[ResultRow] = field(default_factory=list)
    lap_chart: list[LapChartRow] = field(default_factory=list)
    driver_laps: dict[int, list[DriverLap]] = field(default_factory=dict)


# --- Narrative ----------------------------------------------------------

@dataclass
class NarrativeHeader:
    """Top-level race metadata — who, where, when, outcome."""

    subsession_id: int
    cust_id: int
    driver_name: str
    track_id: int
    track_name: str
    track_config: str
    car_name: str
    series_name: str
    session_date: str
    sof: int
    field_size: int
    start_position: int
    finish_position: int
    incidents: int
    irating_old: int
    irating_new: int


@dataclass
class PositionPoint:
    """Driver position at the end of one lap."""

    lap: int
    position: int


@dataclass
class PlaceChange:
    """A single position change event during the race."""

    lap: int
    lap_dist_pct: float
    corner_name: str | None
    from_position: int
    to_position: int


@dataclass
class Lap1Story:
    """Summary of what happened on the opening lap."""

    grid_position: int
    position_after_lap1: int
    position_after_lap2: int
    place_changes: list[PlaceChange] = field(default_factory=list)


@dataclass
class GapPoint:
    """Gap to a rival at the end of one lap (seconds)."""

    lap: int
    gap_s: float  # positive = rival ahead of player


@dataclass
class RivalGaps:
    """Gap timeline to one key rival."""

    cust_id: int
    display_name: str
    finish_position: int
    gaps: list[GapPoint] = field(default_factory=list)


@dataclass
class IncidentEvent:
    """A discrete incident that affected the driver's race."""

    lap: int
    lap_dist_pct: float
    corner_name: str | None
    delta_incidents: int
    position_before: int
    position_after: int
    time_lost_estimate_s: float


@dataclass
class Stint:
    """A continuous running segment between pit stops or race start/end."""

    start_lap: int
    end_lap: int
    median_clean_pace: float | None  # seconds; None when < 3 clean laps
    trend_s: float | None  # second-half median minus first-half median


@dataclass
class CautionSegment:
    """Laps spent under caution / full-course yellow."""

    start_lap: int
    end_lap: int


@dataclass
class PaceSummary:
    """Aggregated pace statistics for the driver's race."""

    median_clean_lap: float | None
    best_lap: float | None
    consistency_stdev: float | None
    clean_lap_count: int
    pace_rank: int | None  # None when player has < 3 clean laps
    ranked_drivers: int
    unranked_drivers: int


@dataclass
class IRatingAttribution:
    """Breaks down what drove the iRating change."""

    irating_old: int
    irating_new: int
    irating_delta: int
    pace_deserved_position: int | None
    actual_position: int
    incident_time_lost_s: float
    lap1_net_positions: int  # positive = gained places on lap 1
    summary_lines: list[str] = field(default_factory=list)


@dataclass
class RaceNarrative:
    """The deterministic product: every fact the debrief may state."""

    header: NarrativeHeader
    position_timeline: list[PositionPoint] = field(default_factory=list)
    lap1: Lap1Story | None = None
    gaps: list[RivalGaps] = field(default_factory=list)
    incidents: list[IncidentEvent] = field(default_factory=list)
    stints: list[Stint] = field(default_factory=list)
    cautions: list[CautionSegment] = field(default_factory=list)
    pace: PaceSummary | None = None
    attribution: IRatingAttribution | None = None
    key_rivals: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-serializable dict (persistence + AI prompt payload)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RaceNarrative":
        """Rebuild a narrative from to_dict() output."""
        return cls(
            header=NarrativeHeader(**d["header"]),
            position_timeline=[
                PositionPoint(**p) for p in d.get("position_timeline", [])
            ],
            lap1=(
                Lap1Story(
                    grid_position=d["lap1"]["grid_position"],
                    position_after_lap1=d["lap1"]["position_after_lap1"],
                    position_after_lap2=d["lap1"]["position_after_lap2"],
                    place_changes=[
                        PlaceChange(**c) for c in d["lap1"].get("place_changes", [])
                    ],
                )
                if d.get("lap1")
                else None
            ),
            gaps=[
                RivalGaps(
                    cust_id=g["cust_id"],
                    display_name=g["display_name"],
                    finish_position=g["finish_position"],
                    gaps=[GapPoint(**p) for p in g.get("gaps", [])],
                )
                for g in d.get("gaps", [])
            ],
            incidents=[IncidentEvent(**i) for i in d.get("incidents", [])],
            stints=[Stint(**s) for s in d.get("stints", [])],
            cautions=[CautionSegment(**c) for c in d.get("cautions", [])],
            pace=PaceSummary(**d["pace"]) if d.get("pace") else None,
            attribution=(
                IRatingAttribution(**d["attribution"])
                if d.get("attribution")
                else None
            ),
            key_rivals=list(d.get("key_rivals", [])),
        )
