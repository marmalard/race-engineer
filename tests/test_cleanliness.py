"""Tests for lap-cleanliness detection (pure; offline + live paths)."""

import pandas as pd

from core.telemetry.cleanliness import (
    IncidentMark,
    IncidentTracker,
    check_lap_cleanliness,
)


def _frame(counts, dists=None):
    n = len(counts)
    return pd.DataFrame({
        "PlayerCarMyIncidentCount": counts,
        "LapDist": dists if dists is not None else [float(i * 10) for i in range(n)],
    })


def test_clean_lap():
    r = check_lap_cleanliness(_frame([4, 4, 4, 4]))
    assert r.clean and r.marks == []


def test_single_increment_marks_distance_and_delta():
    r = check_lap_cleanliness(_frame([4, 4, 5, 5], dists=[0.0, 100.0, 200.0, 300.0]))
    assert not r.clean
    assert r.marks == [IncidentMark(distance_m=200.0, delta=1)]


def test_multiple_increments():
    r = check_lap_cleanliness(_frame([0, 1, 1, 5], dists=[0.0, 50.0, 100.0, 150.0]))
    assert [(m.distance_m, m.delta) for m in r.marks] == [(50.0, 1), (150.0, 4)]


def test_count_decrease_ignored():
    """A backward count (session reset artifacts) is never a mark."""
    r = check_lap_cleanliness(_frame([4, 2, 2, 2]))
    assert r.clean


def test_missing_columns_fail_open():
    r = check_lap_cleanliness(pd.DataFrame({"Speed": [1.0, 2.0]}))
    assert r.clean and r.marks == []


def test_empty_frame_is_clean():
    assert check_lap_cleanliness(_frame([])).clean


def test_tracker_records_and_closes():
    t = IncidentTracker()
    t.feed(4, 100.0)
    t.feed(4, 200.0)
    t.feed(5, 300.0)          # +1 at 300m
    t.feed(5, 400.0)
    marks = t.close_lap()
    assert marks == [IncidentMark(distance_m=300.0, delta=1)]
    # closed -> next lap starts fresh but the count baseline carries over
    t.feed(5, 50.0)
    assert t.close_lap() == []


def test_tracker_ignores_none_inputs():
    t = IncidentTracker()
    t.feed(4, 100.0)
    t.feed(None, 200.0)       # tow/out-of-world tick
    t.feed(5, None)
    t.feed(5, 300.0)          # rise observed vs last GOOD count (4 -> 5)
    assert t.close_lap() == [IncidentMark(distance_m=300.0, delta=1)]


def test_tracker_reset_discards_marks_but_keeps_baseline():
    t = IncidentTracker()
    t.feed(4, 100.0)
    t.feed(6, 200.0)          # +2
    t.reset()
    assert t.close_lap() == []
    t.feed(6, 50.0)           # same count after reset -> no phantom mark
    assert t.close_lap() == []


def test_tracker_first_feed_never_marks():
    """The very first observed count is a baseline, not an incident."""
    t = IncidentTracker()
    t.feed(12, 500.0)
    assert t.close_lap() == []
