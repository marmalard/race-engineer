# Track-Limits Asterisk (Lap Cleanliness)

**Date:** 2026-07-11
**Status:** Design — approved in brainstorm, pending spec review
**Context:** Deferred from Live Voice UX round 2 (agreed 2026-07-10). Closes the Stage-3 watcher watch item: "no cleanliness gate on promoted PBs — an off-track-but-complete fast lap can become the reference."

## Problem

A lap with a minor track-limits infraction usually has **perfect telemetry** — continuous, monotonic, full coverage. The normalizer's `is_valid` (rightly) accepts it, so today such a lap:
1. can be **promoted as a personal-best reference** by the watcher — every future session then gets coached against a time that wasn't legal, and a real clean PB can never displace it;
2. is spoken by the live coach as a plain lap time — *"2:07.2, three tenths quicker"* — when the honest engineer line is *"2:07.2 — but track limits at Griffins, that time won't count."*

The data is great (the corners you drove cleanly are still reference-quality driving); the **time** is what shouldn't count. Keep the lap, coach the lap, asterisk the time.

## Decisions (locked in brainstorm)

- **Dirty rule: ANY mid-lap increase in `PlayerCarMyIncidentCount`** (1x off-track, 2x loss of control, 4x contact — indistinguishable at 1x granularity, and a lap with *any* incident shouldn't be a reference anyway). The delta is kept per mark so the voice can phrase 1x/2x/4x differently.
- **v1 consumers: the watcher PB gate + the live voice asterisk.** A laps-table `is_clean` column (→ profile "clean laps" accuracy) is explicitly deferred — the profile's representative-lap filter already bounds that damage.
- **Coach the dirty lap, never promote it.** Debrief/nudges run normally; promotion and session-baseline selection skip it.

## Non-Goals

- No laps-table schema change / profile integration (deferred).
- No distinction between "marginally over the white line" and "four wheels through the gravel" — iRacing's incident count is the arbiter, as it is in the sim.
- No re-audit of already-promoted references (the back-filled PBs stand; strictly-faster *clean* laps will displace them over time). A manual re-audit can be a follow-up script if desired.
- `NormalizedLap` and the normalizer are untouched — detection runs on the raw lap DataFrame / live ticks.

## Architecture

New pure module **`core/telemetry/cleanliness.py`** (no I/O, no pyirsdk):

```python
# (No phrasing here — the 1x/2x/4x wording map is presentation and lives in
# core/live/nudges.py::format_asterisk_speech; this module only detects.)

@dataclass
class IncidentMark:
    """One mid-lap incident-count increment."""
    distance_m: float      # LapDist at the tick the count rose
    delta: int             # 1 / 2 / 4 (whatever iRacing added)

@dataclass
class LapCleanliness:
    clean: bool
    marks: list[IncidentMark]   # empty when clean

def check_lap_cleanliness(df: pd.DataFrame) -> LapCleanliness:
    """Offline: one per-lap DataFrame (needs PlayerCarMyIncidentCount + LapDist
    columns — both in IBTParser.CORE_CHANNELS, so present in get_laps() output).
    A count increase between consecutive rows = one mark at that row's LapDist.
    Missing columns -> clean (fail-open: cleanliness is an enhancement, never
    a reason to break processing)."""

class IncidentTracker:
    """Live: pure per-tick state machine (mirrors LapBoundaryTracker's style).
    feed(incident_count, lap_dist_m) records a mark when the count rises;
    close_lap() returns the accumulated marks and resets for the next lap;
    reset() discards (called on lap discard / reconnect). None inputs are
    ignored (tow / out-of-world ticks)."""
```

Corner naming stays at the consumers via the existing pure `corner_name_at(corners, dist_m)` (`core/race/narrative.py:278`) — both consumers already hold a loaded `corners` list.

## Consumer 1 — watcher PB gate (`core/watcher/processor.py`)

- After normalization, compute `check_lap_cleanliness` per raw lap DataFrame, keyed by lap number (the raw frames and `NormalizedLap.lap_number` join on it).
- `best` (fastest plausible) is **unchanged** — it remains the debrief target and the reported best time. We still coach dirty laps.
- **Promotion candidate = fastest plausible AND clean lap.** May be a different (slower) lap than `best`; if no clean plausible lap exists, nothing is promoted.
- `SessionReport` gains:
  - `best_lap_dirty: bool` (the session's fastest lap had an incident)
  - `dirty_note: str | None` — e.g. `"fastest lap (2:07.2) had track limits at Griffins — best clean lap (2:07.8) promoted instead"` or `"... — no clean lap to promote"`. Corner named via `corner_name_at` with the already-loaded corners; falls back to `"~{km} km from start/finish"`-style position text only if no corner matches (reuse the annotator convention).
- The CLI (`scripts/watch_telemetry.py::_format_report`) prints `dirty_note` when present.
- This closes the CLAUDE.md watch item; the ROAD-only plausibility ceiling note is unrelated and stays.

## Consumer 2 — live voice asterisk (`scripts/live_coach.py` + `core/live/nudges.py`)

- `PlayerCarMyIncidentCount` added to `READ_CHANNELS` (NOT to `LapBuffer.SAMPLE_CHANNELS` — the buffer's normalizer-shape contract is untouched).
- Each tick feeds `IncidentTracker.feed(count, lap_dist)` with the same guards as the prompt scheduler (skip when `LapDist` is None or `OnPitRoad`; on `tick.discarded` call `tracker.reset()`).
- On a completed **valid** lap, `close_lap()` yields the marks:
  - **Clean:** exactly today's behavior.
  - **Dirty:** debrief + normal lap speech still run, then an appended asterisk clause from a new pure `format_asterisk_speech(marks, corners) -> str` in `nudges.py`:
    - 1x → `" — but track limits at {corner}, that time won't count."`
    - 2x → `" — but you lost it at {corner}, that time won't count."`
    - 4x → `" — but contact at {corner}, that time won't count."`
    - Multiple marks: phrase the FIRST (earliest) mark only, appending `" (and {n} more)"` when n ≥ 1 further marks exist. Corner fallback when unnamed: `"out there"`.
  - **Dirty laps never become the session baseline or session-best.** First-lap-dirty → no baseline is set; the speech makes it unambiguous: baseline wording is replaced by `"That lap had {phrase} — I won't use it as the baseline. Give me a clean one."` A dirty faster lap later in the session likewise does not replace `session_best` (stored references are never replaced mid-session already).
- The terminal/feed block (`emit`) gets the same asterisk text appended (visual channel parity, per round-2 convention).
- Session log: the `lap` event gains `dirty: bool` and `marks: [{distance_m, delta}, ...]`; the skipped-baseline case logs a `dirty_baseline_skipped` event.

## Edge cases / honest limits

- **Attribution lag:** iRacing sometimes increments the count a few ticks after the physical moment — the named corner can occasionally be the *following* corner. Acceptable for a voice line; documented here, not compensated for in v1.
- **Increment on the lap's first tick** (boundary spillover from the previous lap's incident): counted against the lap where the increment is observed — deterministic and simple; the lag caveat above covers it.
- **Tow/reset mid-lap:** the lap is discarded by the existing tracker anyway; `IncidentTracker.reset()` keeps marks from leaking into the next lap.
- **Pit-road increments** (rare): ticks are not fed while `OnPitRoad`, and pit-touched laps are discarded regardless.
- **Session reconnect:** live_coach re-creates the tracker at connect (same lifecycle as the prompt scheduler).
- **Watcher offline path & pit/out-laps:** cleanliness is only consulted for promotion; invalid/implausible laps are already excluded upstream.

## Testing

- `tests/test_cleanliness.py` (new): clean frame → clean; single/multiple increments with exact `distance_m`/`delta`; missing columns → clean (fail-open); `IncidentTracker` feed/close/reset semantics incl. None-input ignore and no-leak-across-laps.
- `tests/test_watcher_processor.py` (extend): fastest-dirty + slower-clean → clean lap promoted + `best_lap_dirty` + `dirty_note` mentions both times; all-dirty → nothing promoted; all-clean path byte-identical behavior (existing tests unchanged).
- `tests/test_nudges.py` (extend): `format_asterisk_speech` exact strings for 1x/2x/4x, multi-mark "(and 1 more)", unnamed-corner fallback.
- `tests/test_live_coach_helpers.py` or tracker tests: dirty-baseline-skip decision if extracted as a pure helper.

## Files

| File | Change |
|------|--------|
| `core/telemetry/cleanliness.py` | **new** — `IncidentMark`, `LapCleanliness`, `check_lap_cleanliness`, `IncidentTracker` |
| `core/watcher/processor.py` | promotion pool = plausible ∧ clean; `SessionReport.best_lap_dirty`/`dirty_note` |
| `scripts/watch_telemetry.py` | print `dirty_note` |
| `core/live/nudges.py` | + `format_asterisk_speech` |
| `scripts/live_coach.py` | READ_CHANNELS + tracker wiring + asterisk/baseline-skip speech + logging |
