# PTT Live Engineer + Natural Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Phase 5 live engineer in three independently-useful stages: neural voice for the existing coach, race-state awareness with four sparse engineer calls, and wheel-button push-to-talk with hybrid fast-path/Claude answers.

**Architecture:** Everything extends the live coach process (`scripts/live_coach.py`, 60Hz tick loop). New pure package `core/engineer/` (state machines fed tick dicts — the `LapBoundaryTracker` mold); the Speaker gains a priority slot; STT and Claude run on worker threads so the tick never blocks. Spec: `docs/superpowers/specs/2026-07-18-ptt-engineer-design.md`.

**Tech Stack:** kokoro 0.9.4 (torch 2.13 CPU) + sounddevice for TTS, faster-whisper (CTranslate2, `base.en` int8) for STT, pygame for the wheel button, anthropic (Haiku) for open questions. **Compat verified 2026-07-18:** `uv pip install --dry-run` resolves kokoro + faster-whisper + sounddevice + pygame jointly on the Python 3.14 venv (99 packages, no conflicts) — the Piper and whisper.cpp fallbacks are dead branches and do NOT get built. Runtime smoke happens in Task 1.

**Dependency placement rule:** the four new packages go in a `rig` dependency group, NOT `[project.dependencies]` — kokoro drags torch+spacy+transformers (~60 packages) and must never bloat a friend's `uv sync` (B2 installer). The rig installs with `uv sync --group rig`. If anyone runs plain `uv sync` on the rig afterward the group is removed and the coach degrades to SAPI with a visible startup line — accepted, documented in Task 14.

**House rules that bind every task:** Edit tool only (never PowerShell Set-Content); no double quotes in commit messages; run tests with `.venv/Scripts/python.exe -m pytest`; exact-string tests for every spoken line; fake engines/clients only — no SAPI, no mic, no network, no model loads in the suite.

---

## File map

| File | Role |
|---|---|
| `pyproject.toml` | add `rig` dependency group |
| `scripts/check_engineer_deps.py` | Create: runtime smoke for kokoro/whisper/audio/joystick (rig-only, not in suite) |
| `core/live/speaker.py` | Modify: priority slot, `say_priority()`, `cancel_pending()`, neural-first `create_speaker` |
| `core/live/voice_engine.py` | Create: Kokoro engine factory (returns None on any failure → SAPI fallback) |
| `core/engineer/__init__.py` | Create: empty package init |
| `core/engineer/radio_budget.py` | Create: global spacing limiter for engineer speech |
| `core/engineer/race_state.py` | Create: PURE per-tick CarIdx state machine + `snapshot()`; owns `ENGINEER_CHANNELS` |
| `core/engineer/calls.py` | Create: threat/attack/closing-laps calls + phrasing helpers |
| `core/engineer/corner_loss.py` | Create: where-you're-losing-the-guy-ahead tracker |
| `core/engineer/intents.py` | Create: deterministic transcript → answer fast path |
| `core/engineer/answers.py` | Create: fast-path/Claude/offline orchestration |
| `core/engineer/stt.py` | Create: faster-whisper wrapper (lazy, import-guarded) |
| `core/engineer/mic.py` | Create: sounddevice capture with hard cap |
| `core/engineer/ptt_input.py` | Create: pygame joystick open + pure press/release edge detector |
| `core/coaching/prompts/engineer.py` | Create: radio tone contract for the Claude path |
| `scripts/live_coach.py` | Modify: `--no-engineer` + `--ptt-button` flags, Stage B/C wiring |
| `scripts/probe_ptt_button.py` | Create: prints joystick button presses so the founder finds the index |
| `app/pages/toolbox.py` | Modify: `_coach()` gains `engineer` kwarg |
| `tests/test_speaker.py` | Modify: priority-slot tests |
| `tests/test_voice_engine.py` | Create |
| `tests/test_radio_budget.py` | Create |
| `tests/test_race_state.py` | Create |
| `tests/test_engineer_calls.py` | Create |
| `tests/test_corner_loss.py` | Create |
| `tests/test_intents.py` | Create |
| `tests/test_answers.py` | Create |
| `tests/test_ptt_input.py` | Create |
| `tests/test_toolbox_commands.py` | Modify: engineer-flag coupling |

Work on a feature branch `ptt-engineer` in a worktree (the production app hot-reloads the main checkout — never branch there while the rig runs).

---

## Stage A — the voice

### Task 1: Rig dependency group + runtime smoke

**Files:**
- Modify: `pyproject.toml`
- Create: `scripts/check_engineer_deps.py`

- [ ] **Step 1: Add the `rig` group to `pyproject.toml`**

Append to the `[dependency-groups]` table (below `dev`):

```toml
rig = [
    "kokoro>=0.9.4",
    "faster-whisper>=1.2.1",
    "sounddevice>=0.5.5",
    "pygame>=2.6.1",
]
```

- [ ] **Step 2: Lock and sync**

Run (uv.exe lives at `%APPDATA%\Python\Python314\Scripts\uv.exe`; the venv has no pip):

```
uv lock
uv sync --group rig
```

Expected: lock succeeds; sync installs ~70 new packages (torch CPU ~200MB download). If `uv lock` fails on a resolver conflict, STOP and report — the dry-run said it resolves, so a failure means the index moved.

- [ ] **Step 3: Write the smoke script**

Create `scripts/check_engineer_deps.py`:

```python
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
```

- [ ] **Step 4: Run the smoke**

Run: `.venv/Scripts/python.exe scripts/check_engineer_deps.py`
Expected: all four sections pass; synthesis ratio < 1.0x. **If the kokoro result-tuple unpacking fails** (API drift), fix the extraction in this script AND use the working extraction in Task 3's `voice_engine.py`. If kokoro import itself dies on 3.14, STOP and report (fallback re-decision needed — do not improvise Piper).

- [ ] **Step 5: Verify the suite is untouched and commit**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: same pass count as master (1090 + skips).

```bash
git add pyproject.toml uv.lock scripts/check_engineer_deps.py
git commit -m 'feat(engineer): rig dependency group + runtime smoke script'
```

### Task 2: Speaker priority slot

**Files:**
- Modify: `core/live/speaker.py`
- Test: `tests/test_speaker.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_speaker.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_speaker.py -q`
Expected: FAIL — `AttributeError: 'Speaker' object has no attribute 'say_priority'`

- [ ] **Step 3: Implement**

In `core/live/speaker.py`, replace the single `_pending` slot with two tiers. `NullSpeaker` gains the two no-op methods:

```python
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
```

In `Speaker.__init__` replace `self._pending: str | None = None` with:

```python
        self._pending: str | None = None           # normal tier (cues, calls)
        self._pending_priority: str | None = None  # PTT answers
```

Replace `say` and add the two methods:

```python
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
```

Replace the worker's dequeue block inside `_run`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_speaker.py -q`
Expected: all PASS (old tests included — `say` semantics within its tier are unchanged).

- [ ] **Step 5: Commit**

```bash
git add core/live/speaker.py tests/test_speaker.py
git commit -m 'feat(voice): Speaker priority slot -- say_priority beats cues, cancel_pending for PTT press'
```

### Task 3: Kokoro engine factory + neural-first create_speaker

**Files:**
- Create: `core/live/voice_engine.py`
- Modify: `core/live/speaker.py` (`create_speaker` only)
- Test: `tests/test_voice_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_voice_engine.py`:

```python
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
        def __call__(self, text, voice):
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_voice_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.live.voice_engine'`

- [ ] **Step 3: Implement `core/live/voice_engine.py`**

```python
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
    factory = pipeline_factory or _default_pipeline_factory
    play = player or _default_player
    try:
        import numpy as np
        pipeline = factory()
    except Exception:
        logger.warning("Neural voice unavailable; falling back to SAPI",
                       exc_info=True)
        return None

    def speak(text: str) -> None:
        chunks = []
        for result in pipeline(text, voice=VOICE):
            audio = result[2] if isinstance(result, tuple) else result.audio
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            chunks.append(np.asarray(audio, dtype=np.float32))
        if chunks:
            play(np.concatenate(chunks), SAMPLE_RATE)

    return speak
```

(If Task 1's smoke required a different result-extraction, mirror it here.)

- [ ] **Step 4: Rewrite `create_speaker` in `core/live/speaker.py`**

```python
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
```

Note `Speaker.__init__` already treats `engine=None` as SAPI — no change there.

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_voice_engine.py tests/test_speaker.py -q`
Expected: all PASS.

- [ ] **Step 6: Manual rig check (executor runs, founder listens later)**

Run: `.venv/Scripts/python.exe -c "from core.live.speaker import create_speaker; import time; s = create_speaker(); s.say('Radio check. Reference lap two oh seven point seven, loaded.'); time.sleep(12); s.close()"`
Expected: prints `Voice: neural (Kokoro).` and speaks in the Kokoro voice.

- [ ] **Step 7: Commit**

```bash
git add core/live/voice_engine.py core/live/speaker.py tests/test_voice_engine.py
git commit -m 'feat(voice): Kokoro neural engine factory, neural-first create_speaker with SAPI fallback'
```

**Stage A is shippable here** — the existing coach speaks in the new voice with zero changes to `live_coach.py`.

### Task 4: RadioBudget

**Files:**
- Create: `core/engineer/__init__.py` (empty), `core/engineer/radio_budget.py`
- Test: `tests/test_radio_budget.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_radio_budget.py`:

```python
from core.engineer.radio_budget import MIN_SPACING_S, RadioBudget


def test_first_call_allowed():
    b = RadioBudget()
    assert b.try_speak(now=100.0) is True


def test_spacing_blocks_then_reopens():
    b = RadioBudget()
    assert b.try_speak(now=100.0)
    assert b.try_speak(now=100.0 + MIN_SPACING_S - 0.1) is False
    assert b.try_speak(now=100.0 + MIN_SPACING_S + 0.1) is True


def test_blocked_attempt_does_not_reset_the_clock():
    b = RadioBudget()
    assert b.try_speak(now=100.0)
    assert b.try_speak(now=110.0) is False       # blocked
    assert b.try_speak(now=100.0 + MIN_SPACING_S + 0.1) is True


def test_note_priority_counts_for_spacing():
    # A PTT answer is exempt from the gate but still spaces later calls:
    # the engineer should not pile a cue right on top of an answer.
    b = RadioBudget()
    b.note_priority(now=100.0)
    assert b.try_speak(now=105.0) is False
    assert b.try_speak(now=100.0 + MIN_SPACING_S + 0.1) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_radio_budget.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/engineer/radio_budget.py`** (and create empty `core/engineer/__init__.py`)

```python
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
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_radio_budget.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/engineer/__init__.py core/engineer/radio_budget.py tests/test_radio_budget.py
git commit -m 'feat(engineer): RadioBudget global spacing limiter'
```

---

## Stage B — race state + engineer calls

### Task 5: RaceState summarizer

**Files:**
- Create: `core/engineer/race_state.py`
- Test: `tests/test_race_state.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_race_state.py`:

```python
"""RaceState fed synthetic tick dicts -- the session_reader precedent."""

from core.engineer.race_state import ENGINEER_CHANNELS, RaceState

ROSTER = [
    {"CarIdx": 0, "UserName": "Lewis Hamilton", "IRating": 3500},
    {"CarIdx": 1, "UserName": "Anthony Moorman2", "IRating": 1900},
    {"CarIdx": 2, "UserName": "Max Verstappen", "IRating": 4100},
]


def tick(st, laps, positions, f2, laps_remain=10, time_remain=1800.0):
    return {
        "SessionTime": st,
        "CarIdxLap": laps,
        "CarIdxPosition": positions,
        "CarIdxLapDistPct": [0.5, 0.5, 0.5],
        "CarIdxF2Time": f2,
        "CarIdxOnPitRoad": [False, False, False],
        "SessionLapsRemain": laps_remain,
        "SessionTimeRemain": time_remain,
    }


def make_state():
    s = RaceState(player_idx=1)
    s.set_roster(ROSTER)
    return s


def test_engineer_channels_cover_the_feed():
    for key in ("CarIdxLap", "CarIdxPosition", "CarIdxF2Time",
                "CarIdxOnPitRoad", "SessionLapsRemain", "SessionTimeRemain",
                "SessionTime"):
        assert key in ENGINEER_CHANNELS


def test_feed_ignores_non_list_caridx_ticks():
    s = make_state()
    bad = tick(10.0, [2, 2, 2], [2, 3, 1], [5.0, 12.0, 0.0])
    bad["CarIdxLap"] = 2  # scalar churn tick
    assert s.feed(bad) is False


def test_lap_boundary_records_gaps_to_position_neighbors():
    s = make_state()
    # player P2: car 2 (P1) ahead, car 0 (P3) behind. F2 = time behind leader.
    s.feed(tick(100.0, [2, 2, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    assert s.feed(tick(230.0, [2, 3, 2], [3, 2, 1], [14.1, 12.0, 0.0])) is True
    g = s.lap_gaps[-1]
    assert g.lap == 3
    assert g.position == 2
    assert g.ahead_idx == 2
    assert abs(g.gap_ahead_s - 12.0) < 1e-9    # 12.0 - 0.0
    assert g.behind_idx == 0
    assert abs(g.gap_behind_s - 2.1) < 1e-9    # 14.1 - 12.0


def test_player_lap_time_derived_from_boundary_session_times():
    s = make_state()
    s.feed(tick(100.0, [2, 2, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    s.feed(tick(230.0, [2, 3, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    s.feed(tick(361.5, [2, 4, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    assert abs(s.player_lap_times[-1] - 131.5) < 1e-9


def test_snapshot_shape_names_and_trend():
    s = make_state()
    s.feed(tick(100.0, [2, 2, 2], [3, 2, 1], [14.0, 12.0, 0.0]))
    s.feed(tick(230.0, [2, 3, 2], [3, 2, 1], [14.0, 12.0, 0.0], laps_remain=6))
    s.feed(tick(360.0, [2, 4, 2], [3, 2, 1], [13.5, 12.5, 0.0], laps_remain=5))
    snap = s.snapshot()
    assert snap["position"] == 2
    assert snap["field_size"] == 3
    assert snap["laps_remaining"] == 5
    assert snap["ahead"]["name"] == "Verstappen"   # speech_name: surname only
    # gap ahead went 12.0 -> 12.5: +0.5/lap (positive = losing ground)
    assert abs(snap["ahead"]["trend_s_per_lap"] - 0.5) < 1e-9
    assert snap["behind"]["name"] == "Hamilton"
    # gap behind went 2.0 -> 1.0: -1.0/lap (negative = he is closing)
    assert abs(snap["behind"]["trend_s_per_lap"] - -1.0) < 1e-9


def test_no_neighbor_yields_none_blocks():
    s = RaceState(player_idx=0)
    s.set_roster(ROSTER[:1])
    one = {
        "SessionTime": 100.0, "CarIdxLap": [2], "CarIdxPosition": [1],
        "CarIdxLapDistPct": [0.1], "CarIdxF2Time": [0.0],
        "CarIdxOnPitRoad": [False],
        "SessionLapsRemain": 10, "SessionTimeRemain": 1800.0,
    }
    s.feed(one)
    one2 = dict(one, SessionTime=230.0, CarIdxLap=[3])
    s.feed(one2)
    snap = s.snapshot()
    assert snap["ahead"] is None and snap["behind"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_state.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/engineer/race_state.py`**

```python
"""Rolling race-state summarizer over the live CarIdx arrays.

PURE state machine in the LapBoundaryTracker mold: no pyirsdk, no I/O.
live_coach feeds one sample dict per tick; feed() returns True on the
player's lap boundary. Trend math runs only on lap boundaries -- per-tick
work is an array read. snapshot() is the compact race-state dict that
grounds BOTH the PTT fast path and the Claude path (one representation,
two consumers).

Gap convention: CarIdxF2Time is race-time behind the leader, so
gap_ahead_s = my_f2 - ahead_f2 (positive) and gap_behind_s =
behind_f2 - my_f2 (positive). Trend is gap[-1] - gap[-2] per lap:
NEGATIVE trend on `behind` means he is closing; POSITIVE trend on
`ahead` means you are losing ground.

Not available live (accepted): opponent pedals/tires/fuel. Opponent
behavior is inferred from gaps and lap times -- what real engineers do.
"""

import re
from dataclasses import dataclass

# The extra channels live_coach reads for the engineer. CarIdx values are
# EXPECTED to be lists here -- the scalar churn guard must not apply.
ENGINEER_CHANNELS = [
    "SessionTime",
    "CarIdxLap",
    "CarIdxPosition",
    "CarIdxLapDistPct",
    "CarIdxF2Time",
    "CarIdxOnPitRoad",
    "SessionLapsRemain",
    "SessionTimeRemain",
]

# iRacing SessionLapsRemain sentinel for unlimited/timed sessions.
_UNLIMITED = 32767

_CARIDX_KEYS = ("CarIdxLap", "CarIdxPosition", "CarIdxF2Time",
                "CarIdxOnPitRoad", "CarIdxLapDistPct")


def speech_name(user_name: str) -> str:
    """iRacing display name -> spoken surname: 'Anthony Moorman2' -> 'Moorman'."""
    cleaned = re.sub(r"\d+$", "", (user_name or "").strip())
    parts = cleaned.split()
    return parts[-1] if parts else "the other car"


@dataclass(frozen=True)
class LapGaps:
    lap: int
    position: int
    ahead_idx: int | None
    gap_ahead_s: float | None
    behind_idx: int | None
    gap_behind_s: float | None


class RaceState:
    def __init__(self, player_idx: int) -> None:
        self.player_idx = player_idx
        self._roster: dict[int, dict] = {}
        self._prev_player_lap: int | None = None
        self._player_lap_start: float | None = None
        self.player_lap_times: list[float] = []
        self.lap_gaps: list[LapGaps] = []
        self._positions: list[int] = []
        self._f2: list[float] = []
        self._laps: list[int] = []
        self._laps_remaining: int | None = None
        self._time_remaining: float | None = None

    def set_roster(self, drivers: list[dict]) -> None:
        """DriverInfo Drivers rows, keyed by CarIdx."""
        self._roster = {
            int(d.get("CarIdx", -1)): d for d in drivers or []
        }

    def feed(self, sample: dict) -> bool:
        """One tick. Returns True on the player's lap boundary."""
        if any(not isinstance(sample.get(k), list) for k in _CARIDX_KEYS):
            return False
        laps = sample["CarIdxLap"]
        if self.player_idx >= len(laps):
            return False
        self._laps = [int(v or 0) for v in laps]
        self._positions = [int(v or 0) for v in sample["CarIdxPosition"]]
        self._f2 = [float(v or 0.0) for v in sample["CarIdxF2Time"]]
        raw_remain = sample.get("SessionLapsRemain")
        self._laps_remaining = (
            int(raw_remain) if isinstance(raw_remain, (int, float))
            and 0 <= int(raw_remain) < _UNLIMITED else None
        )
        raw_time = sample.get("SessionTimeRemain")
        self._time_remaining = (
            float(raw_time) if isinstance(raw_time, (int, float))
            and raw_time >= 0 else None
        )
        st = float(sample.get("SessionTime") or 0.0)

        my_lap = self._laps[self.player_idx]
        boundary = (self._prev_player_lap is not None
                    and my_lap == self._prev_player_lap + 1)
        if boundary:
            if self._player_lap_start is not None:
                self.player_lap_times.append(st - self._player_lap_start)
            self._player_lap_start = st
            self._record_lap_gaps(my_lap)
        elif self._prev_player_lap != my_lap:
            self._player_lap_start = st  # reset/tow/first sight: restart clock
        self._prev_player_lap = my_lap
        return boundary

    def _idx_at_position(self, pos: int) -> int | None:
        if pos < 1:
            return None
        for idx, p in enumerate(self._positions):
            if p == pos and idx != self.player_idx:
                return idx
        return None

    def _record_lap_gaps(self, lap: int) -> None:
        my_pos = self._positions[self.player_idx]
        my_f2 = self._f2[self.player_idx]
        ahead = self._idx_at_position(my_pos - 1)
        behind = self._idx_at_position(my_pos + 1)
        self.lap_gaps.append(LapGaps(
            lap=lap,
            position=my_pos,
            ahead_idx=ahead,
            gap_ahead_s=(my_f2 - self._f2[ahead]) if ahead is not None else None,
            behind_idx=behind,
            gap_behind_s=(self._f2[behind] - my_f2) if behind is not None else None,
        ))

    def current_gap_ahead(self) -> tuple[int, float] | None:
        """Per-tick (ahead_idx, gap_s) for the corner-loss tracker."""
        if not self._positions or self.player_idx >= len(self._positions):
            return None
        ahead = self._idx_at_position(self._positions[self.player_idx] - 1)
        if ahead is None:
            return None
        return ahead, self._f2[self.player_idx] - self._f2[ahead]

    def name_of(self, idx: int | None) -> str:
        if idx is None:
            return "the other car"
        return speech_name(str(self._roster.get(idx, {}).get("UserName", "")))

    def _neighbor(self, which: str) -> dict | None:
        recs = [g for g in self.lap_gaps
                if getattr(g, f"{which}_idx") is not None
                and getattr(g, f"gap_{which}_s") is not None]
        if not recs:
            return None
        last = recs[-1]
        idx = getattr(last, f"{which}_idx")
        gap = getattr(last, f"gap_{which}_s")
        trend = None
        if (len(recs) >= 2 and getattr(recs[-2], f"{which}_idx") == idx
                and recs[-2].lap == last.lap - 1):
            trend = gap - getattr(recs[-2], f"gap_{which}_s")
        driver = self._roster.get(idx, {})
        return {
            "name": self.name_of(idx),
            "irating": driver.get("IRating"),
            "gap_s": round(gap, 2),
            "trend_s_per_lap": round(trend, 2) if trend is not None else None,
        }

    def snapshot(self) -> dict:
        """Compact race-state dict -- the grounding payload."""
        last = self.lap_gaps[-1] if self.lap_gaps else None
        return {
            "position": last.position if last else None,
            "field_size": sum(1 for p in self._positions if p > 0),
            "lap": self._laps[self.player_idx] if self._laps else None,
            "laps_remaining": self._laps_remaining,
            "time_remaining_s": self._time_remaining,
            "last_lap_s": (round(self.player_lap_times[-1], 2)
                           if self.player_lap_times else None),
            "best_lap_s": (round(min(self.player_lap_times), 2)
                           if self.player_lap_times else None),
            "ahead": self._neighbor("ahead"),
            "behind": self._neighbor("behind"),
        }
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_state.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/engineer/race_state.py tests/test_race_state.py
git commit -m 'feat(engineer): RaceState summarizer -- CarIdx tick machine, lap-boundary gaps, snapshot'
```

### Task 6: Engineer calls (threat / attack / closing laps)

**Files:**
- Create: `core/engineer/calls.py`
- Test: `tests/test_engineer_calls.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engineer_calls.py`:

```python
"""Engineer-initiated calls over synthetic gap histories. Spoken lines are
exact-string pinned (nudges precedent)."""

from core.engineer.calls import EngineerCalls, tenths_phrase
from core.engineer.race_state import LapGaps, RaceState
from core.engineer.radio_budget import RadioBudget

ROSTER = [
    {"CarIdx": 0, "UserName": "Lewis Hamilton", "IRating": 3500},
    {"CarIdx": 1, "UserName": "Anthony Moorman2", "IRating": 1900},
    {"CarIdx": 2, "UserName": "Max Verstappen", "IRating": 4100},
]


def state_with(gaps):
    s = RaceState(player_idx=1)
    s.set_roster(ROSTER)
    s.lap_gaps.extend(gaps)
    return s


def g(lap, ahead=None, behind=None, pos=6):
    return LapGaps(lap=lap, position=pos,
                   ahead_idx=2 if ahead is not None else None,
                   gap_ahead_s=ahead,
                   behind_idx=0 if behind is not None else None,
                   gap_behind_s=behind)


def wide_open_budget():
    return RadioBudget(min_spacing_s=0.0)


def test_tenths_phrase_exact_strings():
    assert tenths_phrase(0.08) == "a tenth"
    assert tenths_phrase(0.31) == "three tenths"
    assert tenths_phrase(0.52) == "half a second"
    assert tenths_phrase(0.97) == "a second"
    assert tenths_phrase(1.42) == "1.4 seconds"


def test_threat_fires_after_trend_laps_of_closing_inside_gap():
    calls = EngineerCalls(wide_open_budget())
    s = state_with([g(3, behind=2.0), g(4, behind=1.7), g(5, behind=1.4)])
    spoken, _ = calls.on_lap(s, now=100.0)
    assert spoken == [
        "Hamilton is closing, three tenths a lap. Keep your head down."
    ]


def test_threat_once_then_rearms_when_gap_reopens():
    # on_lap runs every lap boundary in production -- the test must too,
    # because re-arm triggers on the lap where the gap reopens.
    calls = EngineerCalls(wide_open_budget())
    s = state_with([g(3, behind=2.0), g(4, behind=1.7), g(5, behind=1.4)])
    spoken, _ = calls.on_lap(s, now=100.0)
    assert len(spoken) == 1                    # initial fire
    for lap, gap in [(6, 1.2),   # engaged: quiet
                     (7, 2.8),   # reopen past REARM_GAP_S: re-arms, quiet
                     (8, 2.6),   # closing again but gap > threshold: quiet
                     (9, 2.4)]:  # still outside threshold: quiet
        s.lap_gaps.append(g(lap, behind=gap))
        spoken, _ = calls.on_lap(s, now=100.0 + lap * 100.0)
        assert spoken == []
    s.lap_gaps.append(g(10, behind=1.4))       # inside 1.5s, trend intact
    spoken, _ = calls.on_lap(s, now=2000.0)
    # window [2.6, 2.4, 1.4] -> mean 0.6s/lap -> "six tenths"
    assert spoken == [
        "Hamilton is closing, six tenths a lap. Keep your head down."
    ]


def test_attack_line_exact():
    calls = EngineerCalls(wide_open_budget())
    s = state_with([g(3, ahead=4.0), g(4, ahead=3.5), g(5, ahead=3.0)])
    spoken, _ = calls.on_lap(s, now=100.0)
    assert spoken == ["You're pulling Verstappen in, half a second a lap."]


def test_closing_laps_line_exact_and_once():
    calls = EngineerCalls(wide_open_budget())
    s = state_with([g(10, behind=2.1)])
    s._laps_remaining = 5
    spoken, _ = calls.on_lap(s, now=100.0)
    assert spoken == ["Five to go, P6, gap behind 2.1."]
    spoken, _ = calls.on_lap(s, now=200.0)
    assert spoken == []


def test_budget_blocks_and_reports_dropped():
    calls = EngineerCalls(RadioBudget(min_spacing_s=1000.0))
    s = state_with([g(3, ahead=4.0, behind=2.0),
                    g(4, ahead=3.5, behind=1.7),
                    g(5, ahead=3.0, behind=1.4)])
    spoken, dropped = calls.on_lap(s, now=100.0)
    assert len(spoken) == 1        # threat outranks attack, takes the slot
    assert "closing" in spoken[0]
    assert len(dropped) == 1
    assert "pulling" in dropped[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_engineer_calls.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/engineer/calls.py`**

```python
"""Sparse engineer-initiated calls over RaceState lap-gap histories.

Priority order when several fire on one lap boundary: closing-laps >
threat > attack > corner-loss (the extra_call slot). Each candidate
passes RadioBudget.try_speak individually, so spacing decides how many
actually air; blocked lines are returned for JSONL logging, never spoken
late. Episode semantics: threat/attack fire once per engagement and
re-arm only when the gap reopens past REARM_GAP_S or the car changes.
All thresholds are module constants tuned from session logs.
"""

from core.engineer.race_state import RaceState
from core.engineer.radio_budget import RadioBudget

THREAT_GAP_S = 1.5      # behind-gap that counts as a threat
ATTACK_MAX_GAP_S = 5.0  # only call an attack inside striking range
TREND_LAPS = 3          # consecutive laps of movement required
MIN_TREND_S = 0.05      # per-lap movement below this is noise
REARM_GAP_S = 2.5       # gap must reopen past this to re-arm
CLOSING_LAPS_N = 5
CLOSING_TIME_S = 300.0  # timed races: one call at five minutes left

_TENTHS = {1: "a tenth", 2: "two tenths", 3: "three tenths",
           4: "four tenths", 6: "six tenths", 7: "seven tenths",
           8: "eight tenths", 9: "nine tenths"}
_LAP_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
              6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}


def tenths_phrase(seconds: float) -> str:
    """0.31 -> 'three tenths'; 0.5 -> 'half a second'; 1.4 -> '1.4 seconds'."""
    t = round(abs(seconds) * 10)
    if t <= 1:
        return "a tenth"
    if t == 5:
        return "half a second"
    if t in _TENTHS:
        return _TENTHS[t]
    if t == 10:
        return "a second"
    return f"{abs(seconds):.1f} seconds"


def _trend(gaps: list[float]) -> float | None:
    """Mean per-lap movement over a strictly-monotonic closing series."""
    if len(gaps) < TREND_LAPS:
        return None
    window = gaps[-TREND_LAPS:]
    steps = [window[i] - window[i + 1] for i in range(len(window) - 1)]
    if any(s < MIN_TREND_S for s in steps):
        return None
    return sum(steps) / len(steps)


class EngineerCalls:
    def __init__(self, budget: RadioBudget) -> None:
        self._budget = budget
        self._threat_engaged_idx: int | None = None
        self._attack_engaged_idx: int | None = None
        self._closing_done = False

    def on_lap(
        self, state: RaceState, now: float, extra_call: str | None = None
    ) -> tuple[list[str], list[str]]:
        """All candidates for this lap boundary -> (spoken, budget_dropped)."""
        spoken: list[str] = []
        dropped: list[str] = []
        for text in self._candidates(state, extra_call):
            if self._budget.try_speak(now):
                spoken.append(text)
            else:
                dropped.append(text)
        return spoken, dropped

    def _candidates(self, state: RaceState, extra_call: str | None):
        closing = self._closing_laps(state)
        if closing:
            yield closing
        threat = self._threat(state)
        if threat:
            yield threat
        attack = self._attack(state)
        if attack:
            yield attack
        if extra_call:
            yield extra_call

    def _series(self, state: RaceState, which: str):
        """(car_idx, gap history) for the current same-car streak."""
        recs = state.lap_gaps
        if not recs:
            return None, []
        idx = getattr(recs[-1], f"{which}_idx")
        if idx is None:
            return None, []
        gaps: list[float] = []
        expected_lap = recs[-1].lap
        for rec in reversed(recs):
            if (getattr(rec, f"{which}_idx") != idx
                    or getattr(rec, f"gap_{which}_s") is None
                    or rec.lap != expected_lap):
                break
            gaps.append(getattr(rec, f"gap_{which}_s"))
            expected_lap -= 1
        gaps.reverse()
        return idx, gaps

    def _threat(self, state: RaceState) -> str | None:
        idx, gaps = self._series(state, "behind")
        if idx is None or not gaps:
            return None
        if self._threat_engaged_idx is not None:
            if idx != self._threat_engaged_idx or gaps[-1] > REARM_GAP_S:
                self._threat_engaged_idx = None   # re-arm
            else:
                return None                        # still engaged: stay quiet
        rate = _trend(gaps)
        if rate is None or gaps[-1] > THREAT_GAP_S:
            return None
        self._threat_engaged_idx = idx
        return (f"{state.name_of(idx)} is closing, {tenths_phrase(rate)} "
                "a lap. Keep your head down.")

    def _attack(self, state: RaceState) -> str | None:
        idx, gaps = self._series(state, "ahead")
        if idx is None or not gaps:
            return None
        if self._attack_engaged_idx is not None:
            if idx != self._attack_engaged_idx or gaps[-1] > REARM_GAP_S + 2.0:
                self._attack_engaged_idx = None
            else:
                return None
        rate = _trend(gaps)
        if rate is None or gaps[-1] > ATTACK_MAX_GAP_S:
            return None
        self._attack_engaged_idx = idx
        return (f"You're pulling {state.name_of(idx)} in, "
                f"{tenths_phrase(rate)} a lap.")

    def _closing_laps(self, state: RaceState) -> str | None:
        if self._closing_done or not state.lap_gaps:
            return None
        last = state.lap_gaps[-1]
        laps_left = state._laps_remaining
        time_left = state._time_remaining
        lap_hit = laps_left is not None and laps_left == CLOSING_LAPS_N
        time_hit = (laps_left is None and time_left is not None
                    and time_left <= CLOSING_TIME_S)
        if not (lap_hit or time_hit):
            return None
        self._closing_done = True
        gap_txt = (f", gap behind {last.gap_behind_s:.1f}"
                   if last.gap_behind_s is not None else "")
        lead = (f"{_LAP_WORDS.get(CLOSING_LAPS_N, str(CLOSING_LAPS_N))} to go"
                if lap_hit else "Five minutes to go")
        return f"{lead}, P{last.position}{gap_txt}."
```

Note the test reaches into `state._laps_remaining` to set laps remaining — that field is package-internal state shared between the two modules; acceptable inside the package's own tests.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_engineer_calls.py -q`
Expected: PASS. If `test_threat_fires...` fails on the phrase, check `_trend` math: gaps 2.0→1.7→1.4 = 0.3/lap → "three tenths".

- [ ] **Step 5: Commit**

```bash
git add core/engineer/calls.py tests/test_engineer_calls.py
git commit -m 'feat(engineer): threat, attack and closing-laps calls with episode re-arm + budget'
```

### Task 7: Corner-loss tracker

**Files:**
- Create: `core/engineer/corner_loss.py`
- Test: `tests/test_corner_loss.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_corner_loss.py`:

```python
"""Where-you're-losing-the-guy-ahead: per-corner gap deltas over laps.

Two feed-shape rules the tests must honor because production does:
- The first feed of each lap only seeds the position (no crossing can be
  detected without a previous distance), and a corner's entry and exit
  must be crossed on DIFFERENT feeds or the measured loss is zero.
- A lap's losses are banked when the NEXT lap's first feed arrives (the
  boundary tick), so tests feed a boundary tick before take_call --
  exactly the order live_coach produces.
"""

from core.engineer.corner_loss import CornerLossTracker

# (start_m, end_m, name) spans -- the track_db corner shape live_coach loads.
SPANS = [(500.0, 700.0, "The Chase"), (1500.0, 1700.0, "Hell Corner")]


def run_lap(t, lap, gains, ahead_idx=2):
    """Feed one lap crossing both corners; `gains` maps name -> gap growth
    across that corner's span (positive = losing time to the target)."""
    base = 3.0
    after_chase = base + gains["The Chase"]
    t.feed(lap_dist_m=400.0, gap_ahead_s=base, ahead_idx=ahead_idx, lap=lap)
    t.feed(lap_dist_m=600.0, gap_ahead_s=base, ahead_idx=ahead_idx, lap=lap)
    t.feed(lap_dist_m=720.0, gap_ahead_s=after_chase,
           ahead_idx=ahead_idx, lap=lap)
    t.feed(lap_dist_m=1600.0, gap_ahead_s=after_chase,
           ahead_idx=ahead_idx, lap=lap)
    t.feed(lap_dist_m=1720.0,
           gap_ahead_s=after_chase + gains["Hell Corner"],
           ahead_idx=ahead_idx, lap=lap)


def boundary(t, lap, ahead_idx=2):
    """The next lap's first tick -- banks the previous lap's losses."""
    t.feed(lap_dist_m=100.0, gap_ahead_s=3.0, ahead_idx=ahead_idx, lap=lap)


def test_dominant_corner_produces_the_call_after_min_laps():
    t = CornerLossTracker(SPANS)
    run_lap(t, 3, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 4)
    assert t.take_call(target_name="Verstappen") is None   # 1 lap: not yet
    run_lap(t, 4, {"The Chase": 0.28, "Hell Corner": 0.03})
    boundary(t, 5)
    assert t.take_call(target_name="Verstappen") == \
        "You're losing him mainly in The Chase."


def test_call_fires_once_per_target():
    t = CornerLossTracker(SPANS)
    run_lap(t, 3, {"The Chase": 0.30, "Hell Corner": 0.02})
    run_lap(t, 4, {"The Chase": 0.28, "Hell Corner": 0.03})
    boundary(t, 5)
    assert t.take_call(target_name="Verstappen") is not None
    run_lap(t, 5, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 6)
    assert t.take_call(target_name="Verstappen") is None


def test_no_dominant_corner_stays_silent():
    t = CornerLossTracker(SPANS)
    run_lap(t, 3, {"The Chase": 0.10, "Hell Corner": 0.11})
    run_lap(t, 4, {"The Chase": 0.11, "Hell Corner": 0.10})
    boundary(t, 5)
    assert t.take_call(target_name="Verstappen") is None


def test_target_change_resets_accumulation():
    t = CornerLossTracker(SPANS)
    run_lap(t, 3, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 4, ahead_idx=7)  # new car ahead: accumulation resets
    run_lap(t, 5, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 6)
    assert t.take_call(target_name="Someone") is None      # 1 lap on car 2
    run_lap(t, 6, {"The Chase": 0.30, "Hell Corner": 0.02})
    boundary(t, 7)
    assert t.take_call(target_name="Someone") is not None


def test_no_spans_never_calls():
    t = CornerLossTracker([])
    run_lap(t, 3, {"The Chase": 0.3, "Hell Corner": 0.02})
    boundary(t, 4)
    assert t.take_call(target_name="X") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_corner_loss.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/engineer/corner_loss.py`**

```python
"""Attribute the gap to the car ahead to specific corners.

Fed per tick with the player's LapDist and the current gap to the car
directly ahead (RaceState.current_gap_ahead). Samples the gap when the
player crosses each corner span's start and end; the delta across the
span is that corner's contribution this lap. After MIN_LAPS consecutive
laps on the SAME target, if one corner carries a dominant share of the
total loss, take_call() returns one line -- once per target per session.

Self-gating honesty rules: target change or a lap with no samples resets
accumulation; totals below the noise floor never call; the corner name
comes from the same track-db spans the prompt scheduler uses.
"""

MIN_LAPS = 2
DOMINANCE = 0.5          # corner must carry >= 50% of total loss
MIN_LOSS_PER_LAP_S = 0.15  # and >= this much time per lap


class CornerLossTracker:
    def __init__(self, spans: list[tuple[float, float, str]]) -> None:
        self._spans = sorted(spans or [], key=lambda s: s[0])
        self._target: int | None = None
        self._lap: int | None = None
        self._prev_dist: float | None = None
        self._entry_gap: dict[str, float] = {}
        self._lap_losses: dict[str, float] = {}      # this lap
        self._acc: dict[str, list[float]] = {}       # per-corner, per-lap
        self._laps_accumulated = 0
        self._called_targets: set[int] = set()

    def feed(self, lap_dist_m: float, gap_ahead_s: float,
             ahead_idx: int, lap: int) -> None:
        if not self._spans:
            return
        if ahead_idx != self._target:
            self._reset_target(ahead_idx)
        if lap != self._lap:
            self._close_lap()
            self._lap = lap
        prev = self._prev_dist if self._prev_dist is not None else lap_dist_m
        self._prev_dist = lap_dist_m
        for start_m, end_m, name in self._spans:
            if prev < start_m <= lap_dist_m:
                self._entry_gap[name] = gap_ahead_s
            if prev < end_m <= lap_dist_m and name in self._entry_gap:
                self._lap_losses[name] = gap_ahead_s - self._entry_gap.pop(name)

    def take_call(self, target_name: str) -> str | None:
        """One line when a dominant corner emerges; None otherwise.
        target_name is accepted for future phrasing use; the line itself
        stays name-free ('him') because the threat/attack calls already
        named the car."""
        if (self._target is None or self._target in self._called_targets
                or self._laps_accumulated < MIN_LAPS):
            return None
        per_corner = {
            name: sum(losses) / len(losses)
            for name, losses in self._acc.items()
            if len(losses) >= MIN_LAPS
        }
        if not per_corner:
            return None
        total = sum(v for v in per_corner.values() if v > 0)
        if total <= 0:
            return None
        name, loss = max(per_corner.items(), key=lambda kv: kv[1])
        if loss < MIN_LOSS_PER_LAP_S or loss / total < DOMINANCE:
            return None
        self._called_targets.add(self._target)
        return f"You're losing him mainly in {name}."

    def _close_lap(self) -> None:
        if self._lap_losses:
            for name, loss in self._lap_losses.items():
                self._acc.setdefault(name, []).append(loss)
            self._laps_accumulated += 1
        self._lap_losses = {}
        self._entry_gap = {}
        self._prev_dist = None

    def _reset_target(self, new_target: int) -> None:
        self._target = new_target
        self._entry_gap = {}
        self._lap_losses = {}
        self._acc = {}
        self._laps_accumulated = 0
        self._lap = None
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_corner_loss.py -q`
Expected: PASS. Note in `test_target_change_resets_accumulation` the lap-4 feed on car 7 resets, and lap-5/6 runs rebuild two full laps.

- [ ] **Step 5: Commit**

```bash
git add core/engineer/corner_loss.py tests/test_corner_loss.py
git commit -m 'feat(engineer): corner-loss tracker -- per-corner gap attribution, once per target'
```

### Task 8: Stage B wiring in live_coach + Toolbox coupling

**Files:**
- Modify: `scripts/live_coach.py`, `app/pages/toolbox.py`
- Test: `tests/test_toolbox_commands.py`

- [ ] **Step 1: Write the failing coupling tests**

Append to `tests/test_toolbox_commands.py`:

```python
@pytest.mark.parametrize("engineer", [False, True])
def test_toolbox_engineer_flag_parses_against_live_coach_cli(engineer):
    cmd = _coach(engineer=engineer).command
    args = live_coach.build_parser().parse_args(cmd[2:])
    assert args.engineer is engineer


def test_engineer_defaults_on_in_both_cli_and_toolbox():
    assert live_coach.build_parser().parse_args([]).engineer is True
    cmd = _coach().command
    assert live_coach.build_parser().parse_args(cmd[2:]).engineer is True
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_toolbox_commands.py -q`
Expected: FAIL — `_coach() got an unexpected keyword argument 'engineer'` / no attribute `engineer`.

- [ ] **Step 3: Add the flags to `build_parser` in `scripts/live_coach.py`**

```python
    parser.add_argument("--no-engineer", dest="engineer",
                        action="store_false",
                        help="disable race engineer calls + PTT "
                             "(on by default; active in Race sessions only)")
    parser.add_argument("--ptt-button", type=int, default=5,
                        help="joystick button index for push-to-talk "
                             "(find yours with scripts/probe_ptt_button.py)")
    parser.set_defaults(corner_prompts=True, engineer=True)
```

(The existing `parser.set_defaults(corner_prompts=True)` line is replaced by the combined one.)

- [ ] **Step 4: Extend `_coach` in `app/pages/toolbox.py`**

```python
def _coach(mute: bool = False, corner_prompts: bool = True,
           engineer: bool = True) -> ManagedProcess:
    """Coach spawn command. Round-2 CLI: corner prompts are ON by default,
    --no-corner-prompts disables (coupling-tested in test_toolbox_commands --
    a stale flag here killed the coach at startup on 2026-07-14)."""
    cmd = [_PY, "scripts/live_coach.py"]
    if mute:
        cmd.append("--mute")
    if not corner_prompts:
        cmd.append("--no-corner-prompts")
    if not engineer:
        cmd.append("--no-engineer")
    return ManagedProcess(
        "live-coach", cmd, run_dir=_RUN_DIR, workdir=_REPO_ROOT
    )
```

Also add an `engineer` checkbox (default True) next to the existing mute/prompt checkboxes in the Toolbox start-coach UI block, passed through to `_coach(...)` — follow the exact pattern of the `corner_prompts` checkbox already there.

- [ ] **Step 5: Wire Stage B into `main()` in `scripts/live_coach.py`**

Imports (append to the existing `core` import block):

```python
from core.engineer.calls import EngineerCalls  # noqa: E402
from core.engineer.corner_loss import CornerLossTracker  # noqa: E402
from core.engineer.race_state import ENGINEER_CHANNELS, RaceState  # noqa: E402
from core.engineer.radio_budget import RadioBudget  # noqa: E402
```

In `main()`, add to the state block (near `streaks = FaultStreakTracker()`):

```python
    race_state: RaceState | None = None
    engineer_calls: EngineerCalls | None = None
    corner_loss: CornerLossTracker | None = None
```

In the `if not meta_loaded:` connect block (after `corners` and `car` are loaded), create the engineer objects:

```python
                driver_info = ir["DriverInfo"] or {}
                player_idx = int(driver_info.get("DriverCarIdx", 0) or 0)
                race_state = RaceState(player_idx)
                race_state.set_roster(driver_info.get("Drivers", []))
                engineer_calls = EngineerCalls(RadioBudget())
                corner_loss = CornerLossTracker([
                    (c.distance_start_meters, c.distance_end_meters, c.name)
                    for c in corners
                    if c.name and c.distance_start_meters is not None
                    and c.distance_end_meters is not None
                ])
```

Per tick, AFTER the scalar churn-guard block (the CarIdx arrays are lists by design, so they are read separately and must NOT pass through that guard), insert:

```python
            # Engineer feed -- separate read because CarIdx channels are
            # arrays; the scalar churn guard above must not see them.
            engineer_active = (args.engineer and session_type == "Race"
                               and race_state is not None)
            eng_boundary = False
            if race_state is not None:
                eng_sample = {ch: ir[ch] for ch in ENGINEER_CHANNELS}
                eng_boundary = race_state.feed(eng_sample)
                if engineer_active:
                    _dist = sample.get("LapDist")
                    _gap = race_state.current_gap_ahead()
                    if (_dist is not None and _gap is not None
                            and corner_loss is not None):
                        corner_loss.feed(
                            lap_dist_m=float(_dist), gap_ahead_s=_gap[1],
                            ahead_idx=_gap[0],
                            lap=int(sample.get("Lap") or 0),
                        )
            if engineer_active and eng_boundary and engineer_calls is not None:
                extra = None
                if corner_loss is not None:
                    snap_ahead = race_state.snapshot().get("ahead") or {}
                    extra = corner_loss.take_call(
                        target_name=snap_ahead.get("name", "him")
                    )
                spoken, dropped = engineer_calls.on_lap(
                    race_state, now=time.monotonic(), extra_call=extra,
                )
                for line in spoken:
                    emit(f"  [ENG] {line}")
                    speaker.say(line)
                if session_log is not None and (spoken or dropped):
                    session_log.log(
                        "engineer_call", spoken=spoken, dropped=dropped,
                        snapshot=race_state.snapshot(),
                    )
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all PASS including the new coupling tests. `test_toolbox_coach_command_parses_against_live_coach_cli` still passes because the new flags have defaults.

- [ ] **Step 7: Commit**

```bash
git add scripts/live_coach.py app/pages/toolbox.py tests/test_toolbox_commands.py
git commit -m 'feat(engineer): stage B wiring -- race-state feed, engineer calls in Race sessions, --no-engineer flag'
```

**Stage B is shippable here** — next official race gets threat/attack/closing/corner calls in the neural voice.

---

## Stage C — push-to-talk

### Task 9: Intent fast path

**Files:**
- Create: `core/engineer/intents.py`
- Test: `tests/test_intents.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_intents.py`:

```python
"""Deterministic PTT fast path. Answers exact-string pinned."""

from core.engineer.intents import match_intent

SNAP = {
    "position": 6, "field_size": 18, "lap": 12,
    "laps_remaining": 6, "time_remaining_s": None,
    "last_lap_s": 132.41, "best_lap_s": 131.82,
    "ahead": {"name": "Verstappen", "irating": 4100,
              "gap_s": 1.4, "trend_s_per_lap": -0.3},
    "behind": {"name": "Hamilton", "irating": 3500,
               "gap_s": 2.1, "trend_s_per_lap": 0.2},
}


def test_gap_behind():
    assert match_intent("what's the gap behind", SNAP) == \
        "Gap behind, 2.1 seconds to Hamilton."


def test_gap_ahead():
    assert match_intent("gap to the car ahead", SNAP) == \
        "Gap ahead, 1.4 seconds to Verstappen."


def test_bare_gap_means_ahead():
    assert match_intent("what's the gap", SNAP) == \
        "Gap ahead, 1.4 seconds to Verstappen."


def test_position():
    assert match_intent("what position am I in", SNAP) == "P6 of 18."


def test_laps_left():
    assert match_intent("how many laps left", SNAP) == "Six laps to go."


def test_time_left_when_timed_race():
    snap = dict(SNAP, laps_remaining=None, time_remaining_s=722.0)
    assert match_intent("how long is left", snap) == "Twelve minutes left."


def test_pace():
    assert match_intent("what was my last lap", SNAP) == \
        "Last lap 2:12.4, best 2:11.8."


def test_open_question_returns_none():
    assert match_intent("should I pit with the leaders", SNAP) is None


def test_missing_data_returns_none_not_a_wrong_answer():
    empty = {"position": None, "field_size": 0, "lap": None,
             "laps_remaining": None, "time_remaining_s": None,
             "last_lap_s": None, "best_lap_s": None,
             "ahead": None, "behind": None}
    assert match_intent("what's the gap behind", empty) is None
    assert match_intent("what position am I in", empty) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_intents.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/engineer/intents.py`**

```python
"""Deterministic PTT fast path: transcript -> instant answer, or None.

The no-API-on-critical-path house pattern: the common quantitative radio
calls (gaps, position, laps left, pace) answer from the RaceState
snapshot with zero network. Anything unmatched returns None and falls
through to the Claude path. Missing data returns None too -- an honest
fall-through beats a confident wrong answer.
"""

_NUM_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
              6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
              11: "Eleven", 12: "Twelve"}


def _fmt_lap(seconds: float) -> str:
    m, s = divmod(seconds, 60.0)
    return f"{int(m)}:{s:04.1f}"


def _num_word(n: int) -> str:
    return _NUM_WORDS.get(n, str(n))


def match_intent(transcript: str, snap: dict) -> str | None:
    q = (transcript or "").lower()
    ahead = snap.get("ahead")
    behind = snap.get("behind")

    if "gap" in q or "how far" in q:
        if "behind" in q or "back" in q:
            if behind is None:
                return None
            return (f"Gap behind, {behind['gap_s']:.1f} seconds "
                    f"to {behind['name']}.")
        if ahead is None:
            return None
        return f"Gap ahead, {ahead['gap_s']:.1f} seconds to {ahead['name']}."

    if "position" in q or "where am i" in q:
        if snap.get("position") is None:
            return None
        return f"P{snap['position']} of {snap['field_size']}."

    if (("laps" in q and ("left" in q or "remaining" in q or "to go" in q))
            or "how long" in q):
        laps = snap.get("laps_remaining")
        if laps is not None:
            return f"{_num_word(laps)} laps to go."
        t = snap.get("time_remaining_s")
        if t is not None:
            return f"{_num_word(round(t / 60.0))} minutes left."
        return None

    if "last lap" in q or "lap time" in q or "pace" in q:
        last, best = snap.get("last_lap_s"), snap.get("best_lap_s")
        if last is None or best is None:
            return None
        return f"Last lap {_fmt_lap(last)}, best {_fmt_lap(best)}."

    return None
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_intents.py -q`
Expected: PASS. (722s → 12.03 min → rounds to 12 → "Twelve minutes left.")

- [ ] **Step 5: Commit**

```bash
git add core/engineer/intents.py tests/test_intents.py
git commit -m 'feat(engineer): deterministic PTT intent fast path'
```

### Task 10: Tone contract + answer orchestration

**Files:**
- Create: `core/coaching/prompts/engineer.py`, `core/engineer/answers.py`
- Test: `tests/test_answers.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_answers.py`:

```python
"""Answer orchestration: fast path first, Claude second, offline line last.
Fake ask callables only -- no network, no anthropic client."""

from core.engineer.answers import OFFLINE_LINE, answer_question

SNAP = {
    "position": 6, "field_size": 18, "lap": 12,
    "laps_remaining": 6, "time_remaining_s": None,
    "last_lap_s": 132.41, "best_lap_s": 131.82,
    "ahead": {"name": "Verstappen", "irating": 4100,
              "gap_s": 1.4, "trend_s_per_lap": -0.3},
    "behind": None,
}


def test_fast_path_wins_and_never_calls_claude():
    def boom(transcript, state_json):
        raise AssertionError("Claude must not be called for a fast-path hit")

    text, source = answer_question("what's the gap", SNAP, ask=boom)
    assert source == "fast"
    assert text == "Gap ahead, 1.4 seconds to Verstappen."


def test_open_question_goes_to_claude_with_state():
    seen = {}

    def fake_ask(transcript, state_json):
        seen["transcript"] = transcript
        seen["state_json"] = state_json
        return "Pit with the leaders; track position is worth more today."

    text, source = answer_question("should I pit with the leaders",
                                   SNAP, ask=fake_ask)
    assert source == "claude"
    assert text.startswith("Pit with the leaders")
    assert "Verstappen" in seen["state_json"]
    assert seen["transcript"] == "should I pit with the leaders"


def test_no_ask_callable_gives_offline_line():
    text, source = answer_question("should I pit", SNAP, ask=None)
    assert (text, source) == (OFFLINE_LINE, "offline")


def test_claude_failure_gives_offline_line():
    def dies(transcript, state_json):
        raise TimeoutError("network gone")

    text, source = answer_question("should I pit", SNAP, ask=dies)
    assert (text, source) == (OFFLINE_LINE, "offline")


def test_empty_transcript_asks_for_a_repeat():
    text, source = answer_question("", SNAP, ask=None)
    assert (text, source) == ("Say again?", "fast")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_answers.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Create `core/coaching/prompts/engineer.py`**

```python
"""Radio tone contract for the PTT Claude path.

Engineer, not essayist. The model sees the race-state JSON and one
question; the reply is spoken over the radio mid-race.
"""

ENGINEER_SYSTEM_PROMPT = """You are the driver's race engineer on the radio \
during a live iRacing race. The RACE STATE JSON is the truth -- answer from \
it and only it.

Rules:
1. One or two short sentences. This is spoken audio mid-race; every word \
costs attention.
2. Round numbers the way an engineer speaks them: "two point one", "half a \
second a lap", "P6". Never read raw decimals like 2.147.
3. Be honest and decisive. If the state supports a recommendation, make it. \
If it does not contain the answer, say so in one sentence -- never invent \
gaps, positions or strategy facts.
4. No scolding, no pep talks, no filler like "Great question". Calm, flat, \
professional radio register.
5. Refer to other drivers by surname only."""
```

- [ ] **Step 4: Create `core/engineer/answers.py`**

```python
"""PTT answer orchestration: fast path -> Claude -> offline line.

The fast path (intents) is deterministic and instant. Open questions go
to a Haiku-class call grounded in the race-state JSON with a hard
timeout; ANY failure -- no key, timeout, network -- degrades to the
offline line. The coach must keep answering gaps with the wifi down.
"""

import json
import logging
import os

from core.coaching.prompts.engineer import ENGINEER_SYSTEM_PROMPT
from core.engineer.intents import match_intent

logger = logging.getLogger(__name__)

OFFLINE_LINE = "Can't reach the pit wall — stand by."
ENGINEER_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_TIMEOUT_S = 4.0
MAX_TOKENS = 150


def answer_question(transcript: str, snapshot: dict,
                    ask=None) -> tuple[str, str]:
    """-> (spoken text, source) where source in {fast, claude, offline}."""
    if not (transcript or "").strip():
        return "Say again?", "fast"
    fast = match_intent(transcript, snapshot)
    if fast is not None:
        return fast, "fast"
    if ask is None:
        return OFFLINE_LINE, "offline"
    try:
        return ask(transcript, json.dumps(snapshot)), "claude"
    except Exception:
        logger.warning("Claude PTT path failed; offline line", exc_info=True)
        return OFFLINE_LINE, "offline"


def make_claude_ask():
    """Build the ask callable, or None when no API key is configured.
    Deferred anthropic import so the suite never touches it."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic
    client = anthropic.Anthropic(api_key=key, timeout=CLAUDE_TIMEOUT_S)

    def ask(transcript: str, state_json: str) -> str:
        response = client.messages.create(
            model=ENGINEER_MODEL,
            max_tokens=MAX_TOKENS,
            system=ENGINEER_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (f"RACE STATE:\n{state_json}\n\n"
                            f"DRIVER ASKS: {transcript}"),
            }],
        )
        return "".join(
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip() or OFFLINE_LINE

    return ask
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_answers.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/coaching/prompts/engineer.py core/engineer/answers.py tests/test_answers.py
git commit -m 'feat(engineer): PTT answer orchestration -- fast path, Haiku with radio tone contract, offline line'
```

### Task 11: STT and mic capture

**Files:**
- Create: `core/engineer/stt.py`, `core/engineer/mic.py`
- Test: `tests/test_ptt_input.py` gets the mic-cap test (hardware modules stay thin)

- [ ] **Step 1: Implement `core/engineer/stt.py`** (import-guarded; no unit test loads the model)

```python
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
```

- [ ] **Step 2: Implement `core/engineer/mic.py`**

```python
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
        import sounddevice as sd
        self._frames = []
        self._n_samples = 0
        try:
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
```

- [ ] **Step 3: Write the cap + guard tests** (callback called directly — no audio device)

Create `tests/test_ptt_input.py` (mic part; the button part arrives in Task 12):

```python
"""PTT input-side tests: mic cap logic and STT guards. No hardware."""

import numpy as np

from core.engineer.mic import MAX_SECONDS, SAMPLE_RATE, MicCapture
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
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ptt_input.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/engineer/stt.py core/engineer/mic.py tests/test_ptt_input.py
git commit -m 'feat(engineer): mic capture with hard cap + faster-whisper wrapper'
```

### Task 12: PTT button

**Files:**
- Create: `core/engineer/ptt_input.py`, `scripts/probe_ptt_button.py`
- Test: `tests/test_ptt_input.py` (append)

- [ ] **Step 1: Write the failing edge-detector tests**

Append to `tests/test_ptt_input.py`:

```python
from core.engineer.ptt_input import PTTButton


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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ptt_input.py -q`
Expected: FAIL — no `PTTButton`.

- [ ] **Step 3: Implement `core/engineer/ptt_input.py`**

```python
"""PTT wheel-button input: pygame joystick read + pure edge detection.

open_joystick() returns a zero-arg poll callable (True while the button
is held) or None when pygame/the wheel is absent -- PTT then disables
with a visible startup line. PTTButton is the pure press/release edge
detector the tick loop feeds; it is the tested part. Find your button
index with scripts/probe_ptt_button.py.
"""

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class PTTButton:
    """Pure edge detector: feed(held) -> 'press' | 'release' | None."""

    def __init__(self) -> None:
        self._held = False

    def feed(self, held: bool) -> str | None:
        if held and not self._held:
            self._held = True
            return "press"
        if not held and self._held:
            self._held = False
            return "release"
        return None


def open_joystick(button_index: int) -> Callable[[], bool] | None:
    """Poll callable for joystick 0's button, or None when unavailable."""
    try:
        import pygame
        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() == 0:
            logger.warning("No joystick found; PTT disabled")
            return None
        js = pygame.joystick.Joystick(0)
        js.init()

        def poll() -> bool:
            pygame.event.pump()
            return bool(js.get_button(button_index))

        return poll
    except Exception:
        logger.warning("pygame unavailable; PTT disabled", exc_info=True)
        return None
```

- [ ] **Step 4: Create `scripts/probe_ptt_button.py`**

```python
"""Find the wheel button index for --ptt-button. Hold each button; the
index prints when it goes down. Ctrl+C to quit.

    .venv/Scripts/python.exe scripts/probe_ptt_button.py
"""

import time

import pygame

pygame.init()
pygame.joystick.init()
if pygame.joystick.get_count() == 0:
    raise SystemExit("No joystick found -- is the wheel on?")
js = pygame.joystick.Joystick(0)
js.init()
print(f"{js.get_name()}: {js.get_numbuttons()} buttons. Press one...")
prev = set()
while True:
    pygame.event.pump()
    down = {i for i in range(js.get_numbuttons()) if js.get_button(i)}
    for i in sorted(down - prev):
        print(f"button {i} DOWN  ->  run the coach with --ptt-button {i}")
    prev = down
    time.sleep(0.02)
```

- [ ] **Step 5: Run tests and commit**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ptt_input.py -q`
Expected: PASS.

```bash
git add core/engineer/ptt_input.py scripts/probe_ptt_button.py tests/test_ptt_input.py
git commit -m 'feat(engineer): PTT button edge detector + joystick probe script'
```

### Task 13: Stage C wiring in live_coach

**Files:**
- Modify: `scripts/live_coach.py`

No new unit tests — `main()` is the untested driver by convention; every piece it composes is tested. The coupling tests from Task 8 already cover the flags.

- [ ] **Step 1: Add imports** (append to the engineer import block from Task 8)

```python
import threading  # noqa: E402  (stdlib -- put with the stdlib imports at top)
from core.engineer.answers import answer_question, make_claude_ask  # noqa: E402
from core.engineer.mic import MicCapture  # noqa: E402
from core.engineer.ptt_input import PTTButton, open_joystick  # noqa: E402
from core.engineer import stt  # noqa: E402
```

(`threading` goes in the stdlib import group at the top of the file, not the core block.)

- [ ] **Step 2: Create the PTT objects once, before the main loop** (next to `speaker = create_speaker(...)`)

```python
    ptt_poll = open_joystick(args.ptt_button) if args.engineer else None
    ptt_button = PTTButton()
    mic = MicCapture()
    ptt_ask = make_claude_ask() if args.engineer else None
    stt_model = None
    stt_ready = threading.Event()

    def _load_stt() -> None:
        nonlocal stt_model
        stt_model = stt.load_model()
        stt_ready.set()

    if args.engineer and ptt_poll is not None:
        threading.Thread(target=_load_stt, daemon=True).start()
        print(f"PTT: joystick 0 button {args.ptt_button} "
              f"(probe with scripts/probe_ptt_button.py). "
              f"Claude path: {'on' if ptt_ask else 'OFF (no API key)'}.")
    elif args.engineer:
        print("PTT: no joystick found -- engineer calls only.")
```

- [ ] **Step 3: Add the PTT worker function** (module level, near `_diag_fields`)

```python
def _ptt_worker(audio, stt_model, snapshot: dict, ask, speaker,
                emit, session_log, budget) -> None:
    """Runs on a worker thread: STT -> answer -> priority speech. Never
    raises into the tick loop; every failure becomes a spoken line."""
    import time as _time
    try:
        transcript = stt.transcribe(stt_model, audio)
        text, source = answer_question(transcript, snapshot, ask=ask)
        speaker.say_priority(text)
        budget.note_priority(_time.monotonic())
        emit(f"  [PTT] {transcript or '(unintelligible)'} -> {text}")
        if session_log is not None:
            session_log.log("ptt", transcript=transcript, answer=text,
                            source=source, snapshot=snapshot)
    except Exception:
        speaker.say_priority("Say again?")
```

- [ ] **Step 4: Poll the button in the tick loop** (right after the Stage B engineer block from Task 8)

```python
            if engineer_active and ptt_poll is not None:
                event = ptt_button.feed(ptt_poll())
                if event == "press":
                    speaker.cancel_pending()  # driver keyed the radio
                    mic.start()
                elif event == "release":
                    audio = mic.stop()
                    if stt_ready.is_set() and race_state is not None:
                        threading.Thread(
                            target=_ptt_worker,
                            args=(audio, stt_model, race_state.snapshot(),
                                  ptt_ask, speaker, emit, session_log,
                                  engineer_calls._budget),
                            daemon=True,
                        ).start()
                    else:
                        speaker.say_priority(
                            "Radio's still warming up — give me a second."
                        )
```

Also reference the budget cleanly: add a public alias in `EngineerCalls` (Task 6 file) rather than reaching into `_budget` — add to `EngineerCalls.__init__`:

```python
        self.budget = budget          # public: PTT answers note spacing here
        self._budget = budget
```

and use `engineer_calls.budget` in the thread args above.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all PASS (the wiring adds no test-visible behavior; imports must not break collection — `core.engineer.stt` and friends import clean without the rig group because heavy imports are deferred inside functions).

- [ ] **Step 6: Verify import-cleanliness without rig deps explicitly**

Run: `.venv/Scripts/python.exe -c "import core.engineer.stt, core.engineer.mic, core.engineer.ptt_input, core.engineer.answers, core.live.voice_engine; print('imports clean')"`
Expected: `imports clean` (only numpy at module level; kokoro/faster-whisper/sounddevice/pygame/anthropic all deferred).

- [ ] **Step 7: Commit**

```bash
git add scripts/live_coach.py core/engineer/calls.py
git commit -m 'feat(engineer): stage C wiring -- PTT button, mic, STT worker, priority answers'
```

### Task 14: Docs, status, finish

**Files:**
- Modify: `CLAUDE.md`, `README.md` (RUN section note)

- [ ] **Step 1: Add the CLAUDE.md status section** (after "Week Plan v1", following the house format)

```markdown
**PTT Live Engineer + Natural Voice** (complete, branch ptt-engineer — spec docs/superpowers/specs/2026-07-18-ptt-engineer-design.md, plan docs/superpowers/plans/2026-07-18-ptt-engineer.md)
- [x] Stage A voice: Kokoro-82M engine factory (core/live/voice_engine.py, CPU, sounddevice playback; compat-verified on Python 3.14 — Piper fallback never needed) behind the existing Speaker engine seam; create_speaker is neural-first, SAPI on any failure; Speaker grew a priority slot (say_priority beats cues, cancel_pending on PTT press, in-progress never interrupted) + RadioBudget global spacing (20s floor, PTT exempt but spacing-noted)
- [x] Stage B: core/engineer/ package — RaceState (PURE CarIdx tick machine, lap-boundary gap histories, snapshot() grounds both answer paths; CarIdx arrays bypass the scalar churn guard by design), EngineerCalls (threat/attack/closing-laps, episode re-arm, exact-string pinned), CornerLossTracker (per-corner gap attribution, once per target, self-gates on data quality)
- [x] Stage C: PTT loop — pygame wheel button (--ptt-button, probe script) → sounddevice capture (10s cap) → faster-whisper base.en int8 (background-loaded at connect) → intents fast path / Haiku with radio tone contract (4s timeout) / "Can't reach the pit wall — stand by." → say_priority
- [x] Engineer default ON in Race sessions only (--no-engineer to disable); Toolbox coupling-tested; every call/transcript/answer JSONL-logged with snapshot for threshold tuning
- [x] Deps in the `rig` dependency group (kokoro pulls torch+spacy — friend `uv sync` stays lean); plain `uv sync` on the rig strips the group → coach degrades to SAPI with a visible line (re-run `uv sync --group rig`)
- [ ] Driving validation: voice quality (VOICE constant in voice_engine.py), call thresholds (THREAT_GAP_S/TREND_LAPS/REARM_GAP_S in calls.py, DOMINANCE in corner_loss.py), PTT latency + STT accuracy with wheel-mic; find the real button index via scripts/probe_ptt_button.py
- Deferred (spec §9): fuel/pit-window call, model escalation, barge-in, wake-word
```

- [ ] **Step 2: README note** — in the live-coach run section, add:

```markdown
Neural voice + PTT need the rig extras: `uv sync --group rig` (first run
downloads the Kokoro and Whisper models). Plain `uv sync` removes them —
the coach then falls back to the SAPI voice and prints why. Find your
wheel's PTT button index with `scripts/probe_ptt_button.py`, then pass
`--ptt-button N` (default 5).
```

- [ ] **Step 3: Full suite, final check**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all green (1090 baseline + ~40 new).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m 'docs: PTT engineer + natural voice status and run notes'
```

- [ ] **Step 5: Finish the branch**

Use the finishing-a-development-branch skill: merge `ptt-engineer` to master, push, restart the rig (tray: Stop everything → Open) so the watcher and any running coach pick up the new code. Remind the founder: the coach itself stays a deliberate Toolbox/tray toggle (the 2026-07-14 rule — never auto-start it).

---

## Founder validation (not agent-executable)

1. **Stage A:** start the coach in practice; the radio check speaks in the Kokoro voice. If it's SAPI, the startup line says why.
2. **Button:** run `scripts/probe_ptt_button.py`, press the chosen Simagic button, restart the coach with `--ptt-button N` (and set the default in `build_parser` to the real index once known).
3. **Stage B:** next official race — expect at most a handful of engineer calls; log lines `engineer_call` carry snapshots for threshold tuning.
4. **Stage C:** mid-race "what's the gap" answers fast-path in ≤2s; an open question gets a Haiku answer in ≤4s; pull the ethernet cable in practice and confirm the offline line.
```
