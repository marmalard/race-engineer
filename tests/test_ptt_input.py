"""PTT input-side tests: mic cap logic and STT guards. No hardware."""

import numpy as np

from core.engineer.mic import MAX_SECONDS, SAMPLE_RATE, MicCapture
from core.engineer.ptt_input import PTTButton
from core.engineer.stt import transcribe


def test_mic_cap_drops_frames_beyond_max_seconds():
    m = MicCapture()
    chunk = np.zeros((SAMPLE_RATE, 1), dtype=np.float32)  # 1s per callback
    for _ in range(int(MAX_SECONDS) + 5):
        m._cb(chunk, len(chunk), None, None)
    assert m.stop().shape[0] <= int(SAMPLE_RATE * MAX_SECONDS) + SAMPLE_RATE


def test_mic_stop_without_start_returns_empty():
    assert MicCapture().stop().shape[0] == 0


def test_transcribe_guards_none_model_and_empty_audio():
    assert transcribe(None, np.zeros(1600, dtype=np.float32)) == ""
    assert transcribe(object(), np.zeros(0, dtype=np.float32)) == ""


def test_edge_detector_press_release_cycle():
    b = PTTButton()
    assert b.feed(False) is None
    assert b.feed(True) == "press"
    assert b.feed(True) is None          # held: no repeat
    assert b.feed(False) == "release"
    assert b.feed(False) is None


def test_edge_detector_starts_held_yields_press():
    # Coach starts while the button is already down: treat as a press.
    b = PTTButton()
    assert b.feed(True) == "press"
