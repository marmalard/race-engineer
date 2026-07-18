"""Global spacing limiter for engineer-originated speech.

The named failure mode is Trophi-style overload: an engineer who mostly
shuts up is a feature. Every engineer-initiated call passes try_speak();
PTT answers are exempt (the driver asked) but note_priority() records
them so a call never lands right on top of an answer. Cues/verdicts keep
their own gates on top of this -- the budget is a floor, not a router.

Callers pass time.monotonic(); the clock is an argument so tests are
deterministic.
"""

MIN_SPACING_S = 20.0


class RadioBudget:
    def __init__(self, min_spacing_s: float = MIN_SPACING_S) -> None:
        self._min_spacing_s = min_spacing_s
        self._last_spoken: float | None = None

    def try_speak(self, now: float) -> bool:
        """True (and the clock records) if an engineer call may speak now."""
        if (self._last_spoken is not None
                and now - self._last_spoken < self._min_spacing_s):
            return False
        self._last_spoken = now
        return True

    def note_priority(self, now: float) -> None:
        """Record a PTT answer: exempt from the gate, counts for spacing."""
        self._last_spoken = now
