"""Deterministic race narrative engine.

Pure functions: RaceData in, RaceNarrative out. No I/O, no AI. Every
number the debrief states is computed here and testable.

Conventions: lap numbers are 1-based; positions are 1-based; gap_s
positive = rival ahead of the player; times in seconds.
"""

from __future__ import annotations

import statistics

from core.race.models import (
    DriverLap,
    GapPoint,
    IRatingAttribution,
)

MIN_CLEAN_LAPS = 3  # below this a driver is excluded from pace ranking


def clean_laps(
    laps: list[DriverLap], caution_laps: set[int]
) -> list[DriverLap]:
    """Laps usable as pace evidence.

    Clean = not lap 1, valid time, no incident, no pit event, not under
    caution. Event matching is case-insensitive substring ("pitted").
    """
    result = []
    for lap in laps:
        if lap.lap_number <= 1:
            continue
        if lap.lap_time <= 0:
            continue
        if lap.incident:
            continue
        if lap.lap_number in caution_laps:
            continue
        events = " ".join(lap.lap_events).lower()
        if "pit" in events:
            continue
        result.append(lap)
    return result


def median_clean_pace(
    laps: list[DriverLap],
    caution_laps: set[int],
    min_laps: int = MIN_CLEAN_LAPS,
) -> float | None:
    """Median clean-lap time, or None with fewer than min_laps clean laps."""
    clean = clean_laps(laps, caution_laps)
    if len(clean) < min_laps:
        return None
    return statistics.median(l.lap_time for l in clean)


def pace_ranking(
    driver_laps: dict[int, list[DriverLap]],
    caution_laps: set[int],
) -> tuple[list[tuple[int, float]], list[int]]:
    """Rank drivers by median clean pace (ascending = fastest first).

    Returns (ranked, unranked): ranked is (cust_id, median) pairs;
    unranked lists drivers with too few clean laps to judge.
    """
    ranked: list[tuple[int, float]] = []
    unranked: list[int] = []
    for cust_id, laps in driver_laps.items():
        pace = median_clean_pace(laps, caution_laps)
        if pace is None:
            unranked.append(cust_id)
        else:
            ranked.append((cust_id, pace))
    ranked.sort(key=lambda pair: pair[1])
    return ranked, unranked


def compute_gaps(
    player_laps: list[DriverLap], rival_laps: list[DriverLap]
) -> list[GapPoint]:
    """Cumulative time gap per lap; positive = rival ahead.

    Truncates at the first invalid lap time on either side — cumulative
    sums are meaningless past a missing lap.
    """
    player_by_lap = {l.lap_number: l.lap_time for l in player_laps}
    rival_by_lap = {l.lap_number: l.lap_time for l in rival_laps}
    common = sorted(set(player_by_lap) & set(rival_by_lap))

    gaps: list[GapPoint] = []
    player_total = 0.0
    rival_total = 0.0
    for lap in common:
        if player_by_lap[lap] <= 0 or rival_by_lap[lap] <= 0:
            break
        player_total += player_by_lap[lap]
        rival_total += rival_by_lap[lap]
        gaps.append(GapPoint(lap=lap, gap_s=player_total - rival_total))
    return gaps


def build_attribution(
    irating_old: int,
    irating_new: int,
    pace_deserved_position: int | None,
    actual_position: int,
    incident_time_lost_s: float,
    lap1_net_positions: int,
) -> IRatingAttribution:
    """Transparent accounting of rating change vs pace and events.

    No counterfactual elo model — states facts and labeled estimates
    only ("never dishonest" applies to the deterministic layer too).
    """
    delta = irating_new - irating_old
    lines: list[str] = []

    if pace_deserved_position is not None:
        lines.append(
            f"Clean-lap pace ranked P{pace_deserved_position}; "
            f"finished P{actual_position}."
        )
    else:
        lines.append(
            f"Finished P{actual_position}; not enough clean laps to rank "
            "race pace."
        )

    if incident_time_lost_s > 0:
        lines.append(
            f"Incident laps cost an estimated {incident_time_lost_s:.1f}s "
            "vs clean pace (lap-granularity estimate)."
        )

    if lap1_net_positions:
        direction = "gained" if lap1_net_positions > 0 else "lost"
        lines.append(
            f"Lap 1: {direction} {abs(lap1_net_positions)} "
            f"position{'s' if abs(lap1_net_positions) != 1 else ''}."
        )

    lines.append(f"iRating: {irating_old} -> {irating_new} ({delta:+d}).")

    return IRatingAttribution(
        irating_old=irating_old,
        irating_new=irating_new,
        irating_delta=delta,
        pace_deserved_position=pace_deserved_position,
        actual_position=actual_position,
        incident_time_lost_s=incident_time_lost_s,
        lap1_net_positions=lap1_net_positions,
        summary_lines=lines,
    )
