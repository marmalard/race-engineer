"""Where-you're-losing-the-guy-ahead: per-corner gap deltas over laps.

Two feed-shape rules the tests must honor because production does:
- The first feed of each lap only seeds the position (no crossing can be
  detected without a previous distance), and a corner's entry and exit
  must be crossed on DIFFERENT feeds or the measured loss is zero.
- A lap's losses are banked when the NEXT lap's first feed arrives (the
  boundary tick), so tests feed a boundary tick before take_call --
  exactly the order live_coach produces.
"""

from core.engineer.corner_loss import CornerLossTracker

# (start_m, end_m, name) spans -- the track_db corner shape live_coach loads.
SPANS = [(500.0, 700.0, "The Chase"), (1500.0, 1700.0, "Hell Corner")]


def run_lap(t, lap, gains, ahead_idx=2):
    """Feed one lap crossing both corners; `gains` maps name -> gap growth
    across that corner's span (positive = losing time to the target)."""
    base = 3.0
    after_chase = base + gains["The Chase"]
    t.feed(lap_dist_m=400.0, gap_ahead_s=base, ahead_idx=ahead_idx, lap=lap)
    t.feed(lap_dist_m=600.0, gap_ahead_s=base, ahead_idx=ahead_idx, lap=lap)
    t.feed(lap_dist_m=720.0, gap_ahead_s=after_chase,
           ahead_idx=ahead_idx, lap=lap)
    t.feed(lap_dist_m=1600.0, gap_ahead_s=after_chase,
           ahead_idx=ahead_idx, lap=lap)
    t.feed(lap_dist_m=1720.0,
           gap_ahead_s=after_chase + gains["Hell Corner"],
           ahead_idx=ahead_idx, lap=lap)


def boundary(t, lap, ahead_idx=2):
    """The next lap's first tick -- banks the previous lap's losses."""
    t.feed(lap_dist_m=100.0, gap_ahead_s=3.0, ahead_idx=ahead_idx, lap=lap)


def test_dominant_corner_produces_the_call_after_min_laps():
    t = CornerLossTracker(SPANS)
    run_lap(t, 3, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 4)
    assert t.take_call(target_name="Verstappen") is None   # 1 lap: not yet
    run_lap(t, 4, {"The Chase": 0.28, "Hell Corner": 0.03})
    boundary(t, 5)
    assert t.take_call(target_name="Verstappen") == \
        "You're losing him mainly in The Chase."


def test_call_fires_once_per_target():
    t = CornerLossTracker(SPANS)
    run_lap(t, 3, {"The Chase": 0.30, "Hell Corner": 0.02})
    run_lap(t, 4, {"The Chase": 0.28, "Hell Corner": 0.03})
    boundary(t, 5)
    assert t.take_call(target_name="Verstappen") is not None
    run_lap(t, 5, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 6)
    assert t.take_call(target_name="Verstappen") is None


def test_no_dominant_corner_stays_silent():
    t = CornerLossTracker(SPANS)
    run_lap(t, 3, {"The Chase": 0.10, "Hell Corner": 0.11})
    run_lap(t, 4, {"The Chase": 0.11, "Hell Corner": 0.10})
    boundary(t, 5)
    assert t.take_call(target_name="Verstappen") is None


def test_target_change_resets_accumulation():
    t = CornerLossTracker(SPANS)
    run_lap(t, 3, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 4, ahead_idx=7)  # new car ahead: accumulation resets
    run_lap(t, 5, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 6)
    assert t.take_call(target_name="Someone") is None      # 1 lap on car 2
    run_lap(t, 6, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 7)
    assert t.take_call(target_name="Someone") is not None


def test_no_spans_never_calls():
    t = CornerLossTracker([])
    run_lap(t, 3, {"The Chase": 0.3, "Hell Corner": 0.02})
    boundary(t, 4)
    assert t.take_call(target_name="X") is None
