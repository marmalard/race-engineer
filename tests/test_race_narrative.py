"""Tests for the deterministic race narrative engine (pure functions)."""

import pytest

from core.race.models import DriverLap
from core.race.narrative import (
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
