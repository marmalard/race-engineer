"""RaceState fed synthetic tick dicts -- the session_reader precedent."""

from core.engineer.race_state import ENGINEER_CHANNELS, RaceState

ROSTER = [
    {"CarIdx": 0, "UserName": "Lewis Hamilton", "IRating": 3500},
    {"CarIdx": 1, "UserName": "Anthony Moorman2", "IRating": 1900},
    {"CarIdx": 2, "UserName": "Max Verstappen", "IRating": 4100},
]


def tick(st, laps, positions, f2, laps_remain=10, time_remain=1800.0):
    return {
        "SessionTime": st,
        "CarIdxLap": laps,
        "CarIdxPosition": positions,
        "CarIdxLapDistPct": [0.5, 0.5, 0.5],
        "CarIdxF2Time": f2,
        "CarIdxOnPitRoad": [False, False, False],
        "SessionLapsRemain": laps_remain,
        "SessionTimeRemain": time_remain,
    }


def make_state():
    s = RaceState(player_idx=1)
    s.set_roster(ROSTER)
    return s


def test_engineer_channels_cover_the_feed():
    for key in ("CarIdxLap", "CarIdxPosition", "CarIdxF2Time",
                "CarIdxOnPitRoad", "SessionLapsRemain", "SessionTimeRemain",
                "SessionTime"):
        assert key in ENGINEER_CHANNELS


def test_feed_ignores_non_list_caridx_ticks():
    s = make_state()
    bad = tick(10.0, [2, 2, 2], [2, 3, 1], [5.0, 12.0, 0.0])
    bad["CarIdxLap"] = 2  # scalar churn tick
    assert s.feed(bad) is False


def test_lap_boundary_records_gaps_to_position_neighbors():
    s = make_state()
    # player P2: car 2 (P1) ahead, car 0 (P3) behind. F2 = time behind leader.
    s.feed(tick(100.0, [2, 2, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    assert s.feed(tick(230.0, [2, 3, 2], [3, 2, 1], [14.1, 12.0, 0.0])) is True
    g = s.lap_gaps[-1]
    assert g.lap == 3
    assert g.position == 2
    assert g.ahead_idx == 2
    assert abs(g.gap_ahead_s - 12.0) < 1e-9    # 12.0 - 0.0
    assert g.behind_idx == 0
    assert abs(g.gap_behind_s - 2.1) < 1e-9    # 14.1 - 12.0


def test_player_lap_time_derived_from_boundary_session_times():
    s = make_state()
    s.feed(tick(100.0, [2, 2, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    s.feed(tick(230.0, [2, 3, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    s.feed(tick(361.5, [2, 4, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    assert abs(s.player_lap_times[-1] - 131.5) < 1e-9


def test_snapshot_shape_names_and_trend():
    s = make_state()
    s.feed(tick(100.0, [2, 2, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    s.feed(tick(230.0, [2, 3, 2], [3, 2, 1], [14.0, 12.0, 0.0], laps_remain=6))
    s.feed(tick(360.0, [2, 4, 2], [3, 2, 1], [13.5, 12.5, 0.0], laps_remain=5))
    snap = s.snapshot()
    assert snap["position"] == 2
    assert snap["field_size"] == 3
    assert snap["laps_remaining"] == 5
    assert snap["ahead"]["name"] == "Verstappen"   # speech_name: surname only
    # gap ahead went 12.0 -> 12.5: +0.5/lap (positive = losing ground)
    assert abs(snap["ahead"]["trend_s_per_lap"] - 0.5) < 1e-9
    assert snap["behind"]["name"] == "Hamilton"
    # gap behind went 2.0 -> 1.0: -1.0/lap (negative = he is closing)
    assert abs(snap["behind"]["trend_s_per_lap"] - -1.0) < 1e-9


def test_no_neighbor_yields_none_blocks():
    s = RaceState(player_idx=0)
    s.set_roster(ROSTER[:1])
    one = {
        "SessionTime": 100.0, "CarIdxLap": [2], "CarIdxPosition": [1],
        "CarIdxLapDistPct": [0.1], "CarIdxF2Time": [0.0],
        "CarIdxOnPitRoad": [False],
        "SessionLapsRemain": 10, "SessionTimeRemain": 1800.0,
    }
    s.feed(one)
    one2 = dict(one, SessionTime=230.0, CarIdxLap=[3])
    s.feed(one2)
    snap = s.snapshot()
    assert snap["ahead"] is None and snap["behind"] is None
