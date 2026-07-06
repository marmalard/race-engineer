"""Deterministic race narrative engine.

Pure functions: RaceData in, RaceNarrative out. No I/O, no AI. Every
number the debrief states is computed here and testable.

Conventions: lap numbers are 1-based; positions are 1-based; gap_s
positive = rival ahead of the player; times in seconds.
"""

from __future__ import annotations

import statistics

import pandas as pd

from core.race.models import (
    CautionSegment,
    DriverLap,
    GapPoint,
    IRatingAttribution,
    IncidentEvent,
    Lap1Story,
    LapChartRow,
    NarrativeHeader,
    PaceSummary,
    PlaceChange,
    PositionPoint,
    RaceData,
    RaceNarrative,
    ResultRow,
    RivalGaps,
    Stint,
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


# irsdk SessionFlags bits: caution (0x4000) | caution_waving (0x8000)
CAUTION_MASK = 0x4000 | 0x8000

CORNER_TOLERANCE_M = 50.0


def extract_place_changes(
    df: pd.DataFrame, stable_ticks: int = 60
) -> list[dict]:
    """Position changes from PlayerCarPosition, debounced.

    A change counts only when the new position persists for
    stable_ticks (~1s at 60Hz) — timing flickers are noise.
    Returns dicts: {lap, lap_dist_pct, from_position, to_position}.
    """
    pos = df["PlayerCarPosition"].astype(int).to_numpy()
    laps = df["Lap"].astype(int).to_numpy()
    pct = df["LapDistPct"].astype(float).to_numpy()

    changes: list[dict] = []
    if len(pos) == 0:
        return changes
    last_stable = int(pos[0])
    i = 1
    while i < len(pos):
        if pos[i] != last_stable and pos[i] > 0:
            # A change within the final < stable_ticks samples is accepted on
            # the shorter available window deliberately — end-of-race passes
            # are real events; the trade-off is possible last-sample noise.
            end = min(i + stable_ticks, len(pos))
            window = pos[i:end]
            if (window == pos[i]).all():
                changes.append(
                    {
                        "lap": int(laps[i]),
                        "lap_dist_pct": float(pct[i]),
                        "from_position": last_stable,
                        "to_position": int(pos[i]),
                    }
                )
                last_stable = int(pos[i])
                i = end
                continue
        i += 1
    return changes


def detect_incidents(
    df: pd.DataFrame, context_ticks: int = 120
) -> list[dict]:
    """Steps in PlayerCarMyIncidentCount with surrounding context.

    position_before/after sampled context_ticks (~2s) either side of
    the step. Returns dicts: {lap, lap_dist_pct, delta_incidents,
    position_before, position_after}.
    """
    counts = df["PlayerCarMyIncidentCount"].astype(int).to_numpy()
    laps = df["Lap"].astype(int).to_numpy()
    pct = df["LapDistPct"].astype(float).to_numpy()
    pos = df["PlayerCarPosition"].astype(int).to_numpy()

    events: list[dict] = []
    for i in range(1, len(counts)):
        delta = counts[i] - counts[i - 1]
        if delta <= 0:
            continue
        before = max(0, i - context_ticks)
        after = min(len(pos) - 1, i + context_ticks)
        events.append(
            {
                "lap": int(laps[i]),
                "lap_dist_pct": float(pct[i]),
                "delta_incidents": int(delta),
                "position_before": int(pos[before]),
                "position_after": int(pos[after]),
            }
        )
    return events


def detect_pit_laps(df: pd.DataFrame) -> set[int]:
    """Lap numbers where the player touched pit road."""
    mask = df["OnPitRoad"].astype(bool)
    return set(df.loc[mask, "Lap"].astype(int))


def detect_caution_laps(df: pd.DataFrame) -> set[int]:
    """Lap numbers run at least partly under caution flags."""
    flags = df["SessionFlags"].astype("int64")
    mask = (flags & CAUTION_MASK) != 0
    return set(df.loc[mask, "Lap"].astype(int))


def caution_segments(caution_laps: set[int]) -> list[CautionSegment]:
    """Contiguous caution-lap runs as segments."""
    segments: list[CautionSegment] = []
    for lap in sorted(caution_laps):
        if segments and lap == segments[-1].end_lap + 1:
            segments[-1] = CautionSegment(segments[-1].start_lap, lap)
        else:
            segments.append(CautionSegment(lap, lap))
    return segments


def corner_name_at(corners: list, dist_m: float) -> str | None:
    """Name of the corner containing (or within 50m of) a track distance."""
    for corner in corners:
        start = corner.distance_start_meters
        end = corner.distance_end_meters
        if start is None:
            continue
        if end is None:
            end = start
        if start - CORNER_TOLERANCE_M <= dist_m <= end + CORNER_TOLERANCE_M:
            return corner.name
    return None


def build_stints(
    player_laps: list, pit_laps: set[int], caution_laps: set[int]
) -> list[Stint]:
    """Split the race into stints at pit laps; per-stint pace + trend."""
    if not player_laps:
        return []
    lap_numbers = sorted(l.lap_number for l in player_laps)
    boundaries = sorted(p for p in pit_laps if lap_numbers[0] < p <= lap_numbers[-1])

    stints: list[Stint] = []
    start = lap_numbers[0]
    for boundary in boundaries + [lap_numbers[-1] + 1]:
        end = boundary - 1 if boundary in pit_laps else lap_numbers[-1]
        if start <= end:  # skip degenerate stints (e.g., pit on the final lap)
            stint_laps = [l for l in player_laps if start <= l.lap_number <= end]
            clean = clean_laps(stint_laps, caution_laps)
            median = (
                statistics.median(l.lap_time for l in clean)
                if len(clean) >= MIN_CLEAN_LAPS
                else None
            )
            trend = None
            if len(clean) >= 4:
                half = len(clean) // 2
                trend = statistics.median(
                    l.lap_time for l in clean[half:]
                ) - statistics.median(l.lap_time for l in clean[:half])
            stints.append(
                Stint(start_lap=start, end_lap=end, median_clean_pace=median, trend_s=trend)
            )
        start = boundary + 1 if boundary in pit_laps else start
        if boundary not in pit_laps:
            break
    return stints


def select_key_rivals(
    results: list[ResultRow],
    lap_chart: list[LapChartRow],
    player_cust_id: int,
    max_rivals: int = 4,
    min_adjacent_laps: int = 3,
) -> list[int]:
    """Cars worth telling the story against.

    Finishers directly ahead/behind, plus anyone holding an adjacent
    position for >= min_adjacent_laps, capped at max_rivals.
    """
    player_result = next(
        (r for r in results if r.cust_id == player_cust_id), None
    )
    if player_result is None:
        return []
    rivals: list[int] = []
    for r in results:
        if r.cust_id == player_cust_id:
            continue
        if abs(r.finish_position - player_result.finish_position) == 1:
            rivals.append(r.cust_id)

    # Sustained adjacency from the lap chart
    player_pos = {
        row.lap_number: row.position
        for row in lap_chart
        if row.cust_id == player_cust_id
    }
    adjacency: dict[int, int] = {}
    for row in lap_chart:
        if row.cust_id == player_cust_id:
            continue
        p = player_pos.get(row.lap_number)
        if p is not None and abs(row.position - p) == 1:
            adjacency[row.cust_id] = adjacency.get(row.cust_id, 0) + 1
    for cust_id, laps in sorted(adjacency.items(), key=lambda kv: -kv[1]):
        if laps >= min_adjacent_laps and cust_id not in rivals:
            rivals.append(cust_id)
    return rivals[:max_rivals]


def build_narrative(data: RaceData, corners: list) -> RaceNarrative:
    """Assemble the full RaceNarrative from ingested race data.

    Degrades honestly: with no API data (results/lap_chart/driver_laps
    empty) the telemetry-derived facts still populate; pace ranking and
    attribution are omitted rather than approximated.
    """
    df = data.player_telemetry
    pit_laps = detect_pit_laps(df)
    caution_laps = detect_caution_laps(df)

    player_result = next(
        (r for r in data.results if r.cust_id == data.player_cust_id), None
    )
    player_laps = data.driver_laps.get(data.player_cust_id, [])

    # Position timeline: lap chart canonical, telemetry fallback
    chart_points = sorted(
        (
            PositionPoint(lap=row.lap_number, position=row.position)
            for row in data.lap_chart
            if row.cust_id == data.player_cust_id and row.lap_number >= 1
        ),
        key=lambda p: p.lap,
    )
    if chart_points:
        timeline = chart_points
    else:
        per_lap = df[df["Lap"] >= 1].groupby("Lap")["PlayerCarPosition"].last()
        timeline = [
            PositionPoint(lap=int(lap), position=int(pos))
            for lap, pos in per_lap.items()
            if pos > 0
        ]

    # Lap 1 story
    raw_changes = extract_place_changes(df)
    lap1_changes = [
        PlaceChange(
            lap=c["lap"],
            lap_dist_pct=c["lap_dist_pct"],
            corner_name=corner_name_at(
                corners, c["lap_dist_pct"] * data.track_length_m
            ),
            from_position=c["from_position"],
            to_position=c["to_position"],
        )
        for c in raw_changes
        if c["lap"] == 1
    ]
    grid = player_result.starting_position if player_result else (
        timeline[0].position if timeline else 0
    )
    by_lap = {p.lap: p.position for p in timeline}
    lap1 = (
        Lap1Story(
            grid_position=grid,
            position_after_lap1=by_lap.get(1, grid),
            position_after_lap2=by_lap.get(2, by_lap.get(1, grid)),
            place_changes=lap1_changes,
        )
        if timeline
        else None
    )

    # Incidents with corner names and time-lost estimates
    player_median = median_clean_pace(player_laps, caution_laps)
    lap_times = {l.lap_number: l.lap_time for l in player_laps}
    incidents = []
    for e in detect_incidents(df):
        time_lost = 0.0
        if player_median is not None:
            lap_time = lap_times.get(e["lap"], -1.0)
            if lap_time > 0:
                time_lost = max(0.0, lap_time - player_median)
        incidents.append(
            IncidentEvent(
                lap=e["lap"],
                lap_dist_pct=e["lap_dist_pct"],
                corner_name=corner_name_at(
                    corners, e["lap_dist_pct"] * data.track_length_m
                ),
                delta_incidents=e["delta_incidents"],
                position_before=e["position_before"],
                position_after=e["position_after"],
                time_lost_estimate_s=round(time_lost, 2),
            )
        )

    # Pace + ranking (API-dependent)
    pace = None
    attribution = None
    if player_laps:
        ranked, unranked = pace_ranking(data.driver_laps, caution_laps)
        rank_index = next(
            (
                i + 1
                for i, (cust, _) in enumerate(ranked)
                if cust == data.player_cust_id
            ),
            None,
        )
        clean = clean_laps(player_laps, caution_laps)
        valid_times = [l.lap_time for l in player_laps if l.lap_time > 0]
        pace = PaceSummary(
            median_clean_lap=player_median,
            best_lap=min(valid_times) if valid_times else None,
            consistency_stdev=(
                round(statistics.stdev(l.lap_time for l in clean), 3)
                if len(clean) >= 2
                else None
            ),
            clean_lap_count=len(clean),
            pace_rank=rank_index,
            ranked_drivers=len(ranked),
            unranked_drivers=len(unranked),
        )
        if player_result is not None:
            # Dedupe by lap: multiple incident steps on the same lap each
            # carry the full lap's excess time; summing them directly would
            # double-count. Count each incident lap's excess time once only.
            seen_incident_laps: set[int] = set()
            incident_time_lost_deduped = 0.0
            for i in incidents:
                if i.lap not in seen_incident_laps:
                    incident_time_lost_deduped += i.time_lost_estimate_s
                    seen_incident_laps.add(i.lap)
            attribution = build_attribution(
                irating_old=player_result.oldi_rating,
                irating_new=player_result.newi_rating,
                pace_deserved_position=rank_index,
                actual_position=player_result.finish_position,
                incident_time_lost_s=round(incident_time_lost_deduped, 1),
                lap1_net_positions=(grid - lap1.position_after_lap1)
                if lap1
                else 0,
            )

    # Gaps to key rivals
    rivals = select_key_rivals(data.results, data.lap_chart, data.player_cust_id)
    names = {r.cust_id: r.display_name for r in data.results}
    finishes = {r.cust_id: r.finish_position for r in data.results}
    gaps = [
        RivalGaps(
            cust_id=cust_id,
            display_name=names.get(cust_id, str(cust_id)),
            finish_position=finishes.get(cust_id, 0),
            gaps=compute_gaps(player_laps, data.driver_laps.get(cust_id, [])),
        )
        for cust_id in rivals
        if data.driver_laps.get(cust_id)
    ]

    header = NarrativeHeader(
        subsession_id=data.subsession_id,
        cust_id=data.player_cust_id,
        driver_name=data.driver_name,
        track_id=data.track_id,
        track_name=data.track_name,
        track_config=data.track_config,
        car_name=data.car_name,
        series_name=data.series_name,
        session_date=data.session_date,
        sof=data.sof,
        field_size=len(data.roster),
        start_position=grid,
        finish_position=(
            player_result.finish_position if player_result else (
                timeline[-1].position if timeline else 0
            )
        ),
        incidents=int(df["PlayerCarMyIncidentCount"].astype(int).max())
        if len(df)
        else 0,
        irating_old=player_result.oldi_rating if player_result else 0,
        irating_new=player_result.newi_rating if player_result else 0,
    )

    return RaceNarrative(
        header=header,
        position_timeline=timeline,
        lap1=lap1,
        gaps=gaps,
        incidents=incidents,
        stints=build_stints(player_laps, pit_laps, caution_laps),
        cautions=caution_segments(caution_laps),
        pace=pace,
        attribution=attribution,
        key_rivals=rivals,
    )
