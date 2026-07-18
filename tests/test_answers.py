"""Answer orchestration: fast path first, Claude second, offline line last.
Fake ask callables only -- no network, no anthropic client."""

from core.engineer.answers import OFFLINE_LINE, answer_question

SNAP = {
    "position": 6, "field_size": 18, "lap": 12,
    "laps_remaining": 6, "time_remaining_s": None,
    "last_lap_s": 132.41, "best_lap_s": 131.82,
    "ahead": {"name": "Verstappen", "irating": 4100,
              "gap_s": 1.4, "trend_s_per_lap": -0.3},
    "behind": None,
}


def test_fast_path_wins_and_never_calls_claude():
    def boom(transcript, state_json):
        raise AssertionError("Claude must not be called for a fast-path hit")

    text, source = answer_question("what's the gap", SNAP, ask=boom)
    assert source == "fast"
    assert text == "Gap ahead, 1.4 seconds to Verstappen."


def test_open_question_goes_to_claude_with_state():
    seen = {}

    def fake_ask(transcript, state_json):
        seen["transcript"] = transcript
        seen["state_json"] = state_json
        return "Pit with the leaders; track position is worth more today."

    text, source = answer_question("should I pit with the leaders",
                                   SNAP, ask=fake_ask)
    assert source == "claude"
    assert text.startswith("Pit with the leaders")
    assert "Verstappen" in seen["state_json"]
    assert seen["transcript"] == "should I pit with the leaders"


def test_no_ask_callable_gives_offline_line():
    text, source = answer_question("should I pit", SNAP, ask=None)
    assert (text, source) == (OFFLINE_LINE, "offline")


def test_claude_failure_gives_offline_line():
    def dies(transcript, state_json):
        raise TimeoutError("network gone")

    text, source = answer_question("should I pit", SNAP, ask=dies)
    assert (text, source) == (OFFLINE_LINE, "offline")


def test_empty_transcript_asks_for_a_repeat():
    text, source = answer_question("", SNAP, ask=None)
    assert (text, source) == ("Say again?", "fast")
