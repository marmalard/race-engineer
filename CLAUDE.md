# Race Engineer

## Project Overview

Race Engineer is a personal racing engineer for iRacing. It analyzes telemetry, sources community knowledge, and delivers opinionated coaching that helps intermediate drivers get faster. It is not a data visualization tool — it is a coaching system that tells you what you don't know.

Two initial features:
1. **Scouting Report** — pre-session briefing for a car/track combo with pace targets, key corners, and community wisdom
2. **Lap Coaching** — post-session analysis that compares your laps to your own best performance and delivers prioritized, actionable coaching on the 2-3 corners where you're leaving the most time

See `docs/prd.md` for the full product requirements document.

## Architecture

```
race-engineer/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── docs/
│   └── prd.md                    # Product requirements document
├── app/
│   ├── streamlit_app.py          # Main Streamlit entry point
│   ├── pages/
│   │   ├── scouting.py           # Scouting report UI
│   │   └── coaching.py           # Lap coaching UI
│   └── components/               # Shared Streamlit components
├── core/
│   ├── telemetry/
│   │   ├── ibt_parser.py         # IBT file reading and extraction
│   │   ├── normalizer.py         # Distance-based normalization and resampling
│   │   ├── corner_detector.py    # Automated corner segmentation from telemetry
│   │   └── lap_comparator.py     # Lap-to-lap and benchmark comparison logic
│   ├── track/
│   │   ├── track_db.py           # Track database CRUD operations
│   │   ├── corner_registry.py    # Corner names, types, characteristics
│   │   └── models.py             # Track and corner data models
│   ├── benchmark/
│   │   ├── iracing_api.py        # iRacing Data API client
│   │   ├── pace_context.py       # Pace target calculation from API data
│   │   └── garage61_import.py    # Garage 61 CSV ingestion and alignment
│   ├── profile/
│   │   ├── driver_profile.py     # Driver profile accumulation and queries
│   │   ├── session_history.py    # Session storage and retrieval
│   │   └── models.py             # Driver and session data models
│   └── coaching/
│       ├── analyzer.py           # Core analysis: gaps, consistency, patterns
│       ├── synthesizer.py        # AI coaching synthesis (Claude API)
│       ├── scouting.py           # Scouting report generation
│       └── prompts/              # Prompt templates for AI synthesis
│           ├── coaching.py
│           └── scouting.py
├── data/
│   ├── tracks.db                 # SQLite track database
│   └── profiles.db               # SQLite driver profile and session history
└── tests/
    ├── test_ibt_parser.py
    ├── test_normalizer.py
    ├── test_corner_detector.py
    └── test_lap_comparator.py
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
# Clone and install
git clone <repo>
cd race-engineer
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your credentials

# Run the app
streamlit run app/streamlit_app.py
```

## Current Status

**Phase 1: Foundation** (current)
- [ ] IBT parser — read and extract telemetry channels
- [ ] Distance normalizer — resample to distance-based
- [ ] Corner detector — automated segmentation
- [ ] Lap comparator — self-referential comparison
- [ ] Track database — schema and basic CRUD
- [ ] Basic Streamlit shell

**Phase 2: Core Features**
- [ ] Scouting report — pace context from iRacing API + web knowledge synthesis
- [ ] Lap coaching — full pipeline from IBT to AI-generated coaching
- [ ] Track database seeding — initial set of tracks with corner names

**Phase 3: Intelligence**
- [ ] Driver profile — accumulate across sessions
- [ ] Session history — track progression over time
- [ ] Cross-session coaching — "you've improved here, still struggling there"
- [ ] Season awareness — series calendar integration

**Phase 4: Live Awareness**
- [ ] Between-lap coaching
- [ ] Crew Chief integration or TTS output
- [ ] Real-time session monitoring
