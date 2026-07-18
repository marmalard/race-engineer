"""Deterministic PTT fast path. Answers exact-string pinned."""

from core.engineer.intents import match_intent

SNAP = {
    "position": 6, "field_size": 18, "lap": 12,
    "laps_remaining": 6, "time_remaining_s": None,
    "last_lap_s": 132.41, "best_lap_s": 131.82,
    "ahead": {"name": "Verstappen", "irating": 4100,
              "gap_s": 1.4, "trend_s_per_lap": -0.3},
    "behind": {"name": "Hamilton", "irating": 3500,
               "gap_s": 2.1, "trend_s_per_lap": 0.2},
}


def test_gap_behind():
    assert match_intent("what's the gap behind", SNAP) == \
        "Gap behind, 2.1 seconds to Hamilton."


def test_gap_ahead():
    assert match_intent("gap to the car ahead", SNAP) == \
        "Gap ahead, 1.4 seconds to Verstappen."


def test_bare_gap_means_ahead():
    assert match_intent("what's the gap", SNAP) == \
        "Gap ahead, 1.4 seconds to Verstappen."


def test_position():
    assert match_intent("what position am I in", SNAP) == "P6 of 18."


def test_laps_left():
    assert match_intent("how many laps left", SNAP) == "Six laps to go."


def test_time_left_when_timed_race():
    snap = dict(SNAP, laps_remaining=None, time_remaining_s=722.0)
    assert match_intent("how long is left", snap) == "Twelve minutes left."


def test_pace():
    assert match_intent("what was my last lap", SNAP) == \
        "Last lap 2:12.4, best 2:11.8."


def test_open_question_returns_none():
    assert match_intent("should I pit with the leaders", SNAP) is None


def test_missing_data_returns_none_not_a_wrong_answer():
    empty = {"position": None, "field_size": 0, "lap": None,
             "laps_remaining": None, "time_remaining_s": None,
             "last_lap_s": None, "best_lap_s": None,
             "ahead": None, "behind": None}
    assert match_intent("what's the gap behind", empty) is None
    assert match_intent("what position am I in", empty) is None
