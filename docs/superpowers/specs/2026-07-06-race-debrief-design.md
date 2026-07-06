# Race Debrief (Surface 1) — Design

**Date:** 2026-07-06
**Status:** Approved (scope and architecture confirmed with user)
**Context:** First build of the race-intelligence market product (`docs/race-engineer-v2-strategy.md`, §4 Surface 1). The lap-coaching stack continues as founder tooling; this is the product surface: ingest a completed race, reconstruct what actually happened, deliver an engineer's debrief, and let the driver interrogate it. Design promise under test: "every race makes you smarter — win or lose."

## Goals

- One vertical slice: pick a race IBT → deterministic race narrative → AI-written debrief → conversational follow-up, all on one Streamlit page.
- The narrative (facts) is deterministic, typed, and testable; the AI supplies voice and prioritization only. Facts render fully with no API key.
- iRating attribution: a transparent accounting of whether rating was lost to pace or to incidents/decisions — no black-box model.
- Debriefs persist (SQLite) and export as clean markdown — the shareable artifact the distribution strategy leans on.
- Tone contract enforced in the prompt: engineer, not judge; never scold; never invent facts; a wrecked race produces the most *useful* debrief.

## Non-Goals

- No hosted/AI-race support (sessions without official Data API results) — v1 requires an official `SubSessionID`. A degraded IBT-only path is a later spec.
- No driver profile v1 (racecraft tendencies accumulation) — separate spec; this design only ensures the persisted data can feed it.
- No live/CarIdx anything — disk IBTs contain no CarIdx arrays (verified 2026-07-06 on a real race IBT: only `PlayerCarIdx` exists). Surface 3 concern.
- No pre-race briefing content (Surface 2 / Phase 4).
- No multi-class-specific analysis in v1 (single-class races first; class position fields are ingested but the narrative logic assumes one class).

## Decisions (confirmed 2026-07-06)

| Question | Decision |
|---|---|
| First spec scope | Full vertical slice: ingestion + narrative + AI debrief + chat; profile deferred |
| Surface | New Streamlit page with `st.chat_message` follow-up |
| Architecture | Deterministic narrative engine (`core/race/`) + AI synthesis grounded in it |
| V1 extras | Persist debriefs + chat to SQLite; markdown export. Hosted-race degraded path deferred |
| Persistence home | New `data/races.db` (subsession-keyed), NOT the watcher's `sessions` table (IBT-filename-keyed, watcher-owned) |
| Opponent granularity | Lap-by-lap (forced by data: no CarIdx in disk IBT; API lap data is per-lap) |

## Data sources (verified on `mx5 mx52016_oulton international 2026-06-26 16-42-05.ibt`)

1. **Race IBT** — player channels at 60Hz. Race ingestion passes an extended channel list to the existing `IBTParser.parse(channels=...)`: `CORE_CHANNELS + ["PlayerCarPosition", "PlayerCarClassPosition", "SessionFlags", "FuelLevel", "SessionState"]`. No structural parser change.
2. **IBT session YAML** — `WeekendInfo.SubSessionID` (the API linkage), `SeriesID`, `SeasonID`, `EventType`, `Official`, and `DriverInfo.Drivers` roster: UserName, UserID, CarIdx, CarNumber, **IRating**, LicString, CarScreenName. All verified present.
3. **iRacing Data API** — three new methods on `LiveIRacingAPI` (same OAuth/S3-link flow as existing endpoints):
   - `get_subsession_results(subsession_id)` — `GET /data/results/get` → per-driver finish position, laps, incidents, **oldi_rating/newi_rating**, SoF, and the simsession list.
   - `get_lap_chart_data(subsession_id, simsession_number)` — `GET /data/results/lap_chart_data` → every car's position on every lap. **Chunked** response.
   - `get_lap_data(subsession_id, simsession_number, cust_id)` — `GET /data/results/lap_data` → per-lap times + event flags (off-track, pitted, invalid) for one driver. **Chunked** response.
   - Chunk handling: these endpoints return `chunk_info` (base URL + chunk file names) instead of a single S3 link; a private `_fetch_chunked(chunk_info)` helper downloads and concatenates the JSON arrays. `StubIRacingAPI` grows matching methods returning empty/None (graceful fallback pattern).
   - **Simsession selection:** use the entry in `session_results` whose `simsession_type_name`/`session_name` is the race (fall back to `simsession_number == 0`). Practice/quali segments in the same subsession are ignored in v1.
4. **Raw-response cache** — every API JSON is written to `data/race_cache/{subsession_id}/{endpoint}.json` (gitignored) before parsing. Re-opening a race never refetches; copied cache files are the recorded test fixtures.

## Architecture

```
app/pages/race_debrief.py           # display-only: picker, charts, debrief, chat, export
core/race/
  models.py                         # dataclasses: RaceNarrative and parts
  ingest.py                         # orchestrator: IBT + YAML + API (+cache) → RaceData
  narrative.py                      # PURE: RaceData → RaceNarrative
  render.py                         # PURE: RaceNarrative → deterministic markdown
  race_store.py                     # data/races.db persistence
core/coaching/prompts/race_debrief.py   # tone contract + debrief prompt
core/coaching/synthesizer.py        # + generate_race_debrief(), + race chat turn
core/benchmark/iracing_api.py       # + 3 endpoints + chunk helper
```

### Models (`core/race/models.py`)

- `RaceData` — raw ingested bundle: player telemetry DataFrame, roster entries, results rows, lap chart rows, player (and rival) lap-data rows. Intermediate; not persisted.
- `RaceNarrative` — the product of the engine, JSON-serializable via `to_dict()`:
  - `header`: track/config, car, series, SoF, field size, start position (grid), finish position, official iRating old/new/delta, incident count.
  - `position_timeline`: list of (lap, position) for the player + per-rival timelines for key rivals.
  - `lap1`: grid position, position at end of lap 1 (and lap 2), list of within-lap place changes with `lap_dist_pct` and corner name (existing corner DB via lazy seeding — same helper path the watcher/live coach use).
  - `gaps`: per key rival, list of (lap, cumulative_gap_s); positive = rival ahead.
  - `incidents`: list of `IncidentEvent(lap, lap_dist_pct, corner_name, delta_x, position_before, position_after, time_lost_estimate_s)` from `PlayerCarMyIncidentCount` steps, cross-referenced with lap_data event flags.
  - `stints`: pit stops (from `OnPitRoad` edges) splitting the race into stints; per stint: laps, median clean pace, trend (first-half vs second-half median).
  - `cautions`: green/caution segments from `SessionFlags` transitions; empty list for clean road races.
  - `pace`: player median clean lap, best lap, field pace ranking (see attribution), consistency (stdev of clean laps).
  - `irating_attribution`: see below.
  - `key_rivals`: up to 4 CarIdx entries — the cars finishing immediately ahead/behind plus any car holding a position adjacent to the player for ≥3 laps.

### Narrative computations (`core/race/narrative.py`, pure)

- **Clean lap** := no incident-count step on that lap, no pit-in/out, not lap 1, not under caution. Pace metric is the **median** of clean laps (robust to outliers).
- **Pace-deserved finish**: rank all classified drivers by their median clean race lap (from per-driver lap data; drivers with < 3 clean laps are excluded from the ranking and listed as unranked). The player's rank in that ordering = "where your pace deserved to finish."
- **iRating attribution** (transparent accounting, no counterfactual elo model in v1):
  - Actual iRating delta comes from the results API (`newi_rating - oldi_rating`).
  - The narrative states: pace-deserved position vs actual position, then accounts for the difference in time terms — summed `time_lost_estimate_s` of incidents (incident-lap time vs player's clean median), lap-1 net positions, pit delta vs rivals.
  - `time_lost_estimate_s` for an incident lap = that lap's time minus the player's clean median (floor 0). Approximate and labeled as an estimate — honesty over precision.
- **Gap evolution**: rival cumulative race time per lap (sum of their lap times, from lap data) minus player cumulative time. Where rival lap data isn't fetched (only key rivals are, to bound API calls), gaps fall back to position-only trends from the lap chart.
- Sign/units conventions follow the house style: seconds and meters, SI internally, converted at display time via `app/components/units.py`.

### Deterministic render (`core/race/render.py`)

`RaceNarrative → markdown` — header block, position story, incidents table, pace/attribution section. This is what the page shows when the Anthropic key is missing, and the top half of the export artifact. Never contains AI text.

### AI debrief + chat

- **Prompt** (`core/coaching/prompts/race_debrief.py`) — system rules, in order:
  1. You are the driver's race engineer. Engineer, not judge. Never scold; never flatter dishonestly.
  2. Every factual claim must come from the narrative JSON. If asked something not derivable from it, say you don't have that data from this session.
  3. Reframe bad races as intelligence gained. A wrecked race gets the most useful debrief, not the most painful one.
  4. Be opinionated: end with 2–3 takeaways max, concrete and forward-looking ("next restart, hold the inside through T1" not "be more careful").
  - User content: the full `RaceNarrative` JSON + a one-line context (driver name, series).
- **Synthesis** — `generate_race_debrief(narrative)` in the existing synthesizer, same client/caching pattern as coaching synthesis (cached per narrative hash in `st.session_state`, one call per race, not per rerun).
- **Chat** — `st.chat_message`/`st.chat_input` loop. System context = tone contract + narrative JSON + the generated debrief; history capped at the last 20 turns. Each turn appends to the persisted transcript. No tools, no retrieval — the narrative is the whole ground truth, which is what keeps it honest.

### Persistence (`core/race/race_store.py`, `data/races.db`)

```sql
CREATE TABLE races (
    subsession_id INTEGER PRIMARY KEY,
    track_id INTEGER, track_name TEXT, car TEXT, series_name TEXT,
    session_date TEXT, sof INTEGER, field_size INTEGER,
    start_position INTEGER, finish_position INTEGER,
    incidents INTEGER, irating_old INTEGER, irating_new INTEGER,
    ibt_file_path TEXT,
    narrative_json TEXT NOT NULL,          -- full RaceNarrative
    created_at TEXT NOT NULL
);
CREATE TABLE debriefs (
    subsession_id INTEGER PRIMARY KEY REFERENCES races(subsession_id),
    debrief_text TEXT NOT NULL, model TEXT, created_at TEXT NOT NULL
);
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subsession_id INTEGER REFERENCES races(subsession_id),
    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
```

- Scalar columns exist for cheap listing/profile queries; the narrative JSON blob is canonical.
- Re-ingesting a race upserts `races` and preserves chat history.
- Explicit column lists everywhere (same forward-compat rule as the watcher spec) — driver profile v1 will read this DB.

### Streamlit page (`app/pages/race_debrief.py`, display-only)

- **Picker**: scans the telemetry folder for race IBTs + upload fallback. Cheap scan requires reading only header + session YAML — add `IBTParser.parse_session_only(path)` that reads just the session-info byte range (offsets are in the 112-byte header; no full-file read). Previously-analyzed races (from `races.db`) listed for instant re-open.
- **Layout**: header card (finish, SoF, iR delta) → position timeline chart (Plotly, player + key rivals) → gap chart → incident list (with corner names) → deterministic narrative → AI debrief → chat → export button.
- **Export**: `st.download_button` producing `{track}-{date}-debrief.md` = deterministic narrative + AI debrief (+ chat transcript, checkbox-optional).

## Error Handling

- No API credentials / API failure: page shows a clear warning and renders the player-only partial narrative (position timeline from `PlayerCarPosition`, incidents, stints — no field pace ranking, no attribution). Never crashes. Full IBT-only mode remains out of scope; this is just graceful degradation of the same page.
- Broken/absent Anthropic key: narrative + charts render fully; debrief and chat sections show the blocker message. (Current standing blocker — the deterministic path is the majority of this build and fully testable without it.)
- IBT is not a race (`EventType != "Race"` or no `SubSessionID`): picker filters these out; direct upload gets a clear "this isn't an official race session" message.
- Chunk download failures: retry once, then treat as API failure (degrade as above). Cached JSON is written only after a complete successful fetch.

## Testing

- **Real-data fixture**: the Oulton MX-5 official race (2026-06-26, subsession 86748877) — race IBT copied to `tests/fixtures/race/` plus its recorded API JSON from `data/race_cache/` (both gitignored; a fixture README documents how to re-record). Tests skip gracefully when absent, per project pattern.
- `test_race_narrative.py` — pure-function tests on synthetic `RaceData`: clean-lap classification, pace-deserved ranking (incl. <3-clean-laps exclusion), incident time-lost estimates, gap math, lap-1 place-change extraction, caution segmentation.
- `test_race_ingest.py` — integration against the Oulton fixtures: narrative fields populated, simsession selection, cache-hit path (no network when cache present).
- `test_iracing_api.py` additions — chunk assembly from local fake chunk files; stub methods return empty.
- `test_race_store.py` — round-trip, upsert preserves chat, explicit-column discipline.
- `test_race_render.py` — markdown render golden checks on a small synthetic narrative.
- `test_synthesizer.py` additions — race debrief prompt assembly with stub client (no live API).
- `test_ibt_parser.py` addition — `parse_session_only` returns same session metadata as full parse on the sample fixture.

## Rollout

1. Build ingestion + narrative against the Oulton race; validate the narrative reads true against memory of the race (founder is the ground truth for v1).
2. Wire the page + persistence + export; debrief/chat activate when the Anthropic key is rotated.
3. Founder debriefs his own next official races (the tool's existence is itself the race-more nudge); post one real debrief to the friends group — first shareable artifact.
4. Driver profile v1 spec follows, reading `races.db` + the watcher's `sessions` tables.

## Watch items / open questions (park, don't block)

- Incident `time_lost_estimate_s` is a lap-granularity approximation; multi-incident laps conflate. Acceptable for v1 (labeled as estimate); replay-file analysis is the eventual upgrade path (strategy doc §7.1).
- Lap-chart position data and IBT `PlayerCarPosition` can disagree transiently (timing-line vs live). Narrative uses the lap chart as canonical at lap boundaries, ticks only for within-lap color.
- API rate limits: one race = 1 results call + 1 lap-chart call + ~5 lap-data calls (player + rivals). Fine for personal use; batch/backoff is a multi-user concern (strategy doc §7.4).
- Multi-class races: fields are ingested (`CarClassID`, class position) but narrative logic is single-class; multi-class attribution is a follow-up.
- Chat context size: narrative JSON for a long race could get large; if it exceeds a sane budget, summarize gap/timeline arrays before injection (decision deferred until a real long-race narrative exists).
