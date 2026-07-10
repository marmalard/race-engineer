# Auto Race-Capture (Watcher SP1)

**Date:** 2026-07-10
**Status:** Design — approved in brainstorm, pending spec review
**Context:** First sub-project of the Driver Profile effort. Driver Profile v1 (SP2 — racecraft tendencies + a pace/consistency/readiness layer, profile page + debrief injection) follows this and is the reason it exists: the profile is only durable and populated if races are captured automatically.

## Problem

The race debrief (Surface 1) persists a full `RaceNarrative` per race into `races.db`, and that narrative is durable — it survives deletion of the source IBT. But races only enter `races.db` through a **manual** page visit today (`app/pages/race_debrief.py`). iRacing IBT files are ephemeral (they accumulate locally and get deleted). If a race's IBT is deleted before the driver opens the debrief page, the **IBT-derived racecraft signals are lost** — incident location/timing, caution laps, stint pace. (The iRacing Data API is itself durable — results, lap chart, iRating persist server-side — so positions and results are re-fetchable; only the IBT-only signals are at risk.)

The driver profile that SP2 will build is an aggregation over `races.db`. It is meaningless if races aren't reliably captured. So: **the watcher must auto-capture finished races into `races.db` promptly, while the IBT still exists.**

Practice / qualifying / test sessions are already auto-captured by the Stage 3 watcher (session + lap history + PB into `tracks.db`). **Races are the only session type not being captured** — that is the whole of SP1.

## Goals

- The telemetry watcher detects finished race sessions and captures the full (or partial) `RaceNarrative` into `races.db` automatically — no manual page visit.
- Durability-first: never lose the ephemeral IBT-derived signals because official results were slow to settle.
- Reuse the existing race pipeline (`ingest_race` → `build_narrative` → `RaceStore.save_race`) unchanged; the page already runs exactly this flow.
- Fix a latent bug this surfaces: race laps must never be promoted as PB references.

## Non-Goals

- No AI debrief on the capture path. Capture persists only the deterministic narrative; the AI debrief + chat stay on-demand on the page (auto-generating would cost Anthropic API $ per race). Capture ≠ debrief.
- Not the Driver Profile itself (SP2).
- Not oval support (the watcher's plausibility gate is already road-only; unchanged here).

---

## Detection & routing

A race IBT is identified exactly as the page does it — the existing `load_race_ibt` already encodes the rule and raises `RaceIngestError` for non-races:

> `WeekendInfo.EventType == "Race"` **and** a non-zero `SubSessionID`.

New pure classifier in `core/watcher/race_processor.py`:

```python
def classify_ibt(weekend_info: dict) -> str: ...  # "race" | "lap"
```

Returns `"race"` when `EventType == "Race"` and `SubSessionID` is truthy, else `"lap"`. It reads only the already-parsed `WeekendInfo` dict (no I/O) so it is unit-testable.

The watcher CLI (`scripts/watch_telemetry.py`) routes each new IBT:
- **race** → `process_race_ibt(...)` (new).
- **lap** → existing `process_ibt(...)` (practice/qual/test — unchanged).

To classify without parsing twice, the router parses the IBT once and inspects `WeekendInfo`. (Implementation note for the plan: `process_ibt` and `process_race_ibt` both currently parse; the router can do a single lightweight parse to read `WeekendInfo`, then hand off. Parsing an IBT header is cheap; a double parse is acceptable if it keeps the two processors self-contained — the plan decides. Either way the scanner stays pure.)

## `process_race_ibt`

New `core/watcher/race_processor.py`, mirroring `process_ibt`'s contract: **never raises**, returns a report; any exception is captured into the report so a bad file never aborts the folder scan.

```python
@dataclass
class RaceReport:
    path: Path
    subsession_id: int = 0
    track: str = ""
    car: str = ""
    start_position: int = 0
    finish_position: int = 0
    incidents: int = 0
    captured: bool = False     # narrative saved to races.db this scan
    partial: bool = False      # saved without Data API results
    deferred: bool = False     # results not ready + file still young → retry next scan
    error: str | None = None
```

Flow:

1. `ingest_race(path, api)` → `RaceData`. `ingest_race` already degrades to a **partial** `RaceData` (empty `results`/`lap_chart`/`driver_laps`) when `api is None` or the Data API fails — it does **not** raise on API-not-ready. So the "results ready" signal is `len(data.results) > 0`, **not** an exception.
2. Decide, based on results-readiness + file age (see next section):
   - **Full** (`data.results` non-empty): `build_narrative(data, corners)` → `race_store.save_race(narrative, ibt_file_path=str(path))`. `captured=True`.
   - **Partial + give up waiting** (results empty, file old, or no creds): save the partial narrative. `captured=True, partial=True`.
   - **Defer** (results empty, file still young, creds present): do **not** save, do **not** mark processed. `deferred=True`. Retry next scan.
3. Record a race session-history row in `tracks.db` (session_type `"Race"`) when captured — this marks the IBT processed via the existing path-based `processed_ibt_paths()` dedupe **and** gives the SP2 pace layer race lap times. **No PB promotion** from race laps.
4. Corners: reuse the watcher's existing lovely-seeding `_load_corners` helper (races want corner names for incident/place-change labeling, same as the page).

`race_store.save_race` is INSERT-OR-REPLACE keyed `(subsession_id, cust_id)`, so re-capturing (e.g., a later manual page visit that refills API data) is safe and idempotent.

## Durability-first timing (age-gated retry, no persisted counters)

The scanner already provides each candidate's file `mtime`; the age gate is a pure function of `(now, mtime, results_ready, have_creds)` — fully testable, no per-file state persisted across scans.

```python
GRACE_MINUTES = 5.0   # tunable — how long to wait for official results to settle
```

Decision:
- `results_ready` (data.results non-empty) → **full capture**.
- results empty, `have_creds`, `now - mtime < GRACE_MINUTES*60` → **defer** (retry next 30s scan).
- results empty, and (`now - mtime >= GRACE_MINUTES*60` **or** not `have_creds`) → **partial capture** (persist the ephemeral IBT signals; the page can later refill via INSERT-OR-REPLACE).

Rationale: the IBT-only signals are the perishable part; the Data API results are durable and re-fetchable. Waiting a few minutes for results is worth it, but never at the cost of losing the IBT before it's captured.

## Cache-poisoning guard (required)

`_cached_fetch` (in `core/race/ingest.py`) writes **whatever** `fetch()` returns to `data/race_cache/{subsession}/*.json`. If `api.get_subsession_results` returns an **empty** payload (results not yet posted) rather than raising, that empty is cached — and every later retry then reads the cached empty and never re-fetches, stranding the race as partial forever.

**Required fix:** `_cached_fetch` must not persist a falsy fetch result — skip the cache write when `fetch()` returns empty/None, returning it uncached so the next attempt re-fetches. (This is also a latent fix for the page: re-opening a race whose results weren't ready the first time currently reads a poisoned empty cache.) A legitimately-empty payload (e.g. a driver with zero lap_data rows) simply re-fetches next time — a negligible cost, never incorrect.

## Credentials

Race capture needs the iRacing Data API (`LiveIRacingAPI` from env creds), built with the page's existing `_iracing_api()` pattern (returns `None` when creds are absent). The watcher CLI builds the API once per run:
- creds present → full/partial capture per the age gate.
- creds absent → `api=None`: race IBTs are captured **partial immediately** (nothing better will ever come), logged once. The practice/qual/test lap path is entirely unaffected.

## CLI & reporting

`scripts/watch_telemetry.py` gains race-aware routing and printing:
- Deferred: `Race <name> — results not ready, will retry (subsession <id>)`.
- Captured full: `Race captured: Oulton Park, MX-5 Cup, P7→P4 (subsession 86748877)`.
- Captured partial: `Race captured (partial — no results yet): <name> (subsession <id>)`.

The Toolbox page and `--watch` loop are unchanged in structure; races just flow through. All real logic stays in `core/watcher/`; the CLI only lists files and prints.

---

## Files

| File | Change |
|------|--------|
| `core/watcher/race_processor.py` | **new** — `classify_ibt`, `RaceReport`, `process_race_ibt`, age-gate decision helper |
| `core/race/ingest.py` | `_cached_fetch` skips caching falsy results (poisoning guard) |
| `scripts/watch_telemetry.py` | parse once → route race vs lap; print race reports; build `LiveIRacingAPI` once |
| `core/track/track_db.py` | (only if needed) ensure race session-history recording + a way to keep PB promotion off race laps — may be handled entirely in the processor |

Reused unchanged: `core/race/ingest.py::ingest_race` / `load_race_ibt`, `core/race/narrative.py::build_narrative`, `core/race/race_store.py::RaceStore`, `core/watcher/scanner.py`.

## Testing

- **`classify_ibt`**: race (EventType "Race" + SubSessionID) → `"race"`; Practice / Qualify / Test / Open Practice / missing EventType / zero SubSessionID → `"lap"`.
- **Age-gate decision helper** (pure): results-ready → full; empty + young + creds → defer; empty + old → partial; empty + no creds → partial.
- **`process_race_ibt` full path** on the Oulton fixtures (`data/race_cache/86748877` + `tests/fixtures/race`) with a stub API → narrative saved to a temp `races.db`; header asserts start P7 → finish P4; second run idempotent (INSERT-OR-REPLACE, no duplicate).
- **Partial fallback**: `api=None` → partial narrative saved (`partial=True`), empty results.
- **Deferred**: results empty + young file + creds present → nothing saved, `deferred=True`.
- **`_cached_fetch` guard**: a falsy fetch result is not written to disk; a later non-empty fetch succeeds. (Add to `test_race_ingest.py`.)
- **No PB pollution**: a race IBT does not add a `personal_best` row to the ReferenceStore.
- **Routing**: the watcher CLI sends a race IBT to `process_race_ibt` and a practice IBT to `process_ibt` (helper-level test).

Fixtures already exist: the Oulton MX-5 race (subsession 86748877, P7→P4) in `tests/fixtures/race/` + `data/race_cache/86748877/`.

## Edge cases / watch items

- **Hosted / league races**: `EventType` may still be "Race" but Data API results may be absent or delayed → degrades to partial naturally.
- **Two testers in one subsession**: keyed by the local player's `cust_id` (from the IBT's `DriverUserID`); each rig captures its own row.
- **iRating settle lag**: covered by the age gate (partial after `GRACE_MINUTES`).
- **Telemetry disk-writing disabled**: no IBT is written at all — out of scope (a user setting; already true for the practice path).
- **A race already captured via the page** before the watcher sees it: `save_race` INSERT-OR-REPLACE + processed-set dedupe make re-capture a no-op/refresh.
