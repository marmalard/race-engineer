"""Sparse engineer-initiated calls over RaceState lap-gap histories.

Priority order when several fire on one lap boundary: closing-laps >
threat > attack > corner-loss (the extra_call slot). Each candidate
passes RadioBudget.try_speak individually, so spacing decides how many
actually air; blocked lines are returned for JSONL logging, never spoken
late. Episode semantics: threat/attack fire once per engagement and
re-arm only when the gap reopens past REARM_GAP_S or the car changes.
All thresholds are module constants tuned from session logs.
"""

from core.engineer.race_state import RaceState
from core.engineer.radio_budget import RadioBudget

THREAT_GAP_S = 1.5      # behind-gap that counts as a threat
ATTACK_MAX_GAP_S = 5.0  # only call an attack inside striking range
TREND_LAPS = 3          # consecutive laps of movement required
MIN_TREND_S = 0.05      # per-lap movement below this is noise
REARM_GAP_S = 2.5       # gap must reopen past this to re-arm
CLOSING_LAPS_N = 5
CLOSING_TIME_S = 300.0  # timed races: one call at five minutes left

_TENTHS = {1: "a tenth", 2: "two tenths", 3: "three tenths",
           4: "four tenths", 6: "six tenths", 7: "seven tenths",
           8: "eight tenths", 9: "nine tenths"}
_LAP_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
              6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}


def tenths_phrase(seconds: float) -> str:
    """0.31 -> 'three tenths'; 0.5 -> 'half a second'; 1.4 -> '1.4 seconds'."""
    t = round(abs(seconds) * 10)
    if t <= 1:
        return "a tenth"
    if t == 5:
        return "half a second"
    if t in _TENTHS:
        return _TENTHS[t]
    if t == 10:
        return "a second"
    return f"{abs(seconds):.1f} seconds"


def _trend(gaps: list[float]) -> float | None:
    """Mean per-lap movement over a strictly-monotonic closing series."""
    if len(gaps) < TREND_LAPS:
        return None
    window = gaps[-TREND_LAPS:]
    steps = [window[i] - window[i + 1] for i in range(len(window) - 1)]
    if any(s < MIN_TREND_S for s in steps):
        return None
    return sum(steps) / len(steps)


class EngineerCalls:
    def __init__(self, budget: RadioBudget) -> None:
        self.budget = budget          # public: PTT answers call budget.note_priority
        self._budget = budget
        self._threat_engaged_idx: int | None = None
        self._attack_engaged_idx: int | None = None
        self._closing_done = False

    def on_lap(
        self, state: RaceState, now: float, extra_call: str | None = None
    ) -> tuple[list[str], list[str]]:
        """All candidates for this lap boundary -> (spoken, budget_dropped)."""
        spoken: list[str] = []
        dropped: list[str] = []
        for text in self._candidates(state, extra_call):
            if self._budget.try_speak(now):
                spoken.append(text)
            else:
                dropped.append(text)
        return spoken, dropped

    def _candidates(self, state: RaceState, extra_call: str | None):
        closing = self._closing_laps(state)
        if closing:
            yield closing
        threat = self._threat(state)
        if threat:
            yield threat
        attack = self._attack(state)
        if attack:
            yield attack
        if extra_call:
            yield extra_call

    def _series(self, state: RaceState, which: str):
        """(car_idx, gap history) for the current same-car streak."""
        recs = state.lap_gaps
        if not recs:
            return None, []
        idx = getattr(recs[-1], f"{which}_idx")
        if idx is None:
            return None, []
        gaps: list[float] = []
        expected_lap = recs[-1].lap
        for rec in reversed(recs):
            if (getattr(rec, f"{which}_idx") != idx
                    or getattr(rec, f"gap_{which}_s") is None
                    or rec.lap != expected_lap):
                break
            gaps.append(getattr(rec, f"gap_{which}_s"))
            expected_lap -= 1
        gaps.reverse()
        return idx, gaps

    def _threat(self, state: RaceState) -> str | None:
        idx, gaps = self._series(state, "behind")
        if idx is None or not gaps:
            return None
        if self._threat_engaged_idx is not None:
            if idx != self._threat_engaged_idx or gaps[-1] > REARM_GAP_S:
                self._threat_engaged_idx = None   # re-arm
            else:
                return None                        # still engaged: stay quiet
        rate = _trend(gaps)
        if rate is None or gaps[-1] > THREAT_GAP_S:
            return None
        self._threat_engaged_idx = idx
        return (f"{state.name_of(idx)} is closing, {tenths_phrase(rate)} "
                "a lap. Keep your head down.")

    def _attack(self, state: RaceState) -> str | None:
        idx, gaps = self._series(state, "ahead")
        if idx is None or not gaps:
            return None
        if self._attack_engaged_idx is not None:
            if idx != self._attack_engaged_idx or gaps[-1] > REARM_GAP_S + 2.0:
                self._attack_engaged_idx = None
            else:
                return None
        rate = _trend(gaps)
        if rate is None or gaps[-1] > ATTACK_MAX_GAP_S:
            return None
        self._attack_engaged_idx = idx
        return (f"You're pulling {state.name_of(idx)} in, "
                f"{tenths_phrase(rate)} a lap.")

    def _closing_laps(self, state: RaceState) -> str | None:
        if self._closing_done or not state.lap_gaps:
            return None
        last = state.lap_gaps[-1]
        laps_left = state._laps_remaining
        time_left = state._time_remaining
        lap_hit = laps_left is not None and laps_left == CLOSING_LAPS_N
        time_hit = (laps_left is None and time_left is not None
                    and time_left <= CLOSING_TIME_S)
        if not (lap_hit or time_hit):
            return None
        self._closing_done = True
        gap_txt = (f", gap behind {last.gap_behind_s:.1f}"
                   if last.gap_behind_s is not None else "")
        lead = (f"{_LAP_WORDS.get(CLOSING_LAPS_N, str(CLOSING_LAPS_N))} to go"
                if lap_hit else "Five minutes to go")
        return f"{lead}, P{last.position}{gap_txt}."
