"""Deterministic PTT fast path: transcript -> instant answer, or None.

The no-API-on-critical-path house pattern: the common quantitative radio
calls (gaps, position, laps left, pace) answer from the RaceState
snapshot with zero network. Anything unmatched returns None and falls
through to the Claude path. Missing data returns None too -- an honest
fall-through beats a confident wrong answer.
"""

_NUM_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
              6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
              11: "Eleven", 12: "Twelve"}


def _fmt_lap(seconds: float) -> str:
    m, s = divmod(seconds, 60.0)
    return f"{int(m)}:{s:04.1f}"


def _num_word(n: int) -> str:
    return _NUM_WORDS.get(n, str(n))


def match_intent(transcript: str, snap: dict) -> str | None:
    q = (transcript or "").lower()
    ahead = snap.get("ahead")
    behind = snap.get("behind")

    if "gap" in q or "how far" in q:
        if "behind" in q or "back" in q:
            if behind is None:
                return None
            return (f"Gap behind, {behind['gap_s']:.1f} seconds "
                    f"to {behind['name']}.")
        if ahead is None:
            return None
        return f"Gap ahead, {ahead['gap_s']:.1f} seconds to {ahead['name']}."

    if "position" in q or "where am i" in q:
        if snap.get("position") is None:
            return None
        return f"P{snap['position']} of {snap['field_size']}."

    if (("laps" in q and ("left" in q or "remaining" in q or "to go" in q))
            or "how long" in q):
        laps = snap.get("laps_remaining")
        if laps is not None:
            return f"{_num_word(laps)} laps to go."
        t = snap.get("time_remaining_s")
        if t is not None:
            return f"{_num_word(round(t / 60.0))} minutes left."
        return None

    if "last lap" in q or "lap time" in q or "pace" in q:
        last, best = snap.get("last_lap_s"), snap.get("best_lap_s")
        if last is None or best is None:
            return None
        return f"Last lap {_fmt_lap(last)}, best {_fmt_lap(best)}."

    return None
