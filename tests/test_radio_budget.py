from core.engineer.radio_budget import MIN_SPACING_S, RadioBudget


def test_first_call_allowed():
    b = RadioBudget()
    assert b.try_speak(now=100.0) is True


def test_spacing_blocks_then_reopens():
    b = RadioBudget()
    assert b.try_speak(now=100.0)
    assert b.try_speak(now=100.0 + MIN_SPACING_S - 0.1) is False
    assert b.try_speak(now=100.0 + MIN_SPACING_S + 0.1) is True


def test_blocked_attempt_does_not_reset_the_clock():
    b = RadioBudget()
    assert b.try_speak(now=100.0)
    assert b.try_speak(now=110.0) is False       # blocked
    assert b.try_speak(now=100.0 + MIN_SPACING_S + 0.1) is True


def test_note_priority_counts_for_spacing():
    # A PTT answer is exempt from the gate but still spaces later calls:
    # the engineer should not pile a cue right on top of an answer.
    b = RadioBudget()
    b.note_priority(now=100.0)
    assert b.try_speak(now=105.0) is False
    assert b.try_speak(now=100.0 + MIN_SPACING_S + 0.1) is True
