# Race Debrief (Surface 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest a completed iRacing race (IBT + Data API results + session YAML), reconstruct a deterministic race narrative, generate an AI debrief with conversational follow-up, persist it, and serve it friend-testable over Tailscale.

**Architecture:** New `core/race/` package holds a pure, typed narrative engine fed by three sources linked via `SubSessionID`. AI (existing `Synthesizer` pattern) supplies voice only, grounded strictly in the narrative JSON. A new Streamlit page (display-only) renders charts, debrief, chat, and markdown export; persistence in a new `data/races.db` keyed by `(subsession_id, cust_id)`.

**Tech Stack:** Python 3.11+, pandas/numpy, httpx (existing `LiveIRacingAPI`), anthropic, Streamlit + Plotly, SQLite (stdlib), pytest.

**Spec:** `docs/superpowers/specs/2026-07-06-race-debrief-design.md` — read it first.

**Conventions (project-wide, apply to every task):**
- Run tests with `.venv/Scripts/python.exe -m pytest <file> -q` from the repo root (Windows; the venv has no pip — installs go through `uv.exe`, but no new dependencies are needed for this plan).
- Type hints on all signatures, docstrings on public functions, dataclasses for structured data, SI units (seconds, meters) internally.
- Analysis logic in `core/`, display-only code in `app/`. No business logic in Streamlit files.
- Lap times from the Data API arrive in 1/10000s (values > 600); `-1` means no valid time.

---

### Task 1: Data API — chunked endpoints (results, lap chart, lap data)

The three race endpoints return either a plain JSON dict (`results/get`) or a **chunked** payload (`lap_chart_data`, `lap_data`): the followed link yields a dict whose `chunk_info` lists S3 chunk files that concatenate into one JSON array.

**Files:**
- Modify: `core/benchmark/iracing_api.py` (add methods to `LiveIRacingAPI` and `StubIRacingAPI`; do NOT touch the ABC — follow the `get_member_summary` precedent of concrete-only methods)
- Test: `tests/test_iracing_api.py` (additions)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_iracing_api.py` (match the file's existing import style):

```python
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHTTPClient:
    """Serves canned responses keyed by URL substring."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for key, payload in self.routes.items():
            if key in url:
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected URL: {url}")


def _api_with_fake_client(routes: dict):
    from core.benchmark.iracing_api import LiveIRacingAPI, _TokenData

    api = LiveIRacingAPI("cid", "csecret", "user", "pass")
    api._client = _FakeHTTPClient(routes)
    # Pre-seed a valid token so _ensure_token never hits the network
    api._token = _TokenData(access_token="tok", expires_at=9999999999.0)
    return api


def test_fetch_chunked_concatenates_chunks():
    routes = {
        "chunk-a.json": [{"lap_number": 1}],
        "chunk-b.json": [{"lap_number": 2}, {"lap_number": 3}],
    }
    api = _api_with_fake_client(routes)
    data = {
        "chunk_info": {
            "base_download_url": "https://s3.example/",
            "chunk_file_names": ["chunk-a.json", "chunk-b.json"],
        }
    }
    rows = api._fetch_chunked(data)
    assert [r["lap_number"] for r in rows] == [1, 2, 3]


def test_fetch_chunked_without_chunk_info_returns_list_passthrough():
    api = _api_with_fake_client({})
    assert api._fetch_chunked([{"a": 1}]) == [{"a": 1}]
    assert api._fetch_chunked({}) == []


def test_get_subsession_results_calls_results_get():
    payload = {"link": "https://s3.example/signed-results"}
    results_doc = {"subsession_id": 86748877, "session_results": []}
    api = _api_with_fake_client({
        "/data/results/get": payload,
        "signed-results": results_doc,
    })
    out = api.get_subsession_results(86748877)
    assert out["subsession_id"] == 86748877


def test_get_lap_chart_data_unwraps_chunks():
    link_doc = {"link": "https://s3.example/signed-chart"}
    chart_head = {
        "chunk_info": {
            "base_download_url": "https://s3.example/",
            "chunk_file_names": ["c0.json"],
        }
    }
    api = _api_with_fake_client({
        "/data/results/lap_chart_data": link_doc,
        "signed-chart": chart_head,
        "c0.json": [{"cust_id": 1, "lap_number": 0, "lap_position": 5}],
    })
    rows = api.get_lap_chart_data(86748877, 0)
    assert rows[0]["lap_position"] == 5


def test_stub_race_endpoints_graceful():
    from core.benchmark.iracing_api import StubIRacingAPI

    stub = StubIRacingAPI()
    assert stub.get_subsession_results(1) == {}
    assert stub.get_lap_chart_data(1, 0) == []
    assert stub.get_lap_data(1, 0, 2) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_iracing_api.py -q`
Expected: FAIL — `AttributeError: 'LiveIRacingAPI' object has no attribute '_fetch_chunked'` (and missing methods).

- [ ] **Step 3: Implement**

In `core/benchmark/iracing_api.py`, add to `LiveIRacingAPI` (after `_api_get`):

```python
    def _fetch_chunked(self, data: dict | list) -> list:
        """Assemble a chunked Data API payload into one list.

        Chunked endpoints (lap_chart_data, lap_data) return a dict whose
        chunk_info lists S3 files; each file is a JSON array. Non-chunked
        list payloads pass through unchanged.
        """
        if isinstance(data, list):
            return data
        chunk_info = data.get("chunk_info") if isinstance(data, dict) else None
        if not chunk_info:
            return []
        base = chunk_info["base_download_url"]
        rows: list = []
        for name in chunk_info["chunk_file_names"]:
            url = base + name
            for attempt in (1, 2):  # retry once per spec
                try:
                    resp = self._client.get(url)
                    resp.raise_for_status()
                    rows.extend(resp.json())
                    break
                except httpx.HTTPError:
                    if attempt == 2:
                        raise
        return rows

    def get_subsession_results(self, subsession_id: int) -> dict:
        """Get full official results for a subsession (all simsessions)."""
        return self._api_get(
            "/data/results/get", {"subsession_id": subsession_id}
        )

    def get_lap_chart_data(
        self, subsession_id: int, simsession_number: int
    ) -> list[dict]:
        """Get every car's position on every lap (chunked endpoint)."""
        data = self._api_get(
            "/data/results/lap_chart_data",
            {
                "subsession_id": subsession_id,
                "simsession_number": simsession_number,
            },
        )
        return self._fetch_chunked(data)

    def get_lap_data(
        self, subsession_id: int, simsession_number: int, cust_id: int
    ) -> list[dict]:
        """Get one driver's per-lap times and events (chunked endpoint)."""
        data = self._api_get(
            "/data/results/lap_data",
            {
                "subsession_id": subsession_id,
                "simsession_number": simsession_number,
                "cust_id": cust_id,
            },
        )
        return self._fetch_chunked(data)
```

Note: `_FakeHTTPClient.get` in the test raises `AssertionError`, not `httpx.HTTPError`, so the retry loop propagates real test wiring mistakes instead of eating them.

Add to `StubIRacingAPI` (graceful-fallback pattern, like `get_member_recent_races`):

```python
    def get_subsession_results(self, subsession_id: int) -> dict:
        return {}  # Graceful fallback: no data, not an error

    def get_lap_chart_data(
        self, subsession_id: int, simsession_number: int
    ) -> list[dict]:
        return []

    def get_lap_data(
        self, subsession_id: int, simsession_number: int, cust_id: int
    ) -> list[dict]:
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_iracing_api.py -q`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add core/benchmark/iracing_api.py tests/test_iracing_api.py
git commit -m "feat: subsession results + chunked lap endpoints on iRacing API client"
```

---

### Task 2: IBT parser — `parse_session_only` (cheap picker scans)

Race IBTs run 25–205 MB; the picker must identify races without full-file reads. The session YAML sits at `header.session_info_offset` (early in the file), so reading `TOTAL_HEADER_SIZE` bytes for the header, then up to `session_info_offset + session_info_len`, is enough.

**Files:**
- Modify: `core/telemetry/ibt_parser.py`
- Test: `tests/test_ibt_parser.py` (addition)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ibt_parser.py` (reuse the file's existing fixture-skip pattern and sample-IBT path constant — read the top of the file first and match it):

```python
def test_parse_session_only_matches_full_parse(sample_ibt_path):
    """parse_session_only returns the same session metadata as parse()."""
    parser = IBTParser()
    full = parser.parse(sample_ibt_path, channels=["Lap"])
    session_only = parser.parse_session_only(sample_ibt_path)

    assert session_only.track_id == full.session.track_id
    assert session_only.track_name == full.session.track_name
    assert session_only.car_name == full.session.car_name
    assert session_only.session_type == full.session.session_type
    assert session_only.raw.get("WeekendInfo", {}).get("SubSessionID") == \
        full.session.raw.get("WeekendInfo", {}).get("SubSessionID")


def test_parse_session_only_accepts_bytes(sample_ibt_path):
    parser = IBTParser()
    data = sample_ibt_path.read_bytes()
    session = parser.parse_session_only(data)
    assert session.track_id == parser.parse_session_only(sample_ibt_path).track_id
```

If the existing file uses a module-level `SAMPLE_IBT` path + `pytest.mark.skipif` instead of a fixture, follow that pattern instead — the assertion bodies stay the same.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ibt_parser.py -q`
Expected: FAIL — `AttributeError: 'IBTParser' object has no attribute 'parse_session_only'`.

- [ ] **Step 3: Implement**

Add to `IBTParser` (after `parse`):

```python
    def parse_session_only(self, source: Path | bytes) -> IBTSession:
        """Read only the header + session YAML — no telemetry extraction.

        For Path input this reads a few hundred KB instead of the whole
        file (race IBTs run 25-205 MB), making folder scans cheap.
        """
        if isinstance(source, Path):
            with open(source, "rb") as f:
                prefix = f.read(TOTAL_HEADER_SIZE)
                header = self._read_header(prefix)
                needed = header.session_info_offset + header.session_info_len
                f.seek(0)
                data = f.read(needed)
        elif isinstance(source, (bytes, bytearray)):
            data = bytes(source)
            header = self._read_header(data)
        else:
            raise TypeError(f"Expected Path or bytes, got {type(source)}")

        return self._read_session_info(data, header)
```

Check the constant name at the top of the file — the header-size constant used by `_read_header`'s length guard is `TOTAL_HEADER_SIZE`. If `_read_session_info` takes different arguments than `(data, header)`, match its actual signature (read the method before wiring).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ibt_parser.py -q`
Expected: PASS (skips gracefully if the sample fixture is absent — that's the project pattern; if it skips, run once on a machine with `tests/fixtures/sample.ibt` present before calling the task done).

- [ ] **Step 5: Commit**

```bash
git add core/telemetry/ibt_parser.py tests/test_ibt_parser.py
git commit -m "feat: parse_session_only for cheap IBT metadata scans"
```

---

### Task 3: Race models (`core/race/models.py`)

All dataclasses for raw race data and the narrative, plus JSON round-trip for `RaceNarrative` (the store persists it; the AI prompt consumes it).

**Files:**
- Create: `core/race/__init__.py` (empty)
- Create: `core/race/models.py`
- Test: `tests/test_race_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_race_models.py`:

```python
"""Tests for race narrative data models."""

from core.race.models import (
    CautionSegment,
    GapPoint,
    IncidentEvent,
    IRatingAttribution,
    Lap1Story,
    NarrativeHeader,
    PaceSummary,
    PlaceChange,
    PositionPoint,
    RaceNarrative,
    RivalGaps,
    Stint,
)


def _minimal_narrative() -> RaceNarrative:
    return RaceNarrative(
        header=NarrativeHeader(
            subsession_id=86748877,
            cust_id=1226848,
            driver_name="Anthony Moorman",
            track_id=180,
            track_name="Oulton Park Circuit",
            track_config="International",
            car_name="Mazda MX-5 Cup",
            series_name="MX-5 Cup",
            session_date="2026-06-26",
            sof=1350,
            field_size=13,
            start_position=8,
            finish_position=6,
            incidents=5,
            irating_old=1420,
            irating_new=1445,
        ),
        position_timeline=[PositionPoint(lap=1, position=7)],
        lap1=Lap1Story(
            grid_position=8,
            position_after_lap1=7,
            position_after_lap2=7,
            place_changes=[
                PlaceChange(
                    lap=1,
                    lap_dist_pct=0.31,
                    corner_name="Island Bend",
                    from_position=8,
                    to_position=7,
                )
            ],
        ),
        gaps=[
            RivalGaps(
                cust_id=999,
                display_name="Rival One",
                finish_position=5,
                gaps=[GapPoint(lap=1, gap_s=1.2)],
            )
        ],
        incidents=[
            IncidentEvent(
                lap=9,
                lap_dist_pct=0.62,
                corner_name="Knickerbrook",
                delta_incidents=2,
                position_before=6,
                position_after=8,
                time_lost_estimate_s=4.1,
            )
        ],
        stints=[Stint(start_lap=1, end_lap=14, median_clean_pace=113.4, trend_s=0.2)],
        cautions=[CautionSegment(start_lap=3, end_lap=4)],
        pace=PaceSummary(
            median_clean_lap=113.4,
            best_lap=112.9,
            consistency_stdev=0.45,
            clean_lap_count=9,
            pace_rank=5,
            ranked_drivers=11,
            unranked_drivers=2,
        ),
        attribution=IRatingAttribution(
            irating_old=1420,
            irating_new=1445,
            irating_delta=25,
            pace_deserved_position=5,
            actual_position=6,
            incident_time_lost_s=6.3,
            lap1_net_positions=1,
            summary_lines=["Pace deserved ~P5; finished P6."],
        ),
        key_rivals=[999],
    )


def test_narrative_round_trips_through_dict():
    narrative = _minimal_narrative()
    d = narrative.to_dict()
    restored = RaceNarrative.from_dict(d)
    assert restored == narrative


def test_narrative_dict_is_json_serializable():
    import json

    text = json.dumps(_minimal_narrative().to_dict())
    assert "Knickerbrook" in text


def test_optional_sections_survive_round_trip():
    narrative = _minimal_narrative()
    narrative.lap1 = None
    narrative.cautions = []
    restored = RaceNarrative.from_dict(narrative.to_dict())
    assert restored.lap1 is None
    assert restored.cautions == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.race'`.

- [ ] **Step 3: Implement**

Create `core/race/__init__.py` (empty file) and `core/race/models.py`:

```python
"""Data models for race ingestion and the race narrative.

RaceData bundles the raw ingested sources (IBT telemetry, roster,
API results); RaceNarrative is the deterministic engine's product and
the single source of truth for rendering, AI synthesis, and persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd


# --- Raw ingested data -------------------------------------------------

@dataclass
class RosterEntry:
    """One driver from the IBT session YAML roster."""

    car_idx: int
    cust_id: int
    display_name: str
    car_number: str
    irating: int
    license_string: str
    car_name: str


@dataclass
class ResultRow:
    """One driver's official result from the Data API."""

    cust_id: int
    display_name: str
    finish_position: int  # 1-based
    starting_position: int  # 1-based
    laps_complete: int
    incidents: int
    oldi_rating: int
    newi_rating: int
    best_lap_time: float  # seconds, -1.0 if none


@dataclass
class DriverLap:
    """One lap by one driver from the Data API lap_data endpoint."""

    cust_id: int
    lap_number: int
    lap_time: float  # seconds, -1.0 if no valid time
    lap_events: list[str] = field(default_factory=list)
    incident: bool = False


@dataclass
class LapChartRow:
    """One car's position at the end of one lap."""

    cust_id: int
    lap_number: int
    position: int


@dataclass
class RaceData:
    """Everything ingested for one race, pre-narrative.

    player_telemetry columns match IBTParser output for the extended
    race channel list. results/lap_chart/driver_laps are empty when the
    Data API was unavailable (partial-narrative mode).
    """

    subsession_id: int
    player_cust_id: int
    player_car_idx: int
    driver_name: str
    track_id: int
    track_name: str
    track_config: str
    track_directory: str  # lovely-track-data slug source
    track_length_m: float
    car_name: str
    series_name: str
    session_date: str
    sof: int
    player_telemetry: pd.DataFrame
    roster: list[RosterEntry] = field(default_factory=list)
    results: list[ResultRow] = field(default_factory=list)
    lap_chart: list[LapChartRow] = field(default_factory=list)
    driver_laps: dict[int, list[DriverLap]] = field(default_factory=dict)


# --- Narrative ----------------------------------------------------------

@dataclass
class NarrativeHeader:
    subsession_id: int
    cust_id: int
    driver_name: str
    track_id: int
    track_name: str
    track_config: str
    car_name: str
    series_name: str
    session_date: str
    sof: int
    field_size: int
    start_position: int
    finish_position: int
    incidents: int
    irating_old: int
    irating_new: int


@dataclass
class PositionPoint:
    lap: int
    position: int


@dataclass
class PlaceChange:
    lap: int
    lap_dist_pct: float
    corner_name: str | None
    from_position: int
    to_position: int


@dataclass
class Lap1Story:
    grid_position: int
    position_after_lap1: int
    position_after_lap2: int
    place_changes: list[PlaceChange] = field(default_factory=list)


@dataclass
class GapPoint:
    lap: int
    gap_s: float  # positive = rival ahead of player


@dataclass
class RivalGaps:
    cust_id: int
    display_name: str
    finish_position: int
    gaps: list[GapPoint] = field(default_factory=list)


@dataclass
class IncidentEvent:
    lap: int
    lap_dist_pct: float
    corner_name: str | None
    delta_incidents: int
    position_before: int
    position_after: int
    time_lost_estimate_s: float


@dataclass
class Stint:
    start_lap: int
    end_lap: int
    median_clean_pace: float | None
    trend_s: float | None  # second-half median minus first-half median


@dataclass
class CautionSegment:
    start_lap: int
    end_lap: int


@dataclass
class PaceSummary:
    median_clean_lap: float | None
    best_lap: float | None
    consistency_stdev: float | None
    clean_lap_count: int
    pace_rank: int | None  # None when player has < 3 clean laps
    ranked_drivers: int
    unranked_drivers: int


@dataclass
class IRatingAttribution:
    irating_old: int
    irating_new: int
    irating_delta: int
    pace_deserved_position: int | None
    actual_position: int
    incident_time_lost_s: float
    lap1_net_positions: int  # positive = gained places on lap 1
    summary_lines: list[str] = field(default_factory=list)


@dataclass
class RaceNarrative:
    """The deterministic product: every fact the debrief may state."""

    header: NarrativeHeader
    position_timeline: list[PositionPoint] = field(default_factory=list)
    lap1: Lap1Story | None = None
    gaps: list[RivalGaps] = field(default_factory=list)
    incidents: list[IncidentEvent] = field(default_factory=list)
    stints: list[Stint] = field(default_factory=list)
    cautions: list[CautionSegment] = field(default_factory=list)
    pace: PaceSummary | None = None
    attribution: IRatingAttribution | None = None
    key_rivals: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-serializable dict (persistence + AI prompt payload)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RaceNarrative":
        """Rebuild a narrative from to_dict() output."""
        return cls(
            header=NarrativeHeader(**d["header"]),
            position_timeline=[
                PositionPoint(**p) for p in d.get("position_timeline", [])
            ],
            lap1=(
                Lap1Story(
                    grid_position=d["lap1"]["grid_position"],
                    position_after_lap1=d["lap1"]["position_after_lap1"],
                    position_after_lap2=d["lap1"]["position_after_lap2"],
                    place_changes=[
                        PlaceChange(**c) for c in d["lap1"].get("place_changes", [])
                    ],
                )
                if d.get("lap1")
                else None
            ),
            gaps=[
                RivalGaps(
                    cust_id=g["cust_id"],
                    display_name=g["display_name"],
                    finish_position=g["finish_position"],
                    gaps=[GapPoint(**p) for p in g.get("gaps", [])],
                )
                for g in d.get("gaps", [])
            ],
            incidents=[IncidentEvent(**i) for i in d.get("incidents", [])],
            stints=[Stint(**s) for s in d.get("stints", [])],
            cautions=[CautionSegment(**c) for c in d.get("cautions", [])],
            pace=PaceSummary(**d["pace"]) if d.get("pace") else None,
            attribution=(
                IRatingAttribution(**d["attribution"])
                if d.get("attribution")
                else None
            ),
            key_rivals=list(d.get("key_rivals", [])),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_models.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/race/__init__.py core/race/models.py tests/test_race_models.py
git commit -m "feat: race data + narrative models with JSON round-trip"
```

---

### Task 4: Narrative engine part A — laps, pace, ranking, attribution (`core/race/narrative.py`)

Pure functions over API-derived lap data. No telemetry yet (that's Task 5, same module).

**Files:**
- Create: `core/race/narrative.py`
- Test: `tests/test_race_narrative.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_race_narrative.py`:

```python
"""Tests for the deterministic race narrative engine (pure functions)."""

import pytest

from core.race.models import DriverLap
from core.race.narrative import (
    build_attribution,
    clean_laps,
    compute_gaps,
    median_clean_pace,
    pace_ranking,
)


def _laps(cust_id: int, times: list[float], **overrides) -> list[DriverLap]:
    """Laps numbered from 1 with the given times, all clean by default."""
    laps = [
        DriverLap(cust_id=cust_id, lap_number=i + 1, lap_time=t)
        for i, t in enumerate(times)
    ]
    for lap_number, kwargs in overrides.items():
        lap = laps[int(lap_number) - 1]
        for k, v in kwargs.items():
            setattr(lap, k, v)
    return laps


# --- clean_laps ---------------------------------------------------------

def test_clean_laps_excludes_lap1_incidents_pits_cautions_invalid():
    laps = _laps(1, [100.0, 101.0, 102.0, 103.0, 104.0, -1.0])
    laps[1].incident = True                 # lap 2: incident
    laps[2].lap_events = ["pitted"]         # lap 3: pit
    result = clean_laps(laps, caution_laps={5})
    # lap 1 (first lap), lap 2 (incident), lap 3 (pit), lap 5 (caution),
    # lap 6 (invalid time) all excluded -> only lap 4 remains
    assert [l.lap_number for l in result] == [4]


def test_clean_laps_event_matching_is_case_insensitive():
    laps = _laps(1, [100.0, 101.0])
    laps[1].lap_events = ["Pitted"]
    assert [l.lap_number for l in clean_laps(laps, caution_laps=set())] == []


# --- median_clean_pace ---------------------------------------------------

def test_median_clean_pace_requires_three_clean_laps():
    laps = _laps(1, [100.0, 101.0, 103.0])  # lap 1 excluded -> 2 clean
    assert median_clean_pace(laps, caution_laps=set()) is None


def test_median_clean_pace_is_median():
    laps = _laps(1, [100.0, 101.0, 103.0, 105.0])  # clean: 101, 103, 105
    assert median_clean_pace(laps, caution_laps=set()) == 103.0


# --- pace_ranking --------------------------------------------------------

def test_pace_ranking_orders_by_median_and_excludes_thin_data():
    driver_laps = {
        1: _laps(1, [100.0, 101.0, 101.0, 101.0]),   # median 101
        2: _laps(2, [100.0, 99.0, 99.0, 99.0]),       # median 99 (faster)
        3: _laps(3, [100.0, 98.0]),                   # only 1 clean -> unranked
    }
    ranked, unranked = pace_ranking(driver_laps, caution_laps=set())
    assert [cust for cust, _ in ranked] == [2, 1]
    assert unranked == [3]


# --- compute_gaps --------------------------------------------------------

def test_compute_gaps_positive_when_rival_ahead():
    player = _laps(1, [100.0, 100.0, 100.0])
    rival = _laps(2, [99.0, 99.0, 99.0])  # rival pulls 1s/lap ahead
    gaps = compute_gaps(player, rival)
    assert [round(g.gap_s, 3) for g in gaps] == [1.0, 2.0, 3.0]
    assert [g.lap for g in gaps] == [1, 2, 3]


def test_compute_gaps_stops_at_first_invalid_time():
    player = _laps(1, [100.0, -1.0, 100.0])
    rival = _laps(2, [99.0, 99.0, 99.0])
    gaps = compute_gaps(player, rival)
    assert len(gaps) == 1  # lap 2 invalid -> series truncated


# --- build_attribution ----------------------------------------------------

def test_build_attribution_accounts_for_pace_vs_finish():
    attribution = build_attribution(
        irating_old=1420,
        irating_new=1400,
        pace_deserved_position=5,
        actual_position=9,
        incident_time_lost_s=12.5,
        lap1_net_positions=-2,
    )
    assert attribution.irating_delta == -20
    assert attribution.pace_deserved_position == 5
    assert attribution.actual_position == 9
    # Summary lines are deterministic facts, not AI text
    joined = " ".join(attribution.summary_lines)
    assert "P5" in joined and "P9" in joined
    assert "12.5" in joined


def test_build_attribution_handles_unranked_pace():
    attribution = build_attribution(
        irating_old=1420,
        irating_new=1400,
        pace_deserved_position=None,
        actual_position=9,
        incident_time_lost_s=0.0,
        lap1_net_positions=0,
    )
    assert attribution.pace_deserved_position is None
    assert any("not enough clean laps" in line for line in attribution.summary_lines)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_narrative.py -q`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` for `core.race.narrative`.

- [ ] **Step 3: Implement**

Create `core/race/narrative.py`:

```python
"""Deterministic race narrative engine.

Pure functions: RaceData in, RaceNarrative out. No I/O, no AI. Every
number the debrief states is computed here and testable.

Conventions: lap numbers are 1-based; positions are 1-based; gap_s
positive = rival ahead of the player; times in seconds.
"""

from __future__ import annotations

import statistics

from core.race.models import (
    DriverLap,
    GapPoint,
    IRatingAttribution,
)

MIN_CLEAN_LAPS = 3  # below this a driver is excluded from pace ranking


def clean_laps(
    laps: list[DriverLap], caution_laps: set[int]
) -> list[DriverLap]:
    """Laps usable as pace evidence.

    Clean = not lap 1, valid time, no incident, no pit event, not under
    caution. Event matching is case-insensitive substring ("pitted").
    """
    result = []
    for lap in laps:
        if lap.lap_number <= 1:
            continue
        if lap.lap_time <= 0:
            continue
        if lap.incident:
            continue
        if lap.lap_number in caution_laps:
            continue
        events = " ".join(lap.lap_events).lower()
        if "pit" in events:
            continue
        result.append(lap)
    return result


def median_clean_pace(
    laps: list[DriverLap],
    caution_laps: set[int],
    min_laps: int = MIN_CLEAN_LAPS,
) -> float | None:
    """Median clean-lap time, or None with fewer than min_laps clean laps."""
    clean = clean_laps(laps, caution_laps)
    if len(clean) < min_laps:
        return None
    return statistics.median(l.lap_time for l in clean)


def pace_ranking(
    driver_laps: dict[int, list[DriverLap]],
    caution_laps: set[int],
) -> tuple[list[tuple[int, float]], list[int]]:
    """Rank drivers by median clean pace (ascending = fastest first).

    Returns (ranked, unranked): ranked is (cust_id, median) pairs;
    unranked lists drivers with too few clean laps to judge.
    """
    ranked: list[tuple[int, float]] = []
    unranked: list[int] = []
    for cust_id, laps in driver_laps.items():
        pace = median_clean_pace(laps, caution_laps)
        if pace is None:
            unranked.append(cust_id)
        else:
            ranked.append((cust_id, pace))
    ranked.sort(key=lambda pair: pair[1])
    return ranked, unranked


def compute_gaps(
    player_laps: list[DriverLap], rival_laps: list[DriverLap]
) -> list[GapPoint]:
    """Cumulative time gap per lap; positive = rival ahead.

    Truncates at the first invalid lap time on either side — cumulative
    sums are meaningless past a missing lap.
    """
    player_by_lap = {l.lap_number: l.lap_time for l in player_laps}
    rival_by_lap = {l.lap_number: l.lap_time for l in rival_laps}
    common = sorted(set(player_by_lap) & set(rival_by_lap))

    gaps: list[GapPoint] = []
    player_total = 0.0
    rival_total = 0.0
    for lap in common:
        if player_by_lap[lap] <= 0 or rival_by_lap[lap] <= 0:
            break
        player_total += player_by_lap[lap]
        rival_total += rival_by_lap[lap]
        gaps.append(GapPoint(lap=lap, gap_s=player_total - rival_total))
    return gaps


def build_attribution(
    irating_old: int,
    irating_new: int,
    pace_deserved_position: int | None,
    actual_position: int,
    incident_time_lost_s: float,
    lap1_net_positions: int,
) -> IRatingAttribution:
    """Transparent accounting of rating change vs pace and events.

    No counterfactual elo model — states facts and labeled estimates
    only ("never dishonest" applies to the deterministic layer too).
    """
    delta = irating_new - irating_old
    lines: list[str] = []

    if pace_deserved_position is not None:
        lines.append(
            f"Clean-lap pace ranked P{pace_deserved_position}; "
            f"finished P{actual_position}."
        )
    else:
        lines.append(
            f"Finished P{actual_position}; not enough clean laps to rank "
            "race pace."
        )

    if incident_time_lost_s > 0:
        lines.append(
            f"Incident laps cost an estimated {incident_time_lost_s:.1f}s "
            "vs clean pace (lap-granularity estimate)."
        )

    if lap1_net_positions:
        direction = "gained" if lap1_net_positions > 0 else "lost"
        lines.append(
            f"Lap 1: {direction} {abs(lap1_net_positions)} "
            f"position{'s' if abs(lap1_net_positions) != 1 else ''}."
        )

    lines.append(f"iRating: {irating_old} -> {irating_new} ({delta:+d}).")

    return IRatingAttribution(
        irating_old=irating_old,
        irating_new=irating_new,
        irating_delta=delta,
        pace_deserved_position=pace_deserved_position,
        actual_position=actual_position,
        incident_time_lost_s=incident_time_lost_s,
        lap1_net_positions=lap1_net_positions,
        summary_lines=lines,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_narrative.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add core/race/narrative.py tests/test_race_narrative.py
git commit -m "feat: narrative engine part A — clean laps, pace ranking, gaps, attribution"
```

---

### Task 5: Narrative engine part B — telemetry-derived events + `build_narrative`

Place changes, incidents, pits, cautions, stints from the player telemetry DataFrame, corner-name annotation, key-rival selection, and the orchestrator that assembles `RaceNarrative`.

**Files:**
- Modify: `core/race/narrative.py`
- Test: `tests/test_race_narrative.py` (additions)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_race_narrative.py`:

```python
import pandas as pd

from core.race.models import (
    LapChartRow,
    RaceData,
    ResultRow,
    RosterEntry,
)
from core.race.narrative import (
    CAUTION_MASK,
    build_narrative,
    corner_name_at,
    detect_caution_laps,
    detect_incidents,
    detect_pit_laps,
    extract_place_changes,
    select_key_rivals,
)


def _ticks(**columns) -> pd.DataFrame:
    """Telemetry frame from equal-length column lists."""
    return pd.DataFrame(columns)


def _tel(
    n: int,
    lap=None,
    pos=None,
    pct=None,
    incidents=None,
    pit=None,
    flags=None,
) -> pd.DataFrame:
    return _ticks(
        Lap=lap if lap is not None else [1] * n,
        PlayerCarPosition=pos if pos is not None else [5] * n,
        LapDistPct=pct if pct is not None else [i / n for i in range(n)],
        PlayerCarMyIncidentCount=incidents if incidents is not None else [0] * n,
        OnPitRoad=pit if pit is not None else [False] * n,
        SessionFlags=flags if flags is not None else [0] * n,
        LapCurrentLapTime=[float(i) for i in range(n)],
    )


# --- extract_place_changes -------------------------------------------------

def test_extract_place_changes_requires_stability():
    # Position flickers 5->4 for 3 ticks (noise), then settles at 4
    pos = [5] * 100 + [4] * 3 + [5] * 100 + [4] * 100
    df = _tel(303, pos=pos)
    changes = extract_place_changes(df, stable_ticks=60)
    assert len(changes) == 1
    assert changes[0]["from_position"] == 5
    assert changes[0]["to_position"] == 4


# --- detect_incidents --------------------------------------------------------

def test_detect_incidents_reports_steps_with_context():
    n = 800
    incidents = [0] * 400 + [2] * 400  # one 2x at tick 400
    pos = [6] * 380 + [6] * 40 + [8] * 380
    lap = [9] * n
    df = _tel(n, lap=lap, pos=pos, incidents=incidents)
    events = detect_incidents(df, context_ticks=120)
    assert len(events) == 1
    assert events[0]["lap"] == 9
    assert events[0]["delta_incidents"] == 2
    assert events[0]["position_before"] == 6
    assert events[0]["position_after"] == 8


# --- detect_pit_laps / detect_caution_laps ----------------------------------

def test_detect_pit_laps():
    df = _tel(6, lap=[1, 1, 2, 2, 3, 3], pit=[False, False, True, True, False, False])
    assert detect_pit_laps(df) == {2}


def test_detect_caution_laps_uses_flag_bits():
    df = _tel(6, lap=[1, 1, 2, 2, 3, 3], flags=[0, 0, CAUTION_MASK, 0, 0, 0])
    assert detect_caution_laps(df) == {2}


# --- corner_name_at -----------------------------------------------------------

class _FakeCorner:
    def __init__(self, name, start, end):
        self.name = name
        self.distance_start_meters = start
        self.distance_end_meters = end


def test_corner_name_at_matches_with_tolerance():
    corners = [_FakeCorner("Knickerbrook", 2500.0, 2650.0)]
    assert corner_name_at(corners, 2600.0) == "Knickerbrook"
    assert corner_name_at(corners, 2460.0) == "Knickerbrook"  # within 50m
    assert corner_name_at(corners, 1000.0) is None


# --- select_key_rivals ----------------------------------------------------------

def _result(cust_id, finish):
    return ResultRow(
        cust_id=cust_id,
        display_name=f"D{cust_id}",
        finish_position=finish,
        starting_position=finish,
        laps_complete=10,
        incidents=0,
        oldi_rating=1500,
        newi_rating=1500,
        best_lap_time=100.0,
    )


def test_select_key_rivals_adjacent_finishers_and_battles():
    results = [_result(i, i) for i in range(1, 8)]  # player is cust 4, P4
    # cust 7 held the position adjacent to the player for 4 laps
    lap_chart = []
    for lap in range(1, 5):
        lap_chart.append(LapChartRow(cust_id=4, lap_number=lap, position=4))
        lap_chart.append(LapChartRow(cust_id=7, lap_number=lap, position=5))
    rivals = select_key_rivals(results, lap_chart, player_cust_id=4)
    assert 3 in rivals and 5 in rivals  # finished directly ahead/behind
    assert 7 in rivals                   # sustained adjacency battle
    assert len(rivals) <= 4


# --- build_narrative ------------------------------------------------------------

def _race_data() -> RaceData:
    n = 400
    df = _ticks(
        Lap=[1] * 100 + [2] * 100 + [3] * 100 + [4] * 100,
        PlayerCarPosition=[8] * 90 + [7] * 310,
        LapDistPct=list(pd.Series(range(n)) % 100 / 100.0),
        PlayerCarMyIncidentCount=[0] * 250 + [1] * 150,
        OnPitRoad=[False] * n,
        SessionFlags=[0] * n,
        LapCurrentLapTime=[float(i % 100) for i in range(n)],
    )
    laps = {
        1226848: _laps(1226848, [101.0, 100.0, 100.5, 100.2]),
        999: _laps(999, [100.5, 99.5, 99.8, 99.9]),
    }
    return RaceData(
        subsession_id=86748877,
        player_cust_id=1226848,
        player_car_idx=6,
        driver_name="Anthony Moorman",
        track_id=180,
        track_name="Oulton Park Circuit",
        track_config="International",
        track_directory="oulton international",
        track_length_m=4286.5,
        car_name="Mazda MX-5 Cup",
        series_name="MX-5 Cup",
        session_date="2026-06-26",
        sof=1350,
        player_telemetry=df,
        roster=[
            RosterEntry(6, 1226848, "Anthony Moorman", "8", 1420, "D 4.5", "MX-5"),
            RosterEntry(2, 999, "Rival One", "9", 1500, "D 4.9", "MX-5"),
        ],
        results=[_result(999, 6), _result(1226848, 7)],
        lap_chart=[
            LapChartRow(cust_id=1226848, lap_number=lap, position=p)
            for lap, p in [(1, 7), (2, 7), (3, 7), (4, 7)]
        ],
        driver_laps=laps,
    )


def test_build_narrative_assembles_all_sections():
    narrative = build_narrative(_race_data(), corners=[])
    assert narrative.header.subsession_id == 86748877
    assert narrative.header.finish_position == 7
    assert narrative.position_timeline[0].position == 7
    assert narrative.lap1 is not None
    assert narrative.lap1.grid_position == 7  # from ResultRow.starting_position
    assert narrative.pace is not None
    assert narrative.pace.median_clean_lap is not None
    assert narrative.attribution is not None
    assert len(narrative.incidents) == 1
    assert narrative.gaps  # rival 999 fetched laps -> gap series exists


def test_build_narrative_partial_without_api_data():
    data = _race_data()
    data.results = []
    data.lap_chart = []
    data.driver_laps = {}
    narrative = build_narrative(data, corners=[])
    # Telemetry-only facts still present
    assert len(narrative.incidents) == 1
    assert narrative.position_timeline  # falls back to telemetry positions
    # API-dependent facts absent, not faked
    assert narrative.pace is None or narrative.pace.pace_rank is None
    assert narrative.attribution is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_narrative.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_narrative'`.

- [ ] **Step 3: Implement**

Append to `core/race/narrative.py`:

```python
import pandas as pd

from core.race.models import (
    CautionSegment,
    IncidentEvent,
    Lap1Story,
    LapChartRow,
    NarrativeHeader,
    PaceSummary,
    PlaceChange,
    PositionPoint,
    RaceData,
    RaceNarrative,
    ResultRow,
    RivalGaps,
    Stint,
)

# irsdk SessionFlags bits: caution (0x4000) | caution_waving (0x8000)
CAUTION_MASK = 0x4000 | 0x8000

CORNER_TOLERANCE_M = 50.0


def extract_place_changes(
    df: pd.DataFrame, stable_ticks: int = 60
) -> list[dict]:
    """Position changes from PlayerCarPosition, debounced.

    A change counts only when the new position persists for
    stable_ticks (~1s at 60Hz) — timing flickers are noise.
    Returns dicts: {lap, lap_dist_pct, from_position, to_position}.
    """
    pos = df["PlayerCarPosition"].astype(int).to_numpy()
    laps = df["Lap"].astype(int).to_numpy()
    pct = df["LapDistPct"].astype(float).to_numpy()

    changes: list[dict] = []
    if len(pos) == 0:
        return changes
    last_stable = int(pos[0])
    i = 1
    while i < len(pos):
        if pos[i] != last_stable and pos[i] > 0:
            end = min(i + stable_ticks, len(pos))
            window = pos[i:end]
            if (window == pos[i]).all():
                changes.append(
                    {
                        "lap": int(laps[i]),
                        "lap_dist_pct": float(pct[i]),
                        "from_position": last_stable,
                        "to_position": int(pos[i]),
                    }
                )
                last_stable = int(pos[i])
                i = end
                continue
        i += 1
    return changes


def detect_incidents(
    df: pd.DataFrame, context_ticks: int = 120
) -> list[dict]:
    """Steps in PlayerCarMyIncidentCount with surrounding context.

    position_before/after sampled context_ticks (~2s) either side of
    the step. Returns dicts: {lap, lap_dist_pct, delta_incidents,
    position_before, position_after}.
    """
    counts = df["PlayerCarMyIncidentCount"].astype(int).to_numpy()
    laps = df["Lap"].astype(int).to_numpy()
    pct = df["LapDistPct"].astype(float).to_numpy()
    pos = df["PlayerCarPosition"].astype(int).to_numpy()

    events: list[dict] = []
    for i in range(1, len(counts)):
        delta = counts[i] - counts[i - 1]
        if delta <= 0:
            continue
        before = max(0, i - context_ticks)
        after = min(len(pos) - 1, i + context_ticks)
        events.append(
            {
                "lap": int(laps[i]),
                "lap_dist_pct": float(pct[i]),
                "delta_incidents": int(delta),
                "position_before": int(pos[before]),
                "position_after": int(pos[after]),
            }
        )
    return events


def detect_pit_laps(df: pd.DataFrame) -> set[int]:
    """Lap numbers where the player touched pit road."""
    mask = df["OnPitRoad"].astype(bool)
    return set(df.loc[mask, "Lap"].astype(int))


def detect_caution_laps(df: pd.DataFrame) -> set[int]:
    """Lap numbers run at least partly under caution flags."""
    flags = df["SessionFlags"].astype("int64")
    mask = (flags & CAUTION_MASK) != 0
    return set(df.loc[mask, "Lap"].astype(int))


def caution_segments(caution_laps: set[int]) -> list[CautionSegment]:
    """Contiguous caution-lap runs as segments."""
    segments: list[CautionSegment] = []
    for lap in sorted(caution_laps):
        if segments and lap == segments[-1].end_lap + 1:
            segments[-1] = CautionSegment(segments[-1].start_lap, lap)
        else:
            segments.append(CautionSegment(lap, lap))
    return segments


def corner_name_at(corners: list, dist_m: float) -> str | None:
    """Name of the corner containing (or within 50m of) a track distance."""
    for corner in corners:
        start = corner.distance_start_meters
        end = corner.distance_end_meters
        if start is None:
            continue
        if end is None:
            end = start
        if start - CORNER_TOLERANCE_M <= dist_m <= end + CORNER_TOLERANCE_M:
            return corner.name
    return None


def build_stints(
    player_laps: list, pit_laps: set[int], caution_laps: set[int]
) -> list[Stint]:
    """Split the race into stints at pit laps; per-stint pace + trend."""
    if not player_laps:
        return []
    lap_numbers = sorted(l.lap_number for l in player_laps)
    boundaries = sorted(p for p in pit_laps if lap_numbers[0] < p <= lap_numbers[-1])

    stints: list[Stint] = []
    start = lap_numbers[0]
    for boundary in boundaries + [lap_numbers[-1] + 1]:
        end = boundary - 1 if boundary in pit_laps else lap_numbers[-1]
        stint_laps = [l for l in player_laps if start <= l.lap_number <= end]
        clean = clean_laps(stint_laps, caution_laps)
        median = (
            statistics.median(l.lap_time for l in clean)
            if len(clean) >= MIN_CLEAN_LAPS
            else None
        )
        trend = None
        if len(clean) >= 4:
            half = len(clean) // 2
            trend = statistics.median(
                l.lap_time for l in clean[half:]
            ) - statistics.median(l.lap_time for l in clean[:half])
        stints.append(
            Stint(start_lap=start, end_lap=end, median_clean_pace=median, trend_s=trend)
        )
        start = boundary + 1 if boundary in pit_laps else start
        if boundary not in pit_laps:
            break
    return stints


def select_key_rivals(
    results: list[ResultRow],
    lap_chart: list[LapChartRow],
    player_cust_id: int,
    max_rivals: int = 4,
    min_adjacent_laps: int = 3,
) -> list[int]:
    """Cars worth telling the story against.

    Finishers directly ahead/behind, plus anyone holding an adjacent
    position for >= min_adjacent_laps, capped at max_rivals.
    """
    player_result = next(
        (r for r in results if r.cust_id == player_cust_id), None
    )
    if player_result is None:
        return []
    rivals: list[int] = []
    for r in results:
        if r.cust_id == player_cust_id:
            continue
        if abs(r.finish_position - player_result.finish_position) == 1:
            rivals.append(r.cust_id)

    # Sustained adjacency from the lap chart
    player_pos = {
        row.lap_number: row.position
        for row in lap_chart
        if row.cust_id == player_cust_id
    }
    adjacency: dict[int, int] = {}
    for row in lap_chart:
        if row.cust_id == player_cust_id:
            continue
        p = player_pos.get(row.lap_number)
        if p is not None and abs(row.position - p) == 1:
            adjacency[row.cust_id] = adjacency.get(row.cust_id, 0) + 1
    for cust_id, laps in sorted(adjacency.items(), key=lambda kv: -kv[1]):
        if laps >= min_adjacent_laps and cust_id not in rivals:
            rivals.append(cust_id)
    return rivals[:max_rivals]


def build_narrative(data: RaceData, corners: list) -> RaceNarrative:
    """Assemble the full RaceNarrative from ingested race data.

    Degrades honestly: with no API data (results/lap_chart/driver_laps
    empty) the telemetry-derived facts still populate; pace ranking and
    attribution are omitted rather than approximated.
    """
    df = data.player_telemetry
    pit_laps = detect_pit_laps(df)
    caution_laps = detect_caution_laps(df)

    player_result = next(
        (r for r in data.results if r.cust_id == data.player_cust_id), None
    )
    player_laps = data.driver_laps.get(data.player_cust_id, [])

    # Position timeline: lap chart canonical, telemetry fallback
    chart_points = sorted(
        (
            PositionPoint(lap=row.lap_number, position=row.position)
            for row in data.lap_chart
            if row.cust_id == data.player_cust_id and row.lap_number >= 1
        ),
        key=lambda p: p.lap,
    )
    if chart_points:
        timeline = chart_points
    else:
        per_lap = df[df["Lap"] >= 1].groupby("Lap")["PlayerCarPosition"].last()
        timeline = [
            PositionPoint(lap=int(lap), position=int(pos))
            for lap, pos in per_lap.items()
            if pos > 0
        ]

    # Lap 1 story
    raw_changes = extract_place_changes(df)
    lap1_changes = [
        PlaceChange(
            lap=c["lap"],
            lap_dist_pct=c["lap_dist_pct"],
            corner_name=corner_name_at(
                corners, c["lap_dist_pct"] * data.track_length_m
            ),
            from_position=c["from_position"],
            to_position=c["to_position"],
        )
        for c in raw_changes
        if c["lap"] == 1
    ]
    grid = player_result.starting_position if player_result else (
        timeline[0].position if timeline else 0
    )
    by_lap = {p.lap: p.position for p in timeline}
    lap1 = (
        Lap1Story(
            grid_position=grid,
            position_after_lap1=by_lap.get(1, grid),
            position_after_lap2=by_lap.get(2, by_lap.get(1, grid)),
            place_changes=lap1_changes,
        )
        if timeline
        else None
    )

    # Incidents with corner names and time-lost estimates
    player_median = median_clean_pace(player_laps, caution_laps)
    lap_times = {l.lap_number: l.lap_time for l in player_laps}
    incidents = []
    for e in detect_incidents(df):
        time_lost = 0.0
        if player_median is not None:
            lap_time = lap_times.get(e["lap"], -1.0)
            if lap_time > 0:
                time_lost = max(0.0, lap_time - player_median)
        incidents.append(
            IncidentEvent(
                lap=e["lap"],
                lap_dist_pct=e["lap_dist_pct"],
                corner_name=corner_name_at(
                    corners, e["lap_dist_pct"] * data.track_length_m
                ),
                delta_incidents=e["delta_incidents"],
                position_before=e["position_before"],
                position_after=e["position_after"],
                time_lost_estimate_s=round(time_lost, 2),
            )
        )

    # Pace + ranking (API-dependent)
    pace = None
    attribution = None
    if player_laps:
        ranked, unranked = pace_ranking(data.driver_laps, caution_laps)
        rank_index = next(
            (
                i + 1
                for i, (cust, _) in enumerate(ranked)
                if cust == data.player_cust_id
            ),
            None,
        )
        clean = clean_laps(player_laps, caution_laps)
        valid_times = [l.lap_time for l in player_laps if l.lap_time > 0]
        pace = PaceSummary(
            median_clean_lap=player_median,
            best_lap=min(valid_times) if valid_times else None,
            consistency_stdev=(
                round(statistics.stdev(l.lap_time for l in clean), 3)
                if len(clean) >= 2
                else None
            ),
            clean_lap_count=len(clean),
            pace_rank=rank_index,
            ranked_drivers=len(ranked),
            unranked_drivers=len(unranked),
        )
        if player_result is not None:
            attribution = build_attribution(
                irating_old=player_result.oldi_rating,
                irating_new=player_result.newi_rating,
                pace_deserved_position=rank_index,
                actual_position=player_result.finish_position,
                incident_time_lost_s=round(
                    sum(i.time_lost_estimate_s for i in incidents), 1
                ),
                lap1_net_positions=(grid - lap1.position_after_lap1)
                if lap1
                else 0,
            )

    # Gaps to key rivals
    rivals = select_key_rivals(data.results, data.lap_chart, data.player_cust_id)
    names = {r.cust_id: r.display_name for r in data.results}
    finishes = {r.cust_id: r.finish_position for r in data.results}
    gaps = [
        RivalGaps(
            cust_id=cust_id,
            display_name=names.get(cust_id, str(cust_id)),
            finish_position=finishes.get(cust_id, 0),
            gaps=compute_gaps(player_laps, data.driver_laps.get(cust_id, [])),
        )
        for cust_id in rivals
        if data.driver_laps.get(cust_id)
    ]

    header = NarrativeHeader(
        subsession_id=data.subsession_id,
        cust_id=data.player_cust_id,
        driver_name=data.driver_name,
        track_id=data.track_id,
        track_name=data.track_name,
        track_config=data.track_config,
        car_name=data.car_name,
        series_name=data.series_name,
        session_date=data.session_date,
        sof=data.sof,
        field_size=len(data.roster),
        start_position=grid,
        finish_position=(
            player_result.finish_position if player_result else (
                timeline[-1].position if timeline else 0
            )
        ),
        incidents=int(df["PlayerCarMyIncidentCount"].astype(int).max())
        if len(df)
        else 0,
        irating_old=player_result.oldi_rating if player_result else 0,
        irating_new=player_result.newi_rating if player_result else 0,
    )

    return RaceNarrative(
        header=header,
        position_timeline=timeline,
        lap1=lap1,
        gaps=gaps,
        incidents=incidents,
        stints=build_stints(player_laps, pit_laps, caution_laps),
        cautions=caution_segments(caution_laps),
        pace=pace,
        attribution=attribution,
        key_rivals=rivals,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_narrative.py -q`
Expected: PASS (all). Iterate on the synthetic-frame details if an assertion exposes an off-by-one — the tests define the contract.

- [ ] **Step 5: Run the full suite (regression guard)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: no new failures vs the pre-task baseline.

- [ ] **Step 6: Commit**

```bash
git add core/race/narrative.py tests/test_race_narrative.py
git commit -m "feat: narrative engine part B — telemetry events, stints, rivals, build_narrative"
```

---

### Task 6: Deterministic markdown render (`core/race/render.py`)

**Files:**
- Create: `core/race/render.py`
- Test: `tests/test_race_render.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_race_render.py`:

```python
"""Tests for the deterministic narrative -> markdown renderer."""

from tests.test_race_models import _minimal_narrative

from core.race.render import render_narrative_markdown


def test_render_contains_all_sections():
    md = render_narrative_markdown(_minimal_narrative())
    assert "Oulton Park" in md
    assert "P8" in md and "P6" in md          # start -> finish
    assert "Knickerbrook" in md               # incident corner
    assert "1420" in md and "1445" in md      # iRating old/new
    assert "Pace deserved" in md or "pace ranked" in md.lower()


def test_render_handles_partial_narrative():
    narrative = _minimal_narrative()
    narrative.pace = None
    narrative.attribution = None
    narrative.lap1 = None
    narrative.gaps = []
    md = render_narrative_markdown(narrative)
    assert "Oulton Park" in md
    assert "not available" in md.lower()      # honest about missing data


def test_render_never_contains_placeholder_text():
    md = render_narrative_markdown(_minimal_narrative())
    assert "TODO" not in md and "None" not in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_render.py -q`
Expected: FAIL — `ModuleNotFoundError` for `core.race.render`.

- [ ] **Step 3: Implement**

Create `core/race/render.py`:

```python
"""Deterministic RaceNarrative -> markdown.

This is what renders when no AI key is configured, and the factual top
half of the export artifact. Never contains AI text.
"""

from __future__ import annotations

from core.race.models import RaceNarrative


def _fmt_lap_time(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "-"
    minutes, rest = divmod(seconds, 60.0)
    return f"{int(minutes)}:{rest:06.3f}"


def render_narrative_markdown(narrative: RaceNarrative) -> str:
    """Render the full deterministic narrative as markdown."""
    h = narrative.header
    lines: list[str] = []

    config = f" ({h.track_config})" if h.track_config else ""
    lines.append(f"# Race Debrief — {h.track_name}{config}")
    lines.append("")
    lines.append(
        f"**{h.driver_name}** · {h.car_name} · {h.series_name} · "
        f"{h.session_date} · SoF {h.sof} · {h.field_size} cars"
    )
    lines.append("")
    lines.append(
        f"**P{h.start_position} -> P{h.finish_position}** · "
        f"{h.incidents}x incidents · "
        f"iRating {h.irating_old} -> {h.irating_new} "
        f"({h.irating_new - h.irating_old:+d})"
    )
    lines.append("")

    if narrative.lap1 is not None:
        l1 = narrative.lap1
        lines.append("## Lap 1")
        net = l1.grid_position - l1.position_after_lap1
        verb = "gained" if net > 0 else ("lost" if net < 0 else "held")
        detail = f"{verb} {abs(net)}" if net else "held position"
        lines.append(
            f"Grid P{l1.grid_position} -> P{l1.position_after_lap1} "
            f"after lap 1 ({detail})."
        )
        for c in l1.place_changes:
            where = c.corner_name or f"{c.lap_dist_pct:.0%} around the lap"
            direction = "up to" if c.to_position < c.from_position else "down to"
            lines.append(
                f"- {where}: P{c.from_position} {direction} P{c.to_position}"
            )
        lines.append("")

    if narrative.incidents:
        lines.append("## Incidents")
        for e in narrative.incidents:
            where = e.corner_name or f"{e.lap_dist_pct:.0%} around the lap"
            cost = (
                f", ~{e.time_lost_estimate_s:.1f}s lost (estimate)"
                if e.time_lost_estimate_s > 0
                else ""
            )
            lines.append(
                f"- Lap {e.lap}, {where}: {e.delta_incidents}x "
                f"(P{e.position_before} -> P{e.position_after}{cost})"
            )
        lines.append("")

    lines.append("## Pace")
    if narrative.pace is not None:
        p = narrative.pace
        lines.append(
            f"Best {_fmt_lap_time(p.best_lap)} · "
            f"median clean {_fmt_lap_time(p.median_clean_lap)} · "
            f"{p.clean_lap_count} clean laps"
            + (
                f" · stdev {p.consistency_stdev:.3f}s"
                if p.consistency_stdev is not None
                else ""
            )
        )
        if p.pace_rank is not None:
            lines.append(
                f"Clean-lap pace ranked **P{p.pace_rank}** of "
                f"{p.ranked_drivers} ranked drivers"
                + (
                    f" ({p.unranked_drivers} unranked — too few clean laps)"
                    if p.unranked_drivers
                    else ""
                )
                + "."
            )
    else:
        lines.append("Pace analysis not available (no lap data from the API).")
    lines.append("")

    if narrative.stints:
        lines.append("## Stints")
        for s in narrative.stints:
            trend = ""
            if s.trend_s is not None:
                word = "fading" if s.trend_s > 0 else "improving"
                trend = f", {word} {abs(s.trend_s):.2f}s over the stint"
            lines.append(
                f"- Laps {s.start_lap}-{s.end_lap}: median "
                f"{_fmt_lap_time(s.median_clean_pace)}{trend}"
            )
        lines.append("")

    if narrative.cautions:
        lines.append("## Cautions")
        for c in narrative.cautions:
            span = (
                f"lap {c.start_lap}"
                if c.start_lap == c.end_lap
                else f"laps {c.start_lap}-{c.end_lap}"
            )
            lines.append(f"- Caution: {span}")
        lines.append("")

    if narrative.gaps:
        lines.append("## Key battles")
        for rival in narrative.gaps:
            if not rival.gaps:
                continue
            final = rival.gaps[-1].gap_s
            state = "ahead" if final > 0 else "behind"
            lines.append(
                f"- **{rival.display_name}** (P{rival.finish_position}): "
                f"finished {abs(final):.1f}s {state}"
            )
        lines.append("")

    lines.append("## iRating attribution")
    if narrative.attribution is not None:
        for line in narrative.attribution.summary_lines:
            lines.append(f"- {line}")
    else:
        lines.append("Attribution not available (no official results data).")

    return "\n".join(lines)


def render_export_markdown(
    narrative: RaceNarrative,
    debrief_text: str | None,
    chat_transcript: list[dict] | None = None,
) -> str:
    """The shareable artifact: narrative + AI debrief (+ optional chat)."""
    parts = [render_narrative_markdown(narrative)]
    if debrief_text:
        parts.append("\n---\n\n## Engineer's debrief\n")
        parts.append(debrief_text)
    if chat_transcript:
        parts.append("\n---\n\n## Follow-up\n")
        for msg in chat_transcript:
            speaker = "Driver" if msg["role"] == "user" else "Engineer"
            parts.append(f"**{speaker}:** {msg['content']}\n")
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_render.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/race/render.py tests/test_race_render.py
git commit -m "feat: deterministic narrative markdown renderer + export assembly"
```

---

### Task 7: Race store (`core/race/race_store.py`, `data/races.db`)

Mirror `core/benchmark/reference_store.py`'s style (path-taking constructor, lazy init, explicit columns). Primary keys are `(subsession_id, cust_id)` throughout — two testers can race in the same subsession.

**Files:**
- Create: `core/race/race_store.py`
- Test: `tests/test_race_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_race_store.py`:

```python
"""Tests for the race debrief SQLite store."""

import pytest

from core.race.race_store import RaceStore, StoredRaceMeta
from tests.test_race_models import _minimal_narrative


@pytest.fixture
def store(tmp_path):
    return RaceStore(tmp_path / "races.db")


def test_save_and_load_race_round_trip(store):
    narrative = _minimal_narrative()
    store.save_race(narrative, ibt_file_path="C:/tmp/race.ibt")
    loaded = store.get_race(86748877, 1226848)
    assert loaded is not None
    assert loaded == narrative


def test_get_race_missing_returns_none(store):
    assert store.get_race(1, 2) is None


def test_same_subsession_two_drivers_coexist(store):
    a = _minimal_narrative()
    b = _minimal_narrative()
    b.header.cust_id = 555
    b.header.driver_name = "Friend Tester"
    store.save_race(a, ibt_file_path="")
    store.save_race(b, ibt_file_path="")
    assert store.get_race(86748877, 1226848).header.driver_name == "Anthony Moorman"
    assert store.get_race(86748877, 555).header.driver_name == "Friend Tester"


def test_resave_upserts_and_preserves_chat(store):
    narrative = _minimal_narrative()
    store.save_race(narrative, ibt_file_path="")
    store.append_chat_message(86748877, 1226848, "user", "why P6?")
    store.save_race(narrative, ibt_file_path="")  # re-ingest
    chat = store.get_chat(86748877, 1226848)
    assert len(chat) == 1
    assert chat[0]["content"] == "why P6?"


def test_debrief_save_and_get(store):
    narrative = _minimal_narrative()
    store.save_race(narrative, ibt_file_path="")
    store.save_debrief(86748877, 1226848, "Good race.", model="claude-sonnet-4-5")
    assert store.get_debrief(86748877, 1226848) == "Good race."
    store.save_debrief(86748877, 1226848, "Updated.", model="claude-sonnet-4-5")
    assert store.get_debrief(86748877, 1226848) == "Updated."


def test_list_races_returns_meta_newest_first(store):
    a = _minimal_narrative()
    store.save_race(a, ibt_file_path="")
    races = store.list_races()
    assert len(races) == 1
    meta = races[0]
    assert isinstance(meta, StoredRaceMeta)
    assert meta.subsession_id == 86748877
    assert meta.driver_name == "Anthony Moorman"
    assert meta.finish_position == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_store.py -q`
Expected: FAIL — `ModuleNotFoundError` for `core.race.race_store`.

- [ ] **Step 3: Implement**

Create `core/race/race_store.py`:

```python
"""SQLite persistence for race narratives, debriefs, and chat.

data/races.db — deliberately separate from tracks.db (watcher-owned
sessions history) and reference_laps.db. Keyed by (subsession_id,
cust_id): two testers can race in the same subsession.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.race.models import RaceNarrative

DEFAULT_DB_PATH = Path("data/races.db")


@dataclass
class StoredRaceMeta:
    """Scalar race metadata for list views (no narrative payload)."""

    subsession_id: int
    cust_id: int
    driver_name: str
    track_name: str
    car: str
    series_name: str
    session_date: str
    sof: int
    start_position: int
    finish_position: int
    incidents: int
    irating_delta: int
    created_at: str


class RaceStore:
    """CRUD for persisted race debriefs."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS races (
                    subsession_id INTEGER NOT NULL,
                    cust_id INTEGER NOT NULL,
                    driver_name TEXT,
                    track_id INTEGER,
                    track_name TEXT,
                    car TEXT,
                    series_name TEXT,
                    session_date TEXT,
                    sof INTEGER,
                    field_size INTEGER,
                    start_position INTEGER,
                    finish_position INTEGER,
                    incidents INTEGER,
                    irating_old INTEGER,
                    irating_new INTEGER,
                    ibt_file_path TEXT,
                    narrative_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (subsession_id, cust_id)
                );
                CREATE TABLE IF NOT EXISTS debriefs (
                    subsession_id INTEGER NOT NULL,
                    cust_id INTEGER NOT NULL,
                    debrief_text TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (subsession_id, cust_id)
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subsession_id INTEGER NOT NULL,
                    cust_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def save_race(
        self, narrative: RaceNarrative, ibt_file_path: str
    ) -> None:
        """Insert or replace a race narrative (chat is never touched)."""
        h = narrative.header
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO races (
                    subsession_id, cust_id, driver_name, track_id,
                    track_name, car, series_name, session_date, sof,
                    field_size, start_position, finish_position,
                    incidents, irating_old, irating_new, ibt_file_path,
                    narrative_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    h.subsession_id, h.cust_id, h.driver_name, h.track_id,
                    h.track_name, h.car_name, h.series_name, h.session_date,
                    h.sof, h.field_size, h.start_position,
                    h.finish_position, h.incidents, h.irating_old,
                    h.irating_new, ibt_file_path,
                    json.dumps(narrative.to_dict()), self._now(),
                ),
            )

    def get_race(
        self, subsession_id: int, cust_id: int
    ) -> RaceNarrative | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT narrative_json FROM races "
                "WHERE subsession_id = ? AND cust_id = ?",
                (subsession_id, cust_id),
            ).fetchone()
        if row is None:
            return None
        return RaceNarrative.from_dict(json.loads(row["narrative_json"]))

    def list_races(self) -> list[StoredRaceMeta]:
        """Scalar metadata for all stored races, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT subsession_id, cust_id, driver_name, track_name,
                       car, series_name, session_date, sof,
                       start_position, finish_position, incidents,
                       irating_old, irating_new, created_at
                FROM races ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            StoredRaceMeta(
                subsession_id=r["subsession_id"],
                cust_id=r["cust_id"],
                driver_name=r["driver_name"] or "",
                track_name=r["track_name"] or "",
                car=r["car"] or "",
                series_name=r["series_name"] or "",
                session_date=r["session_date"] or "",
                sof=r["sof"] or 0,
                start_position=r["start_position"] or 0,
                finish_position=r["finish_position"] or 0,
                incidents=r["incidents"] or 0,
                irating_delta=(r["irating_new"] or 0) - (r["irating_old"] or 0),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def save_debrief(
        self, subsession_id: int, cust_id: int, text: str, model: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO debriefs (
                    subsession_id, cust_id, debrief_text, model, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (subsession_id, cust_id, text, model, self._now()),
            )

    def get_debrief(self, subsession_id: int, cust_id: int) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT debrief_text FROM debriefs "
                "WHERE subsession_id = ? AND cust_id = ?",
                (subsession_id, cust_id),
            ).fetchone()
        return row["debrief_text"] if row else None

    def append_chat_message(
        self, subsession_id: int, cust_id: int, role: str, content: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (
                    subsession_id, cust_id, role, content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (subsession_id, cust_id, role, content, self._now()),
            )

    def get_chat(self, subsession_id: int, cust_id: int) -> list[dict]:
        """Chat transcript in insertion order as role/content dicts."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages "
                "WHERE subsession_id = ? AND cust_id = ? ORDER BY id",
                (subsession_id, cust_id),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_store.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add core/race/race_store.py tests/test_race_store.py
git commit -m "feat: race store — narratives, debriefs, chat keyed by (subsession, cust)"
```

---

### Task 8: Ingestion orchestrator (`core/race/ingest.py`)

IBT + YAML extraction, API fetch with disk cache, simsession selection, row parsing into models, `ingest_race` entry point. Partial-narrative mode when the API is unavailable.

**Files:**
- Create: `core/race/ingest.py`
- Test: `tests/test_race_ingest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_race_ingest.py`:

```python
"""Tests for race ingestion: parsing, caching, simsession selection.

Integration tests against the real Oulton fixture live at the bottom
and skip when fixtures are absent (recorded by
scripts/record_race_fixture.py — see Task 11).
"""

import json
from pathlib import Path

import pytest

from core.race.ingest import (
    RaceIngestError,
    _cached_fetch,
    parse_lap_chart_rows,
    parse_lap_data_rows,
    parse_results,
    select_race_simsession,
)


# --- select_race_simsession -------------------------------------------------

def test_select_race_simsession_prefers_number_zero():
    sessions = [
        {"simsession_number": -2, "simsession_type_name": "Open Practice"},
        {"simsession_number": -1, "simsession_type_name": "Lone Qualifying"},
        {"simsession_number": 0, "simsession_type_name": "Race"},
    ]
    assert select_race_simsession(sessions)["simsession_number"] == 0


def test_select_race_simsession_falls_back_to_name():
    sessions = [
        {"simsession_number": -1, "simsession_type_name": "Lone Qualifying"},
        {"simsession_number": 1, "simsession_type_name": "Feature Race"},
    ]
    assert select_race_simsession(sessions)["simsession_number"] == 1


def test_select_race_simsession_raises_without_race():
    with pytest.raises(RaceIngestError):
        select_race_simsession(
            [{"simsession_number": -2, "simsession_type_name": "Open Practice"}]
        )


# --- parse_results ------------------------------------------------------------

def test_parse_results_extracts_rows_and_lap_times():
    raw = {
        "session_results": [
            {
                "simsession_number": 0,
                "simsession_type_name": "Race",
                "results": [
                    {
                        "cust_id": 1226848,
                        "display_name": "Anthony Moorman",
                        "finish_position": 6,     # zero-based in the API
                        "starting_position": 7,
                        "laps_complete": 14,
                        "incidents": 5,
                        "oldi_rating": 1420,
                        "newi_rating": 1445,
                        "best_lap_time": 1129000,  # 1/10000s
                    }
                ],
            }
        ]
    }
    rows = parse_results(raw)
    assert len(rows) == 1
    r = rows[0]
    assert r.cust_id == 1226848
    assert r.finish_position == 7      # converted to 1-based
    assert r.starting_position == 8    # converted to 1-based
    assert r.best_lap_time == pytest.approx(112.9)


def test_parse_results_handles_invalid_best_lap():
    raw = {
        "session_results": [
            {
                "simsession_number": 0,
                "simsession_type_name": "Race",
                "results": [
                    {
                        "cust_id": 1,
                        "display_name": "X",
                        "finish_position": 0,
                        "starting_position": 0,
                        "laps_complete": 2,
                        "incidents": 0,
                        "oldi_rating": 1000,
                        "newi_rating": 990,
                        "best_lap_time": -1,
                    }
                ],
            }
        ]
    }
    assert parse_results(raw)[0].best_lap_time == -1.0


# --- parse_lap_chart_rows / parse_lap_data_rows --------------------------------

def test_parse_lap_chart_rows():
    raw = [
        {"cust_id": 1, "lap_number": 0, "lap_position": 3},  # lap 0 dropped
        {"cust_id": 1, "lap_number": 1, "lap_position": 4},
        {"group_id": 2, "lap_number": 1, "lap_position": 5},  # cust via group
    ]
    rows = parse_lap_chart_rows(raw)
    assert [(r.cust_id, r.lap_number, r.position) for r in rows] == [
        (1, 1, 4),
        (2, 1, 5),
    ]


def test_parse_lap_data_rows():
    raw = [
        {
            "cust_id": 1,
            "lap_number": 1,
            "lap_time": 1130000,
            "lap_events": ["off track"],
            "incident": True,
        },
        {"cust_id": 1, "lap_number": 2, "lap_time": -1, "lap_events": []},
    ]
    laps = parse_lap_data_rows(raw, cust_id=1)
    assert laps[0].lap_time == pytest.approx(113.0)
    assert laps[0].incident is True
    assert laps[0].lap_events == ["off track"]
    assert laps[1].lap_time == -1.0


# --- _cached_fetch ---------------------------------------------------------------

def test_cached_fetch_writes_then_reads_cache(tmp_path):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"value": 42}

    path = tmp_path / "sub" / "results.json"
    assert _cached_fetch(path, fetch) == {"value": 42}
    assert _cached_fetch(path, fetch) == {"value": 42}
    assert calls["n"] == 1  # second call served from disk
    assert json.loads(path.read_text())["value"] == 42
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError` for `core.race.ingest`.

- [ ] **Step 3: Implement**

Create `core/race/ingest.py`:

```python
"""Race ingestion: IBT + session YAML + Data API -> RaceData.

Raw API responses are cached to data/race_cache/{subsession_id}/ so a
race is fetched once; cached files double as recorded test fixtures.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from core.race.models import (
    DriverLap,
    LapChartRow,
    RaceData,
    ResultRow,
    RosterEntry,
)
from core.telemetry.ibt_parser import IBTParser

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/race_cache")

RACE_CHANNELS = IBTParser.CORE_CHANNELS + [
    "PlayerCarPosition",
    "PlayerCarClassPosition",
    "SessionFlags",
    "FuelLevel",
    "SessionState",
]


class RaceIngestError(Exception):
    """Raised when a source cannot be ingested as an official race."""


def select_race_simsession(session_results: list[dict]) -> dict:
    """Pick the race simsession from a results payload.

    Prefers simsession_number == 0 (the race in official events);
    falls back to a type-name match for odd formats.
    """
    for entry in session_results:
        if entry.get("simsession_number") == 0:
            return entry
    for entry in session_results:
        name = (entry.get("simsession_type_name") or "").lower()
        if "race" in name:
            return entry
    raise RaceIngestError(
        "No race simsession in results payload "
        f"(found: {[e.get('simsession_type_name') for e in session_results]})"
    )


def _parse_api_lap_time(value) -> float:
    """API lap times are 1/10000s; <= 0 means no valid time."""
    if not isinstance(value, (int, float)) or value <= 0:
        return -1.0
    return value / 10000.0


def parse_results(raw: dict) -> list[ResultRow]:
    """Official race results -> ResultRow list (positions -> 1-based)."""
    race = select_race_simsession(raw.get("session_results", []))
    rows: list[ResultRow] = []
    for r in race.get("results", []):
        rows.append(
            ResultRow(
                cust_id=r.get("cust_id", 0),
                display_name=r.get("display_name", ""),
                finish_position=r.get("finish_position", -1) + 1,
                starting_position=r.get("starting_position", -1) + 1,
                laps_complete=r.get("laps_complete", 0),
                incidents=r.get("incidents", 0),
                oldi_rating=r.get("oldi_rating", 0),
                newi_rating=r.get("newi_rating", 0),
                best_lap_time=_parse_api_lap_time(r.get("best_lap_time")),
            )
        )
    return rows


def parse_lap_chart_rows(raw: list[dict]) -> list[LapChartRow]:
    """Lap chart rows -> LapChartRow list. Lap 0 (grid) is dropped."""
    rows: list[LapChartRow] = []
    for r in raw:
        cust_id = r.get("cust_id") or r.get("group_id") or 0
        lap = r.get("lap_number", 0)
        if lap < 1:
            continue
        rows.append(
            LapChartRow(
                cust_id=cust_id,
                lap_number=lap,
                position=r.get("lap_position", 0),
            )
        )
    return rows


def parse_lap_data_rows(raw: list[dict], cust_id: int) -> list[DriverLap]:
    """Per-driver lap data rows -> DriverLap list."""
    return [
        DriverLap(
            cust_id=cust_id,
            lap_number=r.get("lap_number", 0),
            lap_time=_parse_api_lap_time(r.get("lap_time")),
            lap_events=list(r.get("lap_events", []) or []),
            incident=bool(r.get("incident", False)),
        )
        for r in raw
        if r.get("lap_number", 0) >= 1
    ]


def _cached_fetch(cache_path: Path, fetch: Callable[[], dict | list]):
    """Serve from disk cache, else fetch and cache.

    The cache file is written only after a fully successful fetch.
    """
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    data = fetch()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def load_race_ibt(source: Path | bytes) -> tuple:
    """Parse a race IBT with extended channels; validate it IS a race.

    Returns (IBTFile, meta dict). Raises RaceIngestError for non-race
    sessions or missing SubSessionID.
    """
    parser = IBTParser()
    ibt = parser.parse(source, channels=RACE_CHANNELS)

    raw = ibt.session.raw or {}
    weekend = raw.get("WeekendInfo", {}) or {}
    subsession_id = weekend.get("SubSessionID", 0)
    if weekend.get("EventType") != "Race" or not subsession_id:
        raise RaceIngestError(
            "This IBT is not an official race session "
            f"(EventType={weekend.get('EventType')!r}, "
            f"SubSessionID={subsession_id!r})."
        )

    driver_info = raw.get("DriverInfo", {}) or {}
    player_car_idx = driver_info.get("DriverCarIdx", -1)
    player_cust_id = driver_info.get("DriverUserID", 0)

    roster = []
    for d in driver_info.get("Drivers", []) or []:
        if d.get("IsSpectator") or d.get("CarIsPaceCar"):
            continue
        roster.append(
            RosterEntry(
                car_idx=d.get("CarIdx", -1),
                cust_id=d.get("UserID", 0),
                display_name=d.get("UserName", ""),
                car_number=str(d.get("CarNumber", "")),
                irating=d.get("IRating", 0),
                license_string=d.get("LicString", ""),
                car_name=d.get("CarScreenName", ""),
            )
        )

    iratings = [r.irating for r in roster if r.irating > 0]
    meta = {
        "subsession_id": int(subsession_id),
        "player_cust_id": int(player_cust_id),
        "player_car_idx": int(player_car_idx),
        "driver_name": ibt.session.driver_name,
        "track_id": ibt.session.track_id,
        "track_name": ibt.session.track_name,
        "track_config": weekend.get("TrackConfigName", "") or "",
        "track_directory": ibt.session.track_directory,
        "track_length_m": ibt.session.track_length_km * 1000.0,
        "car_name": ibt.session.car_name,
        "series_name": "",  # filled from results when available
        "session_date": "",  # filled from results when available
        "sof": int(sum(iratings) / len(iratings)) if iratings else 0,
        "roster": roster,
    }
    return ibt, meta


def ingest_race(
    source: Path | bytes,
    api,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    ibt_path_for_record: str = "",
) -> RaceData:
    """Full ingestion: IBT + YAML + API (cached) -> RaceData.

    api is a LiveIRacingAPI/StubIRacingAPI or None. API failures degrade
    to a partial RaceData (results/lap_chart/driver_laps empty) with a
    warning — the page renders what the telemetry alone supports.
    """
    ibt, meta = load_race_ibt(source)
    subsession_id = meta["subsession_id"]
    sub_cache = cache_dir / str(subsession_id)

    results: list[ResultRow] = []
    lap_chart: list[LapChartRow] = []
    driver_laps: dict[int, list[DriverLap]] = {}

    if api is not None:
        try:
            raw_results = _cached_fetch(
                sub_cache / "results.json",
                lambda: api.get_subsession_results(subsession_id),
            )
            if raw_results:
                results = parse_results(raw_results)
                meta["series_name"] = raw_results.get("series_name", "")
                meta["session_date"] = raw_results.get("start_time", "")

                race_sim = select_race_simsession(
                    raw_results.get("session_results", [])
                )
                simsession = race_sim.get("simsession_number", 0)

                raw_chart = _cached_fetch(
                    sub_cache / "lap_chart.json",
                    lambda: api.get_lap_chart_data(subsession_id, simsession),
                )
                lap_chart = parse_lap_chart_rows(raw_chart)

                # Lap data: player + key rivals only (bounds API calls).
                # Rival selection needs results + chart, both now loaded.
                from core.race.narrative import select_key_rivals

                targets = [meta["player_cust_id"]] + select_key_rivals(
                    results, lap_chart, meta["player_cust_id"]
                )
                for cust_id in targets:
                    raw_laps = _cached_fetch(
                        sub_cache / f"lap_data_{cust_id}.json",
                        lambda cid=cust_id: api.get_lap_data(
                            subsession_id, simsession, cid
                        ),
                    )
                    laps = parse_lap_data_rows(raw_laps, cust_id)
                    if laps:
                        driver_laps[cust_id] = laps
        except RaceIngestError:
            raise
        except Exception as exc:  # noqa: BLE001 — degrade, never crash
            logger.warning(
                "Data API fetch failed for subsession %s: %s — "
                "building partial narrative from telemetry only",
                subsession_id,
                exc,
            )
            results, lap_chart, driver_laps = [], [], {}

    return RaceData(
        subsession_id=subsession_id,
        player_cust_id=meta["player_cust_id"],
        player_car_idx=meta["player_car_idx"],
        driver_name=meta["driver_name"],
        track_id=meta["track_id"],
        track_name=meta["track_name"],
        track_config=meta["track_config"],
        track_directory=meta["track_directory"],
        track_length_m=meta["track_length_m"],
        car_name=meta["car_name"],
        series_name=meta["series_name"],
        session_date=meta["session_date"],
        sof=meta["sof"],
        player_telemetry=ibt.telemetry,
        roster=meta["roster"],
        results=results,
        lap_chart=lap_chart,
        driver_laps=driver_laps,
    )
```

Note the API field-name assumptions (`finish_position` zero-based, `lap_position`, `lap_events`, `series_name`, `start_time`): they follow the iRacing Data API docs, but Task 11's real-fixture recording is the verification gate. If a real payload disagrees, fix the parser here and the fake payloads in this test file to match reality — reality wins.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_ingest.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add core/race/ingest.py tests/test_race_ingest.py
git commit -m "feat: race ingestion — IBT+YAML+API with disk cache and partial mode"
```

---

### Task 9: AI layer — debrief prompt, synthesis, chat (`prompts/race_debrief.py`, `synthesizer.py`)

**Files:**
- Create: `core/coaching/prompts/race_debrief.py`
- Modify: `core/coaching/synthesizer.py`
- Test: `tests/test_synthesizer.py` (additions)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_synthesizer.py` (read the file's existing fake-client pattern first; if it monkeypatches differently, adapt the injection, keep the assertions):

```python
from tests.test_race_models import _minimal_narrative

from core.coaching.prompts.race_debrief import (
    RACE_DEBRIEF_SYSTEM_PROMPT,
    build_race_chat_system,
    build_race_debrief_prompt,
)


def test_race_debrief_system_prompt_carries_tone_contract():
    text = RACE_DEBRIEF_SYSTEM_PROMPT.lower()
    assert "engineer" in text
    assert "never" in text          # never scold / never invent
    assert "2" in RACE_DEBRIEF_SYSTEM_PROMPT or "two" in text  # takeaway cap


def test_build_race_debrief_prompt_embeds_narrative_json():
    prompt = build_race_debrief_prompt(_minimal_narrative())
    assert "86748877" in prompt
    assert "Knickerbrook" in prompt
    assert "Anthony Moorman" in prompt


def test_build_race_chat_system_includes_debrief_and_grounding():
    system = build_race_chat_system(_minimal_narrative(), "You raced well.")
    assert "You raced well." in system
    assert "Knickerbrook" in system
    assert "don't have that" in system.lower() or "not in the data" in system.lower()


class _FakeMessages:
    def __init__(self, reply_text: str):
        self.reply_text = reply_text
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        class _Block:
            type = "text"
            text = self.reply_text

        class _Usage:
            input_tokens = 10
            output_tokens = 20

        class _Response:
            content = [_Block()]
            usage = _Usage()
            model = kwargs["model"]

        return _Response()


def _synthesizer_with_fake(reply_text: str):
    from core.coaching.synthesizer import Synthesizer

    synth = Synthesizer(api_key="fake-key")
    fake = _FakeMessages(reply_text)
    synth.client.messages = fake
    return synth, fake


def test_generate_race_debrief_returns_report():
    synth, fake = _synthesizer_with_fake("Solid recovery drive.")
    report = synth.generate_race_debrief(_minimal_narrative())
    assert report.report_text == "Solid recovery drive."
    assert report.track == "Oulton Park Circuit"
    # No web search tools on the debrief path — facts come from the narrative
    assert "tools" not in fake.calls[0]


def test_race_chat_reply_threads_history_and_caps_it():
    synth, fake = _synthesizer_with_fake("About lap 9...")
    history = [{"role": "user", "content": f"q{i}"} for i in range(30)]
    history += [{"role": "assistant", "content": "a"}, {"role": "user", "content": "final"}]
    reply = synth.race_chat_reply(_minimal_narrative(), "Debrief.", history)
    assert reply == "About lap 9..."
    sent = fake.calls[0]["messages"]
    assert len(sent) <= 20            # capped
    assert sent[-1]["content"] == "final"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_synthesizer.py -q`
Expected: FAIL — `ModuleNotFoundError` for `core.coaching.prompts.race_debrief`.

- [ ] **Step 3: Implement the prompt module**

Create `core/coaching/prompts/race_debrief.py`:

```python
"""Prompts for race debrief synthesis and conversational follow-up.

The tone contract lives here as hard system-prompt rules. The narrative
JSON is the ONLY source of facts — the model is told so explicitly.
"""

from __future__ import annotations

import json

from core.race.models import RaceNarrative

RACE_DEBRIEF_SYSTEM_PROMPT = """\
You are the driver's personal race engineer, debriefing them after an
iRacing official race. You work FOR the driver. Rules, in priority order:

1. Engineer, not judge. Never scold, never moralize, never flatter
   dishonestly. You are on the driver's side and you tell the truth.
2. Every factual claim (positions, gaps, lap times, incidents, iRating)
   MUST come from the race data JSON you are given. Never invent or
   extrapolate facts. If the data doesn't contain something, don't
   claim it.
3. Reframe bad races as intelligence gained. A wrecked race gets the
   most USEFUL debrief, not the most painful one. What did this race
   teach that the next one can use?
4. Be opinionated and prioritized. End with at most 2-3 concrete,
   forward-looking takeaways ("next restart, hold the inside into T1"),
   never generic advice ("be more careful").

Voice: direct, calm, specific — a professional engineer on the radio
after the checkered flag. Write in second person. Keep it under 500
words. Use plain paragraphs and a short takeaway list at the end.
"""


def build_race_debrief_prompt(narrative: RaceNarrative) -> str:
    """User message for the one-shot debrief generation."""
    h = narrative.header
    return (
        f"Debrief this race for {h.driver_name} "
        f"({h.car_name}, {h.series_name}).\n\n"
        "--- RACE DATA (JSON) ---\n"
        f"{json.dumps(narrative.to_dict(), indent=2)}\n"
        "--- END RACE DATA ---\n\n"
        "Write the debrief."
    )


def build_race_chat_system(
    narrative: RaceNarrative, debrief_text: str
) -> str:
    """System prompt for follow-up chat, grounded in the same data."""
    return (
        RACE_DEBRIEF_SYSTEM_PROMPT
        + "\n\nYou already delivered this debrief:\n---\n"
        + debrief_text
        + "\n---\n\nThe complete race data JSON:\n"
        + json.dumps(narrative.to_dict())
        + "\n\nAnswer the driver's follow-up questions from this data "
        "only. If a question cannot be answered from it, say plainly "
        "that you don't have that data from this session — never guess. "
        "Keep answers short and conversational; this is radio chatter, "
        "not a report."
    )
```

- [ ] **Step 4: Implement the synthesizer additions**

In `core/coaching/synthesizer.py`: add imports near the existing prompt imports —

```python
from core.coaching.prompts.race_debrief import (
    RACE_DEBRIEF_SYSTEM_PROMPT,
    build_race_chat_system,
    build_race_debrief_prompt,
)
```

Add a `TYPE_CHECKING` import: `from core.race.models import RaceNarrative`.

Add a dataclass next to `CoachingReport`:

```python
@dataclass
class RaceDebriefReport:
    """Generated race debrief with metadata."""

    subsession_id: int
    track: str
    car: str
    report_text: str
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
```

Add two methods to `Synthesizer` (after `generate_coaching_narrative`):

```python
    MAX_CHAT_HISTORY = 20

    def generate_race_debrief(
        self, narrative: "RaceNarrative"
    ) -> RaceDebriefReport:
        """Generate the race debrief from the deterministic narrative.

        No web search — every fact comes from the narrative JSON.
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=RACE_DEBRIEF_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_race_debrief_prompt(narrative),
                }
            ],
        )
        return RaceDebriefReport(
            subsession_id=narrative.header.subsession_id,
            track=narrative.header.track_name,
            car=narrative.header.car_name,
            report_text=self._extract_text(response),
            model_used=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def race_chat_reply(
        self,
        narrative: "RaceNarrative",
        debrief_text: str,
        history: list[dict],
    ) -> str:
        """One follow-up chat turn, grounded in the narrative + debrief.

        history: [{"role": "user"|"assistant", "content": str}, ...],
        newest last. Only the last MAX_CHAT_HISTORY turns are sent.
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=800,
            system=build_race_chat_system(narrative, debrief_text),
            messages=history[-self.MAX_CHAT_HISTORY:],
        )
        return self._extract_text(response)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_synthesizer.py -q`
Expected: PASS (all, including pre-existing).

- [ ] **Step 6: Commit**

```bash
git add core/coaching/prompts/race_debrief.py core/coaching/synthesizer.py tests/test_synthesizer.py
git commit -m "feat: race debrief AI synthesis + grounded chat with tone contract"
```

---

### Task 10: Streamlit page, navigation, server config

Display-only page: picker (upload primary, host folder scan secondary, stored races), narrative + charts, AI debrief, chat, export. Business logic stays in `core/` — the page only orchestrates calls and renders.

**Files:**
- Create: `app/pages/race_debrief.py`
- Modify: `app/streamlit_app.py`
- Create: `.streamlit/config.toml`
- Modify: `.gitignore`
- Test: manual (Streamlit pages are not unit-tested in this project; all logic already tested in Tasks 1–9)

- [ ] **Step 1: Create `.streamlit/config.toml`**

```toml
[server]
maxUploadSize = 400   # race IBTs run 25-205 MB
headless = true
```

- [ ] **Step 2: Add gitignore entries**

Append to `.gitignore` (check for an existing data-section to group with):

```
data/race_cache/
data/races.db
tests/fixtures/race/
```

- [ ] **Step 3: Write the page**

Create `app/pages/race_debrief.py`:

```python
"""Race Debrief page — Surface 1 of the race-intelligence product.

Display-only: all analysis lives in core/race/. The page orchestrates
ingest -> narrative -> store -> render, then AI debrief + chat.
"""

from __future__ import annotations

import os
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from core.race.ingest import (
    RaceIngestError,
    ingest_race,
    load_race_ibt,
)
from core.race.models import RaceNarrative
from core.race.narrative import build_narrative
from core.race.race_store import RaceStore
from core.race.render import render_export_markdown, render_narrative_markdown
from core.telemetry.ibt_parser import IBTParser
from core.track.track_db import TrackDB

TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")
TRACKS_DB = Path("data/tracks.db")


def _make_api():
    """LiveIRacingAPI from env creds, or None (partial-narrative mode)."""
    client_id = os.environ.get("IRACING_CLIENT_ID", "")
    client_secret = os.environ.get("IRACING_CLIENT_SECRET", "")
    username = os.environ.get("IRACING_USERNAME", "")
    password = os.environ.get("IRACING_PASSWORD", "")
    if not all([client_id, client_secret, username, password]):
        return None
    from core.benchmark.iracing_api import LiveIRacingAPI

    return LiveIRacingAPI(client_id, client_secret, username, password)


def _load_corners(track_id: int, track_directory: str, track_length_m: float):
    """Corners for annotation, lazy-seeding like the live coach does."""
    try:
        db = TrackDB(TRACKS_DB)
        corners = db.get_corners(str(track_id))
        if not corners:
            from core.track.lovely_seeder import seed_track_from_lovely

            seed_track_from_lovely(
                db, str(track_id), track_directory, track_length_m
            )
            corners = db.get_corners(str(track_id))
        return corners
    except Exception:  # noqa: BLE001 — corner names are enhancement only
        return []


@st.cache_data(show_spinner=False)
def _scan_race_ibts(folder: str) -> list[dict]:
    """Cheap scan of the host telemetry folder for race IBTs."""
    parser = IBTParser()
    races = []
    for path in sorted(Path(folder).glob("*.ibt"), reverse=True):
        try:
            session = parser.parse_session_only(path)
            weekend = (session.raw or {}).get("WeekendInfo", {}) or {}
            if weekend.get("EventType") == "Race" and weekend.get("SubSessionID"):
                races.append(
                    {
                        "path": str(path),
                        "label": f"{session.track_name} — {session.car_name} "
                        f"— {path.stem[-19:]}",
                    }
                )
        except Exception:  # noqa: BLE001 — skip unreadable files
            continue
    return races


def _analyze(source, ibt_path: str, store: RaceStore) -> RaceNarrative:
    """Ingest -> narrative -> persist. Returns the narrative."""
    api = _make_api()
    try:
        data = ingest_race(source, api)
    finally:
        if api is not None:
            api.close()
    corners = _load_corners(
        data.track_id, data.track_directory, data.track_length_m
    )
    narrative = build_narrative(data, corners)
    store.save_race(narrative, ibt_file_path=ibt_path)
    return narrative


def _position_chart(narrative: RaceNarrative) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[p.lap for p in narrative.position_timeline],
            y=[p.position for p in narrative.position_timeline],
            mode="lines+markers",
            name=narrative.header.driver_name,
        )
    )
    fig.update_yaxes(autorange="reversed", dtick=1, title="Position")
    fig.update_xaxes(dtick=1, title="Lap")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig


def _gap_chart(narrative: RaceNarrative) -> go.Figure:
    fig = go.Figure()
    for rival in narrative.gaps:
        fig.add_trace(
            go.Scatter(
                x=[g.lap for g in rival.gaps],
                y=[g.gap_s for g in rival.gaps],
                mode="lines",
                name=f"{rival.display_name} (P{rival.finish_position})",
            )
        )
    fig.add_hline(y=0.0, line_dash="dot")
    fig.update_yaxes(title="Gap (s) — positive = rival ahead")
    fig.update_xaxes(dtick=1, title="Lap")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig


def _render_debrief_and_chat(narrative: RaceNarrative, store: RaceStore):
    h = narrative.header
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    st.subheader("Engineer's debrief")
    debrief_text = store.get_debrief(h.subsession_id, h.cust_id)

    if not api_key:
        st.info(
            "AI debrief unavailable — ANTHROPIC_API_KEY is not configured. "
            "The narrative above is complete without it."
        )
    else:
        from core.coaching.synthesizer import Synthesizer

        if debrief_text is None:
            if st.button("Generate debrief"):
                with st.spinner("Engineer is reviewing the race..."):
                    synth = Synthesizer(api_key=api_key)
                    report = synth.generate_race_debrief(narrative)
                    store.save_debrief(
                        h.subsession_id, h.cust_id,
                        report.report_text, report.model_used,
                    )
                st.rerun()
        else:
            st.markdown(debrief_text)

            st.subheader("Ask the engineer")
            history = store.get_chat(h.subsession_id, h.cust_id)
            for msg in history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
            question = st.chat_input("Ask about the race...")
            if question:
                store.append_chat_message(
                    h.subsession_id, h.cust_id, "user", question
                )
                with st.spinner("..."):
                    synth = Synthesizer(api_key=api_key)
                    reply = synth.race_chat_reply(
                        narrative,
                        debrief_text,
                        history + [{"role": "user", "content": question}],
                    )
                store.append_chat_message(
                    h.subsession_id, h.cust_id, "assistant", reply
                )
                st.rerun()

    # Export is always available (works without AI)
    st.divider()
    include_chat = st.checkbox("Include chat in export", value=False)
    chat = (
        store.get_chat(h.subsession_id, h.cust_id) if include_chat else None
    )
    st.download_button(
        "Export debrief (markdown)",
        data=render_export_markdown(narrative, debrief_text, chat),
        file_name=f"{h.track_name.replace(' ', '-').lower()}-"
        f"{h.session_date[:10] or 'race'}-debrief.md",
        mime="text/markdown",
    )


def render_race_debrief_page():
    st.header("Race Debrief")
    st.markdown(
        "Upload a race IBT — the engineer reconstructs what happened and "
        "debriefs you on it."
    )
    store = RaceStore()

    narrative: RaceNarrative | None = st.session_state.get("race_narrative")

    tab_upload, tab_stored = st.tabs(["Analyze a race", "Past debriefs"])

    with tab_upload:
        uploaded = st.file_uploader("Race IBT file", type=["ibt"])
        source = None
        ibt_path = ""
        if uploaded is not None:
            source = uploaded.getvalue()
        elif TELEMETRY_DIR.exists():
            races = _scan_race_ibts(str(TELEMETRY_DIR))
            if races:
                choice = st.selectbox(
                    "...or pick from the host telemetry folder",
                    options=[None] + races,
                    format_func=lambda r: "—" if r is None else r["label"],
                )
                if choice:
                    source = Path(choice["path"])
                    ibt_path = choice["path"]

        if source is not None and st.button("Analyze race", type="primary"):
            try:
                with st.spinner("Reconstructing the race..."):
                    narrative = _analyze(source, ibt_path, store)
                st.session_state["race_narrative"] = narrative
            except RaceIngestError as exc:
                st.error(str(exc))

    with tab_stored:
        stored = store.list_races()
        if not stored:
            st.caption("No debriefed races yet.")
        for meta in stored:
            label = (
                f"{meta.session_date[:10]} — {meta.track_name} — "
                f"{meta.driver_name} — P{meta.finish_position} "
                f"({meta.irating_delta:+d} iR)"
            )
            if st.button(label, key=f"open-{meta.subsession_id}-{meta.cust_id}"):
                narrative = store.get_race(meta.subsession_id, meta.cust_id)
                st.session_state["race_narrative"] = narrative

    if narrative is None:
        return

    st.divider()
    h = narrative.header
    if not narrative.pace and not narrative.gaps:
        st.warning(
            "Official results were unavailable — this is a partial "
            "narrative from your telemetry only."
        )
    cols = st.columns(4)
    cols[0].metric("Finish", f"P{h.finish_position}", f"from P{h.start_position}")
    cols[1].metric("iRating", h.irating_new, f"{h.irating_new - h.irating_old:+d}")
    cols[2].metric("SoF", h.sof)
    cols[3].metric("Incidents", f"{h.incidents}x")

    st.plotly_chart(_position_chart(narrative), use_container_width=True)
    if narrative.gaps:
        st.plotly_chart(_gap_chart(narrative), use_container_width=True)

    st.markdown(render_narrative_markdown(narrative))
    st.divider()
    _render_debrief_and_chat(narrative, store)
```

- [ ] **Step 4: Wire navigation**

In `app/streamlit_app.py`, change the selectbox and dispatch:

```python
page = st.sidebar.selectbox(
    "Navigate",
    ["Race Debrief", "Scouting Report", "Lap Coaching"],
)
```

and add before the existing branches:

```python
if page == "Race Debrief":
    from app.pages.race_debrief import render_race_debrief_page

    render_race_debrief_page()
elif page == "Scouting Report":
```

(keep the existing `elif` chain intact).

- [ ] **Step 5: Full test suite + manual smoke**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: no failures.

Manual smoke: `streamlit run app/streamlit_app.py`, open Race Debrief, pick the Oulton race IBT from the folder scan, Analyze. Expect header metrics + position chart + narrative markdown (partial-narrative warning is acceptable if API creds are absent). Note anything broken and fix before committing.

- [ ] **Step 6: Commit**

```bash
git add app/pages/race_debrief.py app/streamlit_app.py .streamlit/config.toml .gitignore
git commit -m "feat: race debrief page — picker, charts, chat, export, nav"
```

---

### Task 11: Real-fixture recording, integration test, deployment docs

The verification gate: run the real Oulton race through the whole pipe, record API fixtures, add the integration test, document the Tailscale deployment.

**Files:**
- Create: `scripts/record_race_fixture.py`
- Create: `tests/fixtures/race/README.md`
- Modify: `tests/test_race_ingest.py` (integration additions)
- Modify: `README.md` (deployment section)

- [ ] **Step 1: Write the recording script**

Create `scripts/record_race_fixture.py`:

```python
"""Record real race fixtures for the integration tests.

Runs full ingestion (live Data API) on a race IBT, then copies the
IBT + cached API JSON into tests/fixtures/race/. Requires iRacing
credentials in .env.

Usage:
    .venv/Scripts/python.exe scripts/record_race_fixture.py <path-to-race.ibt>
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.pages.race_debrief import _make_api  # reuse env-cred construction
from core.race.ingest import DEFAULT_CACHE_DIR, ingest_race
from core.race.narrative import build_narrative

FIXTURE_DIR = Path("tests/fixtures/race")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    ibt_path = Path(sys.argv[1])
    api = _make_api()
    if api is None:
        print("ERROR: iRacing credentials missing from environment.")
        return 1

    try:
        data = ingest_race(ibt_path, api)
    finally:
        api.close()

    if not data.results:
        print("ERROR: API returned no results — fixture would be partial.")
        return 1

    narrative = build_narrative(data, corners=[])
    print(f"subsession {data.subsession_id}: "
          f"P{narrative.header.start_position} -> "
          f"P{narrative.header.finish_position}, "
          f"{len(narrative.incidents)} incident events, "
          f"{len(narrative.gaps)} rival gap series")

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ibt_path, FIXTURE_DIR / "race.ibt")
    cache_src = DEFAULT_CACHE_DIR / str(data.subsession_id)
    cache_dst = FIXTURE_DIR / "cache" / str(data.subsession_id)
    if cache_dst.exists():
        shutil.rmtree(cache_dst)
    shutil.copytree(cache_src, cache_dst)
    print(f"Fixtures written to {FIXTURE_DIR}/ — done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Record the fixtures (requires network + creds)**

Run:

```bash
.venv/Scripts/python.exe scripts/record_race_fixture.py "C:\Users\antho\Documents\iRacing\telemetry\mx5 mx52016_oulton international 2026-06-26 16-42-05.ibt"
```

Expected: a summary line with plausible positions, then `Fixtures written`. **If this fails on API field names** (e.g., `finish_position` is not zero-based, `lap_position` is named differently), fix `core/race/ingest.py` and the Task 8 fake payloads to match the real response — reality wins over the plan. Inspect the recorded JSON in `tests/fixtures/race/cache/` to confirm.

If the three Oulton IBTs differ (one per sim session segment), the right one is the one whose `session_type` is `Race` with the most laps — try `16-42-05` first, fall back to the others.

- [ ] **Step 3: Add the integration test**

Append to `tests/test_race_ingest.py`:

```python
# --- Integration: real Oulton fixtures (skip when absent) -------------------

FIXTURE_DIR = Path("tests/fixtures/race")
FIXTURE_IBT = FIXTURE_DIR / "race.ibt"
FIXTURE_CACHE = FIXTURE_DIR / "cache"

needs_fixture = pytest.mark.skipif(
    not FIXTURE_IBT.exists() or not FIXTURE_CACHE.exists(),
    reason="race fixtures not recorded (scripts/record_race_fixture.py)",
)


@needs_fixture
def test_ingest_real_race_from_cache_no_network():
    """Full ingestion served entirely from recorded cache (api=None ok
    for telemetry, but cache satisfies the API layer via a stub that
    must never be called)."""
    from core.race.ingest import ingest_race

    class _ExplodingAPI:
        def __getattr__(self, name):
            raise AssertionError(f"network call attempted: {name}")

        def close(self):
            pass

    # Cache dir contains {subsession_id}/... — ingest resolves inside it
    data = ingest_race(
        FIXTURE_IBT, _ExplodingAPI(), cache_dir=FIXTURE_CACHE
    )
    assert data.results, "results should come from the recorded cache"
    assert data.player_cust_id > 0
    assert data.driver_laps.get(data.player_cust_id)


@needs_fixture
def test_real_narrative_is_coherent():
    from core.race.ingest import ingest_race
    from core.race.narrative import build_narrative

    data = ingest_race(FIXTURE_IBT, None, cache_dir=FIXTURE_CACHE)
    # api=None -> ingest skips fetch; re-run WITH cache via stub instead:

    class _NeverCalled:
        def __getattr__(self, name):
            raise AssertionError("network call attempted")

        def close(self):
            pass

    data = ingest_race(FIXTURE_IBT, _NeverCalled(), cache_dir=FIXTURE_CACHE)
    narrative = build_narrative(data, corners=[])
    h = narrative.header
    assert 1 <= h.finish_position <= h.field_size
    assert narrative.position_timeline
    assert narrative.pace is not None
    assert narrative.attribution is not None
    # Round-trip through persistence layer format
    from core.race.models import RaceNarrative

    assert RaceNarrative.from_dict(narrative.to_dict()) == narrative
```

Note the wrinkle exposed here: `ingest_race` only consults the cache when `api is not None`. That's intended (no api and no cache = honest partial mode), and the `_ExplodingAPI` pattern proves cache-only operation. If during implementation you find the first `ingest_race(..., None, ...)` call above redundant, delete it — the second form is the real test.

- [ ] **Step 4: Run the integration tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_ingest.py -q`
Expected: PASS (integration tests run, not skipped, since Step 2 recorded fixtures).

Then the full suite: `.venv/Scripts/python.exe -m pytest -q` — no failures.

- [ ] **Step 5: Fixture README + deployment docs**

Create `tests/fixtures/race/README.md`:

```markdown
# Race fixtures (gitignored)

Real official-race fixtures for `tests/test_race_ingest.py` integration
tests. Recorded with:

    .venv/Scripts/python.exe scripts/record_race_fixture.py <race.ibt>

Contents: `race.ibt` (the race session IBT) and `cache/{subsession_id}/`
(recorded Data API JSON: results.json, lap_chart.json, lap_data_*.json).
Tests skip when these are absent. Current recording: MX-5 at Oulton
International, 2026-06-26, subsession 86748877.
```

Append to `README.md` (new section near the Quick Start):

```markdown
## Friend-testable deployment (Tailscale)

The app serves over Tailscale from the host PC — no re-platforming:

    # tailnet-only (testers need Tailscale):
    tailscale serve 8501

    # or public HTTPS URL (no Tailscale account needed):
    tailscale funnel 8501

    streamlit run app/streamlit_app.py

Notes:
- The URL is unlisted; that is the only access control. Add a shared
  passphrase before any wider beta.
- Testers upload their own race IBT files (up to 400 MB — see
  .streamlit/config.toml). Their races are keyed by (subsession, driver)
  and coexist in data/races.db.
- The host's iRacing credentials fetch results for any subsession;
  the host's ANTHROPIC_API_KEY powers all testers' debriefs (watch spend).
- The PC must be on for the URL to work.
```

- [ ] **Step 6: Commit**

```bash
git add scripts/record_race_fixture.py tests/test_race_ingest.py tests/fixtures/race/README.md README.md
git commit -m "feat: race fixture recording, real-data integration tests, deployment docs"
```

---

### Task 12: Founder validation + docs sync (manual gate, no code)

- [ ] **Step 1: Validate the Oulton narrative against memory**

Open the Race Debrief page, analyze the Oulton race, and read the deterministic narrative. The founder is ground truth for v1: do the position story, incidents (laps + corners), and pace ranking match what actually happened? Log any mis-attribution as a bug before trusting the AI layer with the data. Record findings in the session notes / follow-up issues.

- [ ] **Step 2: (When ANTHROPIC_API_KEY is rotated) generate the first real debrief**

Generate the debrief + ask 2-3 follow-up questions. Check the tone contract holds: no scolding, no invented facts, ≤3 takeaways, and "I don't have that data" appears when asked something outside the narrative (e.g., "what tire pressures was P5 running?").

- [ ] **Step 3: Update CLAUDE.md**

Update the Phase 3 checklist in CLAUDE.md: mark race ingestion, narrative, debrief page, chat, persistence, export as complete; note the new `core/race/` package in the architecture tree, the new `data/races.db`, the three new API endpoints, `parse_session_only`, and the deployment section. Follow the existing style (terse bullets under Implementation Notes).

- [ ] **Step 4: Commit docs**

```bash
git add CLAUDE.md
git commit -m "docs: Phase 3 Surface 1 (race debrief) shipped — status + implementation notes"
```

---

## Self-review notes (already applied)

- **Spec coverage:** ingestion (T8) + chunked API (T1) + cheap picker (T2) + models (T3) + narrative computations incl. attribution (T4/T5) + deterministic render (T6) + persistence with composite key (T7) + AI/tone/chat (T9) + page/nav/export/upload config (T10) + real fixtures/integration/deployment docs (T11) + founder validation gate (T12). Multi-class, hosted races, driver profile: out of scope per spec.
- **Reality-wins clauses:** API field-name assumptions are verified at T11 Step 2 with the real recording; the plan explicitly instructs fixing parsers + fakes to match reality.
- **Known simplification:** `build_stints` handles the common 0-1 pit-stop sprint correctly; multi-stop edge cases get refined when a real multi-stop race exists (watch item, not v1 blocker).
- **Type consistency check:** `RaceNarrative.to_dict`/`from_dict` used by store (T7), prompts (T9), and tests (T3/T11); `select_key_rivals` shared by narrative (T5) and ingest (T8); `_make_api` shared by page (T10) and recording script (T11).
