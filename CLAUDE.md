# Race Engineer

## Project Overview

Race Engineer is a personal racing engineer for iRacing. It analyzes telemetry, sources community knowledge, and delivers opinionated coaching that helps intermediate drivers get faster. It is not a data visualization tool — it is a coaching system that tells you what you don't know.

Two initial features:
1. **Scouting Report** — pre-session briefing for a car/track combo with pace targets, key corners, and community wisdom
2. **Lap Coaching** — post-session analysis that compares your laps to your own best performance and delivers prioritized, actionable coaching on the 2-3 corners where you're leaving the most time

See `docs/prd.md` for the full product requirements document, and `docs/race-engineer-v2-strategy.md` (2026-07-06) for the strategic direction that extends it: **coach the race, not the lap**. The lap-coaching stack (debrief engine, live voice coach) continues as the founder's personal tool and the pipeline foundation; the market product is race intelligence — post-race debrief, pre-race field briefing, live engineer with push-to-talk — the gap Trophi/G61/VRS/Crew Chief all leave open. Incumbents sell pace; this sells confidence ("you never start a race blind, you never race alone"). Leading metric: does the user's official-race volume go up?

## Architecture

```
race-engineer/
├── CLAUDE.md
├── README.md
├── pyproject.toml                # uv-managed dependencies (no requirements.txt)
├── docs/
│   └── prd.md                    # Product requirements document
├── app/
│   ├── streamlit_app.py          # Main Streamlit entry point
│   ├── pages/
│   │   ├── scouting.py           # Scouting report UI
│   │   ├── coaching.py           # Lap coaching UI (debrief wired in)
│   │   ├── race_debrief.py       # Race debrief UI (Surface 1): picker, charts, chat, export
│   │   ├── guide.py              # In-app guide: friend onboarding + founder reference
│   │   ├── toolbox.py            # Host-only start/stop/status for live coach + watcher
│   │   ├── progression.py        # Progression page: streak, trends, PB timeline, iR/SR, implied iR
│   │   ├── week_plan.py          # Week Plan page: latest plan + history + optional AI chat
│   │   └── setup.py              # First-run wizard + Settings & Keys (key rotation)
│   └── components/               # Shared Streamlit components
│       ├── units.py              # Unit conversion helpers (metric/imperial)
│       └── track_map.py          # GPS track outline with colored loss regions
├── core/
│   ├── telemetry/
│   │   ├── ibt_parser.py         # IBT file reading and extraction
│   │   ├── normalizer.py         # Distance-based normalization and resampling
│   │   ├── corner_detector.py    # Fallback annotator (demoted from analysis path)
│   │   ├── lap_comparator.py     # Lap-to-lap and benchmark comparison logic
│   │   ├── alignment.py          # Cross-correlation distance-offset alignment
│   │   └── loss_regions.py       # Loss-region extraction from cumulative delta
│   ├── track/
│   │   ├── track_db.py           # Track database CRUD operations
│   │   ├── corner_registry.py    # Match detected corners to DB corners
│   │   ├── crew_chief_seeder.py  # Crew Chief corner name import and seeding
│   │   ├── lovely_seeder.py      # lovely-track-data seeder (185 iRacing configs)
│   │   ├── segment_annotator.py  # Annotate loss regions with corner names
│   │   ├── track_assets.py       # Official iRacing SVG track maps + detail_copy
│   │   └── models.py             # Track and corner data models
│   ├── benchmark/
│   │   ├── iracing_api.py        # iRacing Data API client
│   │   ├── g61_import.py         # Garage 61 CSV import → NormalizedLap
│   │   └── reference_store.py    # SQLite store of reference laps (npz blobs)
│   ├── coaching/
│   │   ├── analyzer.py           # Legacy coaching analysis orchestrator
│   │   ├── debrief.py            # Debrief orchestrator (align→loss regions→diagnose)
│   │   ├── synthesizer.py        # AI coaching synthesis (Claude API)
│   │   ├── scouting.py           # Scouting report generation
│   │   └── prompts/              # Prompt templates for AI synthesis
│   │       ├── coaching.py
│   │       ├── scouting.py
│   │       └── week_plan.py      # WEEKPLAN_SYSTEM_PROMPT — page-only, never the scheduled path
│   ├── live/
│   │   ├── lap_buffer.py         # Accumulate live ticks into normalizer-ready DataFrame
│   │   ├── session_reader.py     # LapBoundaryTracker pure state machine
│   │   ├── nudges.py             # RegionDiagnosis → terse nudge + spoken lap summary
│   │   ├── speaker.py            # Non-blocking SAPI voice (latest-wins queue)
│   │   ├── prompt_scheduler.py   # Distance-triggered in-corner prompts
│   │   ├── feed.py               # In-memory nudge feed + stdlib web display
│   │   └── process_control.py    # ManagedProcess: detached spawn, PID files (data/run/), tree-kill — Toolbox backend
│   ├── watcher/
│   │   ├── scanner.py            # Pure discovery: stability window, dedupe, promotion + plausibility gates
│   │   ├── processor.py          # Per-IBT pipeline: history + PB promotion + debrief (practice/qual/test)
│   │   └── race_processor.py     # Race IBT auto-capture → races.db (age-gated full/partial/defer, no PB)
│   ├── profile/
│   │   ├── models.py             # Tendency/readiness/profile dataclasses + thresholds
│   │   ├── racecraft.py          # PURE: narratives → 4 racecraft tendencies (per-tendency samples)
│   │   ├── pace.py               # PURE: session history → per-combo readiness (representative-lap filter)
│   │   ├── render.py             # Verdict lines, page markdown, capped prompt block
│   │   ├── builder.py            # load_profile — the package's only I/O; degrades to empty
│   │   └── prescriptions.py      # Curated combo→skill prescription seed table (week-plan input)
│   ├── progression/
│   │   ├── models.py             # StreakSummary / ComboImplied / DriverImpliedIR
│   │   ├── streak.py             # PURE: race-week streak math (Tuesday flip)
│   │   ├── trends.py             # PURE: pace / fault / PB trend series (fault ladder reused)
│   │   ├── implied_ir.py         # PURE: weighted implied-iR band roll-up
│   │   ├── ingest.py             # I/O: chart_data per-day cache + weekly implied-iR compute
│   │   └── store.py              # data/progression.db — implied_ir_history weekly snapshots
│   ├── weekplan/
│   │   ├── models.py             # WeekPlan/RaceHalf/PracticeHalf/SRCheck + constants
│   │   ├── build.py              # target-week math, tick decisions, build_week_plan (no AI)
│   │   ├── render.py             # Deterministic markdown; verdicts exact-string pinned
│   │   ├── store.py              # week_plans JSON table in data/progression.db
│   │   └── notify.py             # Marker handshake: watcher writes, tray consumes, one owner
│   ├── config/
│   │   └── env_setup.py          # .env contract: REQUIRED keys, baked defaults (gitignored _baked.py), Setup page backend
│   ├── update/
│   │   ├── version.py            # get_version from pyproject [project] version; bump_version
│   │   ├── manifest.py           # RELEASE_ENTRIES whitelist; is_installed_layout gate
│   │   ├── releases.py           # check_for_update (tag-only GitHub latest, SHA256SUMS required); download_zip
│   │   └── apply.py              # apply_update: sha256 gate → zip-slip guard → extract in temp → selective swap
│   └── race/
│       ├── models.py             # RaceData (raw) + RaceNarrative (product) dataclasses
│       ├── ingest.py             # Race IBT + YAML + Data API → RaceData (disk cache, partial mode)
│       ├── narrative.py          # PURE narrative engine: RaceData → RaceNarrative
│       ├── render.py             # Deterministic RaceNarrative → markdown (+ export assembly)
│       └── race_store.py         # data/races.db — narratives, debriefs, chat, keyed (subsession, cust)
├── scripts/
│   ├── live_coach.py             # Terminal entry point (pyirsdk driver)
│   ├── watch_telemetry.py        # Telemetry folder scan CLI (--watch to poll)
│   ├── record_race_fixture.py    # Record real race API fixtures for integration tests
│   ├── build_release.py          # Release artifact cutter: bump, flat zip, SHA256SUMS, baked-cred refresh
│   └── backfill_diagnoses.py     # Back-fill region diagnoses over recorded history (vs current reference)
├── data/
│   ├── tracks.db                 # SQLite track database
│   ├── profiles.db               # SQLite driver profile and session history
│   ├── reference_laps.db         # SQLite reference lap store (npz-compressed blobs)
│   ├── races.db                  # SQLite race debrief store (gitignored)
│   ├── progression.db            # SQLite implied-iR history snapshots (gitignored)
│   └── race_cache/               # Cached Data API JSON per subsession (gitignored)
└── tests/
    ├── test_ibt_parser.py
    ├── test_normalizer.py
    ├── test_corner_detector.py
    ├── test_corner_detection_tuning.py
    ├── test_lap_comparator.py
    ├── test_multilap_comparator.py
    ├── test_track_db.py
    ├── test_crew_chief_seeder.py
    ├── test_iracing_api.py
    ├── test_synthesizer.py
    ├── test_analyzer.py
    ├── test_scouting.py
    ├── test_unit_helpers.py
    ├── test_parser_cross_validation.py
    ├── test_alignment.py
    ├── test_loss_regions.py
    ├── test_reference_store.py
    ├── test_lovely_seeder.py
    ├── test_segment_annotator.py
    ├── test_debrief.py
    ├── test_track_assets.py
    ├── test_track_map.py
    ├── test_g61_import.py
    ├── test_g61_validation_gate.py
    ├── test_lap_buffer.py
    ├── test_session_reader.py
    ├── test_nudges.py
    ├── test_live_coach_helpers.py
    ├── test_feed.py
    ├── test_speaker.py
    ├── test_prompt_scheduler.py
    ├── test_race_models.py
    ├── test_race_narrative.py
    ├── test_race_render.py
    ├── test_race_store.py
    ├── test_race_ingest.py
    ├── test_watcher_scanner.py
    ├── test_watcher_processor.py
    ├── test_watch_telemetry_helpers.py
    ├── test_process_control.py
    ├── test_update_version.py
    ├── test_env_setup.py
    ├── test_install_shortcut.py
    ├── test_build_release.py
    ├── test_update_releases.py
    ├── test_update_apply.py
    ├── test_backfill_diagnoses.py
    ├── test_progression_streak.py
    ├── test_progression_trends.py
    ├── test_progression_implied_ir.py
    ├── test_progression_store.py
    ├── test_progression_ingest.py
    ├── test_progression_page.py
    ├── test_prescriptions.py
    ├── test_weekplan_build.py
    ├── test_weekplan_render.py
    ├── test_weekplan_store.py
    ├── test_weekplan_notify.py
    └── test_weekplan_page.py
```

## Key Technical Concepts

### Telemetry Pipeline

The telemetry pipeline is the foundation everything is built on. It must be rock solid.

1. **IBT Parsing** — Read iRacing .ibt binary telemetry files. Extract channels: speed, throttle, brake, steering, GPS lat/lon, lap number, lap time, session time. IBT files contain a header with session metadata and channel definitions followed by sample data at a fixed frequency.

2. **Distance Normalization** — Convert time-series telemetry to distance-based. Resample all channels to consistent distance intervals (1 meter). This creates a common x-axis for comparing laps to each other and to external benchmarks. This is critical — without it, lap comparisons are meaningless.

3. **Corner Detection** — Automatically segment a lap into corners using telemetry heuristics:
   - Find local minima in the speed trace (corner apexes)
   - Walk backward from each minimum to find the braking point (brake pressure onset)
   - Walk forward to find full throttle application (corner exit)
   - Each detected segment = one corner
   - Segments between corners = straights
   - Results are matched to the track database for corner names

4. **Lap Comparison** — Compare two distance-normalized laps channel by channel. Calculate deltas for braking point, corner minimum speed, throttle application point, and time gained/lost per corner.

### Corner Detection Heuristics

Corner detection works by analyzing the speed trace:
- Smooth the speed signal to remove noise
- Find local minima below a threshold (these are apex points)
- For each apex, search backward for the braking initiation point (where brake > threshold OR significant deceleration begins)
- Search forward for corner exit (where throttle > threshold AND speed is increasing)
- Merge corners that are very close together (chicanes, esses)
- Filter out false positives (minor speed variations on straights)

The detected corners should be cached per track/car combo and refined over time.

### Self-Referential Benchmarking

The primary coaching approach compares the driver to themselves:
- Within a session: compare each lap to the driver's best lap
- Theoretical best: take the best time through each corner across all laps and sum them
- Cross-session: compare current performance to personal best at this track
- Identify corners where performance varies (consistency issue) vs. corners that are consistently slow (technique issue)

### AI Synthesis

The AI layer translates structured analysis into coaching language. Keep the split clean:
- **Deterministic analysis** produces structured data: corner gaps, braking deltas, consistency scores
- **AI synthesis** takes that structured data and generates natural language coaching
- The AI should be opinionated and prioritize — surface 2-3 things, not everything
- Coaching language should be specific and actionable: "brake at the 3 marker" not "brake earlier"

### Track Database Schema

```sql
-- Tracks
CREATE TABLE tracks (
    track_id TEXT PRIMARY KEY,       -- iRacing track ID
    name TEXT NOT NULL,
    config TEXT,                      -- Track configuration name
    length_meters REAL,
    track_type TEXT,                  -- road, oval, street
    character TEXT,                   -- momentum, point-and-shoot, mixed
    notes TEXT                        -- General track notes
);

-- Corners
CREATE TABLE corners (
    corner_id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT REFERENCES tracks(track_id),
    corner_number INTEGER,           -- Sequential corner number
    name TEXT,                       -- Friendly name (e.g., "Big Bend", "Bus Stop")
    distance_start_meters REAL,      -- Distance from start/finish
    distance_end_meters REAL,
    corner_type TEXT,                -- hairpin, sweeper, chicane, kink, heavy_braking
    notes TEXT                       -- Corner-specific coaching notes
);

-- Sessions
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    track_id TEXT REFERENCES tracks(track_id),
    car TEXT,
    session_type TEXT,               -- practice, qualifying, race
    session_date TIMESTAMP,
    best_lap_time REAL,
    theoretical_best REAL,
    lap_count INTEGER,
    ibt_file_path TEXT,
    notes TEXT
);

-- Laps
CREATE TABLE laps (
    lap_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(session_id),
    lap_number INTEGER,
    lap_time REAL,
    is_valid BOOLEAN,                -- No off-tracks, incidents
    sector_times TEXT                -- JSON array of sector/corner times
);
```

## Development Guidelines

### Principles
- **Data foundation first.** Do not build UI or AI features until the telemetry pipeline (parse → normalize → detect corners → compare laps) works correctly and is tested.
- **Test with real data.** Always validate against actual IBT files. Synthetic test data can mask real parsing issues.
- **Deterministic analysis, creative synthesis.** The analysis code should produce consistent, testable results. The AI synthesis can be creative and opinionated.
- **Progressive enhancement.** Every feature should work with minimal data and get better with more. Scouting report works without personal history. Coaching works without external benchmarks.

### Code Style
- Python 3.11+
- Type hints on all function signatures
- Docstrings on public functions
- Use dataclasses or Pydantic models for structured data
- pandas DataFrames for telemetry data
- Keep analysis logic in `core/`, keep UI logic in `app/`
- No business logic in Streamlit files — they should only handle display

### Testing
- Unit tests for the telemetry pipeline are critical — especially IBT parsing, normalization, and corner detection
- Test corner detection against known tracks where you can manually verify the results
- Integration tests for the full pipeline: IBT file → normalized laps → detected corners → comparison output

### Common Pitfalls
- **IBT file format varies.** Different iRacing versions may have slightly different header structures. Parse defensively.
- **Distance normalization edge cases.** Pit laps, out-laps, and in-laps need to be handled or excluded. Laps with off-tracks may have weird distance jumps.
- **Corner detection tuning.** The heuristics need different sensitivity for different track types. A street circuit with lots of slow corners needs different thresholds than a fast flowing circuit. Consider making thresholds configurable per track type.
- **Garage 61 CSV alignment.** G61 data and IBT data will have different distance references and sample rates. Normalize both to the same distance grid before comparing.

## Dependencies

Core:
- pandas, numpy — data processing
- streamlit — UI
- requests / httpx — API calls
- sqlite3 — track database, session history (stdlib)
- anthropic — Claude API for AI synthesis

Telemetry:
- struct — IBT binary parsing (stdlib)
- scipy — signal processing for corner detection (smoothing, peak finding)

Live coaching:
- pyttsx3 — Windows SAPI text-to-speech (live voice; degrades to silent)

Visualization:
- plotly — interactive telemetry charts
- matplotlib — static plots if needed

## Environment Variables

```
IRACING_USERNAME=          # iRacing credentials for Data API
IRACING_PASSWORD=
ANTHROPIC_API_KEY=         # Claude API for coaching synthesis
```

## Quick Start

```bash
# Clone and install (uses uv; no requirements.txt)
git clone <repo>
cd race-engineer
uv sync        # creates .venv and installs all dependencies
# or: python -m pip install -e .

# Set up environment
cp .env.example .env
# Edit .env with your credentials

# Run the app
streamlit run app/streamlit_app.py

# Run tests
.venv/Scripts/python.exe -m pytest -q
```

## Current Status

**Phase 1: Foundation** (complete)
- [x] IBT parser — read and extract telemetry channels (`core/telemetry/ibt_parser.py`)
- [x] Distance normalizer — resample to distance-based (`core/telemetry/normalizer.py`)
- [x] Corner detector — automated segmentation (`core/telemetry/corner_detector.py`)
- [x] Lap comparator — self-referential comparison (`core/telemetry/lap_comparator.py`)
- [x] Track database — schema and basic CRUD (`core/track/track_db.py`)
- [x] Basic Streamlit shell (`app/streamlit_app.py`)
- [x] Scouting reports — Claude API with web search (`core/coaching/synthesizer.py`)
- [x] iRacing Data API client — Password Limited OAuth (`core/benchmark/iracing_api.py`)

**Phase 2: Core Features** (complete)
- [x] Coaching analysis orchestrator (`core/coaching/analyzer.py`)
- [x] Coaching AI synthesis — structured analysis → Claude → coaching narrative
- [x] Speed trace comparison plots (Plotly) in coaching page
- [x] Cumulative time delta plot in coaching page
- [x] Corner detection tuning — road preset lowered to 3.0 m/s (was 5.0)
- [x] Lap time accuracy — uses `LapCurrentLapTime[-1]` (not `.max()`, which picks up stale previous-lap values)
- [x] Disrupted lap filtering — 10% pace threshold instead of zero-incident filter
- [x] Corner position data in AI prompt (lap_position_percent, distance_from_start)
- [x] Track database seeding — Crew Chief data import, corner name matching
- [x] Pace context from iRacing API integrated into scouting reports
- [x] Unit toggle (metric/imperial) in coaching UI

**Stage 1: Trust Rebuild — reference-lap redesign** (complete, branch stage1-trust-rebuild)
- [x] pyirsdk parser cross-validation oracle (`tests/test_parser_cross_validation.py`)
- [x] Distance-offset alignment — circular cross-correlation, ±150m bounded (`core/telemetry/alignment.py`)
- [x] Loss-region extraction from cumulative delta trace (`core/telemetry/loss_regions.py`)
- [x] G61 CSV import → NormalizedLap, unit heuristics, column alias table (`core/benchmark/g61_import.py`)
- [x] Reference lap store — npz-compressed blobs in SQLite, g61 preferred over personal_best (`core/benchmark/reference_store.py`)
- [x] lovely-track-data seeder — 185 iRacing track configs, fraction→meters (`core/track/lovely_seeder.py`); wired as primary corner seeder in `_match_corner_names` with Crew Chief as fallback
- [x] Loss-region annotation — corner name or position fallback (`core/track/segment_annotator.py`)
- [x] Debrief orchestrator — corner detection removed from analysis path (`core/coaching/debrief.py`)
- [x] Official iRacing track map assets — turns layer, detail_copy HTML (`core/track/track_assets.py`)
- [x] GPS loss map component — Plotly track outline with colored loss regions (`app/components/track_map.py`)
- [x] G61 validation gate — plumbing round-trip verified; awaiting real paired fixtures (`tests/test_g61_validation_gate.py`)
- [x] Coaching page wiring — debrief section + reference expander; AI synthesis cached per analysis
- [ ] Activate validation gate with real G61 fixtures (Spa / Road America paired IBT + CSV)
- [ ] Verify real G61 export headers against CHANNEL_ALIASES in `g61_import.py`

**Live Coaching Spike (between-lap, terminal)** (complete, branch live-coaching-spike)
- [x] LapBuffer — live ticks → normalizer-ready DataFrame (`core/live/lap_buffer.py`)
- [x] LapBoundaryTracker state machine — pit/reset/tow/Lap-0/too-short gating (`core/live/session_reader.py`)
- [x] Deterministic nudges — salience: min-speed > braking > throttle; no AI, no API key on critical path (`core/live/nudges.py`)
- [x] Terminal entry point — pyirsdk driver, prints nudges after each flying lap (`scripts/live_coach.py`)
- [ ] Live driving validation — lap-boundary reliability + nudge naturalness across real sessions
- Note: reuses `build_debrief` / `Normalizer` unchanged; no edits to core analysis engine

**Live Voice Coaching** (complete, branch live-voice-coaching)
- [x] Diagnosis metrics: brake-release delta (trail guard: only where reference trails) + exit-speed delta + reference brake onset (`core/coaching/debrief.py`)
- [x] Five-rung nudge ladder — lift > braking > release (trail) > exit speed > throttle — with speech (car lengths, "k" for km/h) and terse quantity-free in-corner prompt phrasings (`core/live/nudges.py`)
- [x] format_lap_speech — delta-first spoken summary, confirmation nudges ("that's it, keep that"), returns flagged-label set for threading (`core/live/nudges.py`)
- [x] Speaker — daemon-thread SAPI via pyttsx3, one-slot latest-wins queue, in-progress never interrupted, failure degrades to silent (`core/live/speaker.py`)
- [x] PromptScheduler — triggers 300m before reference brake onset, corner-span safety clamp (move past exit or drop under 100m gap), max 3/lap, once-per-lap with rearm (`core/live/prompt_scheduler.py`)
- [x] live_coach wiring — --mute / --corner-prompts flags, ReferenceStore lookup at connect (CarScreenName key, visible-failure logging), stored reference never replaced mid-session, LapDist-None tow guard
- [x] Debrief cards show Brake Release + Exit Speed metrics (`app/pages/coaching.py`)
- [x] Rollout 0 (partial): real G61 CSV verified (LapDistPct-only headers; CHANNEL_ALIASES updated), Spa-Endurance/M2 reference imported to ReferenceStore (track 525, "BMW M2 Racing (G87)", 2:39.155 integrated vs 2:39.302 displayed = 0.09%)
- [ ] Full gate activation: needs the driver's OWN G61 lap export paired with its session IBT (tests/fixtures/g61/)
- [ ] Driving validation: voice audibility/pacing, trail-nudge accuracy, prompt trigger timing (LEAD_M 300m / CLAMP_MARGIN_M 30m / thresholds tunable)

**Live Voice Coaching — Round 2 UX** (complete, branch live-voice-ux-round2 — from first real drive Bathurst/992 Cup 2026-07-10; spec+plan in docs/superpowers/specs+plans/2026-07-*-live-voice-ux-round2*)
- [x] Startup radio check — `format_radio_check` speaks on connect in BOTH cases (with reference: "Radio check, reading you. Reference lap 2 07.7, loaded. Coaching from lap one." / without: "…No reference for this combo — I'll set a baseline from your first lap."); confirms the audio path even when the no-reference case was previously silent (`core/live/nudges.py`)
- [x] Discard acknowledgment — `LapBoundaryTracker.feed()` now returns `TickResult(completed, discarded)`; `DiscardReason` enum RESET/PIT; `format_discard_speech` → "Reset — scratch that lap." / "In the pits — that lap won't count."; RESET/PIT only fire when a real attempt was buffered (≥ min_lap_samples) so garage/pit-box resets stay silent (`core/live/session_reader.py`, `core/live/nudges.py`)
- [x] Normalizer-invalid line — a completed-but-invalid lap (off-track distance jump / <90% coverage) speaks "That lap won't count — data's incomplete." HARD LINE: fires only on broken/incomplete telemetry, never on a clean lap with a minor track-limits infraction (Normalizer.is_valid ignores PlayerTrackSurface/incident count) — the track-limits asterisk is a deferred separate spec
- [x] Approach cue enriched — `approach_cue_from_diagnosis` combines the top-2 faults, DROPS the corner name ("Coming up — brake a couple car lengths later, get to throttle earlier on exit"), coarse car-length magnitude (a bit / a couple car lengths / a lot); solves the "named corners are spatially confusing" field problem; wired into `build_schedule`; old dead `Nudge.prompt` field removed
- [x] Approach cues **on by default** — flag flipped to `--no-corner-prompts` (store_false); discard/invalid also `emit()` to the terminal + iPad web feed, not voice-only
- [ ] Driving validation of round 2: radio-check audibility, discard-line timing, approach-cue phrasing/lead-time; tune magnitude buckets (COARSE_*_MAX_LENGTHS in nudges.py) from data/live_sessions logs
- [x] Track-limits asterisk SHIPPED 2026-07-12 — see "Track-Limits Asterisk" section below

**Track-Limits Asterisk — lap cleanliness** (complete, merged 2026-07-12 — spec/plan in docs/superpowers/specs/2026-07-11-track-limits-asterisk-design.md + plans/2026-07-12-track-limits-asterisk.md)
- [x] Pure detector `core/telemetry/cleanliness.py` — dirty = ANY mid-lap rise in PlayerCarMyIncidentCount (1x/2x/4x kept per mark); `check_lap_cleanliness(df)` offline + `IncidentTracker` live (first-feed baseline, None-ignore, close_lap/reset keep the session-cumulative count baseline); fail-open on missing columns; NO phrasing/corner-naming in the module
- [x] Watcher PB gate — promotion pool = plausible ∧ CLEAN (fastest clean lap promoted; the dirty fastest stays the coached/reported best); `SessionReport.best_lap_dirty` + `dirty_note` (incident noun + corner via corner_name_at, "~X.X km" fallback); CLI prints the NOTE. Verified on the real Spa fixture — both its laps are genuinely dirty, tests pin that assumption
- [x] Live voice asterisk — dirty valid laps still fully coached, speech + terminal/feed get " — but track limits at {corner}, that time won't count." (1x; "you lost it"/2x, "contact"/4x, multi-mark "(and N more)", "out there" fallback); dirty laps NEVER become the session baseline ("That lap had track limits — I won't use it as the baseline. Give me a clean one.") or session-best; marks logged in session JSONL
- [x] Invariant (holistically verified): no dirty lap can reach the ReferenceStore by ANY path (watcher gated; race path never promotes; live coach never writes it)
- Known limits: iRacing's attribution lag can name the NEXT corner occasionally; already-promoted back-fill PBs are NOT re-audited (strictly-faster clean laps displace them over time — a re-audit script is a possible follow-up); shared phrasing via `incident_noun` in nudges.py

**Exit Verdict Cues** (complete, branch exit-verdict-cues — spec docs/superpowers/specs/2026-07-16-exit-verdict-cues-design.md, plan docs/superpowers/plans/2026-07-16-exit-verdict-cues.md; from the third-race field note "hard to know if I'm nailing the advice after the turn")
- [x] FaultKind ladder extracted in nudges.py — cue + verdict share ONE ranking function (`fault_kinds_from_diagnosis`; cue strings byte-identical)
- [x] RegionDiagnosis reference absolutes added (release / throttle-on / exit speed — the reference_brake_onset_m precedent; additive, defaults None)
- [x] core/live/exit_verdict.py — VerdictWatcher fires one quantity-free bucket verdict per prompted corner at span_end+100m ("That's it." / "Too far — back it off." / "Better — still a touch late." / "Still late on the brakes."); precedence fixed→overcorrected→better→unchanged (overcorrect BEFORE better — direction-word safety); speed/throttle faults never scolded for beating the reference; insufficient observation = silence; NaN tick guard (math.isfinite) — a NaN must never produce a confident wrong verdict
- [x] core/live/race_gate.py — FaultStreakTracker (streaks count COACHED laps; update once per comparison lap, full set) + `current_session_type` from SessionInfo per-session SessionType (NOT WeekendInfo.EventType — pre-race-chunk lesson); Race sessions default to `persistent` (primary fault must persist 2+ consecutive laps), `--race-cues full|persistent|off` (choices coupling-tested to RACE_CUE_MODES)
- [x] build_plan in prompt_scheduler — prompts + verdicts from ONE construction site (verdict iff cue actually scheduled, structurally); build_schedule stays as thin wrapper; shared `crossed()` lives in exit_verdict
- [x] live_coach wiring — SessionNum channel (churn-guarded int coercion, session_reader pattern), verdict feed try/except in tick path, verdict/session_type/schedule JSONL events (gated_out count logged for tuning)
- [x] Anti-drift coupling test — replays a real multilap IBT through the watcher; live brake onset == offline diagnosis (0.0m drift observed; brake onset ONLY — live throttle/min-speed definitions intentionally deviate: running min vs argmin)
- [ ] Driving validation: verdict timing (VERDICT_POINT_M 100m), bucket accuracy vs felt reality, race-gate quietness in traffic; tune IMPROVED_FRACTION / RACE_STREAK_MIN from session logs; if the gate "never engages" in a race, check the SessionNum channel first (fail-open to practice behavior)

**Loss-Region Persistence + Technique Tendencies** (complete, branch loss-region-persistence — spec docs/superpowers/specs/2026-07-17-progression-loss-region-persistence-design.md, plan docs/superpowers/plans/2026-07-17-loss-region-persistence.md)
- [x] region_diagnoses table in tracks.db (typed rows, no blobs; DELETE+INSERT idempotent keyed session_id; reference_source/lap_time context per row) + SessionRow.ibt_file_path
- [x] Watcher persists the best-lap debrief's diagnoses (`diagnoses_recorded` on SessionReport; CLI prints it); watcher-only write path — coaching page + live coach stay read-only (locked); parse_best_lap extracted (plausibility gates defined once, shared with back-fill)
- [x] scripts/backfill_diagnoses.py — re-debriefs recorded practice history vs the CURRENT reference per combo (consistent yardstick, deliberate); never promotes, idempotent, --dry-run
- [x] core/profile/technique.py — PURE; adapter row→RegionDiagnosis classified by the live FaultKind ladder (fault_kinds_from_diagnosis — one ranking, three consumers, coupling-tested); dominant fault + per-fault aggregates/trends + recurring corners (position-fallback "~" labels excluded); unlocks at TECHNIQUE_MIN_SESSIONS=5
- [x] Time-to-pace in core/profile/pace.py — median laps to reach 101% of session best (TTP_FACTOR, TTP_MIN_LAPS=5); the first behavioral diagnosis (races give zero warm-up laps)
- Watch item: technique trend measures time_lost vs the reference OF THE DAY — a PB improvement makes later losses look bigger ("growing" can mean the yardstick moved, not decline) and the trend pools across combos; rows store reference_source/lap_time so a per-(combo, reference) trend split is a computable follow-up; re-running the back-fill after PB waves re-baselines history to one yardstick
- [x] Profile wiring: DriverProfile.technique/.time_to_pace, Technique section on the page (warm-up collecting state always visible), prompt-block payloads (enough_data-gated, inside the capped tendencies dict)
- [ ] Run the back-fill on the rig (founder: `.venv/Scripts/python.exe scripts/backfill_diagnoses.py --dry-run` first, then real run; restart the watcher after merge to pick up new code)

**Progression Build** (complete, branch progression-build — spec §6-8 of docs/superpowers/specs/2026-07-17-progression-loss-region-persistence-design.md, plan docs/superpowers/plans/2026-07-17-progression-build.md)
- [x] core/progression/ package: streak (Tuesday-flip race weeks, partial-capture created_at fallback), trends (combo pace series / per-FaultKind time-lost-per-session via the technique adapter — fourth consumer of fault_kinds_from_diagnosis, coupling-tested / PB timeline), implied_ir (weighted band roll-up, ALWAYS a band), store (data/progression.db implied_ir_history, DELETE+INSERT per week), ingest (member_chart_data iR+SR per-day cache via _cached_fetch; compute_week_implied_ir = rank_series_candidates top-3 practice-depth series → harvest_field → place_on_curve raw, MIN_BIN_N honesty rail, cross-series combo dedupe)
- [x] Progression page (Practice nav, first entry): six blocks cheapest-first, every block has a collecting state; implied-iR renders last snapshot on load, recomputes only on button (30 fetches/series first time, week-cached after); snapshot keyed to iracing_week_start
- [x] core/profile/prescriptions.py — 6 curated rows (Porsche/Spa release+throttle, M2 braking+release+Road America throttle, Porsche/Bathurst braking; F4 is a transfer BENEFICIARY not a teacher), capability-framed, no consumer yet (week-plan input contract); FAULT_LABELS promoted public in render.py
- Known limits: implied-iR curve is series-scoped not car-filtered (same approximation as the shipped briefing page; series_name is the honesty label per row); SR chart assumes x100 scaling (normalize_sr heuristic); only combos at CURRENT-week series tracks get placed — coverage varies week to week by design; _cached_fetch (race ingest) now has 3 cross-package consumers — promote to public name on next core/race/ingest.py touch; pace/technique chart x-axes are categorical (session_date strings, even spacing); streak week boundary mixes UTC race dates with local today
- [ ] Founder validation: open the page with real data, click Recompute for this week, sanity-check the implied band against felt pace

**Week Plan v1 — scheduled push** (complete, branch week-plan — spec docs/superpowers/specs/2026-07-17-week-plan-design.md, plan docs/superpowers/plans/2026-07-17-week-plan.md)
- [x] core/weekplan/ package: models (every section optional, warnings never exceptions), build (target week = Tue-Sat current / Sun-Mon next; race half via rank_series_candidates week_delta=1 + harvest_field + place_on_curve raw; practice ladder prescription→race-combo-fallback via the one fault ladder; sports_car_license SR check SR_COMFORT=2.5), render (v3 §3 voice, verdicts exact-string pinned incl. both SR sentences and the curve-pending line — the pins ARE the no-gating guarantee), store (week_plans JSON in progression.db, re-save preserves created_at), notify (single owner of marker path/shape/toast copy)
- [x] Watcher weekly tick (after scans, own try/except, WEEK PLAN FAILED retries next poll): generate on create + write marker; silent hourly refresh while curve unfilled, daily after; no creds = quiet skip
- [x] Tray toast: watchdog tick consumes the marker → one pystray notify per week; tray down = marker persists, toasts on next start
- [x] Week Plan page (Race group, after Start): latest plan + history expander + optional AI narrative/chat (WEEKPLAN_SYSTEM_PROMPT tone contract); Start-page teaser card
- Living artifact: born Sunday with schedule/slots/SR/prescription, curve verdict backfills after the Tuesday flip (curve_filled flag drives refresh + page copy)
- [ ] Founder validation: first real Sunday push (toast fires, plan reads right), curve backfill lands Wednesday, prescription matches felt priorities
- Deferred: prep ledger, run sheet, mental-lap rehearsal, email/Discord channels, per-timeslot split prediction, mid-week conversational adjustments

**Stage 3: Telemetry Watcher** (complete, merged 2026-07-09)
- [x] TrackDB session-history methods — sessions/laps tables activated; record_session pre-creates a stub track row for the FK, healed by the processor's early upsert_track (`core/track/track_db.py`)
- [x] Scanner — 90s write-stability window, sessions-table dedupe, strictly-faster promotion, `is_plausible_lap` 85 m/s gate (ROAD-ONLY assumption — oval needs a track_type-dependent ceiling), `covers_full_lap` 98% gate (`core/watcher/scanner.py`)
- [x] Processor — upsert real track row → record history → promote plausible+complete+CLEAN personal_best (never touches g61; cleanliness gate added 2026-07-12) → debrief vs best reference (`core/watcher/processor.py`)
- [x] CLI — scan once or --watch poll every 30s; failures retry next scan (`scripts/watch_telemetry.py`)
- [x] Normalizer hardening — rejects >100m single-sample forward LapDist jumps (stationary tow/reset teleports that inflated coverage past the 90% check); found via real back-fill corruption (11s "PBs")
- [x] Back-fill executed over the real telemetry folder: 66 files, 30 plausible PBs across 14+ combos, g61 rows verified untouched, Spa 525 PB = the user's real 2:41.384
- ~~Watch item: no cleanliness gate on promoted PBs~~ CLOSED 2026-07-12 by the track-limits asterisk (dirty laps can no longer be promoted; pre-existing back-fill PBs not re-audited)

**Auto Race-Capture — watcher SP1** (complete, merged 2026-07-10 — spec/plan in docs/superpowers/specs+plans/2026-07-10-auto-race-capture*)
- [x] `classify_ibt` — race iff `WeekendInfo.EventType == "Race"` + truthy SubSessionID; CLI routes via a cheap `parse_session_only` header read, races → race processor, everything else → the unchanged lap path (`core/watcher/race_processor.py`, `scripts/watch_telemetry.py`)
- [x] `process_race_ibt` — `ingest_race` → `build_narrative` → `races.db` (INSERT-OR-REPLACE keyed (subsession, cust)); records a "Race" session-history row (marks processed) + player race laps; never raises
- [x] Durability-first timing — `decide_capture(results_ready, have_creds, file_age_s)`: full when Data-API results ready; DEFER (save nothing, retry next 30s scan) while file younger than GRACE_MINUTES=5 with creds; PARTIAL after grace or without creds (the IBT-only signals — incidents/cautions/stints — are the perishable part; API results are durable and refillable later via the page). Ordering invariant: `save_race` BEFORE marking processed — a save failure retries, never loses the race
- [x] Race laps can NO LONGER become PB references — structural fix (race path has no ReferenceStore); previously every race IBT ran the lap path and could promote traffic/fuel laps
- [x] `_cached_fetch` hardening — an empty (results-not-posted-yet) API response is returned uncached instead of poisoning `data/race_cache` and stranding the race as partial forever (also fixes the debrief page re-open case)
- [x] No AI on the capture path — deterministic narrative only; AI debrief stays on-demand on the page
- Watch item: a race captured partial (slow results) is not auto-upgraded to full by the watcher — re-open it on the debrief page to refill API data (chosen over persisted retry state)
**Driver Profile v1 — SP2** (complete, merged 2026-07-11 — spec/plan in docs/superpowers/specs+plans/2026-07-10-driver-profile-v1*)
- [x] `core/profile/` package — derive-on-demand (NO profile table): `load_profile(race_store, track_db, cust_id)` recomputes fresh from races.db + tracks.db every render; any store failure degrades to an empty profile (never breaks a page)
- [x] 4 racecraft tendencies (GLOBAL across all races, any combo — racecraft is a driver trait): starts (lap-1/2 net, positive = gained), pace-vs-result (the headline: actual − pace-deserved position), incidents (rate, lap-1 share, recurring corners ≥2×), trajectory (start→finish net + stint fade). Per-tendency samples — partial captures contribute what they can. Unlock at RACECRAFT_MIN_RACES=3
- [x] Per-combo practice readiness (Race-type sessions EXCLUDED): sessions, clean laps, session-best trend, recent-window consistency (last 3 sessions). Unlock at 2 sessions + 10 laps. **Representative-lap filter** (110% of combo best, REPRESENTATIVE_FACTOR) — added after real-data verification showed ±358s "consistency" from out-laps/crawl laps (watcher is_valid = telemetry-valid, NOT pace-representative)
- [x] TrajectoryTendency DUAL-POOL contract: sample/enough_data cover position-complete races; mean_stint_fade_s pools ALL races — consumers gate fade on its own None-ness
- [x] Verdict one-liners exact-string tested in render.py (like nudges); wording notes: "Session best down X.Xs" not "PB" (a PB can't rise); no double negatives ("You lose 1.8 places")
- [x] Driver Profile page (display only) + registration; `_resolve_cust_id` = most-frequent cust_id, selectbox when several
- [x] Debrief injection: `profile_prompt_block` (enough-data only, 5-combo cap, 2000-char two-stage cap, "" below threshold) threaded through Synthesizer into debrief + chat; tone-contract rule 2 amended — profile facts permitted but must be cited as cross-race tendencies with the profile-stated race count, never as facts about this race
- [x] Store reads added: TrackDB.list_session_history/get_session_laps (SessionRow/LapRow), RaceStore.get_narratives(cust_id) (newest first, subsession tiebreaker — same-timestamp saves are real)
- With today's data (1 race): racecraft shows "collecting 1 of 3"; readiness lit across ~29 combos; prompt block builds from readiness alone (correct per spec)

**Desktop Launcher** (complete, branch desktop-launcher — spec/plan in docs/superpowers/specs+plans/2026-07-12-desktop-launcher*)
- [x] Double-click `Race Engineer` Desktop shortcut → `scripts/start-race-engineer.bat` → `scripts/launch.py`: starts the telemetry watcher (ManagedProcess, run_dir pinned to repo data/run) + Streamlit as a console child (closing the console stops the app; watcher survives), polls port 8501 then opens the browser; idempotent — if 8501 already serves, it just opens the browser
- [x] `scripts/stop-race-engineer.bat` → `scripts/stop_all.py`: stops watcher + live-coach via ManagedProcess, then finds Streamlit by command-line fragments (`_CMDLINE_FRAGMENTS` = repo root + streamlit + streamlit_app.py — matches both `-m streamlit` and `streamlit.exe run` styles, repo-scoped) and tree-kills it
- [x] Coupling tests pin `_CMDLINE_FRAGMENTS` to `launch.STREAMLIT_CMD` (marker can't silently drift from the launch command); port helpers real-socket tested; process/browser I/O untested by convention
- [x] Shortcut created once via `scripts/install_shortcut.py` (WScript.Shell COM through PowerShell, OneDrive-safe Desktop resolution)
- Live coach deliberately NOT auto-started — stays a Toolbox button (driving-only, may want --mute / cue flags)
- [ ] On-rig smoke test (launcher double-click, idempotent re-click, stop .bat, no-orphan check — deferred; user was mid-session during implementation)
- [ ] Roadmap (user request 2026-07-13): **system-tray background app** — persistent tray icon (pystray or similar) with Start/Stop/Status menu for app + watcher + live coach, no console window; the natural successor to the launcher once friends depend on the hosted app (host durability without a console tied to a login session); composes ManagedProcess + launch.py/stop_all.py as-is; pairs with (maybe supersedes) the queued Task Scheduler durability item

**Daemon hardening — real-incident fixes** (2026-07-14, master 834ae41/e6b529f/d7bc1ed)
- [x] Coach survives pyirsdk churn ticks (list values for scalar vars at session transitions — skip the tick in live_coach; `LapBoundaryTracker.feed` ignores malformed Lap) — a single churn tick had killed the coach mid-session
- [x] Both daemons reconfigure stdout to utf-8/errors=replace/line_buffering — a `→` (U+2192, not in cp1252) in the race-report print had killed the detached watcher; line buffering keeps Toolbox log tails fresh
- [x] Watch loop survives bad scans (per-scan try/except, SCAN FAILED + retry next poll); launcher starts the watcher BEFORE the port-8501 idempotency return (dead-watcher-alive-app case)
- [x] Toolbox↔CLI coupling tests (`tests/test_toolbox_commands.py`) — the Toolbox was still passing round-1's `--corner-prompts` (renamed 2026-07-10), so its Start-coach button argparse-crashed the coach instantly; Toolbox now uses round-2 flags (prompts default ON), Start buttons surface instant deaths (1s check + log tail in st.error), run_dir pinned
- [x] `watch_telemetry.py` loads .env itself — previously only Toolbox-inherited spawns had API creds; every other spawn captured races PARTIAL silently. RULE: any UI/launcher that builds a CLI command needs a coupling test against that CLI's parser
- DECIDED (user, 2026-07-14): live coach stays a deliberate Toolbox toggle — never auto-started by the launcher

**Phase 3 (revised per v2 strategy): Race Debrief + Intelligence foundation** (Surface 1 shipped 2026-07-06, branch race-debrief — see `docs/superpowers/specs/2026-07-06-race-debrief-design.md`)
- [x] Race session ingestion: race IBT + Data API results + session YAML → race narrative (position timeline, gap evolution, incident timing, stint pace) (`core/race/ingest.py`, `core/race/narrative.py`)
- [x] Debrief generation (existing synthesis voice) + conversational follow-up loop — engineer, not judge; honest, never scolding (`core/coaching/prompts/race_debrief.py`, chat grounded in narrative JSON)
- [x] iRating attribution: lost to pace or to incidents/decisions? (transparent accounting — pace-deserved position vs actual + labeled time-lost estimates, no counterfactual elo model)
- [x] Persistence + markdown export + Streamlit page (`core/race/race_store.py` → data/races.db keyed (subsession_id, cust_id); `app/pages/race_debrief.py`)
- [x] Friend-testable deployment: Tailscale serve/funnel, upload-first UX (400 MB limit), shared host creds — see README "Friend-testable deployment"
- [ ] Founder validation of the Oulton narrative + first real AI debrief (key rotated + verified; now also exercises the profile injection)
- [x] Driver profile v1 SHIPPED 2026-07-11 (racecraft + practice-readiness layers — see "Driver Profile v1 — SP2" section; technique tendencies deferred, needs loss-region persistence)

**Phase 4 (revised): Pre-Race Briefing / Field Scouting** (v1 shipped 2026-07, branch phase4-briefing-v1 — spec docs/superpowers/specs/2026-07-15-phase4-briefing-v1-design.md, strategy docs/race-engineer-v3-confidence-arc.md)
- [x] core/briefing/ package: models (BriefingData contract), curve (pure pace-vs-iR binning + monotone implied-iR placement, BIN_WIDTH 250 / MIN_BIN_N 5), slots (repeating + explicit descriptors, usual-window inference from watcher session_date), ingest (search_series harvest, HARVEST_CAP 30, per-subsession results cached to data/briefing_cache — search NEVER cached, the week is still growing), render (week-plan-ordered markdown; verdict exact-string pinned; NEVER gates — "you're not ready" is a sentence the product does not say)
- [x] RaceWeek.race_time_descriptors retained by parse_season_schedules (was dropped)
- [x] Race Briefing page: series picker ranked by practice depth at the week's track, car picker from user history, curve chart (field scatter + median line + you), optional AI narrative + ephemeral chat (BRIEFING_SYSTEM_PROMPT tone contract)
- [x] Reuses parse_results/_cached_fetch (race ingest) + build_readiness (profile) — no duplicated parsing
- [x] Founder smoke test 2026-07-15 (5 findings fixed same day): search_series REQUIRES season_year+quarter (season_id alone = 400, and the server IGNORES season_id as a filter — harvest filters rows client-side); car picker offers all practiced cars (at-track first); slots render machine-local; display-only curve smoothing (smoothed_medians — verdict math stays raw), m:ss axis/hover (fmt_lap public), license filter (member_info group_id, SeasonSchedule.license_group) + series search box
- [x] Pace honesty (race debrief, 2026-07-15): all_lap_ranking beside clean rank in PaceSummary (defaults keep old stored narratives deserializing), sample size on every pace claim, low-sample marker < 5 clean laps, tone-contract rule 5 (speed vs execution framing — never headline a survivorship-flattered clean rank)
- [ ] Grid briefing v1.5: reg_drivers roster + opponent cards (plumbing merged, unwired)
- [ ] Field analysis extensions: SoF/split prediction per timeslot, opponent profiles
- [ ] Series calendar awareness → proactive briefings (week-plan push layer)

**Consumer UX Workstream A** (complete, branch consumer-ux-a — spec docs/superpowers/specs/2026-07-15-consumer-ux-packaging-design.md, plan docs/superpowers/plans/2026-07-15-consumer-ux-workstream-a.md)
- [x] A2 glossary component (two-tier TERMS dict, help_text tooltips, Guide section generated from the same dict; coupling test pins the explain() substring to the ingest source)
- [x] A5 error taxonomy (app/components/errors.py explain() + exact-string constants) + st.status phases through ingest_race(on_phase=...) — the only core change, inert when None
- [x] A0 st.navigation shell — app/navigation.py NAV_SPEC (coupling-tested: every render function importable), grouped nav Race/Practice/Help/Host, per-page URLs (/debrief, /briefing, ...), segmented units control; theme un-hides stSidebarNav (it IS the router now); brand block renders BELOW the nav (st.navigation owns the sidebar top — moving the wordmark above needs st.logo, flagged for founder)
- [x] A1 state-aware Start page (default landing): undebriefed-race lead card (pick_undebriefed pure + tested), two entry paths, IBT explainer, sample button, status strip (git SHA / host-guest / watcher freshness)
- [x] A3 frozen sample debrief (app/assets/sample_narrative.json sentinel ids 0/0 + canned sample_debrief.md; round-trip pinned; sample_mode never touches RaceStore)
- [x] A4 Guide restructure (guest-first, glossary section, host reference collapsed) + A6 ride-alongs (TELEMETRY_DIR env var via app/components/host.py replaces the hardcoded founder path in debrief+toolbox, host-only AI metadata, watcher freshness lines, page job lines) + A6b Toolbox radio-transcript feed (core/live/feed.py format_transcript_line, exact-string tested, raw JSONL in collapsed expander)
- [x] Pre-race chunk gate (founder finding 2026-07-15, validated on real Summit + Oulton chunks): iRacing writes one .ibt per recording restart on the race server, all EventType=Race + same SubSessionID — only the chunk whose telemetry enters the YAML Race SessionNum is the race. `ensure_contains_race_segment` in ingest raises `NotRaceChunkError` (fail-open when SessionNum channel or YAML absent); the watcher REROUTES skipped chunks to the lap path with `session_type_override` (quali laps are real pace data and count toward readiness — 'Race' rows are excluded); the debrief picker shows one entry per subsession (largest chunk, `dedupe_race_chunks`); uploads of a pre-race chunk get the NOT_RACE_CHUNK consumer sentence
- [x] Founder copy review passed 2026-07-15 ("this looks fine"); merged to master same evening
- [ ] A7 corner mini-map (phase 2, after top-5) — separate plan

**System-Tray App (B1)** (complete, branch tray-app-b1 — spec §B1 of docs/superpowers/specs/2026-07-15-consumer-ux-packaging-design.md, plan docs/superpowers/plans/2026-07-15-tray-app-b1.md)
- [x] scripts/tray_app.py (pystray + Pillow): tray start = launcher semantics (revive watcher first — the 2026-07-14 lesson — then app detached if 8501 dark; coach NEVER auto-started); menu = Open (REVIVES a stopped rig before opening the browser — founder acceptance finding: Stop everything had left no way back) / live Status / coach Start-Stop / watcher Start-Stop / Stop everything (rig off, tray stays) / Quit (stops everything — founder call: a closed tray must not leave invisible services)
- [x] Streamlit runnable as ManagedProcess 'streamlit-app' (detached, PID-filed, launch.STREAMLIT_CMD imported not copied) — stop_all's cmdline-fragment kill catches it unchanged; launcher .bats remain
- [x] Coupling tests (tests/test_tray_app.py): coach cmd parses via live_coach.build_parser(); watcher/app commands byte-identical to launch.py's by import; ManagedProcess names pinned to the rig's PID files; menu labels + status text exact-string
- [x] scripts/start-tray.bat (pythonw, no console); icon drawn in code (PIL checkerboard, no asset); --smoke mode builds real icon+menu without touching processes
- [ ] On-rig acceptance (founder, round 2 after the Open/Quit fixes): icon appears, Status reads right, coach Start/Stop, Stop everything then Open brings the rig back, Quit stops rig + tray; if the icon dies silently under pythonw, run `python scripts/tray_app.py` in a console to see the traceback
- [ ] After acceptance: re-point the desktop shortcut at the tray (install_shortcut.py) — founder call; then B2 installer

**Friend Installer (B2)** (complete, branch friend-installer-b2 — spec docs/superpowers/specs/2026-07-16-friend-installer-design.md, plan docs/superpowers/plans/2026-07-16-friend-installer.md)
- [x] `core/update/` package: version.py (get_version from pyproject [project] version — the single version source; bump_version), manifest.py (RELEASE_ENTRIES whitelist shared by zip builder + swap; is_installed_layout = uv.exe beside the code), releases.py (check_for_update — tag-only GitHub /releases/latest, draft/prerelease rejected, SHA256SUMS asset required or no offer, fail-quiet None; download_zip), apply.py (apply_update — sha256 gate BEFORE any write incl. malformed-digest typed error, zip-slip guard, extract+validate in temp dir, then selective swap of RELEASE_ENTRIES; data/ + .env + .venv + uv.exe preserved by omission)
- [x] `core/config/env_setup.py`: the ONLY module knowing the .env contract — REQUIRED=(ANTHROPIC_API_KEY, IRACING_USERNAME, IRACING_PASSWORD), DEFAULTS from gitignored `core/config/_baked.py` (ImportError fallback — the repo is PUBLIC, so the founder iRacing app credential is injected at BUILD time by build_release.py and ships only in release artifacts, never git); read/write with dotenv-compatible double-quote escaping (nasty passwords round-trip); write_env updates os.environ so saved keys work without restart
- [x] First-run Setup page (`app/pages/setup.py`, display-only): routes as the ONLY page when is_complete() is False (streamlit_app.py); collects the 3 keys with non-blocking per-field Test buttons (verify_login() on LiveIRacingAPI — new public method; anthropic models.list); re-editable as Settings & Keys in the Host nav group; Start status strip now leads with v{get_version()} (git SHA = dev-only suffix)
- [x] `scripts/build_release.py`: --bump patch|minor, refreshes _baked.py from .env, flat zip of RELEASE_ENTRIES (nested __pycache__/.pyc/.venv excluded; forward-slash names pinned by test), dist/SHA256SUMS (GNU two-space format); SHAs are per-build (zip embeds mtimes) — published SHA256SUMS is the source of truth
- [x] `installer/race-engineer.iss` (Inno Setup 6, per-user, PrivilegesRequired=lowest): FLAT layout — %LOCALAPPDATA%\RaceEngineer IS the code root (data/, .env, .venv live beside app/ core/ scripts/; plan amendment 1 — the spec's nested app\ diagram contradicted every _ROOT-derived path); [Run] = uv sync → install_shortcut --target tray → tray launch + browser; uninstall stops the rig, always removes .venv, PROMPTS before deleting data/.env
- [x] `install_shortcut.py --target launcher|tray`: tray variant targets pythonw.exe directly (no .bat console flash, pinnable) — also satisfies the queued shortcut re-point item; launcher default byte-identical to before
- [x] Tray update channel (spec 5.2): 6h background check caches UpdateInfo; menu item flips "Check for updates" → "Update available (vX.Y.Z) - install"; apply is consent-gated (click) = _stop_rig → download → apply_update → uv sync (uv.exe, CREATE_NO_WINDOW) → _start_rig, watcher-intent semantics preserved by reusing the B1 helpers; any pre-swap failure restarts the old code; dev checkouts never check (is_installed_layout gate); data/run/update.log
- [x] `docs/RELEASING.md`: build_release → ISCC /DAppVersion → tag → gh release create (zip + SHA256SUMS + Setup.exe); tag-only rule; SmartScreen v1 acceptance
- [x] uv.lock refreshed (was stale since B1 — pystray/pillow/pyttsx3 were unlocked; installer uv sync needs the pinned lock)
- [ ] Founder acceptance (not agent-executable): install Inno Setup 6 + drop installer/uv.exe, compile Setup.exe, clean-machine install (3 keys → working Start page; SmartScreen "run anyway" expected), cut v0.1.1 and watch an installed client update with data/.env preserved, uninstall data-prompt check; note the Test iRacing login button only works in a BUILT release (dev checkouts have no baked credential)
- Security notes: repo is PUBLIC — release assets (zip/installer) carry the baked pwlimited credential and are world-downloadable (same v1 acceptance class as the spec, revisit at v2 proxy); update trust anchor = tag-only + SHA256SUMS gate + verify-before-write (adversarially reviewed)

**Phase 5: Live Engineer (push-to-talk)**
- [ ] Rolling race-state summarizer (CarIdx arrays → compact briefing state)
- [ ] PTT + realtime voice, ≤2s latency; sparse event-driven calls, strict rate limiting
- [ ] Crew Chief coexistence decision (post-Surface-2)

**Personal track (continues in parallel): lap coaching**
- [ ] Voice/prompt threshold tuning from session logs; watcher execution; G61 gate fixtures
- Note: real-time technique coaching is deliberately NOT the market product (Trophi's territory, overload trap — see v2 strategy §8); it remains founder tooling and the pace-context layer for race debriefs

## Implementation Notes

### IBT Parser
- Reads the binary format: header (112 bytes) → disk sub-header (32 bytes) → session info YAML → variable headers (144 bytes each) → sample data
- Uses numpy strides for fast channel extraction (no Python per-sample loop)
- Accepts both `Path` and `bytes` input (supports Streamlit file uploads)
- Extracts 18 core channels: Speed, Throttle, Brake, SteeringWheelAngle, Lat, Lon, Alt, Lap, LapCurrentLapTime, LapDist, LapDistPct, SessionTime, SessionTick, RPM, Gear, PlayerTrackSurface, PlayerCarMyIncidentCount, OnPitRoad
- Session info parsed from embedded YAML: track name/ID/length, car name/ID, driver name/ID

### Distance Normalizer
- Resamples to 1 meter intervals using `scipy.interpolate.interp1d`
- Trims trailing stationary data (car stopped at end of session)
- Validates 90% track coverage, rejects laps with distance jumps while moving
- Deduplicates same-distance samples (stationary/low speed)
- Linear interpolation for continuous channels, nearest for discrete (gear)
- Lap time from `LapCurrentLapTime[-1]` (last value), NOT `.max()` — the Lap channel transitions ~30 ticks before LCT resets, so `.max()` picks up the previous lap's stale value

### Corner Detector
- Savitzky-Golay smoothing → `find_peaks` on inverted speed → walk backward for braking → walk forward for exit → merge chicanes → filter false positives
- Road preset: `min_corner_speed_drop=3.0 m/s` (was 5.0, which missed fast sweepers)
- Presets for road/street/oval via `CornerDetector.for_track_type()`
- Detected corner numbers are sequential IDs, NOT official track turn numbers
- **Demoted to fallback annotator** — the coaching analysis path no longer uses it; see Debrief Orchestrator

### Crew Chief Track Seeder
- Imports corner names and distances from Crew Chief's open-source `trackLandmarksData.json` (GitLab)
- `IRACING_TRACK_MAP`: 30 entries mapping to iRacing numeric track IDs — 21 direct iRacing matches + 9 cross-sim matched
- Cross-sim matching (`CROSS_SIM_MAP`): CC entries without `irTrackName` are matched by `pcarsTrackName`, `acTrackNames`, `rf1TrackNames` etc. Canonical keys prefixed `xsim_` (e.g., `xsim_brands_gp`, `xsim_suzuka`)
- Verified track IDs from IBT files: bathurst=219, spa=523 (GP) / 525 (Endurance, "spa 2024 combined"), roadamerica=18, lagunaseca=47, monza=239, sebring=95, brands_hatch=145
- Lazy-seeds on first use: when coaching pipeline processes an IBT file, automatically seeds if no named corners exist
- `format_corner_name()` converts snake_case to display names with ~40 overrides for proper names (Eau Rouge, Raidillon, McPhillamy Park, Paddock Hill Bend, Tertre Rouge, Craner Curves, 130R, etc.)
- `CornerRegistry.match_corners()` maps detected telemetry corners to named DB corners by distance overlap + apex proximity fallback (50m tolerance)
- Corner names flow into `PriorityCorner.corner_name`, `ConsistencyAnalysis.corner_name`, AI prompt `corner_name` field, and UI/plot labels
- Graceful fallback: tracks without Crew Chief data continue to use position-based descriptions

### Coaching Analyzer
- Full pipeline: parse → normalize → filter disrupted laps → detect corners → match corner names → compare laps → rank priority corners
- Disrupted lap filter: 10% pace threshold (not incident count — minor 1x off-tracks don't corrupt telemetry)
- Compares best lap vs median-pace lap for coaching contrast
- Priority corners ranked by abs(time_lost), top 3
- AI prompt includes corner_name (when available), lap_position_percent, and distance_from_start

### Lap Comparator
- Braking onset search starts 200m before corner entry (not at corner start, which is already the braking point)
- Negative corner times rejected (guard against incident laps with non-monotonic elapsed time)
- `total_time_delta` derived from cumulative SessionTime delta (not official lap time difference) for consistency with the per-distance delta trace

### iRacing Data API
- Password Limited OAuth with SHA-256 credential masking: `base64(SHA-256(secret + lowercase(identifier)))`
- Token endpoint: `POST https://oauth.iracing.com/oauth2/token` with `scope=iracing.auth`
- Access tokens expire in 600s, refresh tokens are single-use (up to 7 days)
- Data API: `GET https://members-ng.iracing.com/data/...` returns a signed S3 link, follow it (no auth header) for actual data
- Implemented endpoints: `get_member_info()`, `get_member_summary()`, `get_tracks()`, `get_cars()`, `get_series()`, `get_season_results()`, `get_member_recent_races()`
- `get_member_recent_races()` returns driver's recent official race results with lap times, qualifying times, finish positions, SOF
- `RecentRace` dataclass for parsed results; `_parse_lap_time()` handles both seconds and 1/10000s format (values > 600 assumed sub-second)
- `StubIRacingAPI.get_member_recent_races()` returns empty list (graceful fallback, not an error)

### Scouting Report Pace Context
- Orchestrator in `core/coaching/scouting.py` enriches scouting reports with driver's own race history
- `_try_fetch_pace_context(car_name, track_name)` → `PaceContext | None`: fetches recent races, filters by car/track substring match
- Falls back to track-only match when car+track has no match; returns `None` on any error (missing creds, API failure)
- `PaceContext` dataclass: matching_races, driver_best_lap, driver_best_qual, avg_finish_position, avg_sof, race_count
- Pace data injected into prompt as `--- DRIVER'S OWN RACE HISTORY ---` section with structured JSON
- Scouting reports work identically when API credentials are missing or the API is unavailable

### Unit Toggle (Metric/Imperial)
- Sidebar radio toggle in `streamlit_app.py` stored in `st.session_state["unit_system"]`
- Pure conversion functions in `app/components/units.py`: `speed_value()`, `distance_value()`, `fmt_speed()`, `fmt_distance()`
- All core analysis stays in SI units (m/s, meters); conversion happens only at display time in `coaching.py`
- Converts: speed deltas, braking deltas, position text, plot axes (both X and Y), corner shading coordinates

### Alignment
- Circular cross-correlation (bounded ±150m, default) finds the integer offset that maximises `dot(ref, roll(comp, -lag))` over mean-centred speed traces
- `shift_lap` rolls all telemetry channels and rebuilds `elapsed_time` from rolled per-sample dt deltas — rolling a cumulative array directly breaks monotonicity
- Seam dt estimate for the wrap-around point: `interval / max(speed[0], 1.0)` — prevents a zero-speed divide; keeps elapsed_time strictly increasing after rolling
- `ValueError` raised when trace length < `2 * max_lag + 1`; callers should catch and fall back (no alignment applied) rather than crash

### Loss Regions
- Savitzky-Golay smoothed slope > 0.0005 s/m threshold identifies "losing time" samples; contiguous True spans become candidate regions
- Adjacent regions separated by < 30 m are merged (handles chicanes / linked corners)
- Regions with < 0.05 s time lost are discarded as noise
- `time_lost` is taken from the raw (unsmoothed) delta at the span's boundary indices, not from the smoothed trace — the smoother is for detection only
- Output sorted descending by time_lost; `find_loss_regions()[:top_n]` gives the priority list

### G61 Import
- `CHANNEL_ALIASES` table maps logical channels (distance, distance_pct, speed, throttle, brake, gear, rpm, steering, time, lat, lon) to acceptable G61 column names — **verified against a real export 2026-07** (headers: `Speed,LapDistPct,Lat,Lon,Brake,Throttle,RPM,SteeringWheelAngle,Gear,Clutch,ABSActive,DRSActive,...`)
- Real exports have NO absolute distance column — only `LapDistPct` (fraction 0–1); distance reconstructed as `pct × track_length_m` (percent-scale heuristic for >1.5 max)
- No time column either — elapsed time integrated from ds/v; verified 0.09% vs the G61-displayed lap time on a real Spa lap
- Speed unit heuristic: `max > 130` → km/h → divide by 3.6 (no production car reaches 130 m/s)
- Pedal unit heuristic: `max > 1.5` → percent scale → divide by 100
- Elapsed time: use time column when present; otherwise integrate `dt = ds / max(v, 1.0)` over the output grid
- `G61ImportError` is raised on parse failure or missing required columns; the error message lists the found columns for easy CHANNEL_ALIASES extension

### Reference Store
- `data/reference_laps.db` — separate SQLite DB from `tracks.db`; table `reference_laps` with `UNIQUE(track_id, car, source)`
- Telemetry arrays stored as `npz`-compressed blobs in the `channels` column; scalar metadata stored in typed columns for cheap list queries
- `save()` upserts — calling it twice for the same combo replaces the previous lap
- `get(track_id, car)` returns the best available lap: g61 preferred over personal_best (ORDER BY CASE in SQL); returns `None` when no reference exists
- `list_all()` returns `ReferenceLapMeta` objects only (no arrays) for the UI reference expander

### lovely-track-data Seeder
- Source: `https://raw.githubusercontent.com/Lovely-Sim-Racing/lovely-track-data/main/data/iracing/{slug}.json`
- Track slug derived from IBT session YAML name: spaces → hyphens, lowercase (e.g. "spa 2024 up" → "spa-2024-up")
- Real JSON key is `"turn"` (not `"turns"`); `"straight"` and `"sector"` arrays are intentionally ignored — only turn entries produce Corner rows
- Corner positions are fractions (0–1); converted to meters by `fraction × track_length_m`
- `corner_number` is positional (sorted by start fraction), NOT the official turn number
- Returns 0 on 404 or network failure; callers fall back to Crew Chief seeder or heuristic detection
- **Wired as primary seeder**: `_match_corner_names` in `analyzer.py` calls `seed_track_from_lovely` first; Crew Chief fires only when lovely returns 0 or raises. `ibt_track_name` (IBT session YAML field) and `track_length_m` are passed through from `analyze_session`. Any exception from lovely degrades silently to CC (network failures must never break analysis).

### Segment Annotator
- Strict overlap wins: a corner overlapping the loss region is always preferred over a proximity match
- Proximity fallback (50 m tolerance): attributes a braking-zone region to the corner whose entry is up to 50 m ahead of the region's end
- Multiple overlapping corners are slash-joined ("Eau Rouge / Raidillon"); dict.fromkeys preserves order and deduplicates
- Position fallback when no corner matches: `"~4.4 km from start/finish"` — never invents a turn number
- Watch item: brake-onset window may mis-attribute time loss at chicane-dense tracks where the 50 m tolerance spans multiple corners

### Debrief Orchestrator
- Pipeline: `find_distance_offset` → `shift_lap(reference, -offset)` → rebased cumulative delta → `find_loss_regions` → `annotate_region` → `_diagnose_region` per top-N region
- Sign conventions: positive `cum_delta` = driver slower; negative `braking_delta_m` = driver brakes earlier; positive `throttle_delta_m` = driver back on power later
- No corner detection in the analysis path; `diagnoses` are anchored to loss regions, not detected corners
- `_diagnose_region` searches 200 m before region start for brake onset, and 100 m past region end for throttle-on — same window logic as the legacy comparator
- Watch item: brake-onset search window may mis-attribute at chicane-dense tracks if two corners share a braking zone

### Track Assets
- `TrackAssetCache` wraps the iRacing Data API `get_track_assets()` call; assets index cached to `data/track_maps/assets_index.json` (gitignored) after the first download
- Per-track layer SVGs cached to `data/track_maps/{track_id}/{layer}.svg`; layers include `active`, `start-finish`, and `turns` (official turn numbers)
- `get_detail_copy(track_id)` returns the official track description HTML; available for Stage 2 scouting-prompt grounding but not yet wired into the scouting prompt
- Assets dict is keyed by track_id as a string (match IBT session YAML numeric ID)

### Coaching Page (Stage 1 wiring)
- AI synthesis result cached in `st.session_state` keyed by a hash of the analysis inputs — one Claude call per analysis, not per Streamlit rerun
- Stale cached state cleared on new file upload to prevent displaying the wrong debrief
- Reference lap expander shows `ReferenceLapMeta` fields: source, lap_time, driver_name (no speed trace plot, no imported_at display)
- Debrief section: loss map (GPS outline + colored regions), per-region diagnosis cards (label, time lost, braking delta, speed delta, throttle delta), then AI narrative

### Live Coaching Spike
- **Reused-engine principle**: `LapBuffer.to_dataframe()` produces the exact DataFrame shape `Normalizer.normalize_lap` consumes (same columns as `IBTParser.get_laps()`), so `build_debrief` runs on live laps unchanged — zero edits to the core analysis engine.
- **LapBoundaryTracker** is a pure state machine (no pyirsdk, no I/O); fed one sample dict per tick. Coarse gating only: suppresses pre-green laps (Lap < 1), pit-touch laps, laps too short to be real (< `min_lap_samples` ticks), and discards the buffer on a backward Lap jump (reset/tow). Fine validity (90% distance coverage, distance jumps) is left to `Normalizer.is_valid`, checked by the consumer in `live_coach.py` before debriefing.
- **Nudge salience order and thresholds**: min-speed deficit (>= 2.0 m/s) wins — "carry it flat, you lifted" when reference apex >= 50 m/s, else "carry more apex speed"; braking error (>= 8 m) second — "brake later" or "brake earlier"; late throttle (>= 20 m) third — "back to power earlier". Deterministic, no AI.
- **Track slug for lovely-track-data**: live path reads `WeekendInfo:TrackName` (the directory string, e.g. "spa 2024 up") to build the slug, NOT `TrackDisplayName`. Using `TrackDisplayName` was a known bug in the offline path — the live path avoids it deliberately.
- **Run command**: `.venv/Scripts/python.exe scripts/live_coach.py [--mute] [--no-corner-prompts]` with iRacing open and a session loaded. Speaks lap summaries via Windows SAPI (mixed with game audio); approach-triggered corner cues are **on by default** now (pass `--no-corner-prompts` to disable — was `--corner-prompts` opt-in before round 2). With a stored reference lap (ReferenceStore, keyed by track_id + CarScreenName), coaching starts on the first flying lap; otherwise lap 1 sets the session baseline.
- **Deferred to Plan 2 (HUD)**: NiceGUI LAN web service (binds 0.0.0.0, reachable on LAN + tailnet), iPad chat-feed HUD, Web Speech voice. AI nudge rewrite and Streamlit cleanup are separate tracks.

### Race Debrief (Surface 1, 2026-07-06)
- Three-source ingestion linked by `WeekendInfo.SubSessionID` (in the IBT YAML): race IBT player channels (`RACE_CHANNELS` = CORE + PlayerCarPosition/ClassPosition, SessionFlags, FuelLevel, SessionState), Data API subsession results + lap chart + per-driver lap data, YAML roster (iRating/license per driver; SoF = mean of roster iRatings)
- **Disk IBTs contain NO CarIdx arrays** (verified) — opponent detail is lap-granularity from the API's lap_chart_data/lap_data endpoints (chunked: `chunk_info` → S3 chunk files, assembled by `LiveIRacingAPI._fetch_chunked`, retry-once per chunk)
- API raw JSON cached to `data/race_cache/{subsession_id}/` (atomic .tmp+replace writes; corrupt cache = cache miss + re-fetch); cached files double as test fixtures
- API positions are ZERO-based (finish_position 3 = P4) → +1 in `parse_results`; results/lap_data lap times are always 1/10000s (unlike the mixed-format recent-races endpoint)
- Clean lap = not lap 1, valid time, no incident, no pit event, not under caution (`CAUTION_MASK = 0x4000 | 0x8000` on SessionFlags); pace metric = median of clean laps, ≥3 required to rank
- Attribution dedupes incident time-lost by lap (two steps on one lap = that lap's excess counted once); header incident count is telemetry-sourced by design (works in partial mode)
- `select_key_rivals` (finishers ±1 + ≥3-lap adjacency, cap 4) is called in BOTH ingest (bounds lap-data fetches) and build_narrative (gap series) — the two call sites must stay in sync
- Honest degradation: API failure → partial RaceData (empty results/chart/laps) + logged warning, page renders telemetry-only facts with a warning; no AI key → deterministic narrative renders fully
- Chat: system = tone contract + narrative JSON + delivered debrief; history capped at 20, never starts on an assistant turn; page persists a chat turn only after the reply succeeds
- Real fixtures: Oulton MX-5 race (subsession 86748877, P7→P4) in `tests/fixtures/race/` (gitignored except README; re-record with `scripts/record_race_fixture.py`)
- Deployment: `tailscale serve/funnel 8501` + `streamlit run` from the host PC; `.streamlit/config.toml` sets maxUploadSize 400

### Test Suite
- 1022 tests passing on this branch with local fixtures (`uv run pytest -q` or `.venv/Scripts/python.exe -m pytest -q`); skip count varies with local gitignored fixtures (race-capture integration tests need Oulton; some lap tests need specific telemetry files)
- Test fixtures: `tests/fixtures/sample.ibt` (Spa, BMW M2 CS Racing, 2 laps — gitignored)
- Multi-lap fixture from `C:\Users\antho\Documents\iRacing\telemetry\` (Road America F4, 7 laps)
- Bathurst fixture also available for corner detection tuning tests
- Tests skip gracefully when no IBT file is available
- 3 gate tests in `test_g61_validation_gate.py` skip pending real paired G61 fixtures
- Stage 1 new test files: test_parser_cross_validation, test_alignment, test_loss_regions, test_reference_store, test_lovely_seeder, test_segment_annotator, test_debrief, test_track_assets, test_track_map, test_g61_import, test_g61_validation_gate
- Live coaching spike new test files: test_lap_buffer, test_session_reader, test_nudges, test_live_coach_helpers, test_feed
- Live voice coaching new test files: test_speaker (fake engines only, no SAPI), test_prompt_scheduler
- Progression build new test files: test_progression_streak, test_progression_trends, test_progression_implied_ir, test_progression_store, test_progression_ingest, test_progression_page, test_prescriptions
- Legacy test files: test_ibt_parser, test_normalizer, test_corner_detector, test_corner_detection_tuning, test_lap_comparator, test_multilap_comparator, test_track_db, test_iracing_api, test_synthesizer, test_analyzer, test_crew_chief_seeder, test_scouting, test_unit_helpers
