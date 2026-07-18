"""faster-whisper wrapper for PTT questions. Worker-thread use only.

load_model() is called once, on a background thread at coach connect, so
the first question never pays the ~2s model load. Returns None if
faster-whisper is not installed (rig group absent) -- PTT then disables
with a visible startup line; the coach itself is unaffected.
"""

import logging

logger = logging.getLogger(__name__)

MODEL_NAME = "base.en"   # ~74MB int8; radio questions are short + English
SAMPLE_RATE = 16000      # what WhisperModel.transcribe expects


def load_model():
    try:
        from faster_whisper import WhisperModel
        return WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    except Exception:
        logger.warning("faster-whisper unavailable; PTT disabled",
                       exc_info=True)
        return None


def transcribe(model, audio) -> str:
    """float32 mono 16kHz numpy array -> transcript ('' on silence/failure)."""
    if model is None or audio is None or len(audio) == 0:
        return ""
    try:
        segments, _info = model.transcribe(
            audio, language="en", beam_size=1
        )
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception:
        logger.warning("Transcription failed", exc_info=True)
        return ""
