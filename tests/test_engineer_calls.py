"""Engineer-initiated calls over synthetic gap histories. Spoken lines are
exact-string pinned (nudges precedent)."""

from core.engineer.calls import EngineerCalls, tenths_phrase
from core.engineer.race_state import LapGaps, RaceState
from core.engineer.radio_budget import RadioBudget

ROSTER = [
    {"CarIdx": 0, "UserName": "Lewis Hamilton", "IRating": 3500},
    {"CarIdx": 1, "UserName": "Anthony Moorman2", "IRating": 1900},
    {"CarIdx": 2, "UserName": "Max Verstappen", "IRating": 4100},
]


def state_with(gaps):
    s = RaceState(player_idx=1)
    s.set_roster(ROSTER)
    s.lap_gaps.extend(gaps)
    return s


def g(lap, ahead=None, behind=None, pos=6):
    return LapGaps(lap=lap, position=pos,
                   ahead_idx=2 if ahead is not None else None,
                   gap_ahead_s=ahead,
                   behind_idx=0 if behind is not None else None,
                   gap_behind_s=behind)


def wide_open_budget():
    return RadioBudget(min_spacing_s=0.0)


def test_tenths_phrase_exact_strings():
    assert tenths_phrase(0.08) == "a tenth"
    assert tenths_phrase(0.31) == "three tenths"
    assert tenths_phrase(0.52) == "half a second"
    assert tenths_phrase(0.97) == "a second"
    assert tenths_phrase(1.42) == "1.4 seconds"


def test_threat_fires_after_trend_laps_of_closing_inside_gap():
    calls = EngineerCalls(wide_open_budget())
    s = state_with([g(3, behind=2.0), g(4, behind=1.7), g(5, behind=1.4)])
    spoken, _ = calls.on_lap(s, now=100.0)
    assert spoken == [
        "Hamilton is closing, three tenths a lap. Keep your head down."
    ]


def test_threat_once_then_rearms_when_gap_reopens():
    # on_lap runs every lap boundary in production -- the test must too,
    # because re-arm triggers on the lap where the gap reopens.
    calls = EngineerCalls(wide_open_budget())
    s = state_with([g(3, behind=2.0), g(4, behind=1.7), g(5, behind=1.4)])
    spoken, _ = calls.on_lap(s, now=100.0)
    assert len(spoken) == 1                    # initial fire
    for lap, gap in [(6, 1.2),   # engaged: quiet
                     (7, 2.8),   # reopen past REARM_GAP_S: re-arms, quiet
                     (8, 2.6),   # closing again but gap > threshold: quiet
                     (9, 2.4)]:  # still outside threshold: quiet
        s.lap_gaps.append(g(lap, behind=gap))
        spoken, _ = calls.on_lap(s, now=100.0 + lap * 100.0)
        assert spoken == []
    s.lap_gaps.append(g(10, behind=1.4))       # inside 1.5s, trend intact
    spoken, _ = calls.on_lap(s, now=2000.0)
    # window [2.6, 2.4, 1.4] -> mean 0.6s/lap -> "six tenths"
    assert spoken == [
        "Hamilton is closing, six tenths a lap. Keep your head down."
    ]


def test_attack_line_exact():
    calls = EngineerCalls(wide_open_budget())
    s = state_with([g(3, ahead=4.0), g(4, ahead=3.5), g(5, ahead=3.0)])
    spoken, _ = calls.on_lap(s, now=100.0)
    assert spoken == ["You're pulling Verstappen in, half a second a lap."]


def test_closing_laps_line_exact_and_once():
    calls = EngineerCalls(wide_open_budget())
    s = state_with([g(10, behind=2.1)])
    s._laps_remaining = 5
    spoken, _ = calls.on_lap(s, now=100.0)
    assert spoken == ["Five to go, P6, gap behind 2.1."]
    spoken, _ = calls.on_lap(s, now=200.0)
    assert spoken == []


def test_budget_blocks_and_reports_dropped():
    calls = EngineerCalls(RadioBudget(min_spacing_s=1000.0))
    s = state_with([g(3, ahead=4.0, behind=2.0),
                    g(4, ahead=3.5, behind=1.7),
                    g(5, ahead=3.0, behind=1.4)])
    spoken, dropped = calls.on_lap(s, now=100.0)
    assert len(spoken) == 1        # threat outranks attack, takes the slot
    assert "closing" in spoken[0]
    assert len(dropped) == 1
    assert "pulling" in dropped[0]
