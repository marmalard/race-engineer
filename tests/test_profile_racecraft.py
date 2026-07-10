"""Tests for the pure racecraft-tendency engine (synthetic narratives)."""

from core.profile.racecraft import build_racecraft
from core.race.models import (
    IncidentEvent,
    IRatingAttribution,
    Lap1Story,
    NarrativeHeader,
    RaceNarrative,
    Stint,
)


def _header(**kw) -> NarrativeHeader:
    base = dict(
        subsession_id=1, cust_id=100, driver_name="D", track_id=1,
        track_name="Oulton", track_config="", car_name="MX-5",
        series_name="S", session_date="2026-07-01", sof=1500,
        field_size=20, start_position=7, finish_position=4, incidents=2,
        irating_old=1400, irating_new=1420,
    )
    base.update(kw)
    return NarrativeHeader(**base)


def _lap1(grid=7, after1=9, after2=8) -> Lap1Story:
    return Lap1Story(grid_position=grid, position_after_lap1=after1,
                     position_after_lap2=after2)


def _attr(actual=6, deserved=4, time_lost=8.0) -> IRatingAttribution:
    return IRatingAttribution(
        irating_old=1400, irating_new=1410, irating_delta=10,
        pace_deserved_position=deserved, actual_position=actual,
        incident_time_lost_s=time_lost, lap1_net_positions=0,
    )


def _incident(lap=1, corner="Old Hall") -> IncidentEvent:
    return IncidentEvent(
        lap=lap, lap_dist_pct=0.1, corner_name=corner, delta_incidents=2,
        position_before=5, position_after=7, time_lost_estimate_s=4.0,
    )


def _narr(lap1=None, attribution=None, events=(), stints=(), **header_kw):
    return RaceNarrative(
        header=_header(**header_kw), lap1=lap1, attribution=attribution,
        incidents=list(events), stints=list(stints),
    )


def test_starts_math_and_sign():
    """grid 7 -> P9 after lap1 = -2 (positive = gained)."""
    t = build_racecraft([_narr(lap1=_lap1(7, 9, 8)) for _ in range(3)])
    s = t.starts
    assert s.sample == 3 and s.enough_data
    assert s.mean_lap1_net == -2.0
    assert s.mean_lap2_net == 1.0          # P9 -> P8 = +1
    assert s.races_lost_ground == 3


def test_starts_skips_races_without_lap1():
    t = build_racecraft([_narr(lap1=_lap1()), _narr(), _narr()])
    assert t.starts.sample == 1
    assert not t.starts.enough_data        # 1 < 3


def test_pace_vs_result_positive_means_finishing_worse():
    t = build_racecraft([_narr(attribution=_attr(actual=6, deserved=4))
                         for _ in range(3)])
    p = t.pace_vs_result
    assert p.sample == 3 and p.enough_data
    assert p.mean_positions_left == 2.0
    assert p.mean_incident_time_lost_s == 8.0
    assert p.mean_actual_position == 6.0
    assert p.mean_deserved_position == 4.0


def test_pace_vs_result_skips_none_deserved():
    t = build_racecraft([
        _narr(attribution=_attr()),
        _narr(attribution=_attr(deserved=None)),
        _narr(),
    ])
    assert t.pace_vs_result.sample == 1


def test_incidents_rate_lap1_share_and_recurring():
    races = [
        _narr(events=[_incident(lap=1, corner="Old Hall")], incidents=4),
        _narr(events=[_incident(lap=5, corner="Old Hall")], incidents=2),
        _narr(events=[_incident(lap=1, corner=None)], incidents=0),
    ]
    t = build_racecraft(races)
    i = t.incidents
    assert i.sample == 3 and i.enough_data
    assert i.mean_incident_points == 2.0          # (4+2+0)/3
    assert i.lap1_share == 2 / 3                  # 2 of 3 events on lap 1
    assert i.recurring_corners == [("Old Hall", 2)]


def test_incidents_no_events_share_is_none():
    t = build_racecraft([_narr(incidents=1) for _ in range(3)])
    assert t.incidents.lap1_share is None
    assert t.incidents.recurring_corners == []
    assert t.incidents.mean_incident_points == 1.0


def test_trajectory_net_and_fade():
    races = [
        _narr(stints=[Stint(1, 10, 100.0, 0.3)], start_position=8, finish_position=5),
        _narr(stints=[Stint(1, 10, 100.0, 0.1)], start_position=6, finish_position=6),
        _narr(stints=[Stint(1, 10, 100.0, None)], start_position=10, finish_position=7),
    ]
    t = build_racecraft(races)
    tr = t.trajectory
    assert tr.sample == 3 and tr.enough_data
    assert tr.mean_race_net == 2.0         # +3, 0, +3 -> mean 2.0
    assert abs(tr.mean_stint_fade_s - 0.2) < 1e-9   # (0.3 + 0.1) / 2


def test_trajectory_skips_partial_headers():
    t = build_racecraft([_narr(start_position=0, finish_position=0)])
    assert t.trajectory.sample == 0 and not t.trajectory.enough_data


def test_empty_input_gives_empty_tendencies():
    t = build_racecraft([])
    assert t.starts.sample == 0 and not t.starts.enough_data
    assert t.incidents.sample == 0
    assert t.pace_vs_result.mean_positions_left is None
