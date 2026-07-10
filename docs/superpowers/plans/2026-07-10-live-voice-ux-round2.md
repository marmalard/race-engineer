# Live Voice Coach UX — Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a startup radio check, a spoken acknowledgment when a lap is discarded, and enrich the approach-corner cue (combined, name-dropped, coarse car-length magnitude, on by default) to the live voice coach.

**Architecture:** All coaching text stays in `core/live/nudges.py` (pure functions). The lap-boundary state machine `core/live/session_reader.py` gains a `TickResult` return so it can report *why* a lap was discarded. `core/live/prompt_scheduler.py`'s `build_schedule` switches its prompt text to the new combined cue. `scripts/live_coach.py` wires the new speech; no analysis-engine changes.

**Tech Stack:** Python 3.11+, pytest, dataclasses/enums, pyttsx3 (SAPI, already wired). Run tests with `.venv/Scripts/python.exe -m pytest`.

---

## Spec

See `docs/superpowers/specs/2026-07-09-live-voice-ux-round2-design.md`.

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `core/live/nudges.py` | Coaching text from diagnoses/enums | + `format_radio_check`, `format_discard_speech`, `approach_cue_from_diagnosis` + coarse-magnitude constants; − dead `Nudge.prompt` field |
| `core/live/session_reader.py` | Lap-boundary state machine | `feed()` → `TickResult(completed, discarded)`; `DiscardReason` enum; RESET/PIT flagging |
| `core/live/prompt_scheduler.py` | Distance-triggered prompts | `build_schedule` uses `approach_cue_from_diagnosis` for prompt text |
| `scripts/live_coach.py` | pyirsdk driver / wiring | radio check always speaks; `TickResult` + discard speech; normalizer-invalid speaks; `--no-corner-prompts` (default on) |
| `tests/test_nudges.py` | | new-function tests; drop `Nudge.prompt` assertions |
| `tests/test_session_reader.py` | | assertions → `TickResult`; discard cases |
| `tests/test_prompt_scheduler.py` | | cue-text assertion update |

**Dependency note:** `nudges.py` will import `DiscardReason` from `session_reader.py`. `session_reader.py` does not import `nudges.py`, so there is no cycle.

---

## Task 1: Approach-corner cue (`approach_cue_from_diagnosis`)

**Files:**
- Modify: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_nudges.py` (the `_diag` helper already exists in this file):

```python
def test_approach_cue_single_fault_no_corner_name():
    from core.live.nudges import approach_cue_from_diagnosis
    cue = approach_cue_from_diagnosis(_diag(label="La Source", braking=-15.0, min_speed=-0.2))
    assert cue == "Coming up — brake a couple car lengths later."
    assert "La Source" not in cue


def test_approach_cue_combines_top_two_faults():
    from core.live.nudges import approach_cue_from_diagnosis
    cue = approach_cue_from_diagnosis(
        _diag(braking=-15.0, throttle=30.0, min_speed=-0.2)
    )
    assert cue == (
        "Coming up — brake a couple car lengths later, "
        "get to throttle earlier on exit."
    )


def test_approach_cue_caps_at_two_faults():
    from core.live.nudges import approach_cue_from_diagnosis
    # apex + braking + throttle all fire; only the top two (apex, braking) speak
    cue = approach_cue_from_diagnosis(_diag(
        min_speed=-4.0, drv_min=16.0, ref_min=20.0,
        braking=-15.0, throttle=30.0,
    ))
    assert cue == "Coming up — carry more apex speed, brake a couple car lengths later."
    assert "throttle" not in cue


def test_approach_cue_coarse_buckets():
    from core.live.nudges import approach_cue_from_diagnosis
    assert approach_cue_from_diagnosis(_diag(braking=-9.0, min_speed=-0.2)) == \
        "Coming up — brake a bit later."
    assert approach_cue_from_diagnosis(_diag(braking=-30.0, min_speed=-0.2)) == \
        "Coming up — brake a lot later."


def test_approach_cue_below_threshold_returns_none():
    from core.live.nudges import approach_cue_from_diagnosis
    assert approach_cue_from_diagnosis(
        _diag(braking=-2.0, min_speed=-0.5, throttle=3.0)
    ) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -k approach_cue -v`
Expected: FAIL with `ImportError: cannot import name 'approach_cue_from_diagnosis'`

- [ ] **Step 3: Write the implementation**

Add to `core/live/nudges.py`, after the existing threshold constants (below `CAR_LENGTH_M`):

```python
# Approach-cue magnitude buckets (car lengths) — coarse on purpose; a driver
# can't act on fake-exact meters at speed. Tunable from data/live_sessions logs.
APPROACH_CUE_MAX_FAULTS = 2
COARSE_A_BIT_MAX_LENGTHS = 2.5
COARSE_COUPLE_MAX_LENGTHS = 5.0
```

Add these functions after `nudge_from_diagnosis`:

```python
def _coarse_length_phrase(meters: float) -> str:
    """Coarse braking magnitude in car lengths: 'a bit' / 'a couple car
    lengths' / 'a lot'. No fake precision — the driver adjusts a marker."""
    lengths = abs(meters) / CAR_LENGTH_M
    if lengths < COARSE_A_BIT_MAX_LENGTHS:
        return "a bit"
    if lengths < COARSE_COUPLE_MAX_LENGTHS:
        return "a couple car lengths"
    return "a lot"


def approach_cue_from_diagnosis(diag: RegionDiagnosis) -> "str | None":
    """One combined approach cue for a corner, or None if nothing crosses
    threshold. Spoken ~300m before the corner, so it names no corner ('here')
    and joins the top APPROACH_CUE_MAX_FAULTS faults by the salience ladder:
    lift > braking > release > exit > throttle."""
    faults: list[str] = []

    if diag.min_speed_delta_ms <= -MIN_SPEED_THRESHOLD_MS:
        if diag.reference_min_speed_ms >= FLAT_CORNER_MIN_SPEED_MS:
            faults.append("carry it flat, don't lift")
        else:
            faults.append("carry more apex speed")

    if diag.braking_delta_m is not None and abs(diag.braking_delta_m) >= BRAKING_THRESHOLD_M:
        coarse = _coarse_length_phrase(diag.braking_delta_m)
        faults.append(
            f"brake {coarse} later" if diag.braking_delta_m < 0
            else f"brake {coarse} earlier"
        )

    if (
        diag.brake_release_delta_m is not None
        and diag.brake_release_delta_m <= -RELEASE_THRESHOLD_M
    ):
        faults.append("carry the brakes deeper")

    if diag.exit_speed_delta_ms <= -EXIT_SPEED_THRESHOLD_MS:
        faults.append("prioritize the exit")

    if diag.throttle_delta_m is not None and diag.throttle_delta_m >= THROTTLE_THRESHOLD_M:
        faults.append("get to throttle earlier on exit")

    if not faults:
        return None
    return "Coming up — " + ", ".join(faults[:APPROACH_CUE_MAX_FAULTS]) + "."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -k approach_cue -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/live/nudges.py tests/test_nudges.py
git commit -m "feat(nudges): combined name-dropped approach cue with coarse magnitude"
```

---

## Task 2: Radio check (`format_radio_check`)

**Files:**
- Modify: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_nudges.py`:

```python
def test_radio_check_with_reference_speaks_time():
    from types import SimpleNamespace
    from core.live.nudges import format_radio_check
    line = format_radio_check(SimpleNamespace(lap_time=127.744))
    assert line == (
        "Radio check, reading you. Reference lap 2 07.7, loaded. "
        "Coaching from lap one."
    )


def test_radio_check_without_reference():
    from core.live.nudges import format_radio_check
    line = format_radio_check(None)
    assert line == (
        "Radio check, reading you. No reference for this combo — "
        "I'll set a baseline from your first lap."
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -k radio_check -v`
Expected: FAIL with `ImportError: cannot import name 'format_radio_check'`

- [ ] **Step 3: Write the implementation**

Add to `core/live/nudges.py`. Add a typing import at the top (under the existing imports):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.benchmark.reference_store import ReferenceLapMeta
```

Then add the function (near `format_lap_speech`):

```python
def format_radio_check(reference: "ReferenceLapMeta | None") -> str:
    """Spoken on sim connect — always, so the audio path is confirmed even
    when no reference exists (that was the silent case). Duck-typed: any
    object with a `.lap_time` float works."""
    if reference is None:
        return (
            "Radio check, reading you. No reference for this combo — "
            "I'll set a baseline from your first lap."
        )
    return (
        "Radio check, reading you. Reference lap "
        f"{_speech_lap_time(reference.lap_time)}, loaded. Coaching from lap one."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -k radio_check -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add core/live/nudges.py tests/test_nudges.py
git commit -m "feat(nudges): startup radio check (fires with or without reference)"
```

---

## Task 3: Discard speech (`format_discard_speech`) + `DiscardReason`

This task adds `DiscardReason` to `session_reader.py` (used by both `nudges.py` here and the tracker in Task 4) and the speech helper.

**Files:**
- Modify: `core/live/session_reader.py` (add enum only)
- Modify: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

- [ ] **Step 1: Add the `DiscardReason` enum**

At the top of `core/live/session_reader.py`, add `from enum import Enum` to the imports, and add this class above `CompletedLap`:

```python
class DiscardReason(str, Enum):
    """Why a lap the driver was working on was thrown away."""

    RESET = "reset"   # backward Lap jump: reset / tow
    PIT = "pit"       # a pit-touched lap that closed
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_nudges.py`:

```python
def test_discard_speech_reset():
    from core.live.nudges import format_discard_speech
    from core.live.session_reader import DiscardReason
    assert format_discard_speech(DiscardReason.RESET) == "Reset — scratch that lap."


def test_discard_speech_pit():
    from core.live.nudges import format_discard_speech
    from core.live.session_reader import DiscardReason
    assert format_discard_speech(DiscardReason.PIT) == "In the pits — that lap won't count."
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -k discard_speech -v`
Expected: FAIL with `ImportError: cannot import name 'format_discard_speech'`

- [ ] **Step 4: Write the implementation**

Add to `core/live/nudges.py`. Add the import near the top:

```python
from core.live.session_reader import DiscardReason
```

Add the function:

```python
def format_discard_speech(reason: DiscardReason) -> str:
    """Brief spoken acknowledgment that a lap was thrown away, so silence is
    never ambiguous."""
    if reason is DiscardReason.PIT:
        return "In the pits — that lap won't count."
    return "Reset — scratch that lap."
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -k discard_speech -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add core/live/session_reader.py core/live/nudges.py tests/test_nudges.py
git commit -m "feat(nudges): DiscardReason enum + discard acknowledgment speech"
```

---

## Task 4: `TickResult` return + RESET/PIT flagging

**Files:**
- Modify: `core/live/session_reader.py`
- Test: `tests/test_session_reader.py`

- [ ] **Step 1: Rewrite the tracker to return `TickResult`**

Replace the body of `core/live/session_reader.py` from the `CompletedLap` dataclass to the end of the file with (keep the module docstring, imports, and the `DiscardReason` enum added in Task 3):

```python
@dataclass
class CompletedLap:
    """A lap that crossed the start/finish line and passed coarse gating."""

    lap_number: int
    dataframe: pd.DataFrame


@dataclass
class TickResult:
    """The outcome of one fed tick: a completed lap, a discard reason, or
    neither (still buffering). At most one of the two is ever set."""

    completed: CompletedLap | None = None
    discarded: DiscardReason | None = None


class LapBoundaryTracker:
    """Accumulates ticks and emits a TickResult on each fed tick."""

    def __init__(self, min_lap_samples: int = 100) -> None:
        self.min_lap_samples = min_lap_samples
        self._buffer = LapBuffer()
        self._current_lap: int | None = None
        self._touched_pit = False

    def feed(self, sample: dict) -> TickResult:
        """Process one tick. Returns a TickResult describing whether this tick
        closed a valid lap, discarded an in-progress lap, or neither."""
        lap = int(sample["Lap"])

        # First tick of the session: start tracking, no boundary yet.
        if self._current_lap is None:
            self._start_lap(lap, sample)
            return TickResult()

        # Lap unchanged: keep buffering this lap.
        if lap == self._current_lap:
            if sample.get("OnPitRoad"):
                self._touched_pit = True
            self._buffer.add(sample)
            return TickResult()

        # Lap went backward (reset / tow): discard and restart cleanly. Only
        # announce it if a real attempt was in the buffer — garage/pit-box
        # resets with tiny buffers stay silent.
        if lap < self._current_lap:
            was_real = (
                self._current_lap >= 1
                and len(self._buffer) >= self.min_lap_samples
            )
            self._start_lap(lap, sample)
            return TickResult(
                discarded=DiscardReason.RESET if was_real else None
            )

        # Lap incremented: the buffered lap is complete. Decide whether to
        # emit it, then start the new lap with this tick.
        completed = self._close_current_lap()
        discarded = None
        if (
            completed is None
            and self._touched_pit
            and self._current_lap is not None
            and self._current_lap >= 1
            and len(self._buffer) >= self.min_lap_samples
        ):
            discarded = DiscardReason.PIT
        self._start_lap(lap, sample)
        return TickResult(completed=completed, discarded=discarded)

    def _start_lap(self, lap: int, first_sample: dict) -> None:
        self._buffer.clear()
        self._current_lap = lap
        self._touched_pit = bool(first_sample.get("OnPitRoad"))
        self._buffer.add(first_sample)

    def _close_current_lap(self) -> CompletedLap | None:
        if self._current_lap is None or self._current_lap < 1:
            return None
        if self._touched_pit:
            return None
        if len(self._buffer) < self.min_lap_samples:
            return None
        return CompletedLap(
            lap_number=self._current_lap,
            dataframe=self._buffer.to_dataframe(),
        )
```

- [ ] **Step 2: Update the existing tests + add discard cases**

Replace the whole body of `tests/test_session_reader.py` below the module docstring with:

```python
from core.live.session_reader import (
    CompletedLap,
    DiscardReason,
    LapBoundaryTracker,
)


def _tick(lap: int, lapdist: float, session_time: float,
          on_pit: bool = False, surface: int = 3) -> dict:
    return {
        "Lap": lap,
        "LapDist": lapdist,
        "Speed": 50.0,
        "Throttle": 1.0,
        "Brake": 0.0,
        "SteeringWheelAngle": 0.0,
        "RPM": 6000.0,
        "Gear": 4,
        "Lat": 50.0,
        "Lon": 5.0,
        "SessionTime": session_time,
        "LapCurrentLapTime": session_time,
        "OnPitRoad": on_pit,
        "PlayerTrackSurface": surface,
    }


def _drive_lap(tracker, lap_num, n=300, t0=0.0, on_pit=False):
    """Feed n ticks of one lap; return the list of TickResults."""
    results = []
    for i in range(n):
        out = tracker.feed(
            _tick(lap_num, float(i), t0 + i * 0.02, on_pit=on_pit)
        )
        results.append(out)
    return results


def test_no_emission_during_a_lap():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    results = _drive_lap(tracker, lap_num=1)
    assert all(r.completed is None for r in results)


def test_lap_completes_on_increment():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=1, n=300, t0=0.0)
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert isinstance(out.completed, CompletedLap)
    assert out.completed.lap_number == 1
    assert len(out.completed.dataframe) == 300
    assert out.discarded is None


def test_out_lap_then_flying_lap():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i < 50)))
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert out.completed is None  # lap 1 touched pit road → suppressed
    assert out.discarded is DiscardReason.PIT


def test_clean_flying_lap_after_pit_lap_emits():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i < 50)))
    tracker.feed(_tick(2, 0.0, 6.0))  # closes lap 1 (pit, suppressed)
    for i in range(1, 300):
        tracker.feed(_tick(2, float(i), 6.0 + i * 0.02))
    out = tracker.feed(_tick(3, 0.0, 12.0))  # closes lap 2
    assert isinstance(out.completed, CompletedLap)
    assert out.completed.lap_number == 2


def test_in_lap_to_pit_suppressed():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i > 250)))
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert out.completed is None
    assert out.discarded is DiscardReason.PIT


def test_reset_lap_backward_discards_buffer():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=5, n=150, t0=0.0)
    # Sim reset: Lap jumps backward to 1. Real attempt was buffered → RESET.
    out = tracker.feed(_tick(1, 0.0, 0.0))
    assert out.completed is None
    assert out.discarded is DiscardReason.RESET
    # And the new lap accumulates cleanly afterward
    for i in range(1, 300):
        tracker.feed(_tick(1, float(i), i * 0.02))
    closed = tracker.feed(_tick(2, 0.0, 6.0))
    assert isinstance(closed.completed, CompletedLap)
    assert closed.completed.lap_number == 1


def test_reset_with_tiny_buffer_is_silent():
    """A backward jump with only a few buffered ticks (garage/pit-box reset)
    must not announce a discard."""
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(10):
        tracker.feed(_tick(3, float(i), i * 0.02))
    out = tracker.feed(_tick(1, 0.0, 0.0))
    assert out.completed is None
    assert out.discarded is None


def test_too_short_lap_suppressed():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(40):
        tracker.feed(_tick(1, float(i), i * 0.02))
    out = tracker.feed(_tick(2, 0.0, 1.0))
    assert out.completed is None
    assert out.discarded is None  # too-short is not announced


def test_lap_zero_is_not_emitted():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    for i in range(300):
        tracker.feed(_tick(0, float(i), i * 0.02))
    out = tracker.feed(_tick(1, 0.0, 6.0))
    assert out.completed is None
    for i in range(1, 300):
        tracker.feed(_tick(1, float(i), 6.0 + i * 0.02))
    closed = tracker.feed(_tick(2, 0.0, 12.0))
    assert isinstance(closed.completed, CompletedLap)
    assert closed.completed.lap_number == 1


def test_emitted_dataframe_is_normalizer_shaped():
    from core.live.lap_buffer import SAMPLE_CHANNELS
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=1, n=300)
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert list(out.completed.dataframe.columns) == SAMPLE_CHANNELS
```

- [ ] **Step 3: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_reader.py -v`
Expected: PASS (11 tests). `test_reset_with_tiny_buffer_is_silent` is new.

- [ ] **Step 4: Commit**

```bash
git add core/live/session_reader.py tests/test_session_reader.py
git commit -m "feat(session-reader): TickResult return with RESET/PIT discard reasons"
```

---

## Task 5: `build_schedule` uses the combined cue

**Files:**
- Modify: `core/live/prompt_scheduler.py`
- Test: `tests/test_prompt_scheduler.py`

- [ ] **Step 1: Update the failing test**

In `tests/test_prompt_scheduler.py`, replace `test_trigger_placed_lead_before_brake_onset` with:

```python
def test_trigger_placed_lead_before_brake_onset():
    schedule = build_schedule([_diag(onset=800.0)], [], TRACK_LEN)
    assert len(schedule) == 1
    assert schedule[0].trigger_m == 500.0
    assert schedule[0].text.startswith("Coming up — brake")
    assert "La Source" not in schedule[0].text  # name dropped in approach cue
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_scheduler.py::test_trigger_placed_lead_before_brake_onset -v`
Expected: FAIL — current text is `"La Source — brake later."`, not `"Coming up — ..."`

- [ ] **Step 3: Switch the prompt text source**

In `core/live/prompt_scheduler.py`:

Change the import line
```python
from core.live.nudges import nudge_from_diagnosis
```
to
```python
from core.live.nudges import approach_cue_from_diagnosis
```

In `build_schedule`, replace this block
```python
        nudge = nudge_from_diagnosis(diag)
        if nudge is None:
            continue
```
with
```python
        cue = approach_cue_from_diagnosis(diag)
        if cue is None:
            continue
```
and change the append line
```python
        prompts.append(ScheduledPrompt(trigger_m=trigger, text=nudge.prompt))
```
to
```python
        prompts.append(ScheduledPrompt(trigger_m=trigger, text=cue))
```

- [ ] **Step 4: Run the full prompt-scheduler suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_scheduler.py -v`
Expected: PASS (all tests — the clamp/threshold/max tests use only trigger math and still hold)

- [ ] **Step 5: Commit**

```bash
git add core/live/prompt_scheduler.py tests/test_prompt_scheduler.py
git commit -m "feat(prompt-scheduler): approach prompts use the combined cue text"
```

---

## Task 6: Remove the now-dead `Nudge.prompt` field

`build_schedule` was the only consumer of `Nudge.prompt`; after Task 5 it is dead.

**Files:**
- Modify: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

- [ ] **Step 1: Confirm nothing else reads `.prompt`**

Run: `git grep -n "\.prompt" -- core scripts app`
Expected: only `core/live/prompt_scheduler.py` matches are gone (Task 5); no remaining reads of `Nudge.prompt`. (`ScheduledPrompt`/`PromptScheduler` are unrelated names — ignore.)

- [ ] **Step 2: Update the tests**

In `tests/test_nudges.py`:

Delete `test_prompt_is_terse_imperative_with_corner` entirely.

In `test_every_rung_has_speech_and_prompt`, remove the prompt assertions so it reads:

```python
def test_every_rung_has_speech():
    rungs = [
        _diag(min_speed=-4.0, drv_min=55.0, ref_min=59.0),  # flat lift
        _diag(min_speed=-4.0, drv_min=16.0, ref_min=20.0),  # apex speed
        _diag(braking=-15.0, min_speed=-0.5),               # brake later
        _diag(braking=14.0, min_speed=-0.5),                # brake earlier
        _diag(release=-15.0, min_speed=-0.5),               # trail
        _diag(exit_speed=-3.0, min_speed=-0.5),             # exit
        _diag(throttle=30.0, min_speed=-0.5),               # throttle
    ]
    for d in rungs:
        n = nudge_from_diagnosis(d)
        assert n is not None
        assert n.speech
        assert n.corner in n.speech
```

- [ ] **Step 3: Remove the field**

In `core/live/nudges.py`, in the `Nudge` dataclass remove the line:
```python
    prompt: str  # terse in-corner imperative (includes corner name)
```
Then remove the `prompt=...` keyword argument from every `Nudge(...)` construction in `nudge_from_diagnosis` (there are six: flat lift, apex speed, brake later, brake earlier, brake release, exit, throttle — remove each `prompt=f"..."` line).

- [ ] **Step 4: Run the nudge suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -v`
Expected: PASS (all — `test_prompt_is_terse_imperative_with_corner` gone, `test_every_rung_has_speech` renamed)

- [ ] **Step 5: Commit**

```bash
git add core/live/nudges.py tests/test_nudges.py
git commit -m "refactor(nudges): drop dead Nudge.prompt field (replaced by approach cue)"
```

---

## Task 7: Wire the three features into `live_coach.py`

No unit test (this file only drives pyirsdk); verified by running the coach in Task 8's manual check. Keep edits minimal and mechanical.

**Files:**
- Modify: `scripts/live_coach.py`

- [ ] **Step 1: Import the new helpers**

In the `from core.live.nudges import (...)` block, add `approach_cue_from_diagnosis` is NOT needed here (only the scheduler uses it). Add `format_discard_speech` and `format_radio_check`:

```python
from core.live.nudges import (  # noqa: E402
    _speech_lap_time,
    format_discard_speech,
    format_lap_block,
    format_lap_speech,
    format_radio_check,
)
```

- [ ] **Step 2: Flip the corner-prompts flag to default-on**

In `_parse_args`, replace the `--corner-prompts` argument with:

```python
    parser.add_argument("--no-corner-prompts", dest="corner_prompts",
                        action="store_false",
                        help="disable approach cues before flagged corners "
                             "(on by default)")
    parser.set_defaults(corner_prompts=True)
```

Leave every `if args.corner_prompts:` block as-is — they now run by default.

- [ ] **Step 3: Always speak the radio check on connect**

Replace this block (the reference-announcement block near the end of `if not meta_loaded:`)
```python
                if ref is not None:
                    emit(
                        f"Reference loaded: {ref.meta.source}, "
                        f"{ref.meta.lap_time:.3f}s"
                        + (f" ({ref.meta.driver_name})"
                           if ref.meta.driver_name else "")
                    )
                    speaker.say(
                        f"Reference lap loaded, "
                        f"{_speech_lap_time(ref.meta.lap_time)}. "
                        "Coaching from lap one."
                    )
                    print(f"Connected: {track_display}.")
                else:
                    print(f"Connected: {track_display}. "
                          "Drive a lap to set baseline.")
```
with
```python
                if ref is not None:
                    emit(
                        f"Reference loaded: {ref.meta.source}, "
                        f"{ref.meta.lap_time:.3f}s"
                        + (f" ({ref.meta.driver_name})"
                           if ref.meta.driver_name else "")
                    )
                    print(f"Connected: {track_display}.")
                else:
                    print(f"Connected: {track_display}. "
                          "Drive a lap to set baseline.")
                speaker.say(
                    format_radio_check(ref.meta if ref is not None else None)
                )
```

- [ ] **Step 4: Handle the discard reason from the tracker**

Replace
```python
            completed = tracker.feed(sample)
```
with
```python
            result = tracker.feed(sample)
            completed = result.completed
            if result.discarded is not None:
                discard_speech = format_discard_speech(result.discarded)
                speaker.say(discard_speech)
                if session_log is not None:
                    session_log.log(
                        "discard", reason=result.discarded.value,
                        speech=discard_speech,
                    )
```

- [ ] **Step 5: Speak when a completed lap fails normalizer validity**

The `if nlap.is_valid:` block currently has no `else`. Add one so an off-track / incomplete lap is not silent. After the entire `if nlap.is_valid:` body, add:

```python
                else:
                    invalid_speech = "That lap won't count — data's incomplete."
                    speaker.say(invalid_speech)
                    if session_log is not None:
                        session_log.log(
                            "invalid", lap=nlap.lap_number,
                            speech=invalid_speech,
                        )
```

(Indentation: the `else` aligns with `if nlap.is_valid:`, inside `if completed is not None:`.)

- [ ] **Step 6: Verify it imports and parses args**

Run: `.venv/Scripts/python.exe -c "import ast; ast.parse(open('scripts/live_coach.py').read()); print('ok')"`
Expected: `ok`

Run: `.venv/Scripts/python.exe scripts/live_coach.py --help`
Expected: help text shows `--no-corner-prompts` and `--mute`, no `--corner-prompts`.

- [ ] **Step 7: Commit**

```bash
git add scripts/live_coach.py
git commit -m "feat(live-coach): radio check, discard/invalid speech, cues on by default"
```

---

## Task 8: Full suite + manual verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (previously 473 passed / 9 skipped; this adds ~11 tests net and removes 1). No failures.

- [ ] **Step 2: Manual live check (with iRacing on track)**

Restart the live coach: `.venv/Scripts/python.exe scripts/live_coach.py`
Confirm, in one session:
- On connect: a spoken radio check fires (drive a no-reference combo too, to hear the no-ref variant).
- Deliberately reset/tow mid-lap → "Reset — scratch that lap."; drive into the pits → "In the pits — that lap won't count."; run wide off-track for an incomplete lap → "That lap won't count — data's incomplete."
- Approach cues fire ~300m before flagged corners with combined phrasing ("Coming up — brake a couple car lengths later, get to throttle earlier on exit"), no corner name.

- [ ] **Step 3: Tune if needed**

If the magnitude buckets feel off from `data/live_sessions/*.jsonl`, adjust `COARSE_A_BIT_MAX_LENGTHS` / `COARSE_COUPLE_MAX_LENGTHS` in `core/live/nudges.py` and re-run `pytest tests/test_nudges.py -k approach_cue` (update expected strings if boundaries move).

- [ ] **Step 4: Finalize the branch**

Use the finishing-a-development-branch skill to merge `live-voice-ux-round2` to master (or open a PR). Update the Atlas manifest next_actions: mark the three voice-UX items done, and note the deferred track-limits asterisk spec.

---

## Self-Review

- **Spec coverage:** Feature A → Task 2 + Task 7 Step 3. Feature B → Task 3 (speech) + Task 4 (tracker) + Task 7 Steps 4–5 (wiring incl. normalizer-invalid). Feature D → Task 1 (cue) + Task 5 (schedule) + Task 7 Step 2 (default on). Non-goal hard line (discard ≠ track-limits) preserved: the normalizer-invalid line fires only on `nlap.is_valid == False` (distance jump / <90% coverage), never on a clean lap.
- **Type consistency:** `TickResult(completed, discarded)`, `DiscardReason.RESET/PIT`, `approach_cue_from_diagnosis(diag) -> str | None`, `format_radio_check(meta|None) -> str`, `format_discard_speech(DiscardReason) -> str` — names used identically across tasks. `build_schedule` uses `cue` (str) directly, matching `ScheduledPrompt.text: str`.
- **No placeholders:** every code step shows complete content.
