"""Non-blocking PC-side speech for the live coach.

A daemon worker thread speaks via Windows SAPI (pyttsx3) so the 60Hz
tick loop never blocks. The pending queue holds ONE slot: a newer say()
replaces an unspoken pending utterance — the driver always hears the
latest thing, never a backlog. An utterance already in progress is not
interrupted. Any engine failure logs once and goes permanently silent;
voice is an enhancement layer, the text surfaces stay canonical.
"""

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class NullSpeaker:
    """Same interface as Speaker; does nothing. Used for --mute and tests."""

    def say(self, text: str) -> None:
        pass

    def close(self) -> None:
        pass


class Speaker:
    """Speaks text on a daemon thread with latest-wins queueing."""

    def __init__(self, engine: Callable[[str], None] | None = None) -> None:
        self._engine = engine if engine is not None else _sapi_engine()
        self._pending: str | None = None
        self._cv = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        """Queue text to be spoken. O(1); replaces any unspoken pending text."""
        with self._cv:
            self._pending = text
            self._cv.notify()

    def close(self) -> None:
        """Signal the worker to stop. In-progress speech completes; any
        pending utterance is discarded. Safe to call more than once."""
        with self._cv:
            self._closed = True
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._pending is None and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
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
    """A Speaker, or NullSpeaker when muted or when TTS is unavailable."""
    if mute:
        return NullSpeaker()
    try:
        return Speaker()
    except Exception:
        logger.warning("TTS unavailable; running muted", exc_info=True)
        return NullSpeaker()
