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
│   │   └── toolbox.py            # Host-only start/stop/status for live coach + watcher
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
│   │       └── scouting.py
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
│   │   └── processor.py          # Per-IBT pipeline: history + PB promotion + debrief
│   └── race/
│       ├── models.py             # RaceData (raw) + RaceNarrative (product) dataclasses
│       ├── ingest.py             # Race IBT + YAML + Data API → RaceData (disk cache, partial mode)
│       ├── narrative.py          # PURE narrative engine: RaceData → RaceNarrative
│       ├── render.py             # Deterministic RaceNarrative → markdown (+ export assembly)
│       └── race_store.py         # data/races.db — narratives, debriefs, chat, keyed (subsession, cust)
├── scripts/
│   ├── live_coach.py             # Terminal entry point (pyirsdk driver)
│   ├── watch_telemetry.py        # Telemetry folder scan CLI (--watch to poll)
│   └── record_race_fixture.py    # Record real race API fixtures for integration tests
├── data/
│   ├── tracks.db                 # SQLite track database
│   ├── profiles.db               # SQLite driver profile and session history
│   ├── reference_laps.db         # SQLite reference lap store (npz-compressed blobs)
│   ├── races.db                  # SQLite race debrief store (gitignored)
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
    └── test_process_control.py
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

**Stage 3: Telemetry Watcher** (complete, merged 2026-07-09)
- [x] TrackDB session-history methods — sessions/laps tables activated; record_session pre-creates a stub track row for the FK, healed by the processor's early upsert_track (`core/track/track_db.py`)
- [x] Scanner — 90s write-stability window, sessions-table dedupe, strictly-faster promotion, `is_plausible_lap` 85 m/s gate (ROAD-ONLY assumption — oval needs a track_type-dependent ceiling), `covers_full_lap` 98% gate (`core/watcher/scanner.py`)
- [x] Processor — upsert real track row → record history → promote plausible+complete personal_best (never touches g61) → debrief vs best reference (`core/watcher/processor.py`)
- [x] CLI — scan once or --watch poll every 30s; failures retry next scan (`scripts/watch_telemetry.py`)
- [x] Normalizer hardening — rejects >100m single-sample forward LapDist jumps (stationary tow/reset teleports that inflated coverage past the 90% check); found via real back-fill corruption (11s "PBs")
- [x] Back-fill executed over the real telemetry folder: 66 files, 30 plausible PBs across 14+ combos, g61 rows verified untouched, Spa 525 PB = the user's real 2:41.384
- Watch item: no cleanliness gate on promoted PBs — an off-track-but-complete fast lap can become the reference (conscious tradeoff for a personal tool; revisit before automated reference trust matters)

**Phase 3 (revised per v2 strategy): Race Debrief + Intelligence foundation** (Surface 1 shipped 2026-07-06, branch race-debrief — see `docs/superpowers/specs/2026-07-06-race-debrief-design.md`)
- [x] Race session ingestion: race IBT + Data API results + session YAML → race narrative (position timeline, gap evolution, incident timing, stint pace) (`core/race/ingest.py`, `core/race/narrative.py`)
- [x] Debrief generation (existing synthesis voice) + conversational follow-up loop — engineer, not judge; honest, never scolding (`core/coaching/prompts/race_debrief.py`, chat grounded in narrative JSON)
- [x] iRating attribution: lost to pace or to incidents/decisions? (transparent accounting — pace-deserved position vs actual + labeled time-lost estimates, no counterfactual elo model)
- [x] Persistence + markdown export + Streamlit page (`core/race/race_store.py` → data/races.db keyed (subsession_id, cust_id); `app/pages/race_debrief.py`)
- [x] Friend-testable deployment: Tailscale serve/funnel, upload-first UX (400 MB limit), shared host creds — see README "Friend-testable deployment"
- [ ] Founder validation of the Oulton narrative + first real AI debrief (blocked on ANTHROPIC_API_KEY rotation)
- [ ] Driver profile v1: technique tendencies + racecraft tendencies (lap-1, restarts, defense, incident patterns) — reads races.db + the watcher's sessions/laps tables (separate spec)

**Phase 4 (revised): Pre-Race Briefing / Field Scouting**
- [ ] Field analysis from Data API: SoF/split prediction, opponent profiles (pace, aggression, incident history)
- [ ] Strategy plan: fuel/tire/pit windows for actual race length
- [ ] Series calendar awareness → proactive briefings

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
- **Run command**: `.venv/Scripts/python.exe scripts/live_coach.py [--mute] [--corner-prompts]` with iRacing open and a session loaded. Speaks lap summaries via Windows SAPI (mixed with game audio); `--corner-prompts` adds approach-triggered prompts (phase 2 — validate plain voice first). With a stored reference lap (ReferenceStore, keyed by track_id + CarScreenName), coaching starts on the first flying lap; otherwise lap 1 sets the session baseline.
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
- 473 tests passing, 9 skipped (`uv run pytest -q` or `.venv/Scripts/python.exe -m pytest -q`)
- Test fixtures: `tests/fixtures/sample.ibt` (Spa, BMW M2 CS Racing, 2 laps — gitignored)
- Multi-lap fixture from `C:\Users\antho\Documents\iRacing\telemetry\` (Road America F4, 7 laps)
- Bathurst fixture also available for corner detection tuning tests
- Tests skip gracefully when no IBT file is available
- 3 gate tests in `test_g61_validation_gate.py` skip pending real paired G61 fixtures
- Stage 1 new test files: test_parser_cross_validation, test_alignment, test_loss_regions, test_reference_store, test_lovely_seeder, test_segment_annotator, test_debrief, test_track_assets, test_track_map, test_g61_import, test_g61_validation_gate
- Live coaching spike new test files: test_lap_buffer, test_session_reader, test_nudges, test_live_coach_helpers, test_feed
- Live voice coaching new test files: test_speaker (fake engines only, no SAPI), test_prompt_scheduler
- Legacy test files: test_ibt_parser, test_normalizer, test_corner_detector, test_corner_detection_tuning, test_lap_comparator, test_multilap_comparator, test_track_db, test_iracing_api, test_synthesizer, test_analyzer, test_crew_chief_seeder, test_scouting, test_unit_helpers
