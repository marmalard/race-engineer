"""Tests for the non-blocking speech queue. No real SAPI — fake engines only."""

import threading
import time

from core.live.speaker import NullSpeaker, Speaker, create_speaker


class _BlockingEngine:
    """Fake engine: each call records the text, then blocks until released."""

    def __init__(self):
        self.spoken = []
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, text: str) -> None:
        self.spoken.append(text)
        self.started.set()
        self.release.wait(timeout=5.0)


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_latest_pending_utterance_wins():
    engine = _BlockingEngine()
    s = Speaker(engine=engine)
    s.say("first")
    assert engine.started.wait(timeout=5.0)  # "first" is now in progress
    s.say("second")  # pending
    s.say("third")   # replaces "second"
    engine.release.set()
    assert _wait_for(lambda: len(engine.spoken) == 2)
    assert engine.spoken == ["first", "third"]
    s.close()


def test_say_never_blocks_while_engine_is_busy():
    engine = _BlockingEngine()
    s = Speaker(engine=engine)
    s.say("first")
    assert engine.started.wait(timeout=5.0)
    t0 = time.monotonic()
    s.say("second")
    assert time.monotonic() - t0 < 0.5  # enqueue is O(1), no wait on speech
    engine.release.set()
    s.close()


def test_engine_failure_goes_silent_without_crashing():
    def broken(text):
        raise RuntimeError("no audio device")

    s = Speaker(engine=broken)
    s.say("a")
    assert _wait_for(lambda: not s._thread.is_alive()), \
        "worker thread should have exited after engine failure"
    s.say("b")  # provably a silent no-op now — must not raise
    s.close()
    s.close()  # idempotent: second close on a dead worker is harmless


def test_null_speaker_is_a_noop():
    n = NullSpeaker()
    n.say("anything")
    n.close()


def test_create_speaker_mute_returns_null():
    assert isinstance(create_speaker(mute=True), NullSpeaker)


def test_priority_beats_pending_normal():
    engine = _BlockingEngine()
    s = Speaker(engine=engine)
    s.say("first")
    assert engine.started.wait(timeout=5.0)
    s.say("cue")               # pending normal
    s.say_priority("answer")   # pending priority -- must win the next slot
    engine.release.set()
    assert _wait_for(lambda: len(engine.spoken) >= 2)
    assert engine.spoken[1] == "answer"
    s.close()


def test_latest_wins_within_priority_tier():
    engine = _BlockingEngine()
    s = Speaker(engine=engine)
    s.say("first")
    assert engine.started.wait(timeout=5.0)
    s.say_priority("a1")
    s.say_priority("a2")  # replaces a1
    engine.release.set()
    assert _wait_for(lambda: len(engine.spoken) == 2)
    assert engine.spoken == ["first", "a2"]
    s.close()


def test_normal_still_speaks_after_priority_drains():
    engine = _BlockingEngine()
    s = Speaker(engine=engine)
    s.say("first")
    assert engine.started.wait(timeout=5.0)
    s.say("cue")
    s.say_priority("answer")
    engine.release.set()
    assert _wait_for(lambda: len(engine.spoken) == 3)
    assert engine.spoken == ["first", "answer", "cue"]
    s.close()


def test_cancel_pending_clears_normal_not_priority():
    engine = _BlockingEngine()
    s = Speaker(engine=engine)
    s.say("first")
    assert engine.started.wait(timeout=5.0)
    s.say("cue")
    s.say_priority("answer")
    s.cancel_pending()  # PTT press: normal slot cleared, priority survives
    engine.release.set()
    assert _wait_for(lambda: len(engine.spoken) == 2)
    assert engine.spoken == ["first", "answer"]
    s.close()


def test_null_speaker_has_priority_interface():
    n = NullSpeaker()
    n.say_priority("anything")
    n.cancel_pending()
    n.close()
