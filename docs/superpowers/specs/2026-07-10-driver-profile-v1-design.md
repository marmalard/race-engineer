# Driver Profile v1 (SP2)

**Date:** 2026-07-10
**Status:** Design — approved in brainstorm, pending spec review
**Context:** Second sub-project of the Driver Profile effort. SP1 (auto race-capture, shipped 2026-07-10) makes `races.db` populate itself; this builds the profile on top. Strategy anchor (docs/race-engineer-v2-strategy.md §"The shared brain"): all three surfaces run on one accumulating driver profile — racecraft tendencies, not just corner technique.

## Problem

The engineer has no memory across races. Every debrief starts from zero: it can say "you lost 2 places on lap 1" but not "that's the third race in a row." And for drivers who practice a lot but race rarely — the product's core anxiety case — there is no surface that turns their practice volume into race confidence ("you've done 40 clean laps here and your pace is tightening").

Two data sources already accumulate durably:
- **`races.db`** — one full `RaceNarrative` per race (SP1 auto-captures them): lap-1 story, incidents with corners and time-lost, stints with fade trends, pace summary, iRating attribution.
- **`tracks.db`** — the watcher's `sessions` + `laps` history for every practice/qual/test session (68 sessions / 408 laps today).

Driver Profile v1 aggregates both into tendencies and readiness signals, shows them on a page, and injects a compact summary into the race-debrief prompt so the AI engineer becomes pattern-aware.

## Goals

- A deterministic profile engine: races + session history in, `DriverProfile` out. Pure, unit-testable on synthetic fixtures.
- A **Driver Profile** Streamlit page rendering it (no AI on the page).
- Compact profile injection into the race-debrief prompt (and chat), with the tone contract amended so profile facts are a permitted source.
- Graceful degradation: every tendency carries its sample size and an `enough_data` flag; below threshold the page shows "collecting data", and the prompt block omits it.

## Non-Goals

- **No new DB table.** The profile is derived on demand from `races.db` + `tracks.db` (dozens of races, hundreds of laps — cheap, always fresh, no staleness). Materialize later only if scale demands.
- **No population benchmarks.** "Is my pace good enough for the 3k split?" needs `result_search_series` population data — a Phase 4 item. v1's readiness signals are benchmark-free (your own progression + consistency).
- **No G61 backfill.** The G61 developer API (verified real, 2026-07-10: token/OAuth, laps/lap_csv/stats — lap-centric) is parked as an optional future pace-layer/backfill source. Not in v1.
- **No technique tendencies** (which corners you lose time in) — needs loss-region persistence; separate effort.
- **No AI in the engine.** The AI only ever *sees* the profile as prompt context; it never computes it.

---

## Architecture

New package `core/profile/`, mirroring the race package's pure-engine style:

```
core/profile/
├── __init__.py
├── models.py       # DriverProfile + tendency dataclasses (values, samples, enough_data, verdicts)
├── racecraft.py    # PURE: list[RaceNarrative] -> racecraft tendencies
├── pace.py         # PURE: session-history rows -> per-combo readiness
├── builder.py      # thin I/O orchestration: stores -> load inputs -> build_profile
└── render.py       # deterministic verdict lines, markdown, and the prompt block
```

`racecraft.py` and `pace.py` are pure (no DB, no I/O). `builder.py` is the only module that touches the stores.

### Thresholds (constants in `models.py`, tunable)

```python
RACECRAFT_MIN_RACES = 3      # tendencies unlock at 3 races with the relevant data
READINESS_MIN_SESSIONS = 2   # per-combo readiness unlocks at 2 sessions...
READINESS_MIN_LAPS = 10      # ...and 10 valid laps
RECURRING_CORNER_MIN = 2     # a corner is "recurring trouble" at 2+ incidents across races
```

Sample sizes are **per tendency**, not global: a partial narrative (SP1's partial capture) missing `lap1` or `attribution` still contributes to the tendencies it does support (incidents are telemetry-sourced and survive partial mode by design).

## Racecraft tendencies (`racecraft.py`)

`build_racecraft(narratives: list[RaceNarrative]) -> RacecraftTendencies`

Sign convention throughout: **positive = gained places** (grid 7 → P5 after lap 1 = +2).

1. **Starts** (`StartsTendency`) — from `narrative.lap1` (skip races where None):
   - `mean_lap1_net` = mean of `grid_position - position_after_lap1`
   - `mean_lap2_net` = mean of `position_after_lap1 - position_after_lap2` (the settle)
   - `races_lost_ground` / `sample`
   - Verdict e.g.: *"You lose ground at the start — avg −1.4 on lap 1 across 6 races (lost in 5 of 6)."*

2. **Pace vs result** (`PaceVsResultTendency`) — **the headline**. From `narrative.attribution` where `pace_deserved_position` is not None:
   - `mean_positions_left` = mean of `actual_position - pace_deserved_position` (positive = finishing worse than pace deserves)
   - `mean_incident_time_lost_s` = mean of `attribution.incident_time_lost_s`
   - Verdict e.g.: *"Your pace deserves ~P4 but you finish ~P6 — the gap is incidents and decisions, not speed."*

3. **Incidents** (`IncidentTendency`) — from `narrative.header.incidents` (rate) + `narrative.incidents` events (timing/location):
   - `mean_incident_points` per race; `lap1_share` = fraction of incident *events* on lap 1
   - `recurring_corners`: `corner_name` counts ≥ `RECURRING_CORNER_MIN` across races (None corner names excluded)
   - Verdict e.g.: *"3.2 incident points/race, 40% on lap 1. Repeat trouble: Old Hall (3×)."*

4. **Trajectory** (`TrajectoryTendency`) — from `header` (skip when `start_position` < 1, i.e. partial without results) + `stints`:
   - `mean_race_net` = mean of `start_position - finish_position`
   - `mean_stint_fade_s` = mean of stint `trend_s` over stints where not None (positive = slower second half)
   - Verdict e.g.: *"You gain +1.8 places over a race on average, but fade late (+0.3s second-half pace)."*

Each tendency dataclass: the metric fields + `sample: int` + `enough_data: bool` (`sample >= RACECRAFT_MIN_RACES`) + `verdict: str` (deterministic, built in `render.py`).

## Pace / readiness layer (`pace.py`)

`build_readiness(sessions: list[SessionRow], laps: dict[str, list[LapRow]]) -> list[ComboReadiness]`

- Input: the watcher's session history, **excluding `session_type == "Race"` rows** (race pace lives in the racecraft layer; traffic/fuel laps would pollute practice consistency).
- Grouped per combo `(track_id, car)`. Per combo (`ComboReadiness`):
  - `sessions: int`, `valid_laps: int`, `last_driven: str` (most recent session_date)
  - `best_lap: float | None` (min session best), `pb_trend_s: float | None` = earliest session's best − latest session's best across sessions that have one (positive = getting faster)
  - `consistency_s: float | None` = stdev of valid lap times in the most recent 3 sessions (None below 5 laps)
  - `enough_data` = `sessions >= READINESS_MIN_SESSIONS and valid_laps >= READINESS_MIN_LAPS`
  - Verdict (descriptive, benchmark-free — never overclaims "ready"): *"14 sessions, 89 clean laps. PB down 1.2s over the run; last 3 sessions within ±0.4s."*
- Output sorted by `valid_laps` descending (most-practiced combos first).

### Store read methods (currently write-only — must be added)

- `TrackDB.list_session_history() -> list[SessionRow]` — all sessions rows (session_id, track_id, track_name via join, car, session_type, session_date, best_lap_time, lap_count).
- `TrackDB.get_session_laps(session_id) -> list[LapRow]` — (lap_number, lap_time, is_valid).
- `RaceStore.get_narratives(cust_id) -> list[RaceNarrative]` — all stored narratives for a driver, newest first (iterates rows; dozens at most).

`SessionRow`/`LapRow` are lightweight dataclasses (in `track_db.py`, following `StoredRaceMeta`'s pattern).

## Builder (`builder.py`)

```python
def load_profile(race_store: RaceStore, track_db: TrackDB, cust_id: int) -> DriverProfile
```
Loads narratives + session history, calls the two pure builders, assembles `DriverProfile` (racecraft + readiness list + `races_captured`, `combos_tracked` counts). Any store failure degrades to the empty profile (page shows "collecting data"; injection emits nothing) — the profile must never break the debrief page.

## Rendering + prompt injection (`render.py`)

- `verdict_*` helpers produce the deterministic one-liners quoted above (unit-tested exact strings, like nudges).
- `profile_markdown(profile) -> str` — the page body (also reusable in exports later).
- `profile_prompt_block(profile) -> str` — compact JSON of **enough-data tendencies only** (verdicts + the numbers behind them) + up to 5 readiness combos, wrapped in `--- DRIVER PROFILE (tendencies across {n} prior races; computed deterministically) ---` fences. Returns `""` when nothing crosses threshold. Hard cap ~2000 chars (drop readiness combos first, then trailing tendencies).

### Prompt integration (`core/coaching/prompts/race_debrief.py`)

- `build_race_debrief_prompt(narrative, profile_block: str = "")` — inserts the block (when non-empty) between the header line and the race data. Same optional param on `build_race_chat_system`. Defaults keep every existing caller/test working.
- **Tone contract amendment** (required): rule 2 currently says facts MUST come from the race data JSON. Amend to: facts must come from the race data JSON **or the driver-profile block when present**; profile facts are cross-race tendencies and must be cited as such ("across your last 6 races"), never presented as facts about *this* race. Everything else in the contract stands.
- The debrief page (`app/pages/race_debrief.py`) builds the block via `load_profile` + `profile_prompt_block` (wrapped in try/except → `""`) and passes it to both prompt builders. **Cache note:** the existing AI-debrief session-state cache is keyed by a hash of the analysis inputs — the profile block must join that key so a changed profile invalidates the cached debrief.

## Profile page (`app/pages/driver_profile.py`)

Registered alongside the existing pages. Display only, no business logic:
- **Header row**: races captured, combos tracked, total clean laps.
- **Racecraft section**: one card per tendency — verdict line + the numbers; below threshold the card renders *"Collecting data — N of 3 races captured."* Pace-vs-result gets top billing.
- **Readiness section**: table of `ComboReadiness` (combo, sessions, clean laps, PB, PB trend, consistency, last driven), enough-data combos first; sub-threshold combos greyed with counts.
- **Empty state** (0 races, 0 sessions): a short explainer that races auto-capture via the watcher and practice accrues automatically.

## Testing

- `tests/test_profile_racecraft.py` — synthetic `RaceNarrative` fixtures (a `_narrative(...)` helper building minimal dicts through `RaceNarrative.from_dict`): each tendency's math (means, signs, lap1_share, recurring corners), per-tendency samples with partial narratives (lap1 None / attribution None / start_position 0 skip only their tendency), `enough_data` at the 2→3 boundary.
- `tests/test_profile_pace.py` — synthetic session/lap rows: grouping, Race-type exclusion, pb_trend sign, consistency window, thresholds, sort order.
- `tests/test_profile_render.py` — exact verdict strings; prompt block: empty below threshold, contains only enough-data tendencies, respects the char cap, fence text.
- `tests/test_track_db.py` (extend) — the new read methods round-trip against `record_session`/`record_laps`.
- `tests/test_race_store.py` (extend) — `get_narratives` returns stored narratives newest-first, filtered by cust_id.
- `tests/test_synthesizer.py`-style check (or in prompts tests): `build_race_debrief_prompt` with and without a profile block; amended system prompt contains the profile-source rule.

## Edge cases

- **1 race today**: everything renders as "collecting data"; prompt block is `""` — the debrief is exactly as it is now. The profile lights up as SP1 captures more races.
- **Partial narratives**: contribute per-tendency (incidents yes; starts/attribution/trajectory only if present).
- **Two testers** (friend's cust_id in the same races.db): `get_narratives(cust_id)` filters. The page resolves cust_id as: the most-frequent cust_id in `races.db` (single-user reality); when multiple cust_ids exist, a driver selectbox appears. Zero races → the empty state (no cust_id needed).
- **Sessions with no laps recorded** (empty session rows exist for dedupe): contribute to session counts only if they have a best_lap_time; never to lap counts.
