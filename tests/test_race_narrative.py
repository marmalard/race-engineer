"""Tests for the deterministic race narrative engine (pure functions)."""

import pytest

from core.race.models import DriverLap
from core.race.narrative import (
    all_lap_ranking,
    build_attribution,
    clean_laps,
    compute_gaps,
    median_clean_pace,
    pace_ranking,
)


def _laps(cust_id: int, times: list[float], **overrides) -> list[DriverLap]:
    """Laps numbered from 1 with the given times, all clean by default."""
    laps = [
        DriverLap(cust_id=cust_id, lap_number=i + 1, lap_time=t)
        for i, t in enumerate(times)
    ]
    for lap_number, kwargs in overrides.items():
        lap = laps[int(lap_number) - 1]
        for k, v in kwargs.items():
            setattr(lap, k, v)
    return laps


# --- clean_laps ---------------------------------------------------------

def test_clean_laps_excludes_lap1_incidents_pits_cautions_invalid():
    laps = _laps(1, [100.0, 101.0, 102.0, 103.0, 104.0, -1.0])
    laps[1].incident = True                 # lap 2: incident
    laps[2].lap_events = ["pitted"]         # lap 3: pit
    result = clean_laps(laps, caution_laps={5})
    # lap 1 (first lap), lap 2 (incident), lap 3 (pit), lap 5 (caution),
    # lap 6 (invalid time) all excluded -> only lap 4 remains
    assert [l.lap_number for l in result] == [4]


def test_clean_laps_event_matching_is_case_insensitive():
    laps = _laps(1, [100.0, 101.0])
    laps[1].lap_events = ["Pitted"]
    assert [l.lap_number for l in clean_laps(laps, caution_laps=set())] == []


# --- median_clean_pace ---------------------------------------------------

def test_median_clean_pace_requires_three_clean_laps():
    laps = _laps(1, [100.0, 101.0, 103.0])  # lap 1 excluded -> 2 clean
    assert median_clean_pace(laps, caution_laps=set()) is None


def test_median_clean_pace_is_median():
    laps = _laps(1, [100.0, 101.0, 103.0, 105.0])  # clean: 101, 103, 105
    assert median_clean_pace(laps, caution_laps=set()) == 103.0


# --- pace_ranking --------------------------------------------------------

def test_pace_ranking_orders_by_median_and_excludes_thin_data():
    driver_laps = {
        1: _laps(1, [100.0, 101.0, 101.0, 101.0]),   # median 101
        2: _laps(2, [100.0, 99.0, 99.0, 99.0]),       # median 99 (faster)
        3: _laps(3, [100.0, 98.0]),                   # only 1 clean -> unranked
    }
    ranked, unranked = pace_ranking(driver_laps, caution_laps=set())
    assert [cust for cust, _ in ranked] == [2, 1]
    assert unranked == [3]


# --- all_lap_ranking (survivorship counterweight) --------------------------

def test_all_lap_ranking_prices_incident_laps():
    # Driver 1 has blistering clean laps but MOST laps were ruined by
    # incidents (the real 2026-07-12 Summit shape: 6 incidents in 9
    # laps); driver 2 runs steady 101s with zero incidents. The clean
    # ranking crowns driver 1 via survivorship (median 99 vs 101); the
    # all-lap ranking counts the ruined laps and puts driver 2 ahead.
    d1 = _laps(1, [100.0, 99.0, 99.0, 99.0, 115.0, 115.0, 115.0, 115.0])
    for i in (4, 5, 6, 7):
        d1[i].incident = True
    d2 = _laps(2, [100.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0])
    driver_laps = {1: d1, 2: d2}

    clean_ranked, _ = pace_ranking(driver_laps, caution_laps=set())
    assert clean_ranked[0][0] == 1  # survivorship flatters driver 1

    all_ranked = all_lap_ranking(driver_laps)
    assert all_ranked[0][0] == 2  # execution wins over all laps
    # d1 all-lap median over [99,99,99,115,115,115,115] = 115
    assert all_ranked[1] == (1, 115.0)


def test_all_lap_ranking_requires_min_laps_and_skips_invalid():
    driver_laps = {
        1: _laps(1, [100.0, 101.0, -1.0]),  # only 1 valid post-lap-1 lap
        2: _laps(2, [100.0, 99.0, 99.0, 99.0]),
    }
    ranked = all_lap_ranking(driver_laps)
    assert [cust for cust, _ in ranked] == [2]


# --- compute_gaps --------------------------------------------------------

def test_compute_gaps_positive_when_rival_ahead():
    player = _laps(1, [100.0, 100.0, 100.0])
    rival = _laps(2, [99.0, 99.0, 99.0])  # rival pulls 1s/lap ahead
    gaps = compute_gaps(player, rival)
    assert [round(g.gap_s, 3) for g in gaps] == [1.0, 2.0, 3.0]
    assert [g.lap for g in gaps] == [1, 2, 3]


def test_compute_gaps_stops_at_first_invalid_time():
    player = _laps(1, [100.0, -1.0, 100.0])
    rival = _laps(2, [99.0, 99.0, 99.0])
    gaps = compute_gaps(player, rival)
    assert len(gaps) == 1  # lap 2 invalid -> series truncated


# --- build_attribution ----------------------------------------------------

def test_build_attribution_accounts_for_pace_vs_finish():
    attribution = build_attribution(
        irating_old=1420,
        irating_new=1400,
        pace_deserved_position=5,
        actual_position=9,
        incident_time_lost_s=12.5,
        lap1_net_positions=-2,
    )
    assert attribution.irating_delta == -20
    assert attribution.pace_deserved_position == 5
    assert attribution.actual_position == 9
    # Summary lines are deterministic facts, not AI text
    joined = " ".join(attribution.summary_lines)
    assert "P5" in joined and "P9" in joined
    assert "12.5" in joined


def test_build_attribution_pace_claims_carry_sample_and_all_lap_rank():
    attribution = build_attribution(
        irating_old=1400,
        irating_new=1409,
        pace_deserved_position=1,
        actual_position=6,
        incident_time_lost_s=7.1,
        lap1_net_positions=-1,
        clean_lap_count=3,
        all_lap_rank=4,
    )
    joined = " ".join(attribution.summary_lines)
    assert "(from 3 clean laps)" in joined
    assert "ALL laps driven" in joined and "P4" in joined


def test_build_attribution_all_lap_line_skipped_when_ranks_agree():
    attribution = build_attribution(
        irating_old=1400,
        irating_new=1410,
        pace_deserved_position=2,
        actual_position=2,
        incident_time_lost_s=0.0,
        lap1_net_positions=0,
        clean_lap_count=8,
        all_lap_rank=2,
    )
    assert not any(
        "ALL laps" in line for line in attribution.summary_lines
    )


def test_build_attribution_handles_unranked_pace():
    attribution = build_attribution(
        irating_old=1420,
        irating_new=1400,
        pace_deserved_position=None,
        actual_position=9,
        incident_time_lost_s=0.0,
        lap1_net_positions=0,
    )
    assert attribution.pace_deserved_position is None
    assert any("not enough clean laps" in line for line in attribution.summary_lines)


import pandas as pd

from core.race.models import (
    LapChartRow,
    RaceData,
    ResultRow,
    RosterEntry,
    Stint,
)
from core.race.narrative import (
    CAUTION_MASK,
    build_narrative,
    build_stints,
    corner_name_at,
    detect_caution_laps,
    detect_incidents,
    detect_pit_laps,
    extract_place_changes,
    select_key_rivals,
)


def _ticks(**columns) -> pd.DataFrame:
    """Telemetry frame from equal-length column lists."""
    return pd.DataFrame(columns)


def _tel(
    n: int,
    lap=None,
    pos=None,
    pct=None,
    incidents=None,
    pit=None,
    flags=None,
) -> pd.DataFrame:
    return _ticks(
        Lap=lap if lap is not None else [1] * n,
        PlayerCarPosition=pos if pos is not None else [5] * n,
        LapDistPct=pct if pct is not None else [i / n for i in range(n)],
        PlayerCarMyIncidentCount=incidents if incidents is not None else [0] * n,
        OnPitRoad=pit if pit is not None else [False] * n,
        SessionFlags=flags if flags is not None else [0] * n,
        LapCurrentLapTime=[float(i) for i in range(n)],
    )


# --- extract_place_changes -------------------------------------------------

def test_extract_place_changes_requires_stability():
    # Position flickers 5->4 for 3 ticks (noise), then settles at 4
    pos = [5] * 100 + [4] * 3 + [5] * 100 + [4] * 100
    df = _tel(303, pos=pos)
    changes = extract_place_changes(df, stable_ticks=60)
    assert len(changes) == 1
    assert changes[0]["from_position"] == 5
    assert changes[0]["to_position"] == 4


# --- detect_incidents --------------------------------------------------------

def test_detect_incidents_reports_steps_with_context():
    n = 800
    incidents = [0] * 400 + [2] * 400  # one 2x at tick 400
    pos = [6] * 380 + [6] * 40 + [8] * 380
    lap = [9] * n
    df = _tel(n, lap=lap, pos=pos, incidents=incidents)
    events = detect_incidents(df, context_ticks=120)
    assert len(events) == 1
    assert events[0]["lap"] == 9
    assert events[0]["delta_incidents"] == 2
    assert events[0]["position_before"] == 6
    assert events[0]["position_after"] == 8


# --- detect_pit_laps / detect_caution_laps ----------------------------------

def test_detect_pit_laps():
    df = _tel(6, lap=[1, 1, 2, 2, 3, 3], pit=[False, False, True, True, False, False])
    assert detect_pit_laps(df) == {2}


def test_detect_caution_laps_uses_flag_bits():
    df = _tel(6, lap=[1, 1, 2, 2, 3, 3], flags=[0, 0, CAUTION_MASK, 0, 0, 0])
    assert detect_caution_laps(df) == {2}


# --- corner_name_at -----------------------------------------------------------

class _FakeCorner:
    def __init__(self, name, start, end):
        self.name = name
        self.distance_start_meters = start
        self.distance_end_meters = end


def test_corner_name_at_matches_with_tolerance():
    corners = [_FakeCorner("Knickerbrook", 2500.0, 2650.0)]
    assert corner_name_at(corners, 2600.0) == "Knickerbrook"
    assert corner_name_at(corners, 2460.0) == "Knickerbrook"  # within 50m
    assert corner_name_at(corners, 1000.0) is None


# --- select_key_rivals ----------------------------------------------------------

def _result(cust_id, finish):
    return ResultRow(
        cust_id=cust_id,
        display_name=f"D{cust_id}",
        finish_position=finish,
        starting_position=finish,
        laps_complete=10,
        incidents=0,
        oldi_rating=1500,
        newi_rating=1500,
        best_lap_time=100.0,
    )


def test_select_key_rivals_adjacent_finishers_and_battles():
    results = [_result(i, i) for i in range(1, 8)]  # player is cust 4, P4
    # cust 7 held the position adjacent to the player for 4 laps
    lap_chart = []
    for lap in range(1, 5):
        lap_chart.append(LapChartRow(cust_id=4, lap_number=lap, position=4))
        lap_chart.append(LapChartRow(cust_id=7, lap_number=lap, position=5))
    rivals = select_key_rivals(results, lap_chart, player_cust_id=4)
    assert 3 in rivals and 5 in rivals  # finished directly ahead/behind
    assert 7 in rivals                   # sustained adjacency battle
    assert len(rivals) <= 4


# --- build_narrative ------------------------------------------------------------

def _race_data() -> RaceData:
    n = 400
    df = _ticks(
        Lap=[1] * 100 + [2] * 100 + [3] * 100 + [4] * 100,
        PlayerCarPosition=[8] * 90 + [7] * 310,
        LapDistPct=list(pd.Series(range(n)) % 100 / 100.0),
        PlayerCarMyIncidentCount=[0] * 250 + [1] * 150,
        OnPitRoad=[False] * n,
        SessionFlags=[0] * n,
        LapCurrentLapTime=[float(i % 100) for i in range(n)],
    )
    laps = {
        1226848: _laps(1226848, [101.0, 100.0, 100.5, 100.2]),
        999: _laps(999, [100.5, 99.5, 99.8, 99.9]),
    }
    return RaceData(
        subsession_id=86748877,
        player_cust_id=1226848,
        player_car_idx=6,
        driver_name="Anthony Moorman",
        track_id=180,
        track_name="Oulton Park Circuit",
        track_config="International",
        track_directory="oulton international",
        track_length_m=4286.5,
        car_name="Mazda MX-5 Cup",
        series_name="MX-5 Cup",
        session_date="2026-06-26",
        sof=1350,
        player_telemetry=df,
        roster=[
            RosterEntry(6, 1226848, "Anthony Moorman", "8", 1420, "D 4.5", "MX-5"),
            RosterEntry(2, 999, "Rival One", "9", 1500, "D 4.9", "MX-5"),
        ],
        results=[_result(999, 6), _result(1226848, 7)],
        lap_chart=[
            LapChartRow(cust_id=1226848, lap_number=lap, position=p)
            for lap, p in [(1, 7), (2, 7), (3, 7), (4, 7)]
        ],
        driver_laps=laps,
    )


def test_build_narrative_assembles_all_sections():
    narrative = build_narrative(_race_data(), corners=[])
    assert narrative.header.subsession_id == 86748877
    assert narrative.header.finish_position == 7
    assert narrative.position_timeline[0].position == 7
    assert narrative.lap1 is not None
    assert narrative.lap1.grid_position == 7  # from ResultRow.starting_position
    assert narrative.pace is not None
    assert narrative.pace.median_clean_lap is not None
    assert narrative.attribution is not None
    assert len(narrative.incidents) == 1
    assert narrative.gaps  # rival 999 fetched laps -> gap series exists


def test_build_narrative_partial_without_api_data():
    data = _race_data()
    data.results = []
    data.lap_chart = []
    data.driver_laps = {}
    narrative = build_narrative(data, corners=[])
    # Telemetry-only facts still present
    assert len(narrative.incidents) == 1
    assert narrative.position_timeline  # falls back to telemetry positions
    # API-dependent facts absent, not faked
    assert narrative.pace is None or narrative.pace.pace_rank is None
    assert narrative.attribution is None


# --- incident time-lost deduplication (Issue 1) --------------------------

def test_incident_time_lost_deduped_by_lap():
    """Two incident steps on the same lap → attribution counts that lap once."""
    # 5 laps × 50 ticks = 250 ticks total
    n = 250
    lap_col = [1] * 50 + [2] * 50 + [3] * 50 + [4] * 50 + [5] * 50
    # Two incident steps both in lap 3 (ticks 110 and 130)
    inc_col = [0] * 110 + [1] * 20 + [2] * 120
    df = _ticks(
        Lap=lap_col,
        PlayerCarPosition=[5] * n,
        LapDistPct=[i / 50 % 1.0 for i in range(n)],
        PlayerCarMyIncidentCount=inc_col,
        OnPitRoad=[False] * n,
        SessionFlags=[0] * n,
        LapCurrentLapTime=[float(i % 50) for i in range(n)],
    )
    # Lap 3 is an incident lap (slow); laps 2, 4, 5 are clean
    player_laps_list = _laps(1226848, [101.0, 100.0, 120.0, 100.5, 100.2])
    player_laps_list[2].incident = True  # lap 3
    laps = {
        1226848: player_laps_list,
        999: _laps(999, [100.5, 99.5, 99.8, 99.9, 100.0]),
    }
    data = RaceData(
        subsession_id=86748877,
        player_cust_id=1226848,
        player_car_idx=6,
        driver_name="Anthony Moorman",
        track_id=180,
        track_name="Oulton Park Circuit",
        track_config="International",
        track_directory="oulton international",
        track_length_m=4286.5,
        car_name="Mazda MX-5 Cup",
        series_name="MX-5 Cup",
        session_date="2026-06-26",
        sof=1350,
        player_telemetry=df,
        roster=[
            RosterEntry(6, 1226848, "Anthony Moorman", "8", 1420, "D 4.5", "MX-5"),
            RosterEntry(2, 999, "Rival One", "9", 1500, "D 4.9", "MX-5"),
        ],
        results=[_result(999, 6), _result(1226848, 7)],
        lap_chart=[
            LapChartRow(cust_id=1226848, lap_number=lap, position=5)
            for lap in range(1, 6)
        ],
        driver_laps=laps,
    )
    narrative = build_narrative(data, corners=[])
    # Both incident steps must be detected on lap 3
    lap3_events = [i for i in narrative.incidents if i.lap == 3]
    assert len(lap3_events) == 2, "Expected two incident events on lap 3"
    # Individual events each carry the full lap's excess time (per-event context)
    assert lap3_events[0].time_lost_estimate_s == lap3_events[1].time_lost_estimate_s
    single_lap_excess = lap3_events[0].time_lost_estimate_s
    assert single_lap_excess > 0
    # Attribution must count the excess once, not twice
    assert narrative.attribution is not None
    assert narrative.attribution.incident_time_lost_s == pytest.approx(
        single_lap_excess, abs=0.2
    ), (
        f"Expected ~{single_lap_excess}, got "
        f"{narrative.attribution.incident_time_lost_s} (double-count not fixed?)"
    )


# --- Fix 1: lap-1 incident time-lost must be zeroed ----------------------

def test_lap1_incident_time_lost_is_zero_and_attribution_excludes_it():
    """Incidents on lap 1 must have time_lost_estimate_s == 0.0.

    The lap-1 time mixes the standing-start overhead with any incident
    penalty, so we cannot isolate the incident cost. Fix: zero the
    estimate for all lap-1 events. The attribution sum consequently
    excludes them (adding 0.0 is a no-op).
    """
    n = 600
    lap_col = [1] * 100 + [2] * 100 + [3] * 100 + [4] * 100 + [5] * 100 + [6] * 100
    # Incident step at tick 50 (lap 1) then at tick 450 (lap 5)
    inc_col = [0] * 50 + [1] * 400 + [2] * 150
    df = _ticks(
        Lap=lap_col,
        PlayerCarPosition=[5] * n,
        LapDistPct=[i / 100 % 1.0 for i in range(n)],
        PlayerCarMyIncidentCount=inc_col,
        OnPitRoad=[False] * n,
        SessionFlags=[0] * n,
        LapCurrentLapTime=[float(i % 100) for i in range(n)],
    )
    # Lap 1: 130 s (standing-start lap, looks slow but isn't meaningful)
    # Lap 5: 120 s (genuine incident lap, vs ~100 s clean median)
    player_laps_list = _laps(1226848, [130.0, 100.0, 100.5, 100.2, 120.0, 100.3])
    player_laps_list[0].incident = True  # lap 1
    player_laps_list[4].incident = True  # lap 5
    data = RaceData(
        subsession_id=86748877,
        player_cust_id=1226848,
        player_car_idx=6,
        driver_name="Anthony Moorman",
        track_id=180,
        track_name="Oulton Park Circuit",
        track_config="International",
        track_directory="oulton international",
        track_length_m=4286.5,
        car_name="Mazda MX-5 Cup",
        series_name="MX-5 Cup",
        session_date="2026-06-26",
        sof=1350,
        player_telemetry=df,
        roster=[RosterEntry(6, 1226848, "Anthony Moorman", "8", 1420, "D 4.5", "MX-5")],
        results=[_result(1226848, 3)],
        lap_chart=[
            LapChartRow(cust_id=1226848, lap_number=lap, position=5)
            for lap in range(1, 7)
        ],
        driver_laps={1226848: player_laps_list},
    )
    narrative = build_narrative(data, corners=[])

    # Lap-1 incident: time_lost must be 0.0 regardless of standing-start overhead
    lap1_events = [i for i in narrative.incidents if i.lap == 1]
    assert len(lap1_events) == 1, f"Expected one lap-1 incident, got {len(lap1_events)}"
    assert lap1_events[0].time_lost_estimate_s == 0.0, (
        f"Lap-1 time_lost must be 0.0, got {lap1_events[0].time_lost_estimate_s:.2f} "
        f"(standing-start overhead cannot be isolated)"
    )

    # Lap-5 incident: time_lost must be positive (120 s vs ~100.25 s clean median)
    lap5_events = [i for i in narrative.incidents if i.lap == 5]
    assert len(lap5_events) == 1
    lap5_lost = lap5_events[0].time_lost_estimate_s
    assert lap5_lost > 0.0

    # Attribution: incident_time_lost_s must equal only the lap-5 excess
    assert narrative.attribution is not None
    assert narrative.attribution.incident_time_lost_s == pytest.approx(lap5_lost, abs=0.2), (
        f"Attribution must count only lap-5 incident ({lap5_lost:.2f} s), "
        f"got {narrative.attribution.incident_time_lost_s} "
        f"(lap-1 overhead is leaking into the sum)"
    )


# --- build_stints direct unit tests (Issue 2) ----------------------------

def test_build_stints_no_pits_single_stint():
    """No pit laps → single stint spanning all laps."""
    laps = _laps(1, [101.0, 100.0, 100.5, 100.2, 100.3])
    stints = build_stints(laps, pit_laps=set(), caution_laps=set())
    assert len(stints) == 1
    assert stints[0].start_lap == 1
    assert stints[0].end_lap == 5


def test_build_stints_single_pit_splits_at_boundary():
    """Single pit on lap 3 → two stints: laps 1-2 and laps 4-7."""
    laps = _laps(1, [101.0, 100.0, 30.0, 100.5, 100.2, 100.3, 100.1])
    stints = build_stints(laps, pit_laps={3}, caution_laps=set())
    assert len(stints) == 2
    assert stints[0].start_lap == 1
    assert stints[0].end_lap == 2
    assert stints[1].start_lap == 4
    assert stints[1].end_lap == 7


def test_build_stints_pit_on_final_lap_no_degenerate_trailing_stint():
    """Pit on the final lap must not produce a degenerate Stint(start > end)."""
    laps = _laps(
        1, [101.0, 100.0, 100.5, 100.2, 100.3, 100.1, 100.0, 100.4, 100.2, 30.0]
    )  # 10 laps, lap 10 is the pit lap
    stints = build_stints(laps, pit_laps={10}, caution_laps=set())
    for stint in stints:
        assert stint.start_lap <= stint.end_lap, (
            f"Degenerate stint emitted: start_lap={stint.start_lap} "
            f"> end_lap={stint.end_lap}"
        )
    assert len(stints) == 1
    assert stints[0].start_lap == 1
    assert stints[0].end_lap == 9
