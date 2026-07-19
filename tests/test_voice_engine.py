"""Neural voice factory tests. No kokoro, no audio device -- fakes only."""

import numpy as np

from core.live import voice_engine
from core.live.speaker import NullSpeaker, Speaker, create_speaker


def test_neural_engine_returns_none_when_pipeline_factory_fails():
    def broken_factory():
        raise ImportError("no kokoro")

    assert voice_engine.neural_engine(pipeline_factory=broken_factory) is None


def test_neural_engine_speaks_through_player():
    played = []

    class FakePipeline:
        def __call__(self, text, voice, speed):
            yield ("g", "p", np.zeros(2400, dtype=np.float32))
            yield ("g", "p", np.ones(2400, dtype=np.float32))

    def player(wav, samplerate):
        played.append((len(wav), samplerate))

    engine = voice_engine.neural_engine(
        pipeline_factory=FakePipeline, player=player
    )
    assert engine is not None
    engine("hello")
    assert played == [(4800, voice_engine.SAMPLE_RATE)]


def test_speak_passes_the_speed_constant():
    seen = {}

    class FakePipeline:
        def __call__(self, text, voice, speed):
            seen["speed"] = speed
            yield ("g", "p", np.ones(2400, dtype=np.float32))

    engine = voice_engine.neural_engine(
        pipeline_factory=FakePipeline, player=lambda wav, sr: None
    )
    engine("hello")
    assert seen["speed"] == voice_engine.SPEED


def test_quiet_synthesis_is_peak_normalized():
    # Field note 2026-07-18: raw Kokoro output was inaudible under game
    # audio. A quiet waveform must reach TARGET_PEAK before playback.
    played = []

    class FakePipeline:
        def __call__(self, text, voice, speed):
            yield ("g", "p", np.full(2400, 0.2, dtype=np.float32))

    engine = voice_engine.neural_engine(
        pipeline_factory=FakePipeline, player=lambda wav, sr: played.append(wav)
    )
    engine("hello")
    peak = float(np.max(np.abs(played[0])))
    assert abs(peak - voice_engine.TARGET_PEAK * voice_engine.GAIN) < 1e-6
    assert peak <= 1.0  # gain values > 1.0 must clip, never overflow


def test_create_speaker_uses_neural_when_available(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "core.live.voice_engine.neural_engine",
        lambda: lambda text: calls.append(text),
    )
    s = create_speaker()
    assert isinstance(s, Speaker)
    s.say("hi")
    import time
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not calls:
        time.sleep(0.01)
    assert calls == ["hi"]
    s.close()


def test_create_speaker_mute_never_touches_neural(monkeypatch):
    def boom():
        raise AssertionError("neural_engine must not be called when muted")

    monkeypatch.setattr("core.live.voice_engine.neural_engine", boom)
    assert isinstance(create_speaker(mute=True), NullSpeaker)
