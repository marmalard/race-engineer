"""Non-blocking PC-side speech for the live coach.

A daemon worker thread speaks via Windows SAPI (pyttsx3) so the 60Hz
tick loop never blocks. The pending queue has TWO tiers: a normal tier
(coaching cues) and a priority tier (PTT answers). Priority always wins
the next slot over a pending normal utterance; latest-wins within each
tier. An utterance already in progress is not interrupted.
cancel_pending() drops any unspoken normal utterance — used on a PTT
key press to silence queued cues before the driver speaks. Any engine
failure logs once and goes permanently silent; voice is an enhancement
layer, the text surfaces stay canonical.
"""

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class NullSpeaker:
    """Same interface as Speaker; does nothing. Used for --mute and tests."""

    def say(self, text: str) -> None:
        pass

    def say_priority(self, text: str) -> None:
        pass

    def cancel_pending(self) -> None:
        pass

    def close(self) -> None:
        pass


class Speaker:
    """Speaks text on a daemon thread with latest-wins queueing."""

    def __init__(self, engine: Callable[[str], None] | None = None) -> None:
        self._engine = engine if engine is not None else _sapi_engine()
        self._pending: str | None = None           # normal tier (cues, calls)
        self._pending_priority: str | None = None  # PTT answers
        self._cv = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        """Queue text to be spoken. O(1); replaces any unspoken pending text
        in the normal tier. A pending priority utterance still wins."""
        with self._cv:
            self._pending = text
            self._cv.notify()

    def say_priority(self, text: str) -> None:
        """Queue a PTT answer: always beats a pending normal utterance for
        the next slot. Latest-wins within the priority tier. In-progress
        speech is still never interrupted."""
        with self._cv:
            self._pending_priority = text
            self._cv.notify()

    def cancel_pending(self) -> None:
        """Drop any unspoken NORMAL utterance (PTT press: the engineer shuts
        up when the driver keys the radio). Priority answers survive."""
        with self._cv:
            self._pending = None

    def close(self) -> None:
        """Signal the worker to stop. In-progress speech completes; any
        pending utterance is discarded. Safe to call more than once."""
        with self._cv:
            self._closed = True
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while (self._pending is None
                       and self._pending_priority is None
                       and not self._closed):
                    self._cv.wait()
                if self._closed:
                    return
                if self._pending_priority is not None:
                    text, self._pending_priority = self._pending_priority, None
                else:
                    text, self._pending = self._pending, None
            try:
                self._engine(text)  # blocking; in-progress speech completes
            except Exception:
                logger.warning(
                    "Speech engine failed; voice going silent "
                    "(text surfaces unaffected)",
                    exc_info=True,
                )
                return  # worker exits; say() becomes a harmless sink


def _sapi_engine() -> Callable[[str], None]:
    """Windows SAPI via pyttsx3. Fresh init per utterance — slower by
    ~100ms but avoids pyttsx3's known event-loop reuse quirks."""
    import pyttsx3  # deferred so tests never import it

    def speak(text: str) -> None:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()

    return speak


def create_speaker(mute: bool = False) -> Speaker | NullSpeaker:
    """A Speaker (neural voice when the rig group is installed, else SAPI),
    or NullSpeaker when muted or when no TTS is available."""
    if mute:
        return NullSpeaker()
    from core.live import voice_engine
    engine = voice_engine.neural_engine()
    if engine is not None:
        print("Voice: neural (Kokoro).")
    else:
        print("Voice: SAPI fallback (run uv sync --group rig for the "
              "neural voice).")
    try:
        return Speaker(engine=engine)  # engine=None -> SAPI inside Speaker
    except Exception:
        logger.warning("TTS unavailable; running muted", exc_info=True)
        return NullSpeaker()
