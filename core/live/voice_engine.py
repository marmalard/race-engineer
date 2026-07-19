"""Neural TTS engine factory for the live coach's Speaker.

Kokoro-82M synthesized on CPU (iRacing owns the GPU), played through
sounddevice. Returns a plain Callable[[str], None] -- the exact engine
seam Speaker already takes -- or None on ANY failure, in which case
create_speaker falls back to SAPI. Voice is an enhancement layer; the
text surfaces stay canonical.

First run downloads the model (~330MB) from HuggingFace; the factory is
called once at coach startup so that cost never lands mid-session.
"""

import logging
from typing import Callable

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000     # Kokoro's fixed output rate
VOICE = "am_michael"    # calm US male -- the engineer register
SPEED = 1.15            # >1 = faster; field note 2026-07-18: default read slow
# Kokoro's raw waveform peaks well below full scale, which made the voice
# inaudible under game audio (SAPI plays at system TTS volume, so the old
# voice cut through). Every utterance is peak-normalized to TARGET_PEAK,
# then GAIN applies on top (values > 1.0 clip radio-style -- raise it if
# normalization alone still loses to engine noise).
TARGET_PEAK = 0.95
GAIN = 1.0


def _default_pipeline_factory():
    from kokoro import KPipeline
    return KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")


def _default_player(wav, samplerate: int) -> None:
    import sounddevice as sd
    sd.play(wav, samplerate)
    sd.wait()  # blocking is correct: the engine runs on Speaker's worker


def neural_engine(
    pipeline_factory: Callable | None = None,
    player: Callable | None = None,
) -> Callable[[str], None] | None:
    """Build the Kokoro speak callable, or None if the stack is absent.

    Injection points exist for tests only; production callers pass nothing.
    """
    import numpy as np  # core dep, always present; the speak closure captures it

    factory = pipeline_factory or _default_pipeline_factory
    play = player or _default_player
    try:
        pipeline = factory()
    except Exception:
        logger.warning("Neural voice unavailable; falling back to SAPI",
                       exc_info=True)
        return None

    def speak(text: str) -> None:
        chunks = []
        for result in pipeline(text, voice=VOICE, speed=SPEED):
            audio = result[2] if isinstance(result, tuple) else result.audio
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            chunks.append(np.asarray(audio, dtype=np.float32))
        if chunks:
            wav = np.concatenate(chunks)
            peak = float(np.max(np.abs(wav)))
            if peak > 0.0:
                wav = np.clip(wav * (TARGET_PEAK * GAIN / peak), -1.0, 1.0)
            play(wav, SAMPLE_RATE)

    return speak
