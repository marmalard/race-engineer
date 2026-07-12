# Track-Limits Asterisk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect laps with mid-lap incidents (any `PlayerCarMyIncidentCount` rise), keep coaching them but never promote them as PB references, and have the live voice asterisk the time ("— but track limits at Griffins, that time won't count").

**Architecture:** New pure `core/telemetry/cleanliness.py` (offline `check_lap_cleanliness(df)` + live `IncidentTracker` state machine, both emitting `IncidentMark`s). Two consumers wire it in: the watcher's promotion pool becomes plausible∧clean (report gains a dirty note), and `live_coach.py` appends asterisk speech / skips dirty session baselines. Phrasing lives in `nudges.py`; corner naming reuses `corner_name_at` from `core/race/narrative.py`.

**Tech Stack:** Python 3.11+, pandas, pytest. Run tests with `.venv/Scripts/python.exe -m pytest`.

## Spec

See `docs/superpowers/specs/2026-07-11-track-limits-asterisk-design.md`.

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `core/telemetry/cleanliness.py` | detection only (no phrasing) | **new** |
| `core/watcher/processor.py` | promotion pool = plausible∧clean; report fields | modify |
| `scripts/watch_telemetry.py` | print `dirty_note` | modify |
| `core/live/nudges.py` | `format_asterisk_speech`, `format_dirty_baseline_speech` | modify |
| `scripts/live_coach.py` | READ_CHANNELS, tracker wiring, asterisk/baseline-skip, logging | modify |
| Tests | `test_cleanliness.py` (new); `test_watcher_processor.py`, `test_nudges.py` (extend) | |

---

## Task 1: pure cleanliness module

**Files:**
- Create: `core/telemetry/cleanliness.py`
- Test: `tests/test_cleanliness.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cleanliness.py`:

```python
"""Tests for lap-cleanliness detection (pure; offline + live paths)."""

import pandas as pd

from core.telemetry.cleanliness import (
    IncidentMark,
    IncidentTracker,
    check_lap_cleanliness,
)


def _frame(counts, dists=None):
    n = len(counts)
    return pd.DataFrame({
        "PlayerCarMyIncidentCount": counts,
        "LapDist": dists if dists is not None else [float(i * 10) for i in range(n)],
    })


def test_clean_lap():
    r = check_lap_cleanliness(_frame([4, 4, 4, 4]))
    assert r.clean and r.marks == []


def test_single_increment_marks_distance_and_delta():
    r = check_lap_cleanliness(_frame([4, 4, 5, 5], dists=[0.0, 100.0, 200.0, 300.0]))
    assert not r.clean
    assert r.marks == [IncidentMark(distance_m=200.0, delta=1)]


def test_multiple_increments():
    r = check_lap_cleanliness(_frame([0, 1, 1, 5], dists=[0.0, 50.0, 100.0, 150.0]))
    assert [(m.distance_m, m.delta) for m in r.marks] == [(50.0, 1), (150.0, 4)]


def test_count_decrease_ignored():
    """A backward count (session reset artifacts) is never a mark."""
    r = check_lap_cleanliness(_frame([4, 2, 2, 2]))
    assert r.clean


def test_missing_columns_fail_open():
    r = check_lap_cleanliness(pd.DataFrame({"Speed": [1.0, 2.0]}))
    assert r.clean and r.marks == []


def test_empty_frame_is_clean():
    assert check_lap_cleanliness(_frame([])).clean


def test_tracker_records_and_closes():
    t = IncidentTracker()
    t.feed(4, 100.0)
    t.feed(4, 200.0)
    t.feed(5, 300.0)          # +1 at 300m
    t.feed(5, 400.0)
    marks = t.close_lap()
    assert marks == [IncidentMark(distance_m=300.0, delta=1)]
    # closed -> next lap starts fresh but the count baseline carries over
    t.feed(5, 50.0)
    assert t.close_lap() == []


def test_tracker_ignores_none_inputs():
    t = IncidentTracker()
    t.feed(4, 100.0)
    t.feed(None, 200.0)       # tow/out-of-world tick
    t.feed(5, None)
    t.feed(5, 300.0)          # rise observed vs last GOOD count (4 -> 5)
    assert t.close_lap() == [IncidentMark(distance_m=300.0, delta=1)]


def test_tracker_reset_discards_marks_but_keeps_baseline():
    t = IncidentTracker()
    t.feed(4, 100.0)
    t.feed(6, 200.0)          # +2
    t.reset()
    assert t.close_lap() == []
    t.feed(6, 50.0)           # same count after reset -> no phantom mark
    assert t.close_lap() == []


def test_tracker_first_feed_never_marks():
    """The very first observed count is a baseline, not an incident."""
    t = IncidentTracker()
    t.feed(12, 500.0)
    assert t.close_lap() == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cleanliness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.telemetry.cleanliness'`.

- [ ] **Step 3: Implement**

Create `core/telemetry/cleanliness.py`:

```python
"""Lap-cleanliness detection: did the incident count rise during this lap?

A lap with a minor infraction usually has PERFECT telemetry — the
normalizer rightly accepts it. This module answers the different question
"does the TIME count?": any mid-lap rise in PlayerCarMyIncidentCount
(1x off-track, 2x loss of control, 4x contact) marks the lap dirty.

Detection only — no phrasing here (the 1x/2x/4x wording lives in
core/live/nudges.py) and no corner naming (consumers use
core.race.narrative.corner_name_at with their loaded corners).
Fail-open everywhere: cleanliness is an enhancement; a missing channel
must never break lap processing.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass
class IncidentMark:
    """One mid-lap incident-count increment."""

    distance_m: float   # LapDist at the tick the count rose
    delta: int          # how much iRacing added (1 / 2 / 4)


@dataclass
class LapCleanliness:
    clean: bool
    marks: list[IncidentMark]


def check_lap_cleanliness(df: pd.DataFrame) -> LapCleanliness:
    """Offline path: one per-lap DataFrame from IBTParser.get_laps().

    Needs PlayerCarMyIncidentCount + LapDist columns (both in
    CORE_CHANNELS). Missing columns or an empty frame -> clean
    (fail-open). Count DECREASES are ignored (session-reset artifacts)."""
    if (
        "PlayerCarMyIncidentCount" not in df.columns
        or "LapDist" not in df.columns
        or len(df) == 0
    ):
        return LapCleanliness(clean=True, marks=[])
    counts = df["PlayerCarMyIncidentCount"].astype(int).to_numpy()
    dists = df["LapDist"].astype(float).to_numpy()
    marks: list[IncidentMark] = []
    for i in range(1, len(counts)):
        delta = int(counts[i] - counts[i - 1])
        if delta > 0:
            marks.append(IncidentMark(distance_m=float(dists[i]), delta=delta))
    return LapCleanliness(clean=not marks, marks=marks)


class IncidentTracker:
    """Live path: pure per-tick state machine (no pyirsdk, no I/O).

    feed() one (incident_count, lap_dist_m) pair per tick; close_lap()
    returns the lap's marks and clears them (the count baseline carries
    over — the sim's counter is session-cumulative); reset() discards
    marks on a lap discard without losing the baseline. None inputs
    (tow / out-of-world ticks) are ignored entirely."""

    def __init__(self) -> None:
        self._last_count: int | None = None
        self._marks: list[IncidentMark] = []

    def feed(self, incident_count: "int | None", lap_dist_m: "float | None") -> None:
        if incident_count is None or lap_dist_m is None:
            return
        if self._last_count is not None:
            delta = int(incident_count) - self._last_count
            if delta > 0:
                self._marks.append(
                    IncidentMark(distance_m=float(lap_dist_m), delta=delta)
                )
        self._last_count = int(incident_count)

    def close_lap(self) -> list[IncidentMark]:
        marks, self._marks = self._marks, []
        return marks

    def reset(self) -> None:
        self._marks = []
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cleanliness.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add core/telemetry/cleanliness.py tests/test_cleanliness.py
git commit -m "feat(cleanliness): pure lap-cleanliness detector (offline + live)"
```

---

## Task 2: watcher PB gate

**Files:**
- Modify: `core/watcher/processor.py`
- Modify: `scripts/watch_telemetry.py` (`_format_report`)
- Test: `tests/test_watcher_processor.py`

READ `core/watcher/processor.py` fully first. Current flow: `lap_dfs = parser.get_laps(ibt)` → `lap_numbers` → `normalize_session` → `valid` → `plausible` (is_plausible_lap + covers_full_lap) → `best = min(plausible)` → upsert track → record history → promotion (`should_promote` vs existing personal_best) → debrief vs best reference.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_watcher_processor.py` (it already has the `dbs` fixture and a monkeypatch pattern in `test_short_coverage_lap_not_promoted` — mirror it):

```python
def _mk_lap(lap_number, lap_time, track_length):
    """Plausible, full-coverage NormalizedLap for promotion tests."""
    n = int(track_length)
    z = np.zeros(n)
    return NormalizedLap(
        lap_number=lap_number, lap_time=lap_time, track_length=track_length,
        distance=np.arange(n, dtype=float),
        speed=np.full(n, track_length / lap_time), throttle=z, brake=z,
        steering=z, gear=np.ones(n), rpm=np.full(n, 5000.0), lat=z, lon=z,
        elapsed_time=np.linspace(0, lap_time, n), is_valid=True,
    )


def _mk_lap_df(lap_number, incident_counts):
    """Raw per-lap frame the cleanliness check reads (Lap col for keying)."""
    import pandas as pd
    n = len(incident_counts)
    return pd.DataFrame({
        "Lap": [lap_number] * n,
        "LapDist": [float(i * 100) for i in range(n)],
        "PlayerCarMyIncidentCount": incident_counts,
    })


def _run_with(monkeypatch, tmp_path, dbs, lap_dfs, nlaps, track_length=4000.0):
    import core.watcher.processor as proc_mod
    from unittest.mock import MagicMock

    mock_session = MagicMock()
    mock_session.track_id = "525"
    mock_session.track_name = "Spa"
    mock_session.track_directory = "spa 2024 combined"
    mock_session.track_length_km = track_length / 1000.0
    mock_session.car_name = "M2"
    mock_session.driver_name = "Test Driver"
    mock_session.session_type = "practice"
    mock_ibt = MagicMock()
    mock_ibt.session = mock_session

    monkeypatch.setattr(proc_mod.IBTParser, "parse", lambda self, p: mock_ibt)
    monkeypatch.setattr(proc_mod.IBTParser, "get_laps", lambda self, ibt: lap_dfs)
    monkeypatch.setattr(
        proc_mod.Normalizer, "normalize_session", lambda *a, **kw: nlaps,
    )
    track_db, ref_store = dbs
    fake = tmp_path / "fake.ibt"
    fake.write_bytes(b"")
    return process_ibt(fake, track_db, ref_store), ref_store


def test_fastest_dirty_lap_not_promoted_clean_one_is(tmp_path, dbs, monkeypatch):
    """Coach the dirty lap (it stays report.best) but promote the clean one."""
    lap_dfs = [
        _mk_lap_df(1, [0, 0, 1, 1]),   # dirty (fast)
        _mk_lap_df(2, [1, 1, 1, 1]),   # clean (slower)
    ]
    nlaps = [_mk_lap(1, 100.0, 4000.0), _mk_lap(2, 102.0, 4000.0)]
    report, ref_store = _run_with(monkeypatch, tmp_path, dbs, lap_dfs, nlaps)

    assert report.error is None
    assert report.best_lap_time == 100.0          # coached/reported best unchanged
    assert report.best_lap_dirty
    assert report.dirty_note is not None
    assert report.promoted
    metas = ref_store.list_all()
    assert len(metas) == 1
    assert metas[0].lap_time == pytest.approx(102.0)   # the CLEAN lap


def test_all_dirty_nothing_promoted(tmp_path, dbs, monkeypatch):
    lap_dfs = [_mk_lap_df(1, [0, 0, 2, 2])]
    nlaps = [_mk_lap(1, 100.0, 4000.0)]
    report, ref_store = _run_with(monkeypatch, tmp_path, dbs, lap_dfs, nlaps)

    assert report.error is None
    assert not report.promoted
    assert report.best_lap_dirty
    assert "no clean lap" in (report.dirty_note or "")
    assert ref_store.list_all() == []


def test_all_clean_behavior_unchanged(tmp_path, dbs, monkeypatch):
    lap_dfs = [_mk_lap_df(1, [3, 3, 3, 3])]
    nlaps = [_mk_lap(1, 100.0, 4000.0)]
    report, ref_store = _run_with(monkeypatch, tmp_path, dbs, lap_dfs, nlaps)

    assert report.error is None
    assert report.promoted and not report.best_lap_dirty
    assert report.dirty_note is None
```

(Existing imports at the top of the file already include `numpy as np`, `NormalizedLap`, `process_ibt`, `pytest` — verify and add any missing.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watcher_processor.py -k dirty -v`
Expected: FAIL — `AttributeError: 'SessionReport' object has no attribute 'best_lap_dirty'` (or TypeError on the field).

- [ ] **Step 3: Implement in `core/watcher/processor.py`**

(a) Imports:
```python
from core.race.narrative import corner_name_at
from core.telemetry.cleanliness import check_lap_cleanliness
```

(b) `SessionReport` gains two fields (after `promoted`):
```python
    best_lap_dirty: bool = False
    dirty_note: str | None = None
```

(c) After the `plausible` list is built and `best` selected, compute cleanliness and the promotion candidate. Insert after `report.best_lap_time = best.lap_time if best else None`:

```python
        # Cleanliness: any mid-lap incident-count rise makes a lap's TIME
        # untrustworthy as a reference, even though its telemetry is fine.
        # We still coach it (best stays the debrief target below) — we just
        # never promote it. Keyed by lap number to join raw frames to
        # normalized laps.
        cleanliness = {
            int(df["Lap"].iloc[0]): check_lap_cleanliness(df)
            for df in lap_dfs if len(df) > 0
        }

        def _is_clean(lap) -> bool:
            c = cleanliness.get(lap.lap_number)
            return c.clean if c is not None else True   # fail-open

        clean_plausible = [l for l in plausible if _is_clean(l)]
        candidate = (
            min(clean_plausible, key=lambda l: l.lap_time)
            if clean_plausible else None
        )
```

(d) The promotion block currently uses `best`; switch it to `candidate`:
```python
        if best is None:
            return report

        if candidate is not None and should_promote(
            candidate.lap_time,
            existing_pb.lap_time if existing_pb else None,
        ):
            ref_store.save(
                track_id, session.car_name, candidate,
                source="personal_best", driver_name=session.driver_name,
            )
            report.promoted = True
```
(the `existing_pb` lookup stays exactly where it is, unchanged).

(e) Dirty-note construction, right after the promotion block:
```python
        if not _is_clean(best):
            report.best_lap_dirty = True
            first = cleanliness[best.lap_number].marks[0]
            corners = _load_corners(
                track_db, track_id, session.track_directory, track_length_m,
            )
            where = (
                corner_name_at(corners, first.distance_m)
                or f"~{first.distance_m / 1000:.1f} km from start/finish"
            )
            fmt = lambda t: f"{int(t // 60)}:{t % 60:06.3f}"  # noqa: E731
            if candidate is not None:
                report.dirty_note = (
                    f"fastest lap ({fmt(best.lap_time)}) had an incident at "
                    f"{where} — best clean lap ({fmt(candidate.lap_time)}) "
                    "used for promotion instead"
                )
            else:
                report.dirty_note = (
                    f"fastest lap ({fmt(best.lap_time)}) had an incident at "
                    f"{where} — no clean lap to promote"
                )
```

(f) The debrief block below is UNTOUCHED (it still debriefs `best`), except its `is_own_new_pb` check compares against the promoted lap — verify: it uses `report.promoted and ref.source == "personal_best"`; with candidate≠best the freshly promoted reference may legitimately be the comparison for `best`. That's correct behavior (debrief the fast dirty lap against the clean reference) — leave as is.

(g) In `scripts/watch_telemetry.py::_format_report`, after the `if r.promoted:` line block, add:
```python
    if r.dirty_note:
        lines.append(f"  NOTE: {r.dirty_note}")
```

- [ ] **Step 4: Run the watcher suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watcher_processor.py tests/test_watch_telemetry_helpers.py -v`
Expected: PASS — 3 new + all existing (the pre-existing tests use frames WITHOUT PlayerCarMyIncidentCount → fail-open clean → behavior unchanged; `test_short_coverage_lap_not_promoted`'s mock df has only a Lap column → clean).

- [ ] **Step 5: Commit**

```bash
git add core/watcher/processor.py scripts/watch_telemetry.py tests/test_watcher_processor.py
git commit -m "feat(watcher): cleanliness gate on PB promotion (coach dirty laps, promote clean)"
```

---

## Task 3: asterisk + dirty-baseline speech

**Files:**
- Modify: `core/live/nudges.py`
- Test: `tests/test_nudges.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_nudges.py`:

```python
def _corner_list():
    from core.track.models import Corner
    return [Corner(corner_id=None, track_id="t", corner_number=1,
                   name="Old Hall", distance_start_meters=180.0,
                   distance_end_meters=260.0, corner_type=None)]


def test_asterisk_track_limits_named_corner():
    from core.live.nudges import format_asterisk_speech
    from core.telemetry.cleanliness import IncidentMark
    s = format_asterisk_speech([IncidentMark(200.0, 1)], _corner_list())
    assert s == " — but track limits at Old Hall, that time won't count."


def test_asterisk_spin_and_contact_phrasing():
    from core.live.nudges import format_asterisk_speech
    from core.telemetry.cleanliness import IncidentMark
    assert format_asterisk_speech([IncidentMark(200.0, 2)], _corner_list()) == \
        " — but you lost it at Old Hall, that time won't count."
    assert format_asterisk_speech([IncidentMark(200.0, 4)], _corner_list()) == \
        " — but contact at Old Hall, that time won't count."


def test_asterisk_multiple_marks_and_fallback_corner():
    from core.live.nudges import format_asterisk_speech
    from core.telemetry.cleanliness import IncidentMark
    s = format_asterisk_speech(
        [IncidentMark(200.0, 1), IncidentMark(900.0, 1)], _corner_list()
    )
    assert s == (
        " — but track limits at Old Hall (and 1 more), that time won't count."
    )
    assert format_asterisk_speech([IncidentMark(900.0, 1)], []) == \
        " — but track limits out there, that time won't count."


def test_asterisk_empty_marks_is_empty():
    from core.live.nudges import format_asterisk_speech
    assert format_asterisk_speech([], _corner_list()) == ""


def test_dirty_baseline_speech():
    from core.live.nudges import format_dirty_baseline_speech
    from core.telemetry.cleanliness import IncidentMark
    assert format_dirty_baseline_speech([IncidentMark(200.0, 1)]) == (
        "That lap had track limits — I won't use it as the baseline. "
        "Give me a clean one."
    )
    assert format_dirty_baseline_speech([IncidentMark(200.0, 4)]) == (
        "That lap had contact — I won't use it as the baseline. "
        "Give me a clean one."
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -k "asterisk or dirty_baseline" -v`
Expected: FAIL — `ImportError: cannot import name 'format_asterisk_speech'`.

- [ ] **Step 3: Implement in `core/live/nudges.py`**

Imports (top, with the other core imports):
```python
from core.race.narrative import corner_name_at
from core.telemetry.cleanliness import IncidentMark
```

Functions (near the other format_* helpers):

```python
# Spoken phrasing per incident-count delta. Verb form for the asterisk
# clause; noun form for the baseline-refusal line. Unknown deltas (never
# observed, defensive) fall back to the generic noun/verb.
_ASTERISK_VERB = {1: "track limits", 2: "you lost it", 4: "contact"}
_ASTERISK_NOUN = {1: "track limits", 2: "a moment", 4: "contact"}


def format_asterisk_speech(
    marks: "list[IncidentMark]", corners: list
) -> str:
    """Appended to the normal lap speech when a valid lap is dirty.

    Phrases the FIRST (earliest) mark; extra marks become '(and N more)'.
    Empty marks -> "" (clean lap, nothing to append)."""
    if not marks:
        return ""
    first = marks[0]
    phrase = _ASTERISK_VERB.get(first.delta, "an incident")
    where = corner_name_at(corners, first.distance_m) or "out there"
    extra = f" (and {len(marks) - 1} more)" if len(marks) > 1 else ""
    return f" — but {phrase} at {where}{extra}, that time won't count."


def format_dirty_baseline_speech(marks: "list[IncidentMark]") -> str:
    """Spoken instead of 'Baseline set' when the would-be baseline is dirty."""
    phrase = _ASTERISK_NOUN.get(marks[0].delta, "an incident") if marks else "an incident"
    return (
        f"That lap had {phrase} — I won't use it as the baseline. "
        "Give me a clean one."
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_nudges.py -v`
Expected: PASS (all — 6 new + existing).

- [ ] **Step 5: Commit**

```bash
git add core/live/nudges.py tests/test_nudges.py
git commit -m "feat(nudges): asterisk + dirty-baseline speech for dirty laps"
```

---

## Task 4: live_coach wiring

No unit tests (pyirsdk driver); verified by ast + `--help` + full suite. READ `scripts/live_coach.py` fully first; the loop was reshaped in voice round 2 (`tick = tracker.feed(sample)`, `tick.discarded` block, `if nlap.is_valid:` with baseline/else branches).

- [ ] **Step 1: Imports + channel**

Add to the nudges import block: `format_asterisk_speech, format_dirty_baseline_speech` (keep alphabetical order). Add:
```python
from core.telemetry.cleanliness import IncidentTracker  # noqa: E402
```
Change:
```python
READ_CHANNELS = SAMPLE_CHANNELS + ["Lap", "OnPitRoad", "PlayerTrackSurface"]
```
to:
```python
READ_CHANNELS = SAMPLE_CHANNELS + [
    "Lap", "OnPitRoad", "PlayerTrackSurface", "PlayerCarMyIncidentCount",
]
```

- [ ] **Step 2: Tracker lifecycle**

Where `scheduler = PromptScheduler()` is created (before the loop), add:
```python
    incident_tracker = IncidentTracker()
```
Inside the `if not meta_loaded:` connect block (with the other per-connect resets like `scheduler.set_schedule([])`), add:
```python
                incident_tracker = IncidentTracker()
```

- [ ] **Step 3: Per-tick feed + discard reset**

Right after the `tick.discarded` handling block, add:
```python
            # Incident marks for the cleanliness asterisk. Same guards as
            # the prompt scheduler: no feeds while towed/out-of-world or on
            # pit road (pit laps are discarded anyway).
            if tick.discarded is not None:
                incident_tracker.reset()
            else:
                _dist = sample.get("LapDist")
                if _dist is not None and not sample.get("OnPitRoad"):
                    incident_tracker.feed(
                        sample.get("PlayerCarMyIncidentCount"), float(_dist),
                    )
```
(Fold the reset into the existing `if tick.discarded is not None:` block instead of a second if — cleaner; implementer's choice, behavior identical.)

- [ ] **Step 4: Consume marks on lap completion**

At the TOP of the `if completed is not None:` block (before `scheduler.rearm()`), add:
```python
                marks = incident_tracker.close_lap()
```
Then three edits inside `if nlap.is_valid:`:

(a) **Baseline branch** (`if comparison is None:`): wrap it —
```python
                    if comparison is None:
                        if marks:
                            skip_speech = format_dirty_baseline_speech(marks)
                            emit(skip_speech)
                            speaker.say(skip_speech)
                            if session_log is not None:
                                session_log.log(
                                    "dirty_baseline_skipped",
                                    lap=nlap.lap_number,
                                    lap_time=nlap.lap_time,
                                    marks=[
                                        {"distance_m": m.distance_m,
                                         "delta": m.delta}
                                        for m in marks
                                    ],
                                    speech=skip_speech,
                                )
                        else:
                            session_best = nlap
                            ... (existing baseline body unchanged, indented)
```
i.e. the existing baseline body (session_best assignment, emit, speech, log) moves under `else:`.

(b) **Debrief branch** (`else:` — comparison exists): after `speech, prev_flagged = format_lap_speech(...)` and BEFORE `speaker.say(speech)`, add:
```python
                        asterisk = format_asterisk_speech(marks, corners)
                        speech += asterisk
```
and change the emit above it from `emit(format_lap_block(...))` to:
```python
                        emit(format_lap_block(
                            nlap.lap_number, nlap.lap_time,
                            result.total_time_delta, result.diagnoses,
                        ) + asterisk)
```
NOTE the ordering problem: `asterisk` must be computed BEFORE the `emit(...)` call to be appended there — compute it first:
```python
                        asterisk = format_asterisk_speech(marks, corners)
                        emit(format_lap_block(...) + asterisk)
                        ...
                        speech, prev_flagged = format_lap_speech(...)
                        speech += asterisk
                        speaker.say(speech)
```
Add `dirty=bool(marks)` and `marks=[{"distance_m": m.distance_m, "delta": m.delta} for m in marks]` to the existing `session_log.log("lap", ...)` kwargs.

(c) **Session-best guard** — change:
```python
                        if (reference_lap is None
                                and nlap.lap_time < session_best.lap_time):
                            session_best = nlap
```
to:
```python
                        if (reference_lap is None and not marks
                                and nlap.lap_time < session_best.lap_time):
                            session_best = nlap
```

- [ ] **Step 5: Verify**

Run: `.venv/Scripts/python.exe -c "import ast; ast.parse(open('scripts/live_coach.py').read()); print('ok')"` → ok
Run: `.venv/Scripts/python.exe scripts/live_coach.py --help` → prints help
Run: `.venv/Scripts/python.exe -m pytest -q` → full suite passes.

- [ ] **Step 6: Commit**

```bash
git add scripts/live_coach.py
git commit -m "feat(live-coach): asterisk dirty lap times; never baseline a dirty lap"
```

---

## Task 5: full suite + finalize

- [ ] **Step 1:** `.venv/Scripts/python.exe -m pytest -q` — all pass (~+19 tests over 546/9 baseline).
- [ ] **Step 2:** Manual sanity vs a real IBT (optional but cheap): run `scripts/watch_telemetry.py` against the telemetry folder — already-processed files are skipped; confirm no errors and the clean path prints as before.
- [ ] **Step 3:** finishing-a-development-branch (merge to master). Then: CLAUDE.md (close the PB-cleanliness watch item, add a cleanliness section, bump test count), Atlas next_actions (remove the deferred-spec item; add driving-validation of the asterisk), memory update.

---

## Self-Review

- **Spec coverage:** detector (offline+live, fail-open, decrease-ignored, None-ignore, baseline-carry) → Task 1. Watcher gate (best unchanged, candidate=plausible∧clean, report fields, note wording incl. no-clean case, CLI print) → Task 2. Phrasing (1x/2x/4x verb + noun forms, multi-mark, fallback corner, empty→"") → Task 3. Live wiring (READ_CHANNELS not SAMPLE_CHANNELS, guards, reset-on-discard, asterisk on both channels, dirty-baseline refusal, session-best guard, logging) → Task 4. Edge cases: tow/reset (tracker.reset via discard), pit (no feed + discarded), reconnect (new tracker at connect), first-feed-baseline (Task 1 test).
- **Type consistency:** `IncidentMark(distance_m, delta)` used identically in Tasks 1/2/3/4; `check_lap_cleanliness(df) -> LapCleanliness`; `IncidentTracker.feed(count, dist)/close_lap()/reset()`; `format_asterisk_speech(marks, corners) -> str`; `format_dirty_baseline_speech(marks) -> str`; `SessionReport.best_lap_dirty/dirty_note`.
- **No placeholders:** all code shown; Task 4's ordering caveat is spelled out with the corrected sequence.
