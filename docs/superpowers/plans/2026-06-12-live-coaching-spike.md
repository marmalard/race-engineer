# Live Between-Lap Coaching Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A terminal program that attaches to a running iRacing session and, after each completed lap, prints terse coaching nudges derived from the existing loss-region engine — proving lap-boundary detection and nudge quality before any HUD is built.

**Architecture:** A pure lap-boundary state machine (`LapBoundaryTracker`) is fed per-tick sample dicts and emits a completed-lap DataFrame when a valid lap finishes, discarding pit/reset/tow laps. A `LapBuffer` accumulates ticks into the exact DataFrame shape `Normalizer.normalize_lap` already consumes. A `nudges` module turns a `RegionDiagnosis` into one terse imperative line. A thin terminal entry point drives pyirsdk, feeds the tracker, normalizes each completed lap, runs the existing `build_debrief` against the session best, and prints nudges. Everything risky is a pure function tested against synthetic tick streams; the pyirsdk driver is thin and validated by real driving.

**Tech Stack:** Python 3.14, pyirsdk (already a dependency), pandas/numpy, the existing `core.telemetry` / `core.coaching.debrief` / `core.track` modules unchanged.

**Spec:** `docs/superpowers/specs/2026-06-12-live-coaching-spike-design.md`

**Conventions for all tasks:**
- Test runner: `.venv/Scripts/python.exe -m pytest` (uv is not on PATH on this machine; PowerShell shell, use `;` not `&&`).
- The analysis core is REUSED UNCHANGED. New code lives in `core/live/` and `scripts/`. Do not edit `normalizer.py`, `debrief.py`, `loss_regions.py`, or `segment_annotator.py`.
- Sign conventions (from `RegionDiagnosis`, driver-vs-reference): `braking_delta_m` negative = driver brakes EARLIER than reference; `min_speed_delta_ms` negative = driver OVER-SLOWS (lower apex speed); `throttle_delta_m` positive = driver back to power LATER.
- `RegionDiagnosis` fields (from `core/coaching/debrief.py`): `region` (a `LossRegion` with `distance_start`, `distance_end`, `time_lost`), `label: str`, `braking_delta_m: float | None`, `min_speed_delta_ms: float`, `throttle_delta_m: float | None`, `driver_min_speed_ms: float`, `reference_min_speed_ms: float`.

**File structure created by this plan:**

```
core/live/
├── __init__.py            # NEW (empty package marker)
├── lap_buffer.py          # NEW: LapBuffer — accumulate tick dicts → normalizer-ready DataFrame
├── session_reader.py      # NEW: LapBoundaryTracker — pure lap-boundary state machine
└── nudges.py              # NEW: RegionDiagnosis → terse Nudge; per-lap terminal block
scripts/
└── live_coach.py          # NEW: terminal entry point (pyirsdk driver + wiring; manual validation)
tests/
├── test_lap_buffer.py     # NEW
├── test_session_reader.py # NEW (the risk: synthetic tick scenarios)
└── test_nudges.py         # NEW
```

The pyirsdk driver in `scripts/live_coach.py` cannot be unit-tested without a live sim, so it is kept thin: all logic that CAN be tested lives in `core/live/` pure classes. The driver only adapts pyirsdk → sample dicts and prints.

---

### Task 1: LapBuffer — accumulate live ticks into a normalizer-ready DataFrame

**Files:**
- Create: `core/live/__init__.py`
- Create: `core/live/lap_buffer.py`
- Test: `tests/test_lap_buffer.py`

- [ ] **Step 1: Create the package marker**

Create `core/live/__init__.py` as an empty file (one blank line is fine).

- [ ] **Step 2: Write the failing test**

Create `tests/test_lap_buffer.py`:

```python
"""Tests for LapBuffer — accumulating live ticks into a DataFrame the
Normalizer can consume."""

import numpy as np
import pandas as pd

from core.live.lap_buffer import LapBuffer, SAMPLE_CHANNELS
from core.telemetry.normalizer import NormalizedLap, Normalizer


def _tick(lapdist: float, session_time: float, speed: float = 50.0) -> dict:
    """A full live sample dict with all channels plus some extras the
    buffer should ignore."""
    return {
        "LapDist": lapdist,
        "Speed": speed,
        "Throttle": 1.0,
        "Brake": 0.0,
        "SteeringWheelAngle": 0.0,
        "RPM": 6000.0,
        "Gear": 4,
        "Lat": 50.0,
        "Lon": 5.0,
        "SessionTime": session_time,
        "LapCurrentLapTime": session_time,
        # Extra channels the buffer is not responsible for storing:
        "Lap": 3,
        "OnPitRoad": False,
        "PlayerTrackSurface": 3,
    }


def test_buffer_starts_empty():
    buf = LapBuffer()
    assert len(buf) == 0


def test_add_increments_length():
    buf = LapBuffer()
    buf.add(_tick(0.0, 0.0))
    buf.add(_tick(1.0, 0.02))
    assert len(buf) == 2


def test_to_dataframe_has_exactly_sample_channels():
    buf = LapBuffer()
    buf.add(_tick(0.0, 0.0))
    df = buf.to_dataframe()
    assert list(df.columns) == SAMPLE_CHANNELS
    # Extras like Lap / OnPitRoad are NOT columns
    assert "OnPitRoad" not in df.columns


def test_clear_empties_buffer():
    buf = LapBuffer()
    buf.add(_tick(0.0, 0.0))
    buf.clear()
    assert len(buf) == 0
    assert len(buf.to_dataframe()) == 0


def test_dataframe_feeds_normalizer():
    """A buffered lap must be consumable by the real Normalizer."""
    buf = LapBuffer()
    track_length = 1000.0
    # Build a plausible single lap: distance 0..999, time rising
    for i in range(1000):
        buf.add(_tick(float(i), i * 0.02, speed=50.0))
    df = buf.to_dataframe()
    nlap = Normalizer().normalize_lap(df, lap_number=3, track_length_m=track_length)
    assert isinstance(nlap, NormalizedLap)
    assert nlap.is_valid
    assert nlap.distance[1] - nlap.distance[0] == 1.0
    assert np.all(nlap.speed >= 0)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lap_buffer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.live.lap_buffer'`

- [ ] **Step 4: Implement**

Create `core/live/lap_buffer.py`:

```python
"""Accumulate live telemetry ticks into a DataFrame the Normalizer consumes.

The live reader hands us one sample dict per sim tick. We store only the
channels `Normalizer.normalize_lap` reads, in the same column shape that
`IBTParser.get_laps()` produces — so the entire offline analysis pipeline
runs on live data unchanged.
"""

import pandas as pd

# Exactly the channels Normalizer.normalize_lap reads (see normalizer.py).
# Order is fixed so the produced DataFrame is deterministic.
SAMPLE_CHANNELS = [
    "LapDist",
    "Speed",
    "Throttle",
    "Brake",
    "SteeringWheelAngle",
    "RPM",
    "Gear",
    "Lat",
    "Lon",
    "SessionTime",
    "LapCurrentLapTime",
]


class LapBuffer:
    """Accumulates per-tick sample dicts for a single lap."""

    def __init__(self) -> None:
        self._rows: list[dict] = []

    def add(self, sample: dict) -> None:
        """Append one tick, keeping only the channels the Normalizer needs."""
        self._rows.append({ch: sample[ch] for ch in SAMPLE_CHANNELS})

    def to_dataframe(self) -> pd.DataFrame:
        """Build the lap DataFrame in normalizer-ready column order."""
        return pd.DataFrame(self._rows, columns=SAMPLE_CHANNELS)

    def clear(self) -> None:
        """Discard all buffered ticks."""
        self._rows = []

    def __len__(self) -> int:
        return len(self._rows)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lap_buffer.py -v`
Expected: 5 PASS. If `test_dataframe_feeds_normalizer` fails, the column set is wrong — compare against the channels read in `core/telemetry/normalizer.py:80-108` and fix `SAMPLE_CHANNELS`, not the test.

- [ ] **Step 6: Commit**

```bash
git add core/live/__init__.py core/live/lap_buffer.py tests/test_lap_buffer.py
git commit -m "feat: LapBuffer accumulates live ticks into normalizer-ready DataFrame"
```

---

### Task 2: LapBoundaryTracker — the lap-boundary state machine (the risk)

**Files:**
- Create: `core/live/session_reader.py`
- Test: `tests/test_session_reader.py`

This is the highest-risk component. It is a pure class fed one sample dict at a time; it never touches pyirsdk, so every scenario (clean lap, out-lap, in-lap, off-track, reset, tow) is unit-tested against hand-built tick streams.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_reader.py`:

```python
"""Tests for the LapBoundaryTracker state machine.

Fed one sample dict per tick, it emits a CompletedLap when a valid lap
boundary is crossed and suppresses pit / reset / tow / too-short laps.
No pyirsdk, no live sim — pure synthetic tick streams.
"""

from core.live.session_reader import CompletedLap, LapBoundaryTracker


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
    """Feed n ticks of one lap; return the list of emissions."""
    emissions = []
    for i in range(n):
        out = tracker.feed(
            _tick(lap_num, float(i), t0 + i * 0.02, on_pit=on_pit)
        )
        emissions.append(out)
    return emissions


def test_no_emission_during_a_lap():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    emissions = _drive_lap(tracker, lap_num=1)
    assert all(e is None for e in emissions)


def test_lap_completes_on_increment():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=1, n=300, t0=0.0)
    # First tick of lap 2 closes lap 1
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert isinstance(out, CompletedLap)
    assert out.lap_number == 1
    assert len(out.dataframe) == 300


def test_out_lap_then_flying_lap():
    """Lap 1 is the out-lap; lap 2 flying. Both should emit (the consumer
    decides validity downstream), but the out-lap with a pit sample must
    be suppressed."""
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Lap 1 = out-lap, started in pit (first 50 ticks on pit road)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i < 50)))
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert out is None  # lap 1 touched pit road → suppressed


def test_clean_flying_lap_after_pit_lap_emits():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Lap 1 = pit lap (suppressed)
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i < 50)))
    tracker.feed(_tick(2, 0.0, 6.0))  # closes lap 1 (suppressed)
    # Lap 2 = clean flying lap
    for i in range(1, 300):
        tracker.feed(_tick(2, float(i), 6.0 + i * 0.02))
    out = tracker.feed(_tick(3, 0.0, 12.0))  # closes lap 2
    assert isinstance(out, CompletedLap)
    assert out.lap_number == 2


def test_in_lap_to_pit_suppressed():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Lap 1 dives into pit near the end
    for i in range(300):
        tracker.feed(_tick(1, float(i), i * 0.02, on_pit=(i > 250)))
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert out is None


def test_reset_lap_backward_discards_buffer():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=5, n=150, t0=0.0)
    # Sim reset: Lap jumps backward to 1, no completed lap emitted
    out = tracker.feed(_tick(1, 0.0, 0.0))
    assert out is None
    # And the new lap accumulates cleanly afterward
    for i in range(1, 300):
        tracker.feed(_tick(1, float(i), i * 0.02))
    closed = tracker.feed(_tick(2, 0.0, 6.0))
    assert isinstance(closed, CompletedLap)
    assert closed.lap_number == 1


def test_too_short_lap_suppressed():
    tracker = LapBoundaryTracker(min_lap_samples=100)
    # Only 40 ticks before the lap flips — too short to be a real lap
    for i in range(40):
        tracker.feed(_tick(1, float(i), i * 0.02))
    out = tracker.feed(_tick(2, 0.0, 1.0))
    assert out is None


def test_emitted_dataframe_is_normalizer_shaped():
    from core.live.lap_buffer import SAMPLE_CHANNELS
    tracker = LapBoundaryTracker(min_lap_samples=100)
    _drive_lap(tracker, lap_num=1, n=300)
    out = tracker.feed(_tick(2, 0.0, 6.0))
    assert list(out.dataframe.columns) == SAMPLE_CHANNELS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_reader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.live.session_reader'`

- [ ] **Step 3: Implement**

Create `core/live/session_reader.py`:

```python
"""Pure lap-boundary state machine for live telemetry.

Fed one sample dict per sim tick, it decides when a lap completes and
whether the completed lap is worth analyzing. It owns no pyirsdk and no
I/O, so the whole risk surface (pits, resets, tows, out/in-laps) is
unit-testable against synthetic tick streams.

Validity here is deliberately coarse: suppress laps that touched pit road,
laps too short to be real, and discard the buffer on a backward Lap jump
(reset/tow). Finer validity (distance coverage, distance jumps) is left to
`Normalizer.normalize_lap`, whose `is_valid` flag the consumer checks
downstream — this keeps the state machine simple and its responsibility
single.
"""

from dataclasses import dataclass

import pandas as pd

from core.live.lap_buffer import LapBuffer


@dataclass
class CompletedLap:
    """A lap that crossed the start/finish line and passed coarse gating."""

    lap_number: int
    dataframe: pd.DataFrame


class LapBoundaryTracker:
    """Accumulates ticks and emits CompletedLap on valid lap boundaries."""

    def __init__(self, min_lap_samples: int = 100) -> None:
        self.min_lap_samples = min_lap_samples
        self._buffer = LapBuffer()
        self._current_lap: int | None = None
        self._touched_pit = False

    def feed(self, sample: dict) -> CompletedLap | None:
        """Process one tick. Returns a CompletedLap iff this tick closed a
        valid lap, else None."""
        lap = int(sample["Lap"])

        # First tick of the session: start tracking, no boundary yet.
        if self._current_lap is None:
            self._start_lap(lap, sample)
            return None

        # Lap unchanged: keep buffering this lap.
        if lap == self._current_lap:
            if sample.get("OnPitRoad"):
                self._touched_pit = True
            self._buffer.add(sample)
            return None

        # Lap went backward (reset / tow): discard and restart cleanly.
        if lap < self._current_lap:
            self._start_lap(lap, sample)
            return None

        # Lap incremented: the buffered lap is complete. Decide whether to
        # emit it, then start the new lap with this tick.
        completed = self._close_current_lap()
        self._start_lap(lap, sample)
        return completed

    def _start_lap(self, lap: int, first_sample: dict) -> None:
        self._buffer.clear()
        self._current_lap = lap
        self._touched_pit = bool(first_sample.get("OnPitRoad"))
        self._buffer.add(first_sample)

    def _close_current_lap(self) -> CompletedLap | None:
        if self._touched_pit:
            return None
        if len(self._buffer) < self.min_lap_samples:
            return None
        return CompletedLap(
            lap_number=self._current_lap,
            dataframe=self._buffer.to_dataframe(),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_reader.py -v`
Expected: 8 PASS. These scenarios are the spike's whole risk; if any fail, fix the state machine, not the tests.

- [ ] **Step 5: Commit**

```bash
git add core/live/session_reader.py tests/test_session_reader.py
git commit -m "feat: LapBoundaryTracker state machine with pit/reset/tow gating"
```

---

### Task 3: Nudges — RegionDiagnosis → one terse imperative line

**Files:**
- Create: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_nudges.py`:

```python
"""Tests for turning a RegionDiagnosis into a terse coaching nudge."""

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import Nudge, format_lap_block, nudge_from_diagnosis
from core.telemetry.loss_regions import LossRegion


def _diag(label="Eau Rouge", time_lost=0.4, braking=None, min_speed=0.0,
          throttle=None, drv_min=60.0, ref_min=60.0) -> RegionDiagnosis:
    return RegionDiagnosis(
        region=LossRegion(distance_start=1000.0, distance_end=1100.0,
                          time_lost=time_lost),
        label=label,
        braking_delta_m=braking,
        min_speed_delta_ms=min_speed,
        throttle_delta_m=throttle,
        driver_min_speed_ms=drv_min,
        reference_min_speed_ms=ref_min,
    )


def test_lifted_at_high_speed_corner_says_carry_it_flat():
    # Over-slowing (min_speed_delta strongly negative) at a fast corner
    n = nudge_from_diagnosis(_diag(min_speed=-4.0, drv_min=55.0, ref_min=59.0))
    assert n is not None
    assert "carry it flat" in n.message.lower()
    assert n.corner == "Eau Rouge"


def test_overslow_at_slow_corner_says_carry_more_apex_speed():
    n = nudge_from_diagnosis(
        _diag(label="La Source", min_speed=-4.0, drv_min=16.0, ref_min=20.0)
    )
    assert n is not None
    assert "apex speed" in n.message.lower()


def test_braking_early_says_brake_later():
    # Negative braking delta = driver brakes earlier than reference
    n = nudge_from_diagnosis(_diag(braking=-15.0, min_speed=-0.2))
    assert n is not None
    assert "brake later" in n.message.lower()
    assert "15" in n.detail


def test_braking_late_says_brake_earlier():
    n = nudge_from_diagnosis(_diag(braking=14.0, min_speed=-0.2))
    assert n is not None
    assert "brake earlier" in n.message.lower()


def test_late_throttle_says_back_to_power_earlier():
    n = nudge_from_diagnosis(_diag(throttle=30.0, min_speed=-0.2, braking=2.0))
    assert n is not None
    assert "power earlier" in n.message.lower()


def test_below_threshold_returns_none():
    # Everything tiny → nothing worth saying
    n = nudge_from_diagnosis(_diag(braking=2.0, min_speed=-0.5, throttle=3.0))
    assert n is None


def test_min_speed_dominates_braking_when_both_present():
    # A big lift outranks a modest braking error → headline is the lift
    n = nudge_from_diagnosis(_diag(braking=-9.0, min_speed=-5.0,
                                   drv_min=54.0, ref_min=59.0))
    assert "carry it flat" in n.message.lower()


def test_format_lap_block_lists_top_n():
    diags = [
        _diag(label="Eau Rouge", time_lost=2.0, min_speed=-4.0,
              drv_min=55.0, ref_min=59.0),
        _diag(label="Les Combes", time_lost=0.2, braking=-14.0),
        _diag(label="Pouhon", time_lost=0.1, throttle=30.0),
    ]
    block = format_lap_block(lap_number=6, lap_time=143.4,
                             total_delta=1.2, diagnoses=diags, top_n=2)
    assert "Lap 6" in block
    assert "Eau Rouge" in block
    assert "Les Combes" in block
    assert "Pouhon" not in block  # capped at top_n=2


def test_format_lap_block_baseline_when_no_diagnoses():
    block = format_lap_block(lap_number=1, lap_time=142.0,
                             total_delta=0.0, diagnoses=[], top_n=2,
                             is_baseline=True)
    assert "baseline" in block.lower()
    assert "Lap 1" in block
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.live.nudges'`

- [ ] **Step 3: Implement**

Create `core/live/nudges.py`:

```python
"""Turn a deterministic RegionDiagnosis into one terse coaching nudge.

No AI, no API key on the critical path. Each loss region yields at most
one imperative line plus the number that justifies it, chosen by salience:
a big apex-speed deficit (a lift) outranks a braking-point error, which
outranks a late throttle pickup. Thresholds are tuned during the spike so
only meaningful deltas speak.
"""

from dataclasses import dataclass

from core.coaching.debrief import RegionDiagnosis

# Salience thresholds — below these, a delta is not worth a nudge.
BRAKING_THRESHOLD_M = 8.0
MIN_SPEED_THRESHOLD_MS = 2.0
THROTTLE_THRESHOLD_M = 20.0
# Reference apex speed above this (m/s) = a fast/flat corner where the
# right coaching is "carry it flat" rather than "carry more apex speed".
# 50 m/s ≈ 180 km/h.
FLAT_CORNER_MIN_SPEED_MS = 50.0


@dataclass
class Nudge:
    """One imperative coaching line for a single corner."""

    corner: str
    message: str
    detail: str  # the justifying number, e.g. "-14 km/h" or "15m"


def _kmh(ms: float) -> float:
    return ms * 3.6


def nudge_from_diagnosis(diag: RegionDiagnosis) -> Nudge | None:
    """The single most salient nudge for this region, or None if nothing
    crosses threshold."""
    corner = diag.label

    # 1) Apex-speed deficit (a lift / over-slow) is the headline when big.
    if diag.min_speed_delta_ms <= -MIN_SPEED_THRESHOLD_MS:
        deficit_kmh = abs(_kmh(diag.min_speed_delta_ms))
        detail = f"-{deficit_kmh:.0f} km/h"
        if diag.reference_min_speed_ms >= FLAT_CORNER_MIN_SPEED_MS:
            return Nudge(corner, "carry it flat, you lifted", detail)
        return Nudge(corner, "carry more apex speed", detail)

    # 2) Braking-point error.
    if diag.braking_delta_m is not None and abs(diag.braking_delta_m) >= BRAKING_THRESHOLD_M:
        meters = abs(diag.braking_delta_m)
        if diag.braking_delta_m < 0:
            return Nudge(corner, "brake later", f"{meters:.0f}m")
        return Nudge(corner, "brake earlier", f"{meters:.0f}m")

    # 3) Late throttle pickup.
    if diag.throttle_delta_m is not None and diag.throttle_delta_m >= THROTTLE_THRESHOLD_M:
        return Nudge(corner, "back to power earlier", f"{diag.throttle_delta_m:.0f}m")

    return None


def _fmt_lap_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}:{secs:06.3f}"


def format_lap_block(
    lap_number: int,
    lap_time: float,
    total_delta: float,
    diagnoses: list[RegionDiagnosis],
    top_n: int = 2,
    is_baseline: bool = False,
) -> str:
    """The terminal block printed after one completed lap."""
    header = f"Lap {lap_number}  ({_fmt_lap_time(lap_time)}, {total_delta:+.1f}s)"
    if is_baseline:
        return f"{header}\n  baseline set — drive a faster lap for nudges"

    nudges = []
    for diag in diagnoses[:top_n]:
        n = nudge_from_diagnosis(diag)
        if n is not None:
            nudges.append(n)

    if not nudges:
        return f"{header}\n  clean lap — nothing to flag"

    lines = [header]
    for n in nudges:
        lines.append(f"  {n.corner} — {n.message}  ({n.detail})")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -v`
Expected: 9 PASS. Thresholds (`BRAKING_THRESHOLD_M` etc.) are tuned during live validation; do not weaken a test to pass — adjust the rule.

- [ ] **Step 5: Commit**

```bash
git add core/live/nudges.py tests/test_nudges.py
git commit -m "feat: deterministic nudges from RegionDiagnosis metrics"
```

---

### Task 4: Terminal entry point — drive pyirsdk, wire the loop, print nudges

**Files:**
- Create: `scripts/live_coach.py`

This is the thin, manually-validated driver. It contains no logic that isn't already tested in Tasks 1–3; it only adapts pyirsdk to sample dicts and orchestrates. There is no unit test (it needs a live sim); it is validated by the user driving real sessions.

- [ ] **Step 1: Implement the entry point**

Create `scripts/live_coach.py`:

```python
"""Live between-lap coaching — terminal spike.

Run this with iRacing open and on track:

    .venv/Scripts/python.exe scripts/live_coach.py

After each completed flying lap it prints coaching nudges derived from the
existing loss-region engine, comparing the lap to your best lap so far in
the session. Pit laps, out/in-laps, and resets are suppressed.

This is the de-risk spike: it proves lap-boundary detection and nudge
quality before any HUD is built. All real logic lives in tested modules
under core/live/ and core/coaching/; this file only drives pyirsdk.
"""

import sys
import time
from pathlib import Path

# Ensure project root on path when run as a script.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import irsdk  # noqa: E402

from core.coaching.debrief import build_debrief  # noqa: E402
from core.live.lap_buffer import SAMPLE_CHANNELS  # noqa: E402
from core.live.nudges import format_lap_block  # noqa: E402
from core.live.session_reader import LapBoundaryTracker  # noqa: E402
from core.telemetry.normalizer import Normalizer  # noqa: E402
from core.track.lovely_seeder import seed_track_from_lovely  # noqa: E402
from core.track.track_db import TrackDB  # noqa: E402

DB_PATH = Path("data/tracks.db")
# Channels the tracker + buffer need: the normalizer-ready set plus the
# boundary/validity flags the state machine reads.
READ_CHANNELS = SAMPLE_CHANNELS + ["Lap", "OnPitRoad", "PlayerTrackSurface"]
TICK_SECONDS = 1.0 / 60.0


def _parse_track_length_km(weekend_info: dict) -> float:
    """TrackLength like '7.00 km' -> 7.0 (km)."""
    raw = str(weekend_info.get("TrackLength", "0 km"))
    try:
        return float(raw.split()[0])
    except (ValueError, IndexError):
        return 0.0


def _session_meta(ir: "irsdk.IRSDK") -> tuple[str, float, str]:
    """Return (track_id_str, track_length_m, track_name) from live YAML."""
    weekend = ir["WeekendInfo"] or {}
    track_id = str(weekend.get("TrackID", "") or "")
    track_length_m = _parse_track_length_km(weekend) * 1000.0
    track_name = str(weekend.get("TrackDisplayName", "track"))
    return track_id, track_length_m, track_name


def _load_corners(track_id: str, track_name: str, track_length_m: float) -> list:
    """Named corners for labeling, seeding from lovely-track-data on first use."""
    if not track_id:
        return []
    db = TrackDB(DB_PATH)
    if db.get_track(track_id) is None:
        # No track row → nothing to attach corners to; skip seeding.
        return []
    corners = db.get_corners(track_id)
    if not corners:
        try:
            seed_track_from_lovely(
                db, track_id=track_id,
                ibt_track_name=track_name.lower().replace(" ", " "),
                track_length_m=track_length_m,
            )
            corners = db.get_corners(track_id)
        except Exception:
            corners = []
    return corners


def main() -> None:
    ir = irsdk.IRSDK()
    print("Race Engineer live coach — waiting for iRacing…")

    tracker = LapBoundaryTracker()
    normalizer = Normalizer()
    session_best = None
    corners: list = []
    meta_loaded = False

    try:
        while True:
            if not (ir.is_initialized and ir.is_connected):
                ir.shutdown()
                meta_loaded = False
                ir.startup()
                time.sleep(0.5)
                continue

            if not meta_loaded:
                track_id, track_length_m, track_name = _session_meta(ir)
                corners = _load_corners(track_id, track_name, track_length_m)
                session_best = None
                meta_loaded = True
                print(f"Connected: {track_name}. Drive a lap to set baseline.")

            ir.freeze_var_buffer_latest()
            sample = {ch: ir[ch] for ch in READ_CHANNELS}

            completed = tracker.feed(sample)
            if completed is not None:
                _, track_length_m, _ = _session_meta(ir)
                nlap = normalizer.normalize_lap(
                    completed.dataframe, completed.lap_number, track_length_m
                )
                if nlap.is_valid:
                    if session_best is None:
                        session_best = nlap
                        print(format_lap_block(
                            nlap.lap_number, nlap.lap_time, 0.0, [],
                            is_baseline=True,
                        ))
                    else:
                        result = build_debrief(nlap, session_best, corners)
                        print(format_lap_block(
                            nlap.lap_number, nlap.lap_time,
                            result.total_time_delta, result.diagnoses,
                        ))
                        if nlap.lap_time < session_best.lap_time:
                            session_best = nlap

            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ir.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports and starts without a sim**

Run: `.venv/Scripts/python.exe -c "import ast; ast.parse(open('scripts/live_coach.py', encoding='utf-8').read()); print('syntax ok')"`
Expected: `syntax ok`

Then verify the imports resolve and it reaches the wait loop (no sim running, so it will print the waiting line and idle — interrupt after a moment):

Run: `.venv/Scripts/python.exe scripts/live_coach.py` then press Ctrl+C after it prints the waiting message.
Expected: prints "Race Engineer live coach — waiting for iRacing…" then "Stopped." on Ctrl+C, no traceback.

- [ ] **Step 3: Run the full suite to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all prior tests still pass plus the 22 new ones (5 + 8 + 9); existing skips unchanged.

- [ ] **Step 4: Commit**

```bash
git add scripts/live_coach.py
git commit -m "feat: live coach terminal entry point (pyirsdk driver + wiring)"
```

---

### Task 5: Docs — record the spike and how to run it

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

Add to the architecture tree a `core/live/` section (`lap_buffer.py`, `session_reader.py`, `nudges.py`) and `scripts/live_coach.py`. Add a "Live Coaching Spike" entry under Current Status (after Stage 1) marking it complete and noting it awaits live driving validation. Add an Implementation Notes section "Live Coaching Spike" capturing: the reused-engine principle (build_debrief runs on live laps unchanged), the `LapBoundaryTracker` gating rules (pit/reset/tow/too-short suppressed; coverage left to the Normalizer's is_valid), the nudge salience order and thresholds (min-speed > braking > throttle; 8m / 2 m/s / 20m), and the run command (`.venv/Scripts/python.exe scripts/live_coach.py` with iRacing on track). Run `.venv/Scripts/python.exe -m pytest -q` first and record the exact passed/skipped counts.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: live coaching spike status and run instructions"
```

---

## Self-review notes

- **Spec coverage:** session reader / lap-boundary state machine (T2), lap buffer (T1), deterministic nudges (T3), terminal entry point (T4), docs (T5). The two de-risk unknowns map directly: lap-boundary reliability → T2's synthetic scenarios; nudge naturalness → T3's rules + live validation in T4. Reuse-unchanged of `build_debrief`/`Normalizer` is honored (no core edits).
- **Validity-gate split is deliberate:** the tracker does coarse gating (pit/reset/too-short) because those need the live per-tick flags; fine validity (90% coverage, distance jumps) is the Normalizer's existing `is_valid`, checked in T4 before debriefing. The spec's "sustained off-track" gate is covered transitively — an off-track excursion that corrupts the distance trace fails the Normalizer's distance-jump check; pure off-tracks that don't corrupt telemetry are (correctly) not suppressed, matching the offline pipeline's 10%-pace philosophy.
- **Type consistency:** `CompletedLap(lap_number, dataframe)` produced in T2, consumed in T4; `Nudge(corner, message, detail)` and `format_lap_block(...)`/`nudge_from_diagnosis(...)` defined in T3, used in T4; `SAMPLE_CHANNELS` defined in T1, reused in T2's test and T4's `READ_CHANNELS`.
- **Manual-validation honesty:** T4 has no unit test by design (needs a live sim); all testable logic is in T1–T3 pure modules. T4's acceptance is the user driving — which IS the spike's purpose.
- **Deferred per spec:** NiceGUI HUD, Web Speech voice, AI nudge rewrite, Streamlit cleanup — none appear here; they are Plan 2 / separate tracks.
