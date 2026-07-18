"""Runtime smoke for the rig-only engineer deps. NOT part of the test
suite -- run manually on the rig after `uv sync --group rig`:

    .venv/Scripts/python.exe scripts/check_engineer_deps.py

Downloads the Kokoro (~330MB) and Whisper base.en (~74MB) models from
HuggingFace on first run.
"""

import sys
import time
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> None:
    import numpy as np

    print("1/4 kokoro synthesis...")
    from kokoro import KPipeline
    pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    t0 = time.monotonic()
    chunks = []
    for result in pipeline("Radio check, reading you loud and clear.",
                           voice="am_michael"):
        audio = result[2] if isinstance(result, tuple) else result.audio
        chunks.append(audio.detach().cpu().numpy())
    wav = np.concatenate(chunks)
    synth_s = time.monotonic() - t0
    audio_s = len(wav) / 24000.0
    print(f"    synthesized {audio_s:.1f}s of audio in {synth_s:.1f}s "
          f"(ratio {synth_s / audio_s:.2f}x -- must be < 1.0)")

    print("2/4 sounddevice playback...")
    import sounddevice as sd
    sd.play(wav, 24000)
    sd.wait()
    print("    played (did you hear it?)")

    print("3/4 faster-whisper...")
    from faster_whisper import WhisperModel
    t0 = time.monotonic()
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    print(f"    model loaded in {time.monotonic() - t0:.1f}s")
    silence = np.zeros(16000, dtype=np.float32)
    segments, _ = model.transcribe(silence, language="en", beam_size=1)
    list(segments)
    print("    transcribe path works")

    print("4/4 pygame joystick...")
    import pygame
    pygame.init()
    pygame.joystick.init()
    print(f"    {pygame.joystick.get_count()} joystick(s) found "
          f"(wheel must be on for > 0)")
    print("ALL OK")


if __name__ == "__main__":
    main()
