# Telemetry Watcher (Stage 3) — Design

**Date:** 2026-07-06
**Status:** Approved (scope decisions confirmed with user)
**Context:** The live voice coach now coaches against stored reference laps, but the ReferenceStore only gets populated by manual G61 imports — Spa Endurance is the single seeded combo. The watcher closes the loop: every session the driver completes automatically feeds the system, so the live coach works at every track with zero setup and Phase 3 (cross-session coaching) gets its data foundation.

## Goals

- One command processes everything new in the iRacing telemetry folder; `--watch` keeps it running while driving.
- Per new session: record session + lap history rows, auto-promote the session's best valid lap into the ReferenceStore (`personal_best` source), and print a debrief of the best lap against the best available reference.
- Never touch `g61` reference rows. Promotion is automatic and silent-safe: a promoted PB can only improve future coaching.
- A corrupt or half-written IBT file must never abort the scan.

## Non-Goals

- No voice, no AI — the watcher is an offline console tool.
- No UI (Streamlit integration can read the same tables later).
- No deletion/archival of IBT files (the folder stays the user's).
- No cross-session analysis (Phase 3 consumes the history this creates; it is not built here).
- No profiles.db — the `sessions`/`laps` tables already defined in `tracks.db` (schema exists in `track_db.py:55-82`, currently method-less) are the session history home. CLAUDE.md's mention of a separate profiles.db is superseded for now.

## Decisions (confirmed 2026-07-06)

| Question | Decision |
|---|---|
| Process model | Scan command + `--watch` polling flag (no daemon, no service) |
| Per-session actions | Promote PB + print debrief + record session/lap history rows |
| Promotion policy | Automatic; valid laps only; only when faster than the existing `personal_best` for (track_id, car); `g61` rows never written |
| History storage | Existing `sessions`/`laps` tables in `data/tracks.db` via new TrackDB methods |

## Architecture

```
scripts/watch_telemetry.py        # CLI: scan once, or --watch to poll
  └── core/watcher/
      ├── scanner.py              # PURE: discovery, stability, dedupe, promotion decision
      └── processor.py            # per-file pipeline: parse → normalize → record → promote → debrief text
```

Follows the live-coach pattern: pure, tested logic in `core/`, a thin script driving I/O and printing.

### Discovery & stability (`core/watcher/scanner.py`, pure)

- `find_new_ibts(folder_files, processed_paths, now, min_age_s=90.0) -> list[Path]`
  - `folder_files`: list of `(path, mtime, size)` tuples gathered by the script (keeps the core pure — no filesystem in scanner.py).
  - Excludes files whose path is already in `processed_paths` (the dedupe set from the sessions table).
  - **Stability guard:** excludes files with `now - mtime < min_age_s` — iRacing appends to the .ibt for the whole session; a file modified in the last 90 s is assumed still being written. In `--watch` mode this means a session is processed ~90 s after the sim closes it. Simple, no size-tracking state.
  - Returns oldest-first (chronological history order).
- `should_promote(best_lap_time, existing_pb_time) -> bool` — pure: promote when no existing PB or strictly faster. (The G61-untouched guarantee comes from writing only `source='personal_best'`; `ReferenceStore.save` upserts per source and `get()` already prefers g61.)

### Per-file pipeline (`core/watcher/processor.py`)

`process_ibt(path, track_db, ref_store) -> SessionReport`:

1. **Parse** with `IBTParser` (accepts Path). Any exception → return a failed `SessionReport(error=...)`; the caller prints and continues. Failed files are NOT recorded as processed — they retry next scan (a permanently corrupt file prints one line per scan; acceptable, noted as a watch item).
2. **Normalize** all laps (`parser.get_laps` → `Normalizer.normalize_session`, same as the G61 gate test does). Keep valid laps only.
3. **Track row + corners**: create the track row if unknown and lazy-seed corners via `seed_track_from_lovely` using `ibt.session.track_directory` (the directory-string field added 2026-07-06) with Crew Chief fallback — same behavior as the live coach's `_load_corners`, extracted so both paths share it if convenient, otherwise mirrored.
4. **Record history**: one `sessions` row (session_id = the IBT filename stem — unique, stable, human-legible; ibt_file_path = full path — the dedupe key; best_lap_time; theoretical best left NULL for now; lap_count = valid laps) and one `laps` row per valid lap (lap_number, lap_time, is_valid). Sector times NULL.
5. **Promote**: if `should_promote` against the store's existing `personal_best` meta for (track_id, CarScreenName) → `ref_store.save(..., source='personal_best', driver_name=ibt.session.driver_name)`.
6. **Debrief**: `ref = ref_store.get(track_id, car)` (prefers g61). If a reference exists **and is not the same lap just promoted**, run `build_debrief(best_lap, ref.lap, corners)` and format with the existing `format_lap_block`. If the session's own best IS the reference (first session at a combo), report "baseline session — PB recorded" instead.
7. Return `SessionReport` (dataclass: path, track/car names, laps_found, valid_laps, best_lap_time, promoted: bool, debrief_text: str | None, error: str | None) — the script prints it; tests assert on it.

### TrackDB additions (`core/track/track_db.py`)

- `record_session(session_id, track_id, car, session_type, session_date, best_lap_time, lap_count, ibt_file_path)` — INSERT OR REPLACE.
- `record_laps(session_id, laps: list[tuple[int, float, bool]])` — bulk insert (lap_number, lap_time, is_valid); delete-then-insert per session for idempotency.
- `processed_ibt_paths() -> set[str]` — SELECT ibt_file_path FROM sessions (the dedupe set).

### CLI (`scripts/watch_telemetry.py`)

- Default folder: `C:\Users\antho\Documents\iRacing\telemetry` (constant `TELEMETRY_DIR`, overridable with `--folder`).
- Plain run: gather `(path, mtime, size)`, load processed set, process new files oldest-first, print each `SessionReport`, exit.
- `--watch`: same scan in a loop every `POLL_SECONDS = 30`; Ctrl-C exits. No fancy filesystem events — polling is plenty at this cadence.
- Exit code 0 even when individual files fail (failures are reported, not fatal); non-zero only if the folder itself is missing.

## Error Handling

- Per-file try/except around the whole pipeline; one bad file never stops the scan.
- ReferenceStore/TrackDB write failures inside one file's processing are that file's failure (report, retry next scan) — partial history writes are tolerated because `record_*` calls are idempotent (REPLACE / delete-then-insert).
- Empty session (no valid laps): recorded as a session row with lap_count 0 (so it doesn't rescan forever), no promotion, no debrief.

## Testing

Mirrors project style — pure functions unit-tested, fixture-dependent tests skip gracefully.

- `test_watcher_scanner.py`: stability window (fresh file excluded, old file included, boundary), dedupe against processed set, chronological ordering, `should_promote` (no PB / faster / slower / equal).
- `test_track_db.py` additions: record_session upsert idempotency, record_laps replace-on-rerun, processed_ibt_paths round-trip.
- `test_watcher_processor.py`: full `process_ibt` against the sample IBT fixture (skips if absent) with tmp DBs — session recorded, PB promoted on first run, NOT re-promoted on identical rerun, debrief text present when a faster g61 reference is pre-seeded, corrupt-file path returns error report.

## Rollout

1. Run once over the existing telemetry folder — instant back-fill: every combo the driver has IBTs for gets a personal_best reference and history rows. (Yesterday's Spa sessions become history; the g61 Borsuk lap stays the preferred Spa reference automatically.)
2. Habit: run after driving, or leave `--watch` running alongside the live coach.
3. Phase 3 reads the populated `sessions`/`laps` tables.

## Watch items

- iRacing may write multiple IBTs per outing (one per car/session transition) — each is just an independent session here; fine.
- The 90 s stability window is a constant to tune; if iRacing ever pauses writes mid-session > 90 s, a truncated parse would be recorded as processed. Parse failures are retried, so the real risk is a *parseable* partial file — accepted for now.
- `session_type` from the IBT YAML when present, else "unknown"; no attempt to distinguish practice/race beyond that.
