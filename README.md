# Race Engineer

A personal racing engineer for iRacing. Analyzes telemetry, sources community knowledge, and delivers opinionated coaching that helps intermediate drivers get faster.

This is not a data visualization tool — it's a coaching system that tells you what you don't know.

## Features

### Scouting Report (working)
Pre-session briefing for any car/track combo. Powered by Claude AI with live web search for community knowledge — track character, key corners, car-specific notes, and pace context.

### Lap Coaching (working)
Post-session analysis that compares your laps to your own best performance. Identifies the 2-3 corners where you're leaving the most time and delivers prioritized, actionable coaching with AI-generated tips.

**Pipeline:**
- IBT binary file parsing (iRacing telemetry)
- Distance-based normalization (1 meter intervals)
- Automated corner detection (speed trace heuristics)
- Corner name matching from Crew Chief track database (30 tracks)
- Lap-to-lap comparison with per-corner time deltas
- Theoretical best lap calculation
- Consistency vs. technique issue classification
- AI coaching synthesis (Claude API)
- Interactive speed trace and time delta plots (Plotly)

## Architecture

```
race-engineer/
├── app/                          # Streamlit UI
│   ├── streamlit_app.py          # Main entry point
│   └── pages/
│       ├── scouting.py           # Scouting report page
│       └── coaching.py           # Lap coaching page
├── core/
│   ├── telemetry/                # Telemetry pipeline
│   │   ├── ibt_parser.py         # IBT binary file reader
│   │   ├── normalizer.py         # Distance-based resampling
│   │   ├── corner_detector.py    # Automated corner segmentation
│   │   └── lap_comparator.py     # Lap comparison & analysis
│   ├── track/                    # Track database
│   │   ├── models.py             # Track & corner data models
│   │   ├── track_db.py           # SQLite CRUD
│   │   ├── corner_registry.py    # Match detected corners to DB
│   │   └── crew_chief_seeder.py  # Crew Chief corner name import
│   ├── benchmark/
│   │   └── iracing_api.py        # iRacing Data API client
│   └── coaching/
│       ├── analyzer.py           # Coaching analysis orchestrator
│       ├── synthesizer.py        # Claude API integration
│       ├── scouting.py           # Scouting report orchestrator
│       └── prompts/              # Prompt templates
├── data/                         # SQLite databases (created at runtime)
├── tests/                        # Test suite (161 tests)
└── docs/
    └── prd.md                    # Product requirements document
```

## Quick Start

### Prerequisites
- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager
- An Anthropic API key (for scouting reports)

### Setup

```bash
git clone https://github.com/marmalard/race-engineer.git
cd race-engineer

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run tests
uv run pytest

# Start the app
uv run streamlit run app/streamlit_app.py
```

### Using Your Telemetry

iRacing telemetry files (.ibt) are in your `Documents/iRacing/telemetry/` folder. Upload them through the Lap Coaching page, or use the parser directly:

```python
from pathlib import Path
from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer
from core.telemetry.corner_detector import CornerDetector
from core.telemetry.lap_comparator import LapComparator

parser = IBTParser()
ibt = parser.parse(Path("path/to/session.ibt"))

print(f"Track: {ibt.session.track_name}")
print(f"Car: {ibt.session.car_name}")

# Get laps and normalize
laps = parser.get_laps(ibt)
normalizer = Normalizer()
track_length_m = ibt.session.track_length_km * 1000
normalized = normalizer.normalize_session(
    laps,
    [int(df["Lap"].iloc[0]) for df in laps],
    track_length_m,
)

# Detect corners and compare laps
detector = CornerDetector()
segmentation = detector.detect(normalized[0])
comparator = LapComparator()
theoretical = comparator.theoretical_best(normalized, segmentation)
print(f"Best lap: {theoretical.actual_best_time:.3f}s")
print(f"Theoretical best: {theoretical.theoretical_time:.3f}s")
```

## Development Status

### Phase 1: Foundation (complete)
- [x] IBT parser
- [x] Distance normalizer
- [x] Corner detector
- [x] Lap comparator
- [x] Track database
- [x] Basic Streamlit shell
- [x] Scouting reports (Claude API + web search)
- [x] iRacing Data API client (Password Limited OAuth)

### Phase 2: Core Features (in progress)
- [x] Coaching analysis orchestrator
- [x] Coaching AI synthesis (Claude API)
- [x] Speed trace and time delta plots (Plotly)
- [x] Corner detection tuning per track type
- [x] Track database seeding — Crew Chief corner names (30 tracks)
- [ ] Pace context from iRacing API in scouting reports
- [ ] Unit toggle (metric/imperial)

### Phase 3: Intelligence
- [ ] Driver profile accumulation
- [ ] Session history and progression tracking
- [ ] Cross-session coaching

## Tech Stack

- **Python 3.14** with **uv** for package management
- **pandas / numpy / scipy** — telemetry processing
- **Streamlit** — UI
- **Claude API** (Anthropic) — AI coaching synthesis with web search
- **SQLite** — track and session databases
- **plotly** — telemetry visualization

## Philosophy

- **Opinionated over comprehensive.** Surface the 2-3 things that matter.
- **Coaching over data.** "Brake at the 3 marker" not "your braking point is 12m later."
- **Personal over generic.** Compare the driver to themselves first.
- **Actionable over interesting.** Every insight should change what you do next session.
