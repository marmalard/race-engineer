# Live Voice Coaching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spoken between-lap coaching plus approach-triggered in-corner prompts for the live coach, grounded in stored reference laps and two new diagnosis metrics (trail braking, exit speed).

**Architecture:** The diagnosis engine (`core/coaching/debrief.py`) gains brake-release and exit-speed deltas; the nudge layer (`core/live/nudges.py`) grows a five-rung salience ladder and speech/prompt phrasings; a `Speaker` thread wraps Windows SAPI; a pure `PromptScheduler` fires prompts by distance on the following lap; `scripts/live_coach.py` wires it together and loads a stored reference lap (Garage 61) from `ReferenceStore` at connect.

**Tech Stack:** Python 3.14, numpy, pyttsx3 (new — Windows SAPI TTS), pytest. No AI or network on the critical path.

**Spec:** `docs/superpowers/specs/2026-07-06-live-voice-coaching-design.md`

**Run tests with:** `.venv/Scripts/python.exe -m pytest <file> -q` (uv is not on PATH on this machine).

**Conventions that MUST hold across tasks:**
- Sign conventions: `braking_delta_m` / `brake_release_delta_m` negative = driver does it *earlier* than reference; `exit_speed_delta_ms` / `min_speed_delta_ms` negative = driver *slower*; `throttle_delta_m` positive = driver on power *later*.
- `RegionDiagnosis` new fields all have defaults so existing constructions don't break.
- Car identity string is `DriverInfo.Drivers[DriverCarIdx].CarScreenName` — the exact same field `IBTParser` stores (see `core/telemetry/ibt_parser.py:319`) and the coaching page saves references under. Do not derive it any other way.

---

### Task 0: Branch

- [ ] **Step 1: Create the feature branch**

```bash
git checkout -b live-voice-coaching
```

---

### Task 1: Diagnosis engine — brake release, exit speed, reference brake onset

**Files:**
- Modify: `core/coaching/debrief.py`
- Test: `tests/test_debrief.py`

`RegionDiagnosis` gains three fields: `brake_release_delta_m` (trail-braking proxy, guarded so it is only computed where the *reference* trail-brakes), `exit_speed_delta_ms` (speed delta at region end), and `reference_brake_onset_m` (absolute distance of the reference's brake onset — the prompt scheduler's trigger anchor in Task 5).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_debrief.py`:

```python
def _early_release_driver(n: int = 2000) -> NormalizedLap:
    """Brakes at the reference point but releases the brakes ~30m earlier."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 40.0 * np.exp(-((x - 500.0) ** 2) / (2 * 52.0**2))  # slower than ref
    brake = np.where((x > 380) & (x < 450), 0.8, 0.0)  # releases at 450 not 480
    throttle = np.where((x > 380) & (x < 560), 0.0, 1.0)
    return _lap(speed, brake, throttle)


def _straightline_brake_reference(n: int = 2000) -> NormalizedLap:
    """Reference that does NOT trail-brake: brakes done 60m before the apex."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 35.0 * np.exp(-((x - 500.0) ** 2) / (2 * 50.0**2))
    brake = np.where((x > 380) & (x < 440), 0.8, 0.0)  # release 60m before apex
    throttle = np.where((x > 380) & (x < 560), 0.0, 1.0)
    return _lap(speed, brake, throttle)


def _slow_exit_driver(n: int = 2000) -> NormalizedLap:
    """Matches the reference into the corner but recovers speed slowly on exit."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 35.0 * np.exp(-((x - 500.0) ** 2) / (2 * 50.0**2))
    speed = speed - np.where(x >= 500.0, 4.0 * np.exp(-(x - 500.0) / 300.0), 0.0)
    brake = np.where((x > 380) & (x < 480), 0.8, 0.0)
    throttle = np.where((x > 380) & (x < 600), 0.0, 1.0)
    return _lap(speed, brake, throttle)


def test_release_delta_when_driver_releases_early():
    """Driver gives up the brakes ~30m before the reference -> negative delta."""
    result = build_debrief(_early_release_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    assert top.brake_release_delta_m is not None
    assert top.brake_release_delta_m == pytest.approx(-30.0, abs=12.0)


def test_release_delta_none_when_reference_does_not_trail():
    """Reference brakes in a straight line -> trail coaching is meaningless
    here, so the release delta must be None (the trail guard)."""
    result = build_debrief(
        _early_release_driver(), _straightline_brake_reference(), CORNERS
    )
    top = result.diagnoses[0]
    assert top.brake_release_delta_m is None


def test_exit_speed_delta_negative_when_slower_on_exit():
    result = build_debrief(_slow_exit_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    assert top.exit_speed_delta_ms < -1.0


def test_reference_brake_onset_recorded():
    """The reference's brake-onset distance is exposed for the prompt
    scheduler's trigger anchor."""
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    assert top.reference_brake_onset_m == pytest.approx(380.0, abs=15.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_debrief.py -q`
Expected: 4 new tests FAIL (`RegionDiagnosis` has no attribute `brake_release_delta_m` / unexpected keyword), existing 7 PASS.

- [ ] **Step 3: Implement in `core/coaching/debrief.py`**

Add a constant next to the existing ones (after `BRAKE_SEARCH_BACK_M = 200.0`):

```python
# Reference must carry brake to within this distance of its apex for a
# trail-braking (release) delta to be meaningful at this corner.
TRAIL_GUARD_M = 30.0
```

Add three fields to `RegionDiagnosis` (after `reference_min_speed_ms`; defaults keep existing constructions valid):

```python
    brake_release_delta_m: float | None = None  # negative = driver releases earlier
    exit_speed_delta_ms: float = 0.0  # negative = driver slower at region end
    reference_brake_onset_m: float | None = None  # absolute distance, for prompts
```

Add a helper next to `_onset`:

```python
def _release(
    mask: np.ndarray, start_idx: int, apex_idx: int
) -> int | None:
    """Last index in [start_idx, apex_idx] where mask is True."""
    span = mask[start_idx:apex_idx + 1]
    hits = np.flatnonzero(span)
    return int(start_idx + hits[-1]) if len(hits) else None
```

In `_diagnose_region`, after the throttle-delta block and before the `return`, add:

```python
    # Brake release (trail braking) — only meaningful where the reference
    # itself carries brake near its apex; otherwise None (the trail guard).
    ref_release = _release(reference.brake[:n] > BRAKE_THRESHOLD, start, ref_apex)
    drv_release = _release(driver.brake[:n] > BRAKE_THRESHOLD, start, drv_apex)
    reference_trails = (
        ref_release is not None
        and (ref_apex - ref_release) * interval_m <= TRAIL_GUARD_M
    )
    brake_release_delta = (
        (drv_release - ref_release) * interval_m
        if reference_trails and drv_release is not None
        else None
    )

    # Exit speed at the region end — a deficit here compounds down the
    # following straight.
    exit_idx = max(0, min(n - 1, end - 1))
    exit_speed_delta = float(driver.speed[exit_idx] - reference.speed[exit_idx])
```

Update the `return RegionDiagnosis(...)` to pass the new fields:

```python
    return RegionDiagnosis(
        region=region,
        label=annotate_region(region, corners, track_length=driver.track_length),
        braking_delta_m=braking_delta,
        min_speed_delta_ms=drv_min - ref_min,
        throttle_delta_m=throttle_delta,
        driver_min_speed_ms=drv_min,
        reference_min_speed_ms=ref_min,
        brake_release_delta_m=brake_release_delta,
        exit_speed_delta_ms=exit_speed_delta,
        reference_brake_onset_m=(
            ref_brake * interval_m if ref_brake is not None else None
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_debrief.py -q`
Expected: all PASS (11 tests).

- [ ] **Step 5: Run the neighboring suites to catch construction breaks**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py tests/test_analyzer.py tests/test_live_coach_helpers.py -q`
Expected: all PASS (new fields have defaults).

- [ ] **Step 6: Commit**

```bash
git add core/coaching/debrief.py tests/test_debrief.py
git commit -m "feat: brake-release (trail) and exit-speed deltas in region diagnosis"
```

---

### Task 2: Nudge ladder — trail and exit rungs, speech and prompt phrasings

**Files:**
- Modify: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

`Nudge` gains `speech` (full between-lap sentence including corner name) and `prompt` (terse in-corner imperative). The ladder goes lift > braking point > brake release > exit speed > throttle. Braking/release distances are phrased in **car lengths** (4.5 m), speeds in km/h spoken as "k".

- [ ] **Step 1: Update the test helper and write the failing tests**

In `tests/test_nudges.py`, replace the `_diag` helper with (adds the Task 1 fields):

```python
def _diag(label="Eau Rouge", time_lost=0.4, braking=None, min_speed=0.0,
          throttle=None, drv_min=60.0, ref_min=60.0, release=None,
          exit_speed=0.0, onset=None) -> RegionDiagnosis:
    return RegionDiagnosis(
        region=LossRegion(distance_start=1000.0, distance_end=1100.0,
                          time_lost=time_lost),
        label=label,
        braking_delta_m=braking,
        min_speed_delta_ms=min_speed,
        throttle_delta_m=throttle,
        driver_min_speed_ms=drv_min,
        reference_min_speed_ms=ref_min,
        brake_release_delta_m=release,
        exit_speed_delta_ms=exit_speed,
        reference_brake_onset_m=onset,
    )
```

Append the new tests:

```python
def test_early_release_says_carry_brakes_deeper():
    n = nudge_from_diagnosis(_diag(release=-15.0, min_speed=-0.5))
    assert n is not None
    assert "brakes deeper" in n.message.lower()
    assert "15" in n.detail


def test_release_below_threshold_returns_none():
    n = nudge_from_diagnosis(_diag(release=-6.0, min_speed=-0.5))
    assert n is None


def test_slow_exit_says_prioritize_the_exit():
    n = nudge_from_diagnosis(_diag(exit_speed=-3.0, min_speed=-0.5))
    assert n is not None
    assert "exit" in n.message.lower()


def test_braking_point_outranks_release():
    n = nudge_from_diagnosis(_diag(braking=-12.0, release=-15.0, min_speed=-0.5))
    assert "brake later" in n.message.lower()


def test_release_outranks_exit_speed():
    n = nudge_from_diagnosis(_diag(release=-12.0, exit_speed=-3.0, min_speed=-0.5))
    assert "brakes deeper" in n.message.lower()


def test_exit_speed_outranks_throttle():
    n = nudge_from_diagnosis(_diag(exit_speed=-3.0, throttle=30.0, min_speed=-0.5))
    assert "exit" in n.message.lower()


def test_speech_uses_car_lengths_not_meters():
    n = nudge_from_diagnosis(_diag(braking=-15.0, min_speed=-0.5))
    assert "car length" in n.speech.lower()
    assert "15m" not in n.speech


def test_prompt_is_terse_imperative_with_corner():
    """In-corner prompts are quantity-free — the magnitude was spoken
    between laps; at speed the driver needs only the instruction."""
    n = nudge_from_diagnosis(_diag(label="La Source", braking=-15.0, min_speed=-0.5))
    assert n.prompt == "La Source — brake later."
    assert "car length" not in n.prompt


def test_every_rung_has_speech_and_prompt():
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
        assert n.speech and n.prompt
        assert n.corner in n.speech and n.corner in n.prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -q`
Expected: new tests FAIL (`Nudge` has no `speech`; release/exit diagnoses return None), existing PASS.

- [ ] **Step 3: Implement in `core/live/nudges.py`**

Add constants after `THROTTLE_THRESHOLD_M = 20.0`:

```python
RELEASE_THRESHOLD_M = 10.0
EXIT_SPEED_THRESHOLD_MS = 2.0
# Spoken distances use car lengths — drivers translate "a car length later"
# onto their own visual markers far better than raw meters at speed.
CAR_LENGTH_M = 4.5
```

Extend the `Nudge` dataclass:

```python
@dataclass
class Nudge:
    """One imperative coaching line for a single corner."""

    corner: str
    message: str
    detail: str  # the justifying number, e.g. "-14 km/h" or "15m"
    speech: str  # full between-lap spoken sentence (includes corner name)
    prompt: str  # terse in-corner imperative (includes corner name)
```

Add the car-lengths phrase helper after `_kmh`:

```python
def _car_lengths_phrase(meters: float) -> str:
    """'15m' -> '3 and a half car lengths' (rounded to the nearest half)."""
    lengths = max(0.5, round(abs(meters) / CAR_LENGTH_M * 2) / 2)
    if lengths == 0.5:
        return "half a car length"
    if lengths == 1.0:
        return "a car length"
    if lengths == 1.5:
        return "a car length and a half"
    whole = int(lengths)
    if lengths == whole:
        return f"{whole} car lengths"
    return f"{whole} and a half car lengths"
```

Replace the body of `nudge_from_diagnosis` with the five-rung ladder:

```python
def nudge_from_diagnosis(diag: RegionDiagnosis) -> Nudge | None:
    """The single most salient nudge for this region, or None if nothing
    crosses threshold. Salience: lift > braking point > brake release
    (trail) > exit speed > throttle pickup."""
    corner = diag.label

    # 1) Apex-speed deficit (a lift / over-slow) is the headline when big.
    if diag.min_speed_delta_ms <= -MIN_SPEED_THRESHOLD_MS:
        deficit_kmh = abs(_kmh(diag.min_speed_delta_ms))
        detail = f"-{deficit_kmh:.0f} km/h"
        if diag.reference_min_speed_ms >= FLAT_CORNER_MIN_SPEED_MS:
            return Nudge(
                corner, "carry it flat, you lifted", detail,
                speech=f"{corner}. Carry it flat, you lifted.",
                prompt=f"{corner} — carry it flat.",
            )
        return Nudge(
            corner, "carry more apex speed", detail,
            speech=(f"{corner}. Carry more apex speed, you had "
                    f"{deficit_kmh:.0f} k more on the reference."),
            prompt=f"{corner} — carry more speed.",
        )

    # 2) Braking-point error.
    if diag.braking_delta_m is not None and abs(diag.braking_delta_m) >= BRAKING_THRESHOLD_M:
        meters = abs(diag.braking_delta_m)
        lengths = _car_lengths_phrase(meters)
        # Prompts are quantity-free: the magnitude was spoken between laps,
        # and at speed the driver needs only the instruction.
        if diag.braking_delta_m < 0:
            return Nudge(
                corner, "brake later", f"{meters:.0f}m",
                speech=f"{corner}. Brake {lengths} later.",
                prompt=f"{corner} — brake later.",
            )
        return Nudge(
            corner, "brake earlier", f"{meters:.0f}m",
            speech=f"{corner}. Brake {lengths} earlier.",
            prompt=f"{corner} — brake earlier.",
        )

    # 3) Brake release (trail braking) — only present where the reference
    #    trail-brakes (the diagnosis guard), so this never fires at
    #    straight-line-braking corners.
    if (diag.brake_release_delta_m is not None
            and diag.brake_release_delta_m <= -RELEASE_THRESHOLD_M):
        meters = abs(diag.brake_release_delta_m)
        lengths = _car_lengths_phrase(meters)
        return Nudge(
            corner, "carry the brakes deeper", f"{meters:.0f}m",
            speech=(f"{corner}. Release the brakes more slowly, "
                    f"carry them {lengths} deeper."),
            prompt=f"{corner} — carry the brakes deeper.",
        )

    # 4) Exit-speed deficit — compounds down the following straight.
    if diag.exit_speed_delta_ms <= -EXIT_SPEED_THRESHOLD_MS:
        deficit_kmh = abs(_kmh(diag.exit_speed_delta_ms))
        return Nudge(
            corner, "prioritize the exit", f"-{deficit_kmh:.0f} km/h",
            speech=(f"{corner}. Prioritize the exit, you're "
                    f"{deficit_kmh:.0f} k slow onto the straight."),
            prompt=f"{corner} — prioritize the exit.",
        )

    # 5) Late throttle pickup.
    if diag.throttle_delta_m is not None and diag.throttle_delta_m >= THROTTLE_THRESHOLD_M:
        return Nudge(
            corner, "back to power earlier", f"{diag.throttle_delta_m:.0f}m",
            speech=f"{corner}. Back to power earlier.",
            prompt=f"{corner} — power earlier.",
        )

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/live/nudges.py tests/test_nudges.py
git commit -m "feat: five-rung nudge ladder with speech and in-corner prompt phrasings"
```

---

### Task 3: Between-lap speech formatting with confirmations

**Files:**
- Modify: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

`format_lap_speech()` produces the spoken lap summary: delta sentence + top nudge's speech + at most one confirmation ("Pouhon — that's it, keep that.") when a previously flagged corner produced no nudge on an improving lap. Returns `(speech, flagged_labels)` so the caller threads the flagged set between laps.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_nudges.py`:

```python
from core.live.nudges import format_lap_speech


def test_speech_baseline():
    speech, flagged = format_lap_speech(131.4, 0.0, [], is_baseline=True)
    assert speech == "Baseline set. 2 11.4."
    assert flagged == set()


def test_speech_slower_lap_reads_delta_then_top_nudge():
    diags = [_diag(label="Les Combes", braking=-15.0, min_speed=-0.5)]
    speech, flagged = format_lap_speech(132.0, 0.3, diags)
    assert speech.startswith("Up 3 tenths.")
    assert "Les Combes" in speech
    assert "car length" in speech
    assert flagged == {"Les Combes"}


def test_speech_singular_tenth():
    speech, _ = format_lap_speech(132.0, 0.11, [])
    assert speech.startswith("Up a tenth.")


def test_speech_faster_lap():
    speech, _ = format_lap_speech(130.9, -0.4, [])
    assert speech.startswith("4 tenths quicker.")


def test_speech_big_delta_in_seconds():
    speech, _ = format_lap_speech(133.0, 1.4, [])
    assert speech.startswith("Up 1.4 seconds.")


def test_speech_clean_lap():
    speech, _ = format_lap_speech(131.5, 0.05, [])
    assert "clean lap" in speech.lower()


def test_speech_only_top_nudge_is_spoken():
    diags = [
        _diag(label="Eau Rouge", min_speed=-4.0, drv_min=55.0, ref_min=59.0),
        _diag(label="Pouhon", braking=-15.0, min_speed=-0.5),
    ]
    speech, flagged = format_lap_speech(132.0, 0.5, diags)
    assert "Eau Rouge" in speech
    assert "Pouhon" not in speech  # flagged, but not spoken
    assert flagged == {"Eau Rouge", "Pouhon"}


def test_speech_confirmation_when_flagged_corner_heals_on_improving_lap():
    diags = [_diag(label="Eau Rouge", braking=-15.0, min_speed=-0.5)]
    speech, _ = format_lap_speech(
        131.0, 0.2, diags, prev_flagged={"Pouhon", "Eau Rouge"}, improved=True
    )
    assert "Pouhon — that's it, keep that." in speech


def test_speech_no_confirmation_when_lap_did_not_improve():
    speech, _ = format_lap_speech(
        133.0, 1.0, [], prev_flagged={"Pouhon"}, improved=False
    )
    assert "that's it" not in speech
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -q`
Expected: new tests FAIL (`format_lap_speech` not importable), existing PASS.

- [ ] **Step 3: Implement in `core/live/nudges.py`**

Add after `_fmt_lap_time`:

```python
def _speech_lap_time(seconds: float) -> str:
    """131.4 -> '2 11.4' — SAPI reads it as 'two eleven point four'."""
    mins = int(seconds // 60)
    return f"{mins} {seconds % 60:.1f}"


def _speech_delta(total_delta: float) -> str:
    """Lap delta as a spoken sentence, in tenths (or seconds when >= 1s)."""
    tenths = round(abs(total_delta) * 10)
    if tenths == 0:
        return "Even with the reference."
    if tenths >= 10:
        secs = f"{abs(total_delta):.1f}"
        return f"Up {secs} seconds." if total_delta > 0 else f"{secs} seconds quicker."
    if tenths == 1:
        return "Up a tenth." if total_delta > 0 else "A tenth quicker."
    return f"Up {tenths} tenths." if total_delta > 0 else f"{tenths} tenths quicker."


def format_lap_speech(
    lap_time: float,
    total_delta: float,
    diagnoses: list[RegionDiagnosis],
    *,
    is_baseline: bool = False,
    prev_flagged: set[str] | None = None,
    improved: bool = False,
) -> tuple[str, set[str]]:
    """The spoken lap summary and the set of corner labels flagged this lap.

    Voice gets the headline only: delta sentence + the top region's top
    nudge. A confirmation ("that's it, keep that") is appended when a
    corner flagged on the previous lap produced no nudge this lap AND the
    lap improved — closing the learning loop the way a human coach does.
    Callers thread the returned flagged set into the next call's
    prev_flagged.
    """
    if is_baseline:
        return f"Baseline set. {_speech_lap_time(lap_time)}.", set()

    nudges = [
        n for n in (nudge_from_diagnosis(d) for d in diagnoses) if n is not None
    ]
    flagged = {n.corner for n in nudges}

    parts = [_speech_delta(total_delta)]
    if nudges:
        parts.append(nudges[0].speech)
    else:
        parts.append("Clean lap, nothing to flag.")

    if prev_flagged and improved:
        healed = sorted(prev_flagged - flagged)
        if healed:
            parts.append(f"{healed[0]} — that's it, keep that.")

    return " ".join(parts), flagged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/live/nudges.py tests/test_nudges.py
git commit -m "feat: spoken lap summary with tenths phrasing and confirmation nudges"
```

---

### Task 4: Speaker — non-blocking SAPI voice with latest-wins queue

**Files:**
- Create: `core/live/speaker.py`
- Test: `tests/test_speaker.py`
- Modify: `pyproject.toml`

A daemon worker thread speaks via pyttsx3. The pending queue holds **one** slot: a newer `say()` replaces an unspoken pending utterance (latest wins); an utterance already being spoken is never interrupted. Engine failure logs once and goes permanently silent. `NullSpeaker` for `--mute` and tests.

- [ ] **Step 1: Install the dependency**

Add to `pyproject.toml` `dependencies` (after `"pyyaml>=6.0.3",`):

```toml
    "pyttsx3>=2.90",
```

Run: `.venv/Scripts/python.exe -m pip install pyttsx3`
Expected: installs cleanly. **If it fails on Python 3.14** (comtypes compatibility), note the error, leave the pyproject entry, and continue — every test uses a fake engine, and `create_speaker` degrades to `NullSpeaker` at runtime. Flag it in the task report so the engine factory can be swapped to a PowerShell `System.Speech` subprocess later.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_speaker.py`:

```python
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
    time.sleep(0.2)
    s.say("b")  # must not raise even though the worker died
    s.close()


def test_null_speaker_is_a_noop():
    n = NullSpeaker()
    n.say("anything")
    n.close()


def test_create_speaker_mute_returns_null():
    assert isinstance(create_speaker(mute=True), NullSpeaker)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_speaker.py -q`
Expected: FAIL — `No module named 'core.live.speaker'`.

- [ ] **Step 4: Implement `core/live/speaker.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_speaker.py -q`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add core/live/speaker.py tests/test_speaker.py pyproject.toml
git commit -m "feat: non-blocking SAPI speaker with latest-wins queue"
```

---

### Task 5: PromptScheduler — approach-triggered in-corner prompts

**Files:**
- Create: `core/live/prompt_scheduler.py`
- Test: `tests/test_prompt_scheduler.py`

Pure state machine. `build_schedule` turns the previous lap's diagnoses into distance-triggered prompts (anchor = reference brake onset, fallback region start; trigger = anchor − 300 m). Safety clamp: a trigger inside a corner span moves to that corner's end + margin; if the remaining gap to the anchor is under 100 m (or the moved spot is inside another corner), the prompt is dropped. `feed(lap_dist)` fires each prompt once; `rearm()` resets at lap boundaries.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prompt_scheduler.py`:

```python
"""Tests for the in-corner prompt scheduler (pure state machine)."""

from core.coaching.debrief import RegionDiagnosis
from core.live.prompt_scheduler import (
    PromptScheduler,
    ScheduledPrompt,
    build_schedule,
)
from core.telemetry.loss_regions import LossRegion
from core.track.models import Corner

TRACK_LEN = 7000.0


def _diag(label="La Source", start=1000.0, end=1100.0, braking=-15.0,
          onset=None) -> RegionDiagnosis:
    return RegionDiagnosis(
        region=LossRegion(distance_start=start, distance_end=end,
                          time_lost=0.5),
        label=label,
        braking_delta_m=braking,
        min_speed_delta_ms=0.0,
        throttle_delta_m=None,
        driver_min_speed_ms=20.0,
        reference_min_speed_ms=20.0,
        reference_brake_onset_m=onset,
    )


def _corner(start, end, name="C"):
    return Corner(corner_id=None, track_id="t", corner_number=1, name=name,
                  distance_start_meters=start, distance_end_meters=end,
                  corner_type=None)


def test_trigger_placed_lead_before_brake_onset():
    schedule = build_schedule([_diag(onset=800.0)], [], TRACK_LEN)
    assert len(schedule) == 1
    assert schedule[0].trigger_m == 500.0
    assert schedule[0].text.startswith("La Source")


def test_trigger_falls_back_to_region_start_without_onset():
    schedule = build_schedule([_diag(start=1000.0, onset=None)], [], TRACK_LEN)
    assert schedule[0].trigger_m == 700.0


def test_trigger_inside_corner_moves_past_corner_end():
    corners = [_corner(450.0, 550.0)]
    schedule = build_schedule([_diag(onset=800.0)], corners, TRACK_LEN)
    # naive 500 is inside the corner -> moved to 550 + 30 margin
    assert schedule[0].trigger_m == 580.0


def test_trigger_dropped_when_gap_too_small():
    corners = [_corner(450.0, 730.0)]  # moved trigger 760, only 40m to anchor
    schedule = build_schedule([_diag(onset=800.0)], corners, TRACK_LEN)
    assert schedule == []


def test_trigger_dropped_when_moved_lands_in_next_corner():
    corners = [_corner(450.0, 550.0), _corner(560.0, 700.0)]
    schedule = build_schedule([_diag(onset=800.0)], corners, TRACK_LEN)
    assert schedule == []


def test_below_threshold_diagnosis_produces_no_prompt():
    schedule = build_schedule([_diag(braking=-2.0)], [], TRACK_LEN)
    assert schedule == []


def test_max_three_prompts():
    diags = [_diag(label=f"T{i}", onset=1000.0 * (i + 1)) for i in range(5)]
    schedule = build_schedule(diags, [], TRACK_LEN)
    assert len(schedule) == 3


def test_feed_fires_once_on_crossing():
    s = PromptScheduler([ScheduledPrompt(trigger_m=500.0, text="go")])
    assert s.feed(480.0) is None  # first sample primes prev_dist
    assert s.feed(510.0) == "go"
    assert s.feed(520.0) is None  # fired flag holds
    assert s.feed(490.0) is None  # driving backward over it doesn't re-fire


def test_rearm_resets_fired_flags():
    s = PromptScheduler([ScheduledPrompt(trigger_m=500.0, text="go")])
    s.feed(480.0)
    assert s.feed(510.0) == "go"
    s.rearm()
    s.feed(480.0)
    assert s.feed(510.0) == "go"


def test_feed_fires_across_start_finish_wrap():
    s = PromptScheduler([ScheduledPrompt(trigger_m=6950.0, text="wrap")])
    assert s.feed(6900.0) is None
    assert s.feed(20.0) == "wrap"  # crossed s/f between ticks


def test_empty_schedule_is_silent():
    s = PromptScheduler([])
    assert s.feed(100.0) is None
    assert s.feed(200.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_scheduler.py -q`
Expected: FAIL — `No module named 'core.live.prompt_scheduler'`.

- [ ] **Step 3: Implement `core/live/prompt_scheduler.py`**

```python
"""Approach-triggered in-corner prompts from the previous lap's diagnoses.

Pure state machine — no pyirsdk, no I/O. After each debriefed lap,
build_schedule() converts the top loss regions into distance-triggered
prompts for the NEXT lap; feed() is called with LapDist each tick and
returns the prompt text when a trigger is crossed.

Safety rule baked in: a trigger is never placed inside a corner span —
the coach must not speak over a braking zone or mid-corner. A trigger
that would land inside a corner moves to just past that corner's exit;
if the remaining run to the anchor is too short to act on, the prompt
is dropped entirely.
"""

from dataclasses import dataclass

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import nudge_from_diagnosis
from core.track.models import Corner

# Tunable constants — expected to be adjusted from real driving, like the
# nudge thresholds before them.
LEAD_M = 300.0          # how far before the brake-onset anchor to speak
CLAMP_MARGIN_M = 30.0   # breathing room past a corner exit before speaking
MIN_GAP_M = 100.0       # minimum run from trigger to anchor to be actionable
MAX_PROMPTS = 3


@dataclass
class ScheduledPrompt:
    """One armed prompt: speak `text` when the car crosses `trigger_m`."""

    trigger_m: float
    text: str
    fired: bool = False


def _containing_corner(pos: float, corners: list[Corner]) -> Corner | None:
    for c in corners:
        if c.distance_start_meters <= pos <= c.distance_end_meters:
            return c
    return None


def _place_trigger(
    anchor: float,
    corners: list[Corner],
    track_length_m: float,
    lead_m: float,
    margin_m: float,
    min_gap_m: float,
) -> float | None:
    """Trigger distance for an anchor, or None when no safe spot exists."""
    trigger = (anchor - lead_m) % track_length_m
    inside = _containing_corner(trigger, corners)
    if inside is not None:
        trigger = (inside.distance_end_meters + margin_m) % track_length_m
        if _containing_corner(trigger, corners) is not None:
            return None  # chicane-dense stretch; no safe gap to speak in
        gap = (anchor - trigger) % track_length_m
        if gap < min_gap_m or gap > lead_m:
            return None  # too close to act on, or moved past the anchor
    return trigger


def build_schedule(
    diagnoses: list[RegionDiagnosis],
    corners: list[Corner],
    track_length_m: float,
    *,
    lead_m: float = LEAD_M,
    margin_m: float = CLAMP_MARGIN_M,
    min_gap_m: float = MIN_GAP_M,
    max_prompts: int = MAX_PROMPTS,
) -> list[ScheduledPrompt]:
    """Distance-triggered prompts for the next lap, from this lap's
    diagnoses (already sorted by time lost)."""
    if track_length_m <= 0:
        return []
    prompts: list[ScheduledPrompt] = []
    for diag in diagnoses:
        if len(prompts) >= max_prompts:
            break
        nudge = nudge_from_diagnosis(diag)
        if nudge is None:
            continue
        anchor = (
            diag.reference_brake_onset_m
            if diag.reference_brake_onset_m is not None
            else diag.region.distance_start
        )
        trigger = _place_trigger(
            anchor, corners, track_length_m, lead_m, margin_m, min_gap_m
        )
        if trigger is None:
            continue
        prompts.append(ScheduledPrompt(trigger_m=trigger, text=nudge.prompt))
    return prompts


class PromptScheduler:
    """Fires each armed prompt once as the car crosses its trigger."""

    def __init__(self, schedule: list[ScheduledPrompt] | None = None) -> None:
        self._schedule = schedule if schedule is not None else []
        self._prev_dist: float | None = None

    def set_schedule(self, schedule: list[ScheduledPrompt]) -> None:
        self._schedule = schedule
        self._prev_dist = None

    def rearm(self) -> None:
        """Reset fired flags at a lap boundary (same schedule, new lap)."""
        for p in self._schedule:
            p.fired = False

    def feed(self, lap_dist_m: float) -> str | None:
        """One tick. Returns prompt text iff a trigger was crossed."""
        prev, self._prev_dist = self._prev_dist, lap_dist_m
        if prev is None:
            return None
        for p in self._schedule:
            if not p.fired and _crossed(prev, lap_dist_m, p.trigger_m):
                p.fired = True
                return p.text
        return None


def _crossed(prev: float, curr: float, trigger: float) -> bool:
    if curr >= prev:
        return prev < trigger <= curr
    # Wrapped past start/finish between ticks.
    return trigger > prev or trigger <= curr
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_scheduler.py -q`
Expected: 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/live/prompt_scheduler.py tests/test_prompt_scheduler.py
git commit -m "feat: distance-triggered in-corner prompt scheduler with corner-span safety clamp"
```

---

### Task 6: Wire voice, reference lap, and prompts into live_coach.py

**Files:**
- Modify: `scripts/live_coach.py`
- Test: `tests/test_live_coach_helpers.py`

Adds: argparse (`--mute`, `--corner-prompts`), `_car_name` (CarScreenName — MUST match the offline pipeline's field), `_load_reference` (visible-failure lookup), speaker + speech wiring with confirmation state threading, prompt scheduler wiring behind the flag. With a stored reference: coaching starts on the first valid flying lap and the reference is never replaced mid-session; without one: existing session-best behavior unchanged.

- [ ] **Step 1: Write the failing helper tests**

Append to `tests/test_live_coach_helpers.py`:

```python
import numpy as np

from core.benchmark.reference_store import ReferenceStore
from core.telemetry.normalizer import NormalizedLap


def _tiny_lap(n: int = 100) -> NormalizedLap:
    z = np.zeros(n)
    return NormalizedLap(
        lap_number=1, lap_time=131.4, track_length=float(n),
        distance=np.arange(n, dtype=float), speed=np.full(n, 50.0),
        throttle=np.ones(n), brake=z, steering=z, gear=np.full(n, 4),
        rpm=np.full(n, 6000.0), lat=z, lon=z,
        elapsed_time=np.cumsum(np.full(n, 0.02)), is_valid=True,
    )


def test_car_name_reads_car_screen_name():
    """Must read the exact field the offline pipeline stores references
    under (ibt_parser uses CarScreenName) — the store lookup is an exact
    string match."""
    class _FakeIR:
        def __getitem__(self, key):
            assert key == "DriverInfo"
            return {"DriverCarIdx": 1, "Drivers": [
                {"CarScreenName": "Other Car"},
                {"CarScreenName": "BMW M2 CS Racing"},
            ]}
    assert live_coach._car_name(_FakeIR()) == "BMW M2 CS Racing"


def test_car_name_handles_missing_driver_info():
    class _FakeIR:
        def __getitem__(self, key):
            return None
    assert live_coach._car_name(_FakeIR()) == ""


def test_load_reference_none_when_store_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(live_coach, "REFERENCE_DB", tmp_path / "refs.db")
    assert live_coach._load_reference("523", "BMW M2 CS Racing") is None


def test_load_reference_none_for_blank_key(tmp_path, monkeypatch):
    monkeypatch.setattr(live_coach, "REFERENCE_DB", tmp_path / "refs.db")
    assert live_coach._load_reference("", "BMW M2 CS Racing") is None
    assert live_coach._load_reference("523", "") is None


def test_load_reference_returns_stored_g61_lap(tmp_path, monkeypatch):
    db = tmp_path / "refs.db"
    monkeypatch.setattr(live_coach, "REFERENCE_DB", db)
    ReferenceStore(db).save(
        "523", "BMW M2 CS Racing", _tiny_lap(),
        source="g61", driver_name="Fast Alien",
    )
    ref = live_coach._load_reference("523", "BMW M2 CS Racing")
    assert ref is not None
    assert ref.meta.source == "g61"
    assert ref.lap.lap_time == 131.4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_coach_helpers.py -q`
Expected: new tests FAIL (`module 'live_coach' has no attribute '_car_name'`), existing PASS.

- [ ] **Step 3: Implement the wiring in `scripts/live_coach.py`**

Add imports (with the existing `# noqa: E402` group):

```python
import argparse  # add to the stdlib import block at the top

from core.benchmark.reference_store import ReferenceLap, ReferenceStore  # noqa: E402
from core.live.nudges import format_lap_block, format_lap_speech  # noqa: E402  (replaces the existing nudges import line)
from core.live.prompt_scheduler import PromptScheduler, build_schedule  # noqa: E402
from core.live.speaker import create_speaker  # noqa: E402
```

Add a constant next to `DB_PATH`:

```python
REFERENCE_DB = Path("data/reference_laps.db")
```

Add two helpers after `_load_corners`:

```python
def _car_name(ir: "irsdk.IRSDK") -> str:
    """The driver's CarScreenName — the exact field the offline pipeline
    (IBTParser) stores references under, so ReferenceStore lookups match."""
    info = ir["DriverInfo"] or {}
    drivers = info.get("Drivers", [])
    idx = int(info.get("DriverCarIdx", 0) or 0)
    if drivers and idx < len(drivers):
        return str(drivers[idx].get("CarScreenName", "") or "")
    return ""


def _load_reference(track_id: str, car: str) -> "ReferenceLap | None":
    """Stored reference lap for this combo, or None — with a visible reason,
    because a silent car-string mismatch would just look like missing
    trail coaching."""
    if not track_id or not car:
        return None
    try:
        ref = ReferenceStore(REFERENCE_DB).get(track_id, car)
    except Exception as exc:
        print(f"Reference lookup failed for ({track_id!r}, {car!r}): {exc}")
        return None
    if ref is None:
        print(f"No stored reference for ({track_id!r}, {car!r}); "
              "coaching against session best.")
    return ref
```

Replace `main()` with:

```python
def main() -> None:
    args = _parse_args()
    ir = irsdk.IRSDK()
    print("Race Engineer live coach - waiting for iRacing...")

    feed = NudgeFeed()
    start_web_display(feed)
    print(f"Web display: http://{_lan_ip()}:8042  (open in Safari on your iPad)")

    speaker = create_speaker(mute=args.mute)

    def emit(block: str) -> None:
        print(block)
        feed.add(block)

    tracker = LapBoundaryTracker()
    normalizer = Normalizer()
    scheduler = PromptScheduler()
    reference_lap = None       # stored (G61/PB) lap; never replaced mid-session
    session_best = None        # fallback comparison lap when no stored reference
    corners: list = []
    meta_loaded = False
    prev_flagged: set = set()
    prev_delta: float | None = None

    try:
        while True:
            if not (ir.is_initialized and ir.is_connected):
                ir.shutdown()
                meta_loaded = False
                ir.startup()
                time.sleep(0.5)
                continue

            if not meta_loaded:
                track_id, track_length_m, track_dir, track_display = _session_meta(ir)
                corners = _load_corners(
                    track_id, track_dir, track_length_m, track_display
                )
                car = _car_name(ir)
                ref = _load_reference(track_id, car)
                reference_lap = ref.lap if ref is not None else None
                session_best = None
                scheduler.set_schedule([])
                prev_flagged = set()
                prev_delta = None
                meta_loaded = True
                if ref is not None:
                    emit(
                        f"Reference loaded: {ref.meta.source}, "
                        f"{ref.meta.lap_time:.3f}s"
                        + (f" ({ref.meta.driver_name})"
                           if ref.meta.driver_name else "")
                    )
                    speaker.say("Reference lap loaded. Coaching from lap one.")
                    print(f"Connected: {track_display}.")
                else:
                    print(f"Connected: {track_display}. "
                          "Drive a lap to set baseline.")

            ir.freeze_var_buffer_latest()
            sample = {ch: ir[ch] for ch in READ_CHANNELS}

            completed = tracker.feed(sample)

            if args.corner_prompts and not sample.get("OnPitRoad"):
                prompt = scheduler.feed(float(sample["LapDist"] or 0.0))
                if prompt is not None:
                    print(f"  >> {prompt}")
                    speaker.say(prompt)

            if completed is not None:
                scheduler.rearm()
                # track_length_m was captured at connect time and is stable
                # for the session, so reuse it rather than re-reading the YAML.
                nlap = normalizer.normalize_lap(
                    completed.dataframe, completed.lap_number, track_length_m
                )
                if nlap.is_valid:
                    comparison = (
                        reference_lap if reference_lap is not None
                        else session_best
                    )
                    if comparison is None:
                        session_best = nlap
                        emit(format_lap_block(
                            nlap.lap_number, nlap.lap_time, 0.0, [],
                            is_baseline=True,
                        ))
                        speech, prev_flagged = format_lap_speech(
                            nlap.lap_time, 0.0, [], is_baseline=True,
                        )
                        speaker.say(speech)
                    else:
                        result = build_debrief(nlap, comparison, corners)
                        emit(format_lap_block(
                            nlap.lap_number, nlap.lap_time,
                            result.total_time_delta, result.diagnoses,
                        ))
                        improved = (
                            prev_delta is not None
                            and result.total_time_delta < prev_delta
                        )
                        speech, prev_flagged = format_lap_speech(
                            nlap.lap_time, result.total_time_delta,
                            result.diagnoses,
                            prev_flagged=prev_flagged, improved=improved,
                        )
                        speaker.say(speech)
                        prev_delta = result.total_time_delta
                        if args.corner_prompts:
                            scheduler.set_schedule(build_schedule(
                                result.diagnoses, corners, track_length_m,
                            ))
                        if (reference_lap is None
                                and nlap.lap_time < session_best.lap_time):
                            session_best = nlap

            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        speaker.close()
        ir.shutdown()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live between-lap coach")
    parser.add_argument("--mute", action="store_true",
                        help="disable voice output")
    parser.add_argument("--corner-prompts", action="store_true",
                        help="speak approach prompts before flagged corners "
                             "(phase 2, validate --mute-less laps first)")
    return parser.parse_args()
```

- [ ] **Step 4: Run the helper tests and full live suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_coach_helpers.py tests/test_session_reader.py tests/test_lap_buffer.py tests/test_feed.py -q`
Expected: all PASS. (Note: importing the module runs `_parse_args` only under `__main__`, so the test-time exec is safe.)

- [ ] **Step 5: Commit**

```bash
git add scripts/live_coach.py tests/test_live_coach_helpers.py
git commit -m "feat: voice, stored-reference coaching, and in-corner prompts in live coach"
```

---

### Task 7: Streamlit debrief cards — show the two new deltas

**Files:**
- Modify: `app/pages/coaching.py` (diagnosis cards, around line 361–383)

Display-only change; no business logic in Streamlit, no new tests (consistent with existing page code).

- [ ] **Step 1: Extend the metric columns**

In the `for diag in result.diagnoses:` card loop, change `c1, c2, c3 = st.columns(3)` to `c1, c2, c3, c4, c5 = st.columns(5)` and append after the existing `c3.metric(...)` block:

```python
            c4.metric(
                "Brake Release",
                fmt_distance(diag.brake_release_delta_m, imperial, signed=True)
                if diag.brake_release_delta_m is not None
                else "—",
                help="Negative = you release the brakes earlier than the "
                     "reference (less trail braking). Only shown where the "
                     "reference trail-brakes.",
            )
            c5.metric(
                "Exit Speed",
                fmt_speed(diag.exit_speed_delta_ms, imperial),
                help="Negative = you're slower at the corner exit; the loss "
                     "compounds down the following straight",
            )
```

- [ ] **Step 2: Smoke-check the page imports**

Run: `.venv/Scripts/python.exe -c "import ast; ast.parse(open('app/pages/coaching.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/pages/coaching.py
git commit -m "feat: brake-release and exit-speed metrics on debrief cards"
```

---

### Task 8: Full suite, docs, and wrap-up

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the full test suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (should be ~330 passing, 10 skipped). If anything fails, fix before proceeding.

- [ ] **Step 2: Update CLAUDE.md**

Make these updates:
1. Architecture tree: add `speaker.py  # Non-blocking SAPI voice (latest-wins queue)` and `prompt_scheduler.py  # Distance-triggered in-corner prompts` under `core/live/`; add `test_speaker.py` and `test_prompt_scheduler.py` to the tests listing.
2. Dependencies section: add `pyttsx3 — Windows SAPI text-to-speech (live voice)` under Core.
3. Current Status: add a new block after the Live Coaching Spike block:

```markdown
**Live Voice Coaching** (complete, branch live-voice-coaching)
- [x] Diagnosis metrics: brake-release delta (trail guard: only where reference trails) + exit-speed delta + reference brake onset (`core/coaching/debrief.py`)
- [x] Five-rung nudge ladder with speech (car lengths, "k" for km/h) and terse in-corner prompt phrasings (`core/live/nudges.py`)
- [x] format_lap_speech — delta-first spoken summary, confirmation nudges ("that's it, keep that"), returns flagged-label set for threading (`core/live/nudges.py`)
- [x] Speaker — daemon-thread SAPI via pyttsx3, one-slot latest-wins queue, in-progress never interrupted, failure degrades to silent (`core/live/speaker.py`)
- [x] PromptScheduler — triggers 300m before reference brake onset, corner-span safety clamp (move past exit or drop under 100m gap), max 3/lap, once-per-lap with rearm (`core/live/prompt_scheduler.py`)
- [x] live_coach wiring — --mute / --corner-prompts flags, ReferenceStore lookup at connect (CarScreenName key, visible-failure logging), stored reference never replaced mid-session
- [ ] Rollout 0: export real Spa/M2 G61 CSV — closes validation gate AND enables trail coaching
- [ ] Driving validation: voice audibility/pacing, trail-nudge accuracy, prompt trigger timing
```

4. In the Live Coaching Spike section's run command note, update to mention the new flags: `.venv/Scripts/python.exe scripts/live_coach.py [--mute] [--corner-prompts]`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: live voice coaching status and run flags"
```

- [ ] **Step 4: Verify the branch is clean**

Run: `git status`
Expected: clean working tree on `live-voice-coaching`.

---

## Post-implementation (manual, user-driven)

Not part of the automated plan — these need the user:

1. **Rollout 0:** export one Spa / BMW M2 CS Racing lap CSV from Garage 61; verify `CHANNEL_ALIASES` in `core/benchmark/g61_import.py` against the real headers; import into `ReferenceStore` (this also un-skips the 3 G61 validation-gate tests).
2. **Phase 1 driving validation:** run `scripts/live_coach.py`, confirm voice is audible over engine noise, pacing feels right, car-length phrasing lands, trail nudges only fire at genuine trail corners.
3. **Phase 2 driving validation:** add `--corner-prompts`, confirm triggers feel early enough to act on and never talk over a braking zone. Tune `LEAD_M` / `CLAMP_MARGIN_M` / thresholds from real laps.
