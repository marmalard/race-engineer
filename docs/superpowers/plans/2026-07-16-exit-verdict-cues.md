# Exit Verdict Cues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After an approach cue speaks for a corner, evaluate the driver's execution live and speak a one-clause verdict 1–2 s after the exit; gate cues in race sessions behind a fault-persistence filter with a `--race-cues` toggle.

**Architecture:** Pure state machine (`VerdictWatcher`) beside the `PromptScheduler`, fed `(lap_dist, speed, brake, throttle)` ticks. One plan builder arms prompts and verdicts from the same diagnoses. Race gate = pure `FaultStreakTracker` + session-type helper. Core analysis engine untouched except three additive reference fields on `RegionDiagnosis` (the `reference_brake_onset_m` precedent).

**Tech Stack:** Python 3.11+, dataclasses, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-16-exit-verdict-cues-design.md`

**Execution environment:** Run in a git worktree, NOT the main checkout — the production Streamlit app hot-reloads the main checkout (project rule since 2026-07-15). Tests: `.venv/Scripts/python.exe -m pytest -q` (the worktree venv is hardlinked by uv; create with `uv sync` inside the worktree).

**File map:**
- Modify: `core/live/nudges.py` — `FaultKind` enum + `fault_kinds_from_diagnosis`; `approach_cue_from_diagnosis` refactored on top (cue strings byte-identical)
- Modify: `core/coaching/debrief.py` — 3 additive `RegionDiagnosis` fields
- Create: `core/live/exit_verdict.py` — `crossed`, `ArmedVerdict`, bucketing + phrasing, `VerdictWatcher`
- Modify: `core/live/prompt_scheduler.py` — `build_plan` returning (prompts, verdicts); `build_schedule` becomes a thin wrapper; `_crossed` aliases `exit_verdict.crossed`
- Create: `core/live/race_gate.py` — `RaceCueMode`, `current_session_type`, `FaultStreakTracker`, `gate_diagnoses`
- Modify: `scripts/live_coach.py` — `--race-cues` flag, SessionNum channel, watcher wiring
- Create: `tests/test_exit_verdict.py`, `tests/test_race_gate.py`
- Modify: `tests/test_nudges.py`, `tests/test_prompt_scheduler.py`, `tests/test_live_coach_helpers.py`

---

### Task 1: FaultKind enum + fault_kinds_from_diagnosis (nudges.py)

The cue and the verdict must derive from ONE fault-ranking function so they can never disagree. Extract the salience ladder that `approach_cue_from_diagnosis` currently hard-codes, then rebuild the cue on top of it. **Every existing cue string must remain byte-identical** — `tests/test_nudges.py` pins them.

**Files:**
- Modify: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_nudges.py` (it already imports from `core.live.nudges`; add `FaultKind, fault_kinds_from_diagnosis` to that import):

```python
class TestFaultKinds:
    def test_ladder_order_all_faults(self):
        # A diagnosis with every fault crossing threshold ranks by the
        # salience ladder: lift > braking > release > exit > throttle.
        d = _diag(min_speed_delta=-3.0, braking_delta=-15.0,
                  release_delta=-12.0, exit_speed_delta=-3.0,
                  throttle_delta=25.0)
        assert fault_kinds_from_diagnosis(d) == [
            FaultKind.LIFT, FaultKind.BRAKING, FaultKind.RELEASE,
            FaultKind.EXIT_SPEED, FaultKind.THROTTLE,
        ]

    def test_below_threshold_faults_excluded(self):
        d = _diag(min_speed_delta=-1.0, braking_delta=-15.0)
        assert fault_kinds_from_diagnosis(d) == [FaultKind.BRAKING]

    def test_clean_diagnosis_is_empty(self):
        assert fault_kinds_from_diagnosis(_diag()) == []

    def test_cue_agrees_with_kinds(self):
        # The cue speaks iff kinds is non-empty — one ranking function.
        d = _diag(braking_delta=-15.0)
        assert fault_kinds_from_diagnosis(d) != []
        assert approach_cue_from_diagnosis(d) is not None
        assert approach_cue_from_diagnosis(_diag()) is None
```

`_diag` is the existing test helper in `tests/test_nudges.py`; extend its keyword defaults if it lacks any of these fields (all zero/None defaults so existing calls are unaffected).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -q`
Expected: FAIL — `ImportError: cannot import name 'FaultKind'`

- [ ] **Step 3: Implement in `core/live/nudges.py`**

Add after the constants block (`COARSE_COUPLE_MAX_LENGTHS`):

```python
class FaultKind(Enum):
    """One coached fault dimension — the shared vocabulary of the
    approach cue and the exit verdict (they derive from the same
    ranking so they can never disagree)."""

    LIFT = "lift"
    BRAKING = "braking"
    RELEASE = "release"
    EXIT_SPEED = "exit_speed"
    THROTTLE = "throttle"


def fault_kinds_from_diagnosis(diag: RegionDiagnosis) -> "list[FaultKind]":
    """Faults crossing threshold, ordered by the salience ladder:
    lift > braking > release > exit speed > throttle."""
    kinds: list[FaultKind] = []
    if diag.min_speed_delta_ms <= -MIN_SPEED_THRESHOLD_MS:
        kinds.append(FaultKind.LIFT)
    if (diag.braking_delta_m is not None
            and abs(diag.braking_delta_m) >= BRAKING_THRESHOLD_M):
        kinds.append(FaultKind.BRAKING)
    if (diag.brake_release_delta_m is not None
            and diag.brake_release_delta_m <= -RELEASE_THRESHOLD_M):
        kinds.append(FaultKind.RELEASE)
    if diag.exit_speed_delta_ms <= -EXIT_SPEED_THRESHOLD_MS:
        kinds.append(FaultKind.EXIT_SPEED)
    if (diag.throttle_delta_m is not None
            and diag.throttle_delta_m >= THROTTLE_THRESHOLD_M):
        kinds.append(FaultKind.THROTTLE)
    return kinds
```

Add `from enum import Enum` to the module imports.

Refactor `approach_cue_from_diagnosis` to build from the kinds (strings byte-identical to today's):

```python
def _cue_phrase(kind: FaultKind, diag: RegionDiagnosis) -> str:
    if kind is FaultKind.LIFT:
        if diag.reference_min_speed_ms >= FLAT_CORNER_MIN_SPEED_MS:
            return "carry it flat, don't lift"
        return "carry more apex speed"
    if kind is FaultKind.BRAKING:
        coarse = _coarse_length_phrase(diag.braking_delta_m)
        return (f"brake {coarse} later" if diag.braking_delta_m < 0
                else f"brake {coarse} earlier")
    if kind is FaultKind.RELEASE:
        return "carry the brakes deeper"
    if kind is FaultKind.EXIT_SPEED:
        return "prioritize the exit"
    return "get to throttle earlier on exit"


def approach_cue_from_diagnosis(diag: RegionDiagnosis) -> "str | None":
    """One combined approach cue for a corner, or None if nothing crosses
    threshold. Spoken ~300m before the corner, so it names no corner ('here')
    and joins the top APPROACH_CUE_MAX_FAULTS faults by the salience ladder:
    lift > braking > release > exit > throttle."""
    kinds = fault_kinds_from_diagnosis(diag)
    if not kinds:
        return None
    phrases = [_cue_phrase(k, diag) for k in kinds[:APPROACH_CUE_MAX_FAULTS]]
    return "Coming up — " + ", ".join(phrases) + "."
```

Delete the old body's inline fault list (the five `if` blocks appending strings) — `_cue_phrase` + `fault_kinds_from_diagnosis` replace it.

- [ ] **Step 4: Run the nudges tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py tests/test_prompt_scheduler.py -q`
Expected: ALL PASS — including every pre-existing exact-string cue test (byte-identical refactor).

- [ ] **Step 5: Commit**

```bash
git add core/live/nudges.py tests/test_nudges.py
git commit -m "refactor(nudges): FaultKind ladder extracted; cue built on it (strings identical)"
```

---

### Task 2: Additive reference fields on RegionDiagnosis (debrief.py)

The verdict watcher needs absolute reference positions for release, throttle-on, and exit speed — `_diagnose_region` already computes all three internally; expose them exactly as `reference_brake_onset_m` was exposed for the prompts. Additive with defaults: every existing constructor call keeps working.

**Files:**
- Modify: `core/coaching/debrief.py:39-41` (dataclass), `core/coaching/debrief.py:128-141` (return)
- Test: `tests/test_debrief.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_debrief.py` (reuse its existing synthetic-lap helpers for two laps where the reference brakes, trails to the apex, and gets back to full throttle — the file already builds such traces for the release/exit metric tests):

```python
def test_reference_absolutes_exposed_for_verdicts():
    # The three new fields mirror reference_brake_onset_m: absolute
    # distances / speed on the ALIGNED reference, for live verdicts.
    result = build_debrief(_driver_lap(), _reference_lap(), [])
    d = result.diagnoses[0]
    assert d.reference_throttle_on_m is not None
    assert d.reference_exit_speed_ms is not None
    # release absolute is None unless the reference trails (same trail
    # guard as brake_release_delta_m)
    assert (d.reference_release_m is None) == (d.brake_release_delta_m is None)
```

(Adapt `_driver_lap`/`_reference_lap` to whatever the existing fixture-builders in that file are named — use the pair the brake-release tests use.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_debrief.py -q`
Expected: FAIL — `AttributeError: ... 'reference_throttle_on_m'`

- [ ] **Step 3: Implement**

In the `RegionDiagnosis` dataclass, after `reference_brake_onset_m`:

```python
    # Absolute reference positions for live exit verdicts (same idea as
    # reference_brake_onset_m). None when the underlying onset is absent;
    # release also None when the reference doesn't trail (trail guard).
    reference_release_m: float | None = None
    reference_throttle_on_m: float | None = None
    reference_exit_speed_ms: float | None = None
```

In `_diagnose_region`'s return statement, after the `reference_brake_onset_m=` entry:

```python
        reference_release_m=(
            ref_release * interval_m
            if reference_trails and ref_release is not None
            else None
        ),
        reference_throttle_on_m=(
            ref_thr * interval_m if ref_thr is not None else None
        ),
        reference_exit_speed_ms=float(reference.speed[exit_idx]),
```

- [ ] **Step 4: Run the debrief tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_debrief.py tests/test_prompt_scheduler.py tests/test_nudges.py -q`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add core/coaching/debrief.py tests/test_debrief.py
git commit -m "feat(debrief): expose reference release/throttle/exit absolutes for live verdicts"
```

---

### Task 3: Race gate module (race_gate.py)

**Files:**
- Create: `core/live/race_gate.py`
- Test: `tests/test_race_gate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_race_gate.py`:

```python
"""Race persistence gate: session-type detection + fault streaks."""

from core.live.nudges import FaultKind
from core.live.race_gate import (
    RACE_STREAK_MIN,
    FaultStreakTracker,
    current_session_type,
    gate_diagnoses,
)
from tests.test_nudges import _diag


SESSION_INFO = {"Sessions": [
    {"SessionNum": 0, "SessionType": "Practice"},
    {"SessionNum": 1, "SessionType": "Lone Qualify"},
    {"SessionNum": 2, "SessionType": "Race"},
]}


class TestCurrentSessionType:
    def test_finds_session_by_num(self):
        assert current_session_type(SESSION_INFO, 2) == "Race"
        assert current_session_type(SESSION_INFO, 0) == "Practice"

    def test_unknown_num_or_malformed_info_is_empty(self):
        assert current_session_type(SESSION_INFO, 9) == ""
        assert current_session_type({}, 0) == ""
        assert current_session_type(None, 0) == ""


class TestFaultStreakTracker:
    def test_streak_builds_over_consecutive_laps(self):
        t = FaultStreakTracker()
        t.update({("T3", FaultKind.BRAKING)})
        assert t.streak("T3", FaultKind.BRAKING) == 1
        t.update({("T3", FaultKind.BRAKING)})
        assert t.streak("T3", FaultKind.BRAKING) == 2

    def test_missing_lap_resets_streak(self):
        t = FaultStreakTracker()
        t.update({("T3", FaultKind.BRAKING)})
        t.update(set())  # clean lap at T3
        assert t.streak("T3", FaultKind.BRAKING) == 0

    def test_fault_kind_change_is_a_new_streak(self):
        t = FaultStreakTracker()
        t.update({("T3", FaultKind.BRAKING)})
        t.update({("T3", FaultKind.LIFT)})
        assert t.streak("T3", FaultKind.BRAKING) == 0
        assert t.streak("T3", FaultKind.LIFT) == 1


class TestGateDiagnoses:
    def _tracker_with_streak(self, n):
        t = FaultStreakTracker()
        for _ in range(n):
            t.update({("La Source", FaultKind.BRAKING)})
        return t

    def test_practice_passes_everything_through(self):
        diags = [_diag(braking_delta=-15.0)]
        out = gate_diagnoses(diags, mode="persistent", is_race=False,
                             tracker=FaultStreakTracker())
        assert out == diags

    def test_race_persistent_needs_streak(self):
        diags = [_diag(braking_delta=-15.0)]
        below = self._tracker_with_streak(RACE_STREAK_MIN - 1)
        at = self._tracker_with_streak(RACE_STREAK_MIN)
        assert gate_diagnoses(diags, mode="persistent", is_race=True,
                              tracker=below) == []
        assert gate_diagnoses(diags, mode="persistent", is_race=True,
                              tracker=at) == diags

    def test_race_off_silences_and_full_passes(self):
        diags = [_diag(braking_delta=-15.0)]
        t = self._tracker_with_streak(5)
        assert gate_diagnoses(diags, mode="off", is_race=True, tracker=t) == []
        assert gate_diagnoses(diags, mode="full", is_race=True,
                              tracker=FaultStreakTracker()) == diags
```

(`_diag` in `tests/test_nudges.py` sets `label="La Source"` — the gate test relies on that; adjust the label literal if the helper differs.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.live.race_gate'`

- [ ] **Step 3: Create `core/live/race_gate.py`**

```python
"""Race-session persistence gate for approach cues + exit verdicts.

Pure — no pyirsdk, no I/O. In a Race session (mode 'persistent', the
default) a corner is only cued once its primary fault has persisted
RACE_STREAK_MIN consecutive laps: one scrappy corner while dicing stays
silent; a repeatable deficit gets flagged. Practice/qualifying behavior
is unchanged. Session type MUST come from SessionInfo's per-session
SessionType — WeekendInfo.EventType reads "Race" for practice sessions
on a race server (the pre-race-chunk lesson, 2026-07-15).
"""

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import FaultKind, fault_kinds_from_diagnosis

RACE_STREAK_MIN = 2
RACE_CUE_MODES = ("full", "persistent", "off")


def current_session_type(session_info: "dict | None", session_num: int) -> str:
    """SessionType string for the current SessionNum, or '' when unknown."""
    if not isinstance(session_info, dict):
        return ""
    for s in session_info.get("Sessions", []) or []:
        if isinstance(s, dict) and s.get("SessionNum") == session_num:
            return str(s.get("SessionType", "") or "")
    return ""


class FaultStreakTracker:
    """Consecutive-lap streaks per (corner label, primary FaultKind)."""

    def __init__(self) -> None:
        self._streaks: dict[tuple[str, FaultKind], int] = {}

    def update(self, lap_faults: "set[tuple[str, FaultKind]]") -> None:
        """Feed one completed lap's (label, primary fault) pairs."""
        self._streaks = {
            key: self._streaks.get(key, 0) + 1 for key in lap_faults
        }

    def streak(self, label: str, kind: FaultKind) -> int:
        return self._streaks.get((label, kind), 0)


def gate_diagnoses(
    diagnoses: list[RegionDiagnosis],
    *,
    mode: str,
    is_race: bool,
    tracker: FaultStreakTracker,
) -> list[RegionDiagnosis]:
    """The diagnoses allowed to cue this lap. Non-race sessions and mode
    'full' pass everything; 'off' silences races; 'persistent' requires
    the primary fault to have persisted RACE_STREAK_MIN laps."""
    if not is_race or mode == "full":
        return list(diagnoses)
    if mode == "off":
        return []
    allowed = []
    for d in diagnoses:
        kinds = fault_kinds_from_diagnosis(d)
        if kinds and tracker.streak(d.label, kinds[0]) >= RACE_STREAK_MIN:
            allowed.append(d)
    return allowed
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_gate.py -q`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add core/live/race_gate.py tests/test_race_gate.py
git commit -m "feat(live): race persistence gate - session type, fault streaks, mode filter"
```

---

### Task 4: Bucketing + phrasing (exit_verdict.py, pure functions)

**Files:**
- Create: `core/live/exit_verdict.py`
- Test: `tests/test_exit_verdict.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exit_verdict.py`:

```python
"""Exit verdicts: bucketing precedence, phrasing, and the watcher."""

from core.live.exit_verdict import (
    IMPROVED_FRACTION,
    bucket_for,
    crossed,
    verdict_text,
)
from core.live.nudges import FaultKind


class TestBucketPrecedence:
    # BRAKING threshold is 8.0 m (imported from nudges).

    def test_under_threshold_is_fixed(self):
        assert bucket_for(FaultKind.BRAKING, -5.0, -15.0) == "fixed"

    def test_sign_flip_past_threshold_overcorrects_braking(self):
        # Coached "later" (was early, -15); driver now brakes 10m LATE.
        assert bucket_for(FaultKind.BRAKING, 10.0, -15.0) == "overcorrected"

    def test_overcorrect_beats_better_precedence(self):
        # Sign flipped AND numerically under half of last lap: must be
        # overcorrected, never "better still late" with the wrong word
        # (the spec's precedence bug).
        assert bucket_for(FaultKind.BRAKING, 9.0, -30.0) == "overcorrected"

    def test_shrunk_but_not_fixed_is_better(self):
        assert bucket_for(FaultKind.BRAKING, -10.0, -25.0) == "better"

    def test_unchanged(self):
        assert bucket_for(FaultKind.BRAKING, -14.0, -15.0) == "unchanged"

    def test_speed_faults_never_overcorrect(self):
        # Carrying MORE speed than the reference is not a fault to scold.
        assert bucket_for(FaultKind.LIFT, 3.0, -4.0) == "fixed"
        assert bucket_for(FaultKind.EXIT_SPEED, 3.0, -4.0) == "fixed"

    def test_early_throttle_is_fixed_not_overcorrected(self):
        assert bucket_for(FaultKind.THROTTLE, -25.0, 30.0) == "fixed"

    def test_release_overcorrects(self):
        # Coached "carry them deeper" (was -12); now 11m PAST the ref.
        assert bucket_for(FaultKind.RELEASE, 11.0, -12.0) == "overcorrected"


class TestVerdictText:
    def test_fixed(self):
        assert verdict_text(FaultKind.BRAKING, "fixed", -3.0) == "That's it."

    def test_braking_directions(self):
        assert (verdict_text(FaultKind.BRAKING, "better", -10.0)
                == "Better — still a touch early.")
        assert (verdict_text(FaultKind.BRAKING, "unchanged", 12.0)
                == "Still late on the brakes.")

    def test_overcorrect_lines(self):
        assert (verdict_text(FaultKind.BRAKING, "overcorrected", 10.0)
                == "Too far — back it off.")
        assert (verdict_text(FaultKind.RELEASE, "overcorrected", 11.0)
                == "Too deep — release sooner.")

    def test_speed_and_throttle_lines(self):
        assert (verdict_text(FaultKind.LIFT, "unchanged", -4.0)
                == "Still slow through there.")
        assert (verdict_text(FaultKind.EXIT_SPEED, "better", -2.5)
                == "Better — still a touch slow off the corner.")
        assert (verdict_text(FaultKind.THROTTLE, "unchanged", 30.0)
                == "Still late to throttle.")


class TestCrossed:
    def test_forward_and_wrap(self):
        assert crossed(480.0, 510.0, 500.0)
        assert not crossed(510.0, 520.0, 500.0)
        assert crossed(6900.0, 20.0, 6950.0)  # start/finish wrap
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exit_verdict.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.live.exit_verdict'`

- [ ] **Step 3: Create `core/live/exit_verdict.py`** (pure functions half; the watcher lands in Task 5)

```python
"""At-exit corner verdicts — closing the approach-cue feedback loop.

Pure state machine, no pyirsdk, no I/O (PromptScheduler's shape). After
an approach cue speaks for a corner, VerdictWatcher observes the
driver's execution of THAT corner from live ticks and speaks a
one-clause bucket verdict ~100 m past the exit: "That's it." /
"Too far — back it off." / "Better — still a touch late." /
"Still late on the brakes." Quantity-free by design — the driver is at
speed and cannot act on numbers.

Anti-drift locks: thresholds and search windows are IMPORTED from their
homes (nudges / debrief), never copied; a coupling test replays a real
lap and asserts the live brake-onset observation matches the offline
diagnosis. Live LapDist vs the aligned reference carries the same small
alignment tolerance the approach-cue triggers already accept.

Spec: docs/superpowers/specs/2026-07-16-exit-verdict-cues-design.md
"""

from dataclasses import dataclass

from core.coaching.debrief import (
    BRAKE_SEARCH_BACK_M,
    BRAKE_THRESHOLD,
    THROTTLE_THRESHOLD,
    RegionDiagnosis,
)
from core.live.nudges import (
    BRAKING_THRESHOLD_M,
    EXIT_SPEED_THRESHOLD_MS,
    MIN_SPEED_THRESHOLD_MS,
    RELEASE_THRESHOLD_M,
    THROTTLE_THRESHOLD_M,
    FaultKind,
)

# Verdict fires this far past the region end — the end of the offline
# throttle search window, ~1-2s past the exit at speed. Tunable from
# data/live_sessions logs like every live threshold before it.
VERDICT_POINT_M = 100.0
# "Better" = live magnitude under this fraction of last lap's.
IMPROVED_FRACTION = 0.5
# Only distance faults where going PAST the reference is genuinely risky
# get the overcorrect call-out; more speed / earlier throttle than the
# reference is not a fault to scold ("fixed").
OVERCORRECT_KINDS = frozenset({FaultKind.BRAKING, FaultKind.RELEASE})

_THRESHOLDS = {
    FaultKind.LIFT: MIN_SPEED_THRESHOLD_MS,
    FaultKind.BRAKING: BRAKING_THRESHOLD_M,
    FaultKind.RELEASE: RELEASE_THRESHOLD_M,
    FaultKind.EXIT_SPEED: EXIT_SPEED_THRESHOLD_MS,
    FaultKind.THROTTLE: THROTTLE_THRESHOLD_M,
}


def crossed(prev: float, curr: float, trigger: float) -> bool:
    """True iff the car crossed `trigger` between two distance samples.
    curr < prev is treated as a start/finish wrap (LapDist is spline-
    monotonic within a lap; genuine reversals are covered by fired
    flags). Shared with PromptScheduler."""
    if curr >= prev:
        return prev < trigger <= curr
    return trigger > prev or trigger <= curr


def bucket_for(kind: FaultKind, live_delta: float, last_delta: float) -> str:
    """Bucket the live delta for the coached fault. Precedence (spec):
    fixed -> overcorrected -> better -> unchanged. Overcorrection is
    checked BEFORE better so a sign-flipped delta can never produce
    'still a touch late' with the wrong direction word."""
    threshold = _THRESHOLDS[kind]
    if abs(live_delta) < threshold:
        return "fixed"
    same_side = (live_delta > 0) == (last_delta > 0)
    if not same_side:
        return "overcorrected" if kind in OVERCORRECT_KINDS else "fixed"
    if abs(live_delta) < IMPROVED_FRACTION * abs(last_delta):
        return "better"
    return "unchanged"


def verdict_text(kind: FaultKind, bucket: str, live_delta: float) -> str:
    """The spoken one-clause verdict. Exact strings are pinned by tests
    (like nudges); tune wording there, nowhere else."""
    if bucket == "fixed":
        return "That's it."
    if bucket == "overcorrected":
        if kind is FaultKind.RELEASE:
            return "Too deep — release sooner."
        return "Too far — back it off."
    better = bucket == "better"
    if kind is FaultKind.BRAKING:
        word = "late" if live_delta > 0 else "early"
        return (f"Better — still a touch {word}." if better
                else f"Still {word} on the brakes.")
    if kind is FaultKind.LIFT:
        return ("Better — still a bit slow." if better
                else "Still slow through there.")
    if kind is FaultKind.RELEASE:
        return ("Better — carry them a touch deeper." if better
                else "Still off the brakes early.")
    if kind is FaultKind.EXIT_SPEED:
        return ("Better — still a touch slow off the corner." if better
                else "Still slow off the corner.")
    return ("Better — still a touch late to throttle." if better
            else "Still late to throttle.")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exit_verdict.py -q`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add core/live/exit_verdict.py tests/test_exit_verdict.py
git commit -m "feat(live): exit-verdict bucketing + phrasing (precedence-safe, exact-string tested)"
```

---

### Task 5: VerdictWatcher state machine (exit_verdict.py)

**Files:**
- Modify: `core/live/exit_verdict.py`
- Test: `tests/test_exit_verdict.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_exit_verdict.py`:

```python
from core.coaching.debrief import RegionDiagnosis
from core.live.exit_verdict import ArmedVerdict, VerdictResult, VerdictWatcher
from core.telemetry.loss_regions import LossRegion

TRACK_LEN = 7000.0


def _armed(span=(1000.0, 1100.0), braking_delta=-15.0, ref_onset=980.0,
           faults=(FaultKind.BRAKING,)) -> ArmedVerdict:
    diag = RegionDiagnosis(
        region=LossRegion(distance_start=span[0], distance_end=span[1],
                          time_lost=0.5),
        label="La Source",
        braking_delta_m=braking_delta,
        min_speed_delta_ms=0.0,
        throttle_delta_m=None,
        driver_min_speed_ms=20.0,
        reference_min_speed_ms=20.0,
        reference_brake_onset_m=ref_onset,
    )
    return ArmedVerdict(diagnosis=diag, faults=list(faults))


def _drive(watcher, start, end, step=10.0, speed=40.0, brake=0.0,
           throttle=0.0):
    """Feed a straight run of ticks; return the first VerdictResult."""
    d = start
    result = None
    while d <= end:
        r = watcher.feed(d, speed, brake, throttle)
        result = result or r
        d += step
    return result


class TestVerdictWatcher:
    def test_braking_verdict_fires_past_exit(self):
        w = VerdictWatcher()
        w.set_plan([_armed()], TRACK_LEN)
        # Approach: no brake until 990 (10m after ref onset 980 = fixed,
        # under the 8m threshold... use 995 for a clear 15m late -> but
        # last lap was EARLY (-15) so 15m late = overcorrected).
        _drive(w, 700.0, 985.0)                      # no brake yet
        w.feed(990.0, 30.0, 0.5, 0.0)                # brake onset at 990
        _drive(w, 1000.0, 1190.0, speed=25.0)        # through the corner
        r = w.feed(1210.0, 30.0, 0.0, 1.0)           # crosses 1100+100
        assert isinstance(r, VerdictResult)
        assert r.label == "La Source"
        assert r.kind is FaultKind.BRAKING
        # onset 990 vs ref 980 -> +10 late; last lap -15 early -> flip
        assert r.bucket == "overcorrected"
        assert r.text == "Too far — back it off."

    def test_fixed_when_onset_matches_reference(self):
        w = VerdictWatcher()
        w.set_plan([_armed()], TRACK_LEN)
        _drive(w, 700.0, 975.0)
        w.feed(983.0, 30.0, 0.5, 0.0)                # 3m late: under 8m
        _drive(w, 990.0, 1190.0, speed=25.0)
        r = w.feed(1210.0, 30.0, 0.0, 1.0)
        assert r.bucket == "fixed"
        assert r.text == "That's it."

    def test_no_brake_observed_is_silent(self):
        w = VerdictWatcher()
        w.set_plan([_armed()], TRACK_LEN)
        r = _drive(w, 700.0, 1250.0)                 # never brakes
        assert r is None                             # insufficient data

    def test_fires_once_per_lap_and_rearm(self):
        w = VerdictWatcher()
        w.set_plan([_armed()], TRACK_LEN)
        _drive(w, 700.0, 975.0)
        w.feed(983.0, 30.0, 0.5, 0.0)
        _drive(w, 990.0, 1190.0)
        assert w.feed(1210.0, 30.0, 0.0, 1.0) is not None
        assert w.feed(1220.0, 30.0, 0.0, 1.0) is None   # fired flag holds
        w.rearm()
        _drive(w, 700.0, 975.0)
        w.feed(983.0, 30.0, 0.5, 0.0)
        _drive(w, 990.0, 1190.0)
        assert w.feed(1210.0, 30.0, 0.0, 1.0) is not None

    def test_reset_position_prevents_false_wrap_fire(self):
        w = VerdictWatcher()
        w.set_plan([_armed(span=(5400.0, 5500.0), ref_onset=5380.0)],
                   TRACK_LEN)
        w.feed(5300.0, 40.0, 0.5, 0.0)
        w.reset_position()                           # towed to pits
        assert w.feed(300.0, 20.0, 0.0, 0.0) is None  # primes, no fire
        assert w.feed(400.0, 20.0, 0.0, 0.0) is None

    def test_lift_verdict_uses_observed_min_speed(self):
        armed = _armed(faults=(FaultKind.LIFT,))
        armed.diagnosis.min_speed_delta_ms = -4.0    # last lap: 4 m/s slow
        w = VerdictWatcher()
        w.set_plan([armed], TRACK_LEN)
        _drive(w, 700.0, 990.0, speed=40.0)
        _drive(w, 1000.0, 1090.0, speed=19.0)        # min 19 vs ref 20:
        r = _drive(w, 1100.0, 1250.0, speed=30.0)    # 1 m/s slow -> fixed
        assert r is not None and r.bucket == "fixed"

    def test_empty_plan_is_silent(self):
        w = VerdictWatcher()
        w.set_plan([], TRACK_LEN)
        assert _drive(w, 0.0, 500.0) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exit_verdict.py -q`
Expected: FAIL — `ImportError: cannot import name 'ArmedVerdict'`

- [ ] **Step 3: Append the watcher to `core/live/exit_verdict.py`**

```python
@dataclass
class ArmedVerdict:
    """One prompted corner awaiting its exit verdict this lap."""

    diagnosis: RegionDiagnosis
    faults: "list[FaultKind]"


@dataclass
class VerdictResult:
    """One spoken verdict plus the numbers behind it (session log)."""

    text: str
    label: str
    kind: FaultKind
    bucket: str
    live_delta: float
    observed_brake_onset_m: "float | None"
    observed_min_speed_ms: "float | None"
    observed_throttle_on_m: "float | None"


@dataclass
class _Observation:
    """Passively accumulated execution facts for one armed corner."""

    fired: bool = False
    brake_onset_m: "float | None" = None
    min_speed_ms: "float | None" = None
    min_speed_m: "float | None" = None
    last_brake_on_m: "float | None" = None
    release_m: "float | None" = None       # last brake-on at/before the
    throttle_on_m: "float | None" = None   # (final) min-speed point
    exit_speed_ms: "float | None" = None


class VerdictWatcher:
    """Observes prompted corners from live ticks; emits one verdict per
    corner per lap when the car crosses span_end + VERDICT_POINT_M."""

    def __init__(self) -> None:
        self._armed: list[ArmedVerdict] = []
        self._obs: list[_Observation] = []
        self._track_length_m: float = 0.0
        self._prev_dist: "float | None" = None

    def set_plan(
        self, verdicts: "list[ArmedVerdict]", track_length_m: float
    ) -> None:
        self._armed = verdicts
        self._track_length_m = track_length_m
        self.rearm()

    def rearm(self) -> None:
        """Fresh observations at a lap boundary (same plan, new lap)."""
        self._obs = [_Observation() for _ in self._armed]
        self._prev_dist = None

    def reset_position(self) -> None:
        """Forget the last distance sample while feeds are being skipped
        (pits/tow) — same rationale as PromptScheduler.reset_position."""
        self._prev_dist = None

    def feed(
        self, lap_dist_m: float, speed_ms: float, brake: float,
        throttle: float,
    ) -> "VerdictResult | None":
        prev, self._prev_dist = self._prev_dist, lap_dist_m
        result: "VerdictResult | None" = None
        for armed, obs in zip(self._armed, self._obs):
            if obs.fired:
                continue
            self._observe(armed, obs, lap_dist_m, speed_ms, brake, throttle)
            if prev is None or self._track_length_m <= 0:
                continue
            verdict_point = (
                armed.diagnosis.region.distance_end + VERDICT_POINT_M
            ) % self._track_length_m
            if crossed(prev, lap_dist_m, verdict_point):
                obs.fired = True
                if result is None:  # one verdict per tick, like prompts
                    result = self._judge(armed, obs)
        return result

    def _observe(
        self, armed: ArmedVerdict, obs: _Observation, dist: float,
        speed: float, brake: float, throttle: float,
    ) -> None:
        span_start = armed.diagnosis.region.distance_start
        span_end = armed.diagnosis.region.distance_end
        window_start = max(0.0, span_start - BRAKE_SEARCH_BACK_M)
        in_window = window_start <= dist <= span_end
        if in_window:
            if brake > BRAKE_THRESHOLD:
                if obs.brake_onset_m is None:
                    obs.brake_onset_m = dist
                obs.last_brake_on_m = dist
            if obs.min_speed_ms is None or speed < obs.min_speed_ms:
                obs.min_speed_ms = speed
                obs.min_speed_m = dist
                # A new (final-so-far) apex: the trailing brake release is
                # the last brake-on seen up to here, and any throttle-on
                # recorded before it was pre-apex — rearm it.
                obs.release_m = obs.last_brake_on_m
                obs.throttle_on_m = None
        if (obs.throttle_on_m is None and obs.min_speed_m is not None
                and dist > obs.min_speed_m
                and dist <= span_end + VERDICT_POINT_M
                and throttle > THROTTLE_THRESHOLD):
            obs.throttle_on_m = dist
        if obs.exit_speed_ms is None and dist >= span_end:
            obs.exit_speed_ms = speed

    def _judge(
        self, armed: ArmedVerdict, obs: _Observation
    ) -> "VerdictResult | None":
        if not armed.faults:
            return None
        kind = armed.faults[0]
        live = self._live_delta(kind, armed.diagnosis, obs)
        last = self._last_delta(kind, armed.diagnosis)
        if live is None or last is None or last == 0.0:
            return None  # insufficient observation: silence, never guess
        bucket = bucket_for(kind, live, last)
        return VerdictResult(
            text=verdict_text(kind, bucket, live),
            label=armed.diagnosis.label,
            kind=kind,
            bucket=bucket,
            live_delta=live,
            observed_brake_onset_m=obs.brake_onset_m,
            observed_min_speed_ms=obs.min_speed_ms,
            observed_throttle_on_m=obs.throttle_on_m,
        )

    @staticmethod
    def _live_delta(
        kind: FaultKind, diag: RegionDiagnosis, obs: _Observation
    ) -> "float | None":
        if kind is FaultKind.BRAKING:
            if obs.brake_onset_m is None or diag.reference_brake_onset_m is None:
                return None
            return obs.brake_onset_m - diag.reference_brake_onset_m
        if kind is FaultKind.LIFT:
            if obs.min_speed_ms is None:
                return None
            return obs.min_speed_ms - diag.reference_min_speed_ms
        if kind is FaultKind.RELEASE:
            if obs.release_m is None or diag.reference_release_m is None:
                return None
            return obs.release_m - diag.reference_release_m
        if kind is FaultKind.EXIT_SPEED:
            if obs.exit_speed_ms is None or diag.reference_exit_speed_ms is None:
                return None
            return obs.exit_speed_ms - diag.reference_exit_speed_ms
        if obs.throttle_on_m is None or diag.reference_throttle_on_m is None:
            return None
        return obs.throttle_on_m - diag.reference_throttle_on_m

    @staticmethod
    def _last_delta(kind: FaultKind, diag: RegionDiagnosis) -> "float | None":
        return {
            FaultKind.BRAKING: diag.braking_delta_m,
            FaultKind.LIFT: diag.min_speed_delta_ms,
            FaultKind.RELEASE: diag.brake_release_delta_m,
            FaultKind.EXIT_SPEED: diag.exit_speed_delta_ms,
            FaultKind.THROTTLE: diag.throttle_delta_m,
        }[kind]
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exit_verdict.py -q`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add core/live/exit_verdict.py tests/test_exit_verdict.py
git commit -m "feat(live): VerdictWatcher - live corner observation + at-exit verdicts"
```

---

### Task 6: build_plan in prompt_scheduler (+ shared crossed)

**Files:**
- Modify: `core/live/prompt_scheduler.py`
- Test: `tests/test_prompt_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prompt_scheduler.py` (add `build_plan` to the module's prompt_scheduler import and `from core.live.nudges import FaultKind`):

```python
def test_build_plan_arms_verdict_per_scheduled_prompt():
    prompts, verdicts = build_plan([_diag(onset=800.0)], [], TRACK_LEN)
    assert len(prompts) == len(verdicts) == 1
    assert verdicts[0].diagnosis.label == "La Source"
    assert verdicts[0].faults[0] is FaultKind.BRAKING


def test_build_plan_dropped_prompt_arms_no_verdict():
    # No safe speaking gap -> prompt dropped -> no verdict either
    corners = [_corner(450.0, 730.0)]
    prompts, verdicts = build_plan([_diag(onset=800.0)], corners, TRACK_LEN)
    assert prompts == [] and verdicts == []


def test_build_schedule_still_returns_prompts_only():
    schedule = build_schedule([_diag(onset=800.0)], [], TRACK_LEN)
    assert len(schedule) == 1 and isinstance(schedule[0], ScheduledPrompt)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_scheduler.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_plan'`

- [ ] **Step 3: Implement in `core/live/prompt_scheduler.py`**

Change the imports:

```python
from core.coaching.debrief import RegionDiagnosis
from core.live.exit_verdict import ArmedVerdict, crossed
from core.live.nudges import (
    approach_cue_from_diagnosis,
    fault_kinds_from_diagnosis,
)
from core.track.models import Corner
```

Replace `build_schedule` with the plan builder + wrapper (loop body identical to today's except the two appends):

```python
def build_plan(
    diagnoses: list[RegionDiagnosis],
    corners: list[Corner],
    track_length_m: float,
    *,
    lead_m: float = LEAD_M,
    margin_m: float = CLAMP_MARGIN_M,
    min_gap_m: float = MIN_GAP_M,
    max_prompts: int = MAX_PROMPTS,
) -> "tuple[list[ScheduledPrompt], list[ArmedVerdict]]":
    """Prompts AND armed exit verdicts for the next lap, from this lap's
    diagnoses. One construction site: a verdict exists iff its corner's
    cue was actually scheduled (spec scope rule 1, structurally)."""
    if track_length_m <= 0:
        return [], []
    prompts: list[ScheduledPrompt] = []
    verdicts: list[ArmedVerdict] = []
    for diag in diagnoses:
        if len(prompts) >= max_prompts:
            break
        cue = approach_cue_from_diagnosis(diag)
        if cue is None:
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
        prompts.append(ScheduledPrompt(trigger_m=trigger, text=cue))
        verdicts.append(
            ArmedVerdict(diagnosis=diag,
                         faults=fault_kinds_from_diagnosis(diag))
        )
    return prompts, verdicts


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
    """Prompts only — thin wrapper kept for existing callers/tests."""
    return build_plan(
        diagnoses, corners, track_length_m, lead_m=lead_m,
        margin_m=margin_m, min_gap_m=min_gap_m, max_prompts=max_prompts,
    )[0]
```

Delete the module-level `_crossed` function and alias it instead (its callers inside the file are unchanged):

```python
_crossed = crossed  # shared wrap-safe crossing (lives in exit_verdict)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompt_scheduler.py tests/test_exit_verdict.py -q`
Expected: ALL PASS (every pre-existing scheduler test untouched and green)

- [ ] **Step 5: Commit**

```bash
git add core/live/prompt_scheduler.py tests/test_prompt_scheduler.py
git commit -m "feat(live): build_plan arms prompts + exit verdicts from one construction site"
```

---

### Task 7: live_coach wiring (--race-cues flag, SessionNum, watcher in the loop)

**Files:**
- Modify: `scripts/live_coach.py`
- Test: `tests/test_live_coach_helpers.py` (parser), `tests/test_toolbox_commands.py` (re-run only)

- [ ] **Step 1: Write the failing parser tests**

Append to `tests/test_live_coach_helpers.py` (it already imports/loads `live_coach`; follow the file's existing import pattern):

```python
class TestRaceCuesFlag:
    def test_default_is_persistent(self):
        args = live_coach.build_parser().parse_args([])
        assert args.race_cues == "persistent"

    def test_choices(self):
        for mode in ("full", "persistent", "off"):
            args = live_coach.build_parser().parse_args(["--race-cues", mode])
            assert args.race_cues == mode

    def test_choices_come_from_race_gate(self):
        # The parser's choices tuple IS race_gate.RACE_CUE_MODES — a mode
        # added in one place cannot silently miss the other.
        from core.live.race_gate import RACE_CUE_MODES
        action = next(a for a in live_coach.build_parser()._actions
                      if a.dest == "race_cues")
        assert tuple(action.choices) == RACE_CUE_MODES
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_coach_helpers.py -q`
Expected: FAIL — `AttributeError: ... 'race_cues'`

- [ ] **Step 3: Wire `scripts/live_coach.py`**

Imports — add:

```python
from core.live.exit_verdict import VerdictWatcher  # noqa: E402
from core.live.prompt_scheduler import PromptScheduler, build_plan  # noqa: E402
from core.live.race_gate import (  # noqa: E402
    RACE_CUE_MODES,
    FaultStreakTracker,
    current_session_type,
    gate_diagnoses,
)
from core.live.nudges import fault_kinds_from_diagnosis  # noqa: E402  (extend the existing nudges import block)
```

(`build_schedule` import is replaced by `build_plan`.)

`READ_CHANNELS` — add `"SessionNum"`:

```python
READ_CHANNELS = SAMPLE_CHANNELS + [
    "Lap", "OnPitRoad", "PlayerTrackSurface", "PlayerCarMyIncidentCount",
    "SessionNum",
]
```

`build_parser` — add after the `--no-corner-prompts` argument:

```python
    parser.add_argument("--race-cues", dest="race_cues",
                        choices=RACE_CUE_MODES, default="persistent",
                        help="cue behavior in Race sessions: full = like "
                             "practice, persistent = only faults seen 2+ "
                             "consecutive laps (default), off = silent")
```

`main()` state — beside `scheduler = PromptScheduler()`:

```python
    verdict_watcher = VerdictWatcher()
    streaks = FaultStreakTracker()
    session_num: int | None = None
    session_type = ""
```

In the `if not meta_loaded:` block, beside `scheduler.set_schedule([])`:

```python
                verdict_watcher.set_plan([], track_length_m)
                streaks = FaultStreakTracker()
                session_num = None
                session_type = ""
```

Also log the mode: add `race_cues=args.race_cues,` to the existing `session_log.log("connect", ...)` call.

After the churn guard (`if any(isinstance(v, list) ...): continue`), refresh the session type when SessionNum changes (SessionInfo YAML is only parsed on change):

```python
            snum = sample.get("SessionNum")
            if snum is not None and int(snum) != session_num:
                session_num = int(snum)
                try:
                    session_type = current_session_type(
                        ir["SessionInfo"], session_num
                    )
                except Exception:
                    session_type = ""
                if session_log is not None:
                    session_log.log("session_type", session_num=session_num,
                                    session_type=session_type)
```

In the `if args.corner_prompts:` tick block, extend BOTH branches. The `lap_dist is not None and not OnPitRoad` branch gains, after the prompt handling:

```python
                    try:
                        verdict = verdict_watcher.feed(
                            float(lap_dist), float(sample.get("Speed") or 0.0),
                            float(sample.get("Brake") or 0.0),
                            float(sample.get("Throttle") or 0.0),
                        )
                    except Exception:  # noqa: BLE001 -- never kill the coach
                        verdict = None
                    if verdict is not None:
                        emit(f"  << {verdict.text}")
                        speaker.say(verdict.text)
                        if session_log is not None:
                            session_log.log(
                                "verdict", text=verdict.text,
                                corner=verdict.label,
                                fault=verdict.kind.value,
                                bucket=verdict.bucket,
                                live_delta=verdict.live_delta,
                                brake_onset_m=verdict.observed_brake_onset_m,
                                min_speed_ms=verdict.observed_min_speed_ms,
                                throttle_on_m=verdict.observed_throttle_on_m,
                                lap=int(sample.get("Lap") or 0),
                            )
```

and the `else:` branch gains `verdict_watcher.reset_position()` beside `scheduler.reset_position()`.

At lap completion: add `verdict_watcher.rearm()` beside `scheduler.rearm()` (covers baseline/dirty/invalid laps where no new plan is built). In the comparison branch, replace the `build_schedule` block with:

```python
                        if args.corner_prompts:
                            streaks.update({
                                (d.label, kinds[0])
                                for d in result.diagnoses
                                if (kinds := fault_kinds_from_diagnosis(d))
                            })
                            gated = gate_diagnoses(
                                result.diagnoses, mode=args.race_cues,
                                is_race=(session_type == "Race"),
                                tracker=streaks,
                            )
                            prompts, verdicts = build_plan(
                                gated, corners, track_length_m,
                            )
                            scheduler.set_schedule(prompts)
                            verdict_watcher.set_plan(verdicts, track_length_m)
                            if session_log is not None:
                                session_log.log("schedule", prompts=[
                                    {"trigger_m": p.trigger_m, "text": p.text}
                                    for p in prompts
                                ], verdicts=[
                                    v.diagnosis.label for v in verdicts
                                ], gated_out=len(result.diagnoses) - len(gated))
```

- [ ] **Step 4: Run the coupled tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_live_coach_helpers.py tests/test_toolbox_commands.py tests/test_tray_app.py -q`
Expected: ALL PASS — the Toolbox/tray spawn commands don't pass `--race-cues`, and the default keeps them valid; these tests are exactly the flag-drift guard (2026-07-14 lesson).

- [ ] **Step 5: Commit**

```bash
git add scripts/live_coach.py tests/test_live_coach_helpers.py
git commit -m "feat(live-coach): exit verdicts + race persistence gate wired (--race-cues)"
```

---

### Task 8: Live-vs-offline anti-drift coupling test

**Files:**
- Test: `tests/test_exit_verdict.py`

- [ ] **Step 1: Write the coupling test**

Append to `tests/test_exit_verdict.py`:

```python
import numpy as np
import pytest

from core.coaching.debrief import build_debrief
from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer

FIXTURE = Path("tests/fixtures/sample.ibt")


@pytest.mark.skipif(not FIXTURE.exists(), reason="needs local sample.ibt")
def test_live_brake_onset_matches_offline_diagnosis():
    """Replay a REAL normalized lap through the watcher tick-by-tick and
    assert its observed brake onset agrees with _diagnose_region's for
    the top loss region — the anti-drift lock from the spec."""
    parser = IBTParser(FIXTURE)
    laps = parser.get_laps()
    normalizer = Normalizer()
    track_len = parser.session_info.track_length_m
    nlaps = [
        normalizer.normalize_lap(df, n, track_len)
        for n, df in laps.items()
    ]
    valid = [lap for lap in nlaps if lap.is_valid]
    if len(valid) < 2:
        pytest.skip("fixture lacks two valid laps")
    driver, reference = valid[0], valid[1]
    result = build_debrief(driver, reference, [])
    diags = [d for d in result.diagnoses
             if d.reference_brake_onset_m is not None
             and d.braking_delta_m is not None]
    if not diags:
        pytest.skip("no braking diagnosis in fixture")
    diag = diags[0]
    interval = float(driver.distance[1] - driver.distance[0])

    w = VerdictWatcher()
    w.set_plan([ArmedVerdict(diagnosis=diag, faults=[FaultKind.BRAKING])],
               track_len)
    for i in range(len(driver.distance)):
        w.feed(float(driver.distance[i]), float(driver.speed[i]),
               float(driver.brake[i]), float(driver.throttle[i]))
    obs = w._obs[0]
    offline_onset_m = (diag.reference_brake_onset_m + diag.braking_delta_m)
    assert obs.brake_onset_m is not None
    assert abs(obs.brake_onset_m - offline_onset_m) <= 2 * interval
```

(Adapt the parser/normalizer call names to the existing usage in `tests/test_debrief.py` — copy its fixture-loading helper if one exists. Add `from pathlib import Path` to the test module imports.)

- [ ] **Step 2: Run it against the real fixture**

Run: `.venv/Scripts/python.exe -m pytest tests/test_exit_verdict.py -q`
Expected: PASS (or SKIP on machines without the gitignored fixture — it must PASS on this machine, which has it)

- [ ] **Step 3: Commit**

```bash
git add tests/test_exit_verdict.py
git commit -m "test(live): anti-drift coupling - live brake onset matches offline diagnosis"
```

---

### Task 9: Full suite, docs, wrap-up

- [ ] **Step 1: Full test suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: ALL PASS (875+ before this feature; every new test green, zero regressions)

- [ ] **Step 2: Update CLAUDE.md**

Add a status section after "Track-Limits Asterisk" (match the existing section style):

```markdown
**Exit Verdict Cues** (complete, branch exit-verdict-cues — spec docs/superpowers/specs/2026-07-16-exit-verdict-cues-design.md)
- [x] FaultKind ladder extracted in nudges.py — cue + verdict share one ranking (cue strings byte-identical)
- [x] RegionDiagnosis reference absolutes added (release/throttle-on/exit speed — the reference_brake_onset_m precedent)
- [x] core/live/exit_verdict.py — VerdictWatcher fires one quantity-free bucket verdict (that's it / too far / better / still) per prompted corner at span_end+100m; overcorrect checked before better; speed/throttle faults never scolded for beating the reference; insufficient observation = silence
- [x] core/live/race_gate.py — FaultStreakTracker + SessionInfo session-type detection (NOT WeekendInfo.EventType); Race sessions default to persistent mode (fault must persist 2+ laps), --race-cues full|persistent|off
- [x] build_plan arms prompts + verdicts from one construction site (verdict iff cue scheduled); anti-drift coupling test (live vs offline brake onset on the real fixture)
- [ ] Driving validation: verdict timing (VERDICT_POINT_M 100m), bucket accuracy vs felt reality, race gate quietness in traffic; tune IMPROVED_FRACTION / RACE_STREAK_MIN from session logs
```

- [ ] **Step 3: Commit docs**

```bash
git add CLAUDE.md
git commit -m "docs: exit-verdict cues status (CLAUDE.md)"
```

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch — merge to master, push, restart the rig's coach is NOT needed (coach is started per-drive from the tray/Toolbox and will pick up the new code next start), but the WATCHER and APP are unaffected (no shared modules changed in their import paths — nudges/debrief are imported by the app; restart the app after merge per the hybrid-module rule).
```
