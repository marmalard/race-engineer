"""PURE racecraft-tendency engine: list[RaceNarrative] -> tendencies.

No I/O, no AI. Sign convention: positive = gained places. Sample sizes
are PER TENDENCY — a partial narrative (auto-captured without API
results) contributes to whichever tendencies its data supports.
"""

from collections import Counter
from statistics import mean

from core.profile.models import (
    RACECRAFT_MIN_RACES,
    RECURRING_CORNER_MIN,
    IncidentTendency,
    PaceVsResultTendency,
    RacecraftTendencies,
    StartsTendency,
    TrajectoryTendency,
)
from core.race.models import RaceNarrative


def _starts(narratives: list[RaceNarrative]) -> StartsTendency:
    lap1s = [n.lap1 for n in narratives if n.lap1 is not None]
    if not lap1s:
        return StartsTendency()
    nets1 = [l.grid_position - l.position_after_lap1 for l in lap1s]
    nets2 = [l.position_after_lap1 - l.position_after_lap2 for l in lap1s]
    return StartsTendency(
        mean_lap1_net=mean(nets1),
        mean_lap2_net=mean(nets2),
        races_lost_ground=sum(1 for x in nets1 if x < 0),
        sample=len(lap1s),
        enough_data=len(lap1s) >= RACECRAFT_MIN_RACES,
    )


def _pace_vs_result(narratives: list[RaceNarrative]) -> PaceVsResultTendency:
    attrs = [
        n.attribution for n in narratives
        if n.attribution is not None
        and n.attribution.pace_deserved_position is not None
    ]
    if not attrs:
        return PaceVsResultTendency()
    return PaceVsResultTendency(
        mean_positions_left=mean(
            [a.actual_position - a.pace_deserved_position for a in attrs]
        ),
        mean_incident_time_lost_s=mean([a.incident_time_lost_s for a in attrs]),
        mean_actual_position=mean([a.actual_position for a in attrs]),
        mean_deserved_position=mean([a.pace_deserved_position for a in attrs]),
        sample=len(attrs),
        enough_data=len(attrs) >= RACECRAFT_MIN_RACES,
    )


def _incidents(narratives: list[RaceNarrative]) -> IncidentTendency:
    if not narratives:
        return IncidentTendency()
    events = [e for n in narratives for e in n.incidents]
    corners = Counter(e.corner_name for e in events if e.corner_name)
    recurring = sorted(
        [(c, k) for c, k in corners.items() if k >= RECURRING_CORNER_MIN],
        key=lambda x: (-x[1], x[0]),
    )
    return IncidentTendency(
        # Guarded by the early return above; keep the inline guard too so a
        # future refactor of that guard can't turn this into StatisticsError.
        mean_incident_points=(
            mean([n.header.incidents for n in narratives])
            if narratives else None
        ),
        lap1_share=(
            sum(1 for e in events if e.lap <= 1) / len(events)
            if events else None
        ),
        recurring_corners=recurring,
        sample=len(narratives),
        enough_data=len(narratives) >= RACECRAFT_MIN_RACES,
    )


def _trajectory(narratives: list[RaceNarrative]) -> TrajectoryTendency:
    # DUAL-POOL contract: mean_race_net / sample / enough_data come from
    # position-complete narratives ONLY; mean_stint_fade_s pools stint
    # trends from ALL narratives (a partial capture has stints but no
    # positions). Consumers must gate the fade field on its own
    # None-ness, not on enough_data — see TrajectoryTendency.
    # Partial captures without results have 0/absent positions — skip them.
    with_pos = [
        n.header for n in narratives
        if n.header.start_position >= 1 and n.header.finish_position >= 1
    ]
    trends = [
        s.trend_s for n in narratives for s in n.stints if s.trend_s is not None
    ]
    if not with_pos and not trends:
        return TrajectoryTendency()
    return TrajectoryTendency(
        mean_race_net=(
            mean([h.start_position - h.finish_position for h in with_pos])
            if with_pos else None
        ),
        mean_stint_fade_s=mean(trends) if trends else None,
        sample=len(with_pos),
        enough_data=len(with_pos) >= RACECRAFT_MIN_RACES,
    )


def build_racecraft(narratives: list[RaceNarrative]) -> RacecraftTendencies:
    """All four tendencies from the driver's stored race narratives."""
    return RacecraftTendencies(
        starts=_starts(narratives),
        pace_vs_result=_pace_vs_result(narratives),
        incidents=_incidents(narratives),
        trajectory=_trajectory(narratives),
    )
