"""Push-to-talk mic capture: record while the button is held, hard cap.

sounddevice InputStream at 16kHz mono float32 -- exactly what the STT
wrapper consumes. start() opens the stream, stop() closes it and returns
the recording. Frames beyond MAX_SECONDS are dropped in the callback
(the cap must hold even if a release event is lost). Any device failure
returns an empty array -- the caller speaks 'Say again?'.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MAX_SECONDS = 10.0


class MicCapture:
    def __init__(self) -> None:
        self._frames: list[np.ndarray] = []
        self._stream = None
        self._max_samples = int(SAMPLE_RATE * MAX_SECONDS)
        self._n_samples = 0

    def _cb(self, indata, frames, time_info, status) -> None:
        if self._n_samples < self._max_samples:
            self._frames.append(indata[:, 0].copy())
            self._n_samples += len(indata)

    def start(self) -> None:
        self._frames = []
        self._n_samples = 0
        try:
            import sounddevice as sd
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                callback=self._cb,
            )
            self._stream.start()
        except Exception:
            logger.warning("Mic unavailable", exc_info=True)
            self._stream = None

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._frames)
