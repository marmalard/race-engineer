# Phase 4 Briefing v1 (Week Plan Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Race Briefing" page that places the driver's practice PB on this week's pace-vs-iRating curve for a chosen series, with field stats, format facts, race slots, and a minimal prep ledger — deterministic core, optional AI narrative + chat.

**Architecture:** New `core/briefing/` package mirroring `core/race/`: `models.py` (pure data), `curve.py` (pure math), `slots.py` (pure slot/window logic), `ingest.py` (Data API harvest + disk cache + tracks.db reads — the only I/O), `render.py` (deterministic markdown + exact-string verdicts). Page is display-only. Reuses `parse_results`/`_cached_fetch` from `core/race/ingest`, `build_readiness` from `core/profile/pace`, and the existing `Synthesizer` for the AI layer.

**Tech Stack:** Python 3.11+, dataclasses, pytest, Streamlit + Plotly, existing `LiveIRacingAPI` (merged phase4 plumbing), Anthropic SDK via existing Synthesizer.

**Spec:** `docs/superpowers/specs/2026-07-15-phase4-briefing-v1-design.md`

**Conventions for every task:** run tests with `.venv/Scripts/python.exe -m pytest -q <file>` from the repo root. NEVER edit files with PowerShell `Set-Content`/`-replace` (BOM corruption — repo rule); use the Edit/Write tools. Keep commit messages free of double quotes.

---

### Task 1: `RaceTimeDescriptor` — retain race slot times in the season schedule parser

The seasons payload's `schedules[].race_time_descriptors` is currently dropped by `parse_season_schedules`. Retain it so the briefing can compute upcoming slots.

**Files:**
- Modify: `core/benchmark/iracing_api.py` (dataclass near `RaceWeek` ~line 150; parser `parse_season_schedules` ~line 885)
- Test: `tests/test_iracing_api_phase4.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_iracing_api_phase4.py`:

```python
# ---------------------------------------------------------------------------
# RaceTimeDescriptor (briefing slots)
# ---------------------------------------------------------------------------

from core.benchmark.iracing_api import RaceTimeDescriptor


class TestRaceTimeDescriptors:
    def _season(self, descriptors):
        return {
            "seasons": [
                {
                    "series_id": 1,
                    "season_id": 10,
                    "season_name": "S",
                    "race_week": 0,
                    "max_weeks": 12,
                    "schedules": [
                        {
                            "series_name": "M2 Cup",
                            "race_week_num": 0,
                            "track": {"track_id": 9, "track_name": "Summit"},
                            "start_date": "2026-07-14",
                            "race_time_descriptors": descriptors,
                        }
                    ],
                }
            ]
        }

    def test_repeating_descriptor_parsed(self):
        payload = self._season(
            [
                {
                    "repeating": True,
                    "first_session_time": "00:15",
                    "repeat_minutes": 120,
                    "day_offset": [0, 1, 2, 3, 4, 5, 6],
                    "session_minutes": 27,
                }
            ]
        )
        week = parse_season_schedules(payload)[0].weeks[0]
        d = week.race_time_descriptors[0]
        assert d.repeating is True
        assert d.first_session_time == "00:15"
        assert d.repeat_minutes == 120
        assert d.day_offset == [0, 1, 2, 3, 4, 5, 6]
        assert d.session_times == []

    def test_explicit_session_times_parsed(self):
        payload = self._season(
            [
                {
                    "repeating": False,
                    "session_times": [
                        "2026-07-18T17:00:00Z",
                        "2026-07-18T21:00:00Z",
                    ],
                }
            ]
        )
        week = parse_season_schedules(payload)[0].weeks[0]
        d = week.race_time_descriptors[0]
        assert d.repeating is False
        assert d.session_times == [
            "2026-07-18T17:00:00Z",
            "2026-07-18T21:00:00Z",
        ]
        assert d.repeat_minutes is None

    def test_missing_descriptors_default_empty(self):
        payload = self._season(None)
        payload["seasons"][0]["schedules"][0].pop("race_time_descriptors")
        week = parse_season_schedules(payload)[0].weeks[0]
        assert week.race_time_descriptors == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_iracing_api_phase4.py -k RaceTimeDescriptors`
Expected: FAIL — `ImportError: cannot import name 'RaceTimeDescriptor'`

- [ ] **Step 3: Implement**

In `core/benchmark/iracing_api.py`, add ABOVE `class RaceWeek` (keep the existing `@dataclass` decorators pattern):

```python
@dataclass
class RaceTimeDescriptor:
    """When a week's races go off. Either repeating (cadence anchored at
    first_session_time GMT) or an explicit session_times list."""

    repeating: bool
    first_session_time: str | None  # "HH:MM" GMT when repeating
    repeat_minutes: int | None
    day_offset: list[int] = field(default_factory=list)
    session_times: list[str] = field(default_factory=list)  # ISO, non-repeating
```

Add to `RaceWeek` (after `max_pct_fuel_fill`):

```python
    race_time_descriptors: list["RaceTimeDescriptor"] = field(default_factory=list)
```

In `parse_season_schedules`, before `weeks.append(RaceWeek(`:

```python
            descriptors = []
            for d in sched.get("race_time_descriptors") or []:
                descriptors.append(RaceTimeDescriptor(
                    repeating=bool(d.get("repeating")),
                    first_session_time=d.get("first_session_time"),
                    repeat_minutes=d.get("repeat_minutes"),
                    day_offset=list(d.get("day_offset") or []),
                    session_times=list(d.get("session_times") or []),
                ))
```

and pass `race_time_descriptors=descriptors,` into the `RaceWeek(...)` call. Ensure `field` is imported from `dataclasses` at the top (it already is if `field(default_factory=...)` appears elsewhere; add if not).

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_iracing_api_phase4.py`
Expected: all pass (existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add core/benchmark/iracing_api.py tests/test_iracing_api_phase4.py
git commit -m "feat(api): retain race_time_descriptors on RaceWeek for briefing slots"
```

---

### Task 2: `core/briefing/models.py` — data models

Pure dataclasses; no logic, no I/O. Tested implicitly by every later task; one smoke test for defaults.

**Files:**
- Create: `core/briefing/__init__.py` (empty)
- Create: `core/briefing/models.py`
- Test: `tests/test_briefing_curve.py` (created here with the smoke test; Task 3 appends)

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_briefing_curve.py`:

```python
"""Tests for core/briefing: models smoke + pure curve math."""

from core.briefing.models import BriefingData, RaceFormat


def test_briefing_data_defaults():
    b = BriefingData(
        series_name="M2 Cup",
        season_id=10,
        race_week=2,
        fmt=RaceFormat(
            track_name="Summit Point Raceway",
            config_name="Summit Point Raceway",
            race_time_limit=12,
            race_lap_limit=None,
            standing_start=True,
            max_pct_fuel_fill=None,
        ),
    )
    assert b.curve is None and b.placement is None and b.prep is None
    assert b.slots == [] and b.warnings == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_curve.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.briefing'`

- [ ] **Step 3: Implement**

Create empty `core/briefing/__init__.py`. Create `core/briefing/models.py`:

```python
"""Briefing data models (pure data, no I/O).

BriefingData is the deterministic contract between ingest and render —
the same role RaceData/RaceNarrative play for the race debrief.
"""

from dataclasses import dataclass, field


@dataclass
class CurveBin:
    """One iRating bin of the field's pace curve."""

    ir_lo: int
    ir_hi: int
    median_lap_s: float
    n: int

    @property
    def ir_center(self) -> int:
        return (self.ir_lo + self.ir_hi) // 2


@dataclass
class PaceCurve:
    """Binned pace-vs-iRating curve for one series week."""

    bins: list[CurveBin]
    points: list[tuple[int, float]]  # raw (irating, best_lap_s) for the chart
    subsessions_used: int
    capped: bool  # True when HARVEST_CAP dropped older subsessions


@dataclass
class CurvePlacement:
    """The user's practice PB placed on the curve."""

    lap_s: float
    implied_ir_lo: int | None  # None when the curve is unusable
    implied_ir_hi: int | None
    delta_to_own_band_s: float | None  # lap - median at own iR (negative = faster)


@dataclass
class FieldStats:
    """SoF and field-size norms from the harvested week."""

    sof_p25: int
    sof_median: int
    sof_p75: int
    field_size_median: int
    splits_median: int  # splits per timeslot (session_id groups)


@dataclass
class ComboPrep:
    """Prep-ledger inputs from the user's own practice history."""

    car: str
    sessions: int
    representative_laps: int
    best_lap_s: float | None
    trend_s: float | None  # first-session best minus last (positive = improved)


@dataclass
class RaceSlot:
    start_utc: str  # ISO 8601
    fits_window: bool


@dataclass
class RaceFormat:
    track_name: str
    config_name: str
    race_time_limit: int | None  # minutes
    race_lap_limit: int | None
    standing_start: bool
    max_pct_fuel_fill: float | None


@dataclass
class BriefingData:
    series_name: str
    season_id: int
    race_week: int
    fmt: RaceFormat
    curve: PaceCurve | None = None
    placement: CurvePlacement | None = None
    field_stats: FieldStats | None = None
    prep: ComboPrep | None = None
    slots: list[RaceSlot] = field(default_factory=list)
    user_irating: int | None = None
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_curve.py`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add core/briefing/__init__.py core/briefing/models.py tests/test_briefing_curve.py
git commit -m "feat(briefing): data models - BriefingData contract"
```

---

### Task 3: `core/briefing/curve.py` — pure curve math

Binning, sparse-bin merging, monotone interpolation for implied iR, placement.

**Files:**
- Create: `core/briefing/curve.py`
- Test: `tests/test_briefing_curve.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_briefing_curve.py`:

```python
from core.briefing.curve import build_curve, place_on_curve

# Synthetic field: pace improves 0.5s per 250 iR from 90.0s @ 1000 iR.
# 6 points per bin so every bin clears MIN_BIN_N=5.
def _points():
    pts = []
    for i, ir_base in enumerate([1000, 1250, 1500, 1750]):
        lap = 90.0 - 0.5 * i
        for j in range(6):
            pts.append((ir_base + j * 10, lap + (j % 3) * 0.01))
    return pts


class TestBuildCurve:
    def test_bins_have_medians_and_counts(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        assert len(curve.bins) == 4
        assert curve.bins[0].n == 6
        assert abs(curve.bins[0].median_lap_s - 90.0) < 0.02
        assert curve.bins[-1].median_lap_s < curve.bins[0].median_lap_s

    def test_invalid_points_filtered(self):
        pts = _points() + [(0, 89.0), (1500, -1.0), (1500, 0.0)]
        curve = build_curve(pts, subsessions_used=10, capped=False)
        assert curve.points == _points()  # invalid rows dropped

    def test_sparse_bins_merge_into_neighbor(self):
        # 3 points at 2000+ (below MIN_BIN_N) merge into the last full bin
        pts = _points() + [(2100, 88.0), (2110, 88.0), (2120, 88.0)]
        curve = build_curve(pts, subsessions_used=10, capped=False)
        assert curve.bins[-1].n == 9  # 6 + 3 merged
        assert curve.bins[-1].ir_hi >= 2120

    def test_empty_and_tiny_input(self):
        assert build_curve([], subsessions_used=0, capped=False).bins == []
        tiny = build_curve([(1500, 90.0)] * 3, subsessions_used=1, capped=False)
        assert tiny.bins == [] or tiny.bins[0].n == 3  # merged single bin OK


class TestPlaceOnCurve:
    def test_faster_lap_implies_higher_irating(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        # 89.0s sits between the 1250 bin (89.5) and the 1500 bin (89.0)
        p = place_on_curve(curve, lap_s=89.0, user_ir=1200)
        assert p.implied_ir_lo is not None
        assert p.implied_ir_lo > 1200
        assert p.delta_to_own_band_s is not None
        assert p.delta_to_own_band_s < 0  # faster than own-band median

    def test_lap_faster_than_whole_field_clamps_to_top(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        p = place_on_curve(curve, lap_s=80.0, user_ir=1500)
        assert p.implied_ir_hi is not None
        assert p.implied_ir_hi >= curve.bins[-1].ir_center

    def test_unusable_curve_returns_none_fields(self):
        empty = build_curve([], subsessions_used=0, capped=False)
        p = place_on_curve(empty, lap_s=90.0, user_ir=1500)
        assert p.implied_ir_lo is None and p.delta_to_own_band_s is None

    def test_no_user_ir_still_gives_implied_band(self):
        curve = build_curve(_points(), subsessions_used=10, capped=False)
        p = place_on_curve(curve, lap_s=89.0, user_ir=None)
        assert p.implied_ir_lo is not None
        assert p.delta_to_own_band_s is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_curve.py`
Expected: FAIL — `ImportError: cannot import name 'build_curve'`

- [ ] **Step 3: Implement**

Create `core/briefing/curve.py`:

```python
"""PURE pace-vs-iRating curve math. No I/O, no API types.

Input points are (irating, best_lap_s) per driver per subsession.
Medians are made monotone (running min as iR rises) before implied-iR
interpolation so one slow bin cannot invert the mapping.
"""

from statistics import median

from core.briefing.models import CurveBin, CurvePlacement, PaceCurve

BIN_WIDTH = 250  # iRating per bin
MIN_BIN_N = 5  # bins thinner than this merge into their lower neighbor


def build_curve(
    points: list[tuple[int, float]],
    subsessions_used: int,
    capped: bool,
) -> PaceCurve:
    """Bin (iR, lap) points into BIN_WIDTH bins with >= MIN_BIN_N each."""
    clean = [(ir, lap) for ir, lap in points if ir > 0 and lap > 0]
    raw_bins: dict[int, list[float]] = {}
    for ir, lap in clean:
        raw_bins.setdefault(ir // BIN_WIDTH, []).append(lap)

    merged: list[tuple[int, int, list[float]]] = []  # (lo_key, hi_key, laps)
    for key in sorted(raw_bins):
        laps = raw_bins[key]
        if merged and len(merged[-1][2]) < MIN_BIN_N:
            lo, _, prev = merged[-1]
            merged[-1] = (lo, key, prev + laps)
        else:
            merged.append((key, key, laps))
    # A trailing sparse bin merges backward into its lower neighbor.
    if len(merged) >= 2 and len(merged[-1][2]) < MIN_BIN_N:
        lo, _, prev = merged[-2]
        _, hi, last = merged[-1]
        merged[-2] = (lo, hi, prev + last)
        merged.pop()

    bins = [
        CurveBin(
            ir_lo=lo * BIN_WIDTH,
            ir_hi=(hi + 1) * BIN_WIDTH - 1,
            median_lap_s=median(laps),
            n=len(laps),
        )
        for lo, hi, laps in merged
        if len(laps) >= MIN_BIN_N or len(merged) == 1
    ]
    return PaceCurve(
        bins=bins, points=clean, subsessions_used=subsessions_used, capped=capped
    )


def _monotone_medians(bins: list[CurveBin]) -> list[tuple[int, float]]:
    """(ir_center, median) with running-min medians as iR rises."""
    out: list[tuple[int, float]] = []
    lowest = float("inf")
    for b in bins:
        lowest = min(lowest, b.median_lap_s)
        out.append((b.ir_center, lowest))
    return out


def place_on_curve(
    curve: PaceCurve, lap_s: float, user_ir: int | None
) -> CurvePlacement:
    """Interpolate lap_s onto the monotone median curve -> implied-iR band."""
    if not curve.bins or lap_s <= 0:
        return CurvePlacement(
            lap_s=lap_s,
            implied_ir_lo=None,
            implied_ir_hi=None,
            delta_to_own_band_s=None,
        )
    pts = _monotone_medians(curve.bins)
    half = BIN_WIDTH // 2

    if lap_s <= pts[-1][1]:  # faster than the fastest bin median
        implied = pts[-1][0]
        implied_hi = implied + half
    elif lap_s >= pts[0][1]:  # slower than the slowest bin median
        implied = pts[0][0]
        implied_hi = implied + half
    else:
        implied = pts[0][0]
        for (ir_a, lap_a), (ir_b, lap_b) in zip(pts, pts[1:]):
            if lap_b <= lap_s <= lap_a:
                span = lap_a - lap_b
                frac = 0.0 if span <= 0 else (lap_a - lap_s) / span
                implied = int(ir_a + frac * (ir_b - ir_a))
                break
        implied_hi = implied + half

    delta = None
    if user_ir is not None:
        own = min(curve.bins, key=lambda b: abs(b.ir_center - user_ir))
        delta = lap_s - own.median_lap_s
    return CurvePlacement(
        lap_s=lap_s,
        implied_ir_lo=max(0, implied - half),
        implied_ir_hi=implied_hi,
        delta_to_own_band_s=delta,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_curve.py`
Expected: all pass. If `test_sparse_bins_merge_into_neighbor` fails on the merge direction, the trailing-sparse-bin block above is the code under test — debug there, don't weaken the test.

- [ ] **Step 5: Commit**

```bash
git add core/briefing/curve.py tests/test_briefing_curve.py
git commit -m "feat(briefing): pure pace-vs-iR curve - binning, monotone implied-iR placement"
```

---

### Task 4: `core/briefing/slots.py` — pure slot + window logic

**Files:**
- Create: `core/briefing/slots.py`
- Test: `tests/test_briefing_slots.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_briefing_slots.py`:

```python
"""Pure slot computation + usual-window inference."""

from datetime import datetime, timezone

from core.benchmark.iracing_api import RaceTimeDescriptor
from core.briefing.slots import infer_window, upcoming_slots

NOW = datetime(2026, 7, 15, 22, 30, tzinfo=timezone.utc)


class TestUpcomingSlots:
    def test_repeating_every_two_hours(self):
        d = RaceTimeDescriptor(
            repeating=True,
            first_session_time="00:15",
            repeat_minutes=120,
            day_offset=[0, 1, 2, 3, 4, 5, 6],
        )
        slots = upcoming_slots([d], NOW, count=3)
        assert [s.isoformat() for s in slots] == [
            "2026-07-16T00:15:00+00:00",
            "2026-07-16T02:15:00+00:00",
            "2026-07-16T04:15:00+00:00",
        ]

    def test_explicit_session_times_filters_past(self):
        d = RaceTimeDescriptor(
            repeating=False,
            first_session_time=None,
            repeat_minutes=None,
            session_times=[
                "2026-07-15T20:00:00Z",  # past
                "2026-07-16T01:00:00Z",
                "2026-07-16T05:00:00Z",
            ],
        )
        slots = upcoming_slots([d], NOW, count=4)
        assert len(slots) == 2
        assert slots[0].isoformat() == "2026-07-16T01:00:00+00:00"

    def test_malformed_descriptor_yields_no_slots(self):
        d = RaceTimeDescriptor(
            repeating=True,
            first_session_time=None,  # broken
            repeat_minutes=None,
        )
        assert upcoming_slots([d], NOW, count=3) == []


class TestInferWindow:
    def test_median_hour_pm_window(self):
        # watcher format: "YYYY-MM-DD HH-MM-SS"; user practices ~21:00
        dates = [
            "2026-07-01 20-45-00",
            "2026-07-03 21-10-00",
            "2026-07-08 21-30-00",
            "2026-07-10 22-05-00",
        ]
        window = infer_window(dates)
        assert window == (19, 23)  # median 21 +/- 2

    def test_too_few_sessions_returns_none(self):
        assert infer_window(["2026-07-01 20-45-00"]) is None

    def test_garbage_dates_skipped(self):
        dates = ["not-a-date"] * 3 + [
            "2026-07-01 20-00-00",
            "2026-07-02 20-30-00",
            "2026-07-03 21-00-00",
        ]
        assert infer_window(dates) == (18, 22)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_slots.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.briefing.slots'`

- [ ] **Step 3: Implement**

Create `core/briefing/slots.py`:

```python
"""PURE race-slot computation and usual-window inference. No I/O.

Slot semantics: repeating descriptors anchor at first_session_time GMT and
repeat every repeat_minutes; explicit descriptors list ISO session_times.
day_offset is intentionally ignored for the daily-repeating common case
(offsets are relative to the week start; every-day series pass [0..6]) —
a wrong-day slot for an exotic schedule is an acceptable v1 degradation.
"""

from datetime import datetime, timedelta, timezone
from statistics import median

from core.benchmark.iracing_api import RaceTimeDescriptor

WINDOW_HALF_HOURS = 2
WINDOW_MIN_SESSIONS = 3


def upcoming_slots(
    descriptors: list[RaceTimeDescriptor],
    now_utc: datetime,
    count: int = 4,
) -> list[datetime]:
    """Next `count` race start times strictly after now_utc, UTC."""
    slots: list[datetime] = []
    for d in descriptors:
        if d.repeating and d.first_session_time and d.repeat_minutes:
            try:
                hh, mm = d.first_session_time.split(":")[:2]
                anchor = now_utc.replace(
                    hour=int(hh), minute=int(mm), second=0, microsecond=0
                )
            except (ValueError, AttributeError):
                continue
            step = timedelta(minutes=d.repeat_minutes)
            t = anchor - timedelta(days=1)  # start safely in the past
            while t <= now_utc:
                t += step
            for _ in range(count):
                slots.append(t)
                t += step
        else:
            for iso in d.session_times:
                try:
                    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if t > now_utc:
                    slots.append(t)
    return sorted(set(slots))[:count]


def infer_window(session_dates: list[str]) -> tuple[int, int] | None:
    """Usual practice window (start_hour, end_hour) local, from watcher
    session_date strings ('YYYY-MM-DD HH-MM-SS'). None below 3 sessions."""
    hours: list[int] = []
    for s in session_dates:
        try:
            hours.append(int(s.split(" ")[1].split("-")[0]))
        except (IndexError, ValueError):
            continue
    if len(hours) < WINDOW_MIN_SESSIONS:
        return None
    mid = int(median(hours))
    return (max(0, mid - WINDOW_HALF_HOURS), min(23, mid + WINDOW_HALF_HOURS))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_slots.py`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add core/briefing/slots.py tests/test_briefing_slots.py
git commit -m "feat(briefing): pure slot computation + usual-window inference"
```

---

### Task 5: `core/briefing/ingest.py` part 1 — series ranking (pure)

**Files:**
- Create: `core/briefing/ingest.py`
- Test: `tests/test_briefing_ingest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_briefing_ingest.py`:

```python
"""Briefing ingest: series ranking (pure) + harvest/build with fakes."""

from core.benchmark.iracing_api import RaceWeek, SeasonSchedule
from core.briefing.ingest import SeriesCandidate, rank_series_candidates
from core.track.track_db import SessionRow


def _season(season_id, series, week_num, track_id, track_name):
    return SeasonSchedule(
        series_id=season_id,
        series_name=series,
        season_id=season_id,
        season_name=f"{series} S3",
        race_week=week_num,
        max_weeks=12,
        weeks=[
            RaceWeek(
                race_week_num=week_num,
                track_id=track_id,
                track_name=track_name,
                config_name="",
                start_date="2026-07-14",
                race_time_limit=12,
                race_lap_limit=None,
                start_type="Standing",
                standing_start=True,
                max_pct_fuel_fill=None,
            )
        ],
    )


def _row(session_id, track_id, car, laps=10):
    return SessionRow(
        session_id=session_id,
        track_id=track_id,
        track_name="",
        car=car,
        session_type="Practice",
        session_date="2026-07-01 21-00-00",
        best_lap_time=90.0,
        lap_count=laps,
    )


class TestRankSeriesCandidates:
    def test_most_practiced_track_ranks_first(self):
        seasons = [
            _season(100, "M2 Cup", 2, 9, "Summit Point Raceway"),
            _season(200, "PCup", 2, 523, "Spa"),
        ]
        sessions = [
            _row("a", "9", "BMW M2"), _row("b", "9", "BMW M2"),
            _row("c", "9", "BMW M2"), _row("d", "523", "992 Cup"),
        ]
        ranked = rank_series_candidates(seasons, sessions)
        assert ranked[0].series_name == "M2 Cup"
        assert ranked[0].practice_sessions == 3
        assert ranked[1].practice_sessions == 1

    def test_unpracticed_series_still_listed(self):
        seasons = [_season(300, "FF1600", 4, 439, "Winton")]
        ranked = rank_series_candidates(seasons, [])
        assert ranked[0].practice_sessions == 0

    def test_current_week_missing_from_schedule_skipped(self):
        s = _season(400, "Odd", 9, 18, "Road America")
        s.weeks[0].race_week_num = 3  # schedule has no week 9 entry
        assert rank_series_candidates([s], []) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_ingest.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.briefing.ingest'`

- [ ] **Step 3: Implement**

Create `core/briefing/ingest.py` (part 1 — Task 6 appends the harvest):

```python
"""Briefing ingestion: Data API harvest + disk cache + tracks.db reads.

The only I/O module in core/briefing (mirrors core/race/ingest.py's role).
Raw subsession results are cached to data/briefing_cache/{season}/{week}/;
cached files double as recorded test fixtures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.benchmark.iracing_api import SeasonSchedule
from core.track.track_db import SessionRow

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/briefing_cache")
HARVEST_CAP = 30  # newest subsessions fetched per series-week


@dataclass
class SeriesCandidate:
    """One pickable series for the current week, ranked by practice depth."""

    season_id: int
    series_name: str
    season_name: str
    race_week: int
    track_id: int
    track_name: str
    practice_sessions: int


def rank_series_candidates(
    seasons: list[SeasonSchedule],
    sessions: list[SessionRow],
) -> list[SeriesCandidate]:
    """Rank this week's series by the user's practice depth at each track.

    tracks.db track_id is TEXT; RaceWeek.track_id is int — compared as str.
    Seasons whose current race_week has no schedule entry are skipped.
    """
    by_track: dict[str, int] = {}
    for s in sessions:
        if s.session_type != "Race":
            by_track[s.track_id] = by_track.get(s.track_id, 0) + 1

    out: list[SeriesCandidate] = []
    for season in seasons:
        week = next(
            (w for w in season.weeks if w.race_week_num == season.race_week),
            None,
        )
        if week is None:
            continue
        out.append(SeriesCandidate(
            season_id=season.season_id,
            series_name=season.series_name,
            season_name=season.season_name,
            race_week=season.race_week,
            track_id=week.track_id,
            track_name=week.track_name,
            practice_sessions=by_track.get(str(week.track_id), 0),
        ))
    out.sort(key=lambda c: (-c.practice_sessions, c.series_name))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_ingest.py`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add core/briefing/ingest.py tests/test_briefing_ingest.py
git commit -m "feat(briefing): series candidate ranking by practice depth"
```

---

### Task 6: `core/briefing/ingest.py` part 2 — field harvest + `build_briefing`

**Files:**
- Modify: `core/briefing/ingest.py`
- Test: `tests/test_briefing_ingest.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_briefing_ingest.py`:

```python
import json
from dataclasses import dataclass

from core.benchmark.iracing_api import RaceTimeDescriptor, SeriesResultRow
from core.briefing.ingest import build_briefing, harvest_field


def _series_row(subsession_id, session_id, sof, drivers, start="2026-07-15T01:15:00Z"):
    return SeriesResultRow(
        subsession_id=subsession_id, session_id=session_id, start_time=start,
        end_time=start, strength_of_field=sof, num_drivers=drivers,
        track_id=9, track_name="Summit Point Raceway",
        event_best_lap_time=82.0, event_average_lap=83.0,
        num_cautions=0, num_lead_changes=0, winner_name="", winner_cust_id=0,
        season_id=100, series_id=100, race_week_num=2, official_session=True,
    )


def _results_payload(laps_by_ir):
    """Minimal subsession-results payload parse_results understands."""
    return {
        "session_results": [{
            "simsession_number": 0,
            "results": [
                {
                    "cust_id": i, "display_name": f"D{i}",
                    "finish_position": i, "starting_position": i,
                    "laps_complete": 10, "incidents": 0,
                    "oldi_rating": ir, "newi_rating": ir,
                    "best_lap_time": int(lap * 10000),
                }
                for i, (ir, lap) in enumerate(laps_by_ir)
            ],
        }]
    }


class FakeAPI:
    def __init__(self, rows, payloads):
        self.rows = rows
        self.payloads = payloads  # subsession_id -> payload
        self.results_calls = []

    def search_series_results(self, **kwargs):
        return self.rows

    def get_subsession_results(self, subsession_id):
        self.results_calls.append(subsession_id)
        return self.payloads[subsession_id]


class TestHarvestField:
    def test_points_and_field_stats(self, tmp_path):
        rows = [
            _series_row(1, 500, sof=1400, drivers=14),
            _series_row(2, 500, sof=1100, drivers=12),
            _series_row(3, 501, sof=1450, drivers=15),
        ]
        payloads = {
            1: _results_payload([(1400, 82.0)] * 6),
            2: _results_payload([(1100, 83.0)] * 6),
            3: _results_payload([(1450, 82.1)] * 6),
        }
        api = FakeAPI(rows, payloads)
        curve, stats = harvest_field(api, 100, 2, cache_dir=tmp_path)
        assert len(curve.points) == 18
        assert curve.subsessions_used == 3
        assert curve.capped is False
        assert stats.sof_median == 1400
        assert stats.field_size_median == 14
        assert stats.splits_median == 1  # session 500 has 2, 501 has 1 -> median 1.5 -> int 1

    def test_cache_hit_skips_api(self, tmp_path):
        rows = [_series_row(1, 500, sof=1400, drivers=14)]
        payloads = {1: _results_payload([(1400, 82.0)] * 6)}
        api = FakeAPI(rows, payloads)
        harvest_field(api, 100, 2, cache_dir=tmp_path)
        api2 = FakeAPI(rows, {})  # would KeyError on API hit
        harvest_field(api2, 100, 2, cache_dir=tmp_path)
        assert api2.results_calls == []

    def test_empty_week_returns_empty_curve(self, tmp_path):
        api = FakeAPI([], {})
        curve, stats = harvest_field(api, 100, 2, cache_dir=tmp_path)
        assert curve.points == [] and stats is None


class TestBuildBriefing:
    def test_full_assembly(self, tmp_path):
        from core.benchmark.iracing_api import RaceWeek, SeasonSchedule

        season = SeasonSchedule(
            series_id=100, series_name="M2 Cup", season_id=100,
            season_name="M2 Cup S3", race_week=2, max_weeks=12,
            weeks=[RaceWeek(
                race_week_num=2, track_id=9,
                track_name="Summit Point Raceway", config_name="",
                start_date="2026-07-14", race_time_limit=12,
                race_lap_limit=None, start_type="Standing",
                standing_start=True, max_pct_fuel_fill=None,
                race_time_descriptors=[RaceTimeDescriptor(
                    repeating=True, first_session_time="00:15",
                    repeat_minutes=120, day_offset=[0, 1, 2, 3, 4, 5, 6],
                )],
            )],
        )
        rows = [_series_row(1, 500, sof=1400, drivers=14)]
        payloads = {1: _results_payload(
            [(1200 + 50 * i, 83.0 - 0.05 * i) for i in range(12)]
        )}
        api = FakeAPI(rows, payloads)
        sessions = [SessionRow(
            session_id=f"s{i}", track_id="9", track_name="Summit",
            car="BMW M2 CS Racing", session_type="Practice",
            session_date=f"2026-07-0{i + 1} 21-00-00",
            best_lap_time=82.2 + 0.1 * i, lap_count=12,
        ) for i in range(3)]
        laps = {f"s{i}": [] for i in range(3)}

        data = build_briefing(
            api=api, season=season, sessions=sessions, laps=laps,
            car="BMW M2 CS Racing", user_irating=1300,
            now_utc=__import__("datetime").datetime(
                2026, 7, 15, 22, 0,
                tzinfo=__import__("datetime").timezone.utc,
            ),
            cache_dir=tmp_path,
        )
        assert data.series_name == "M2 Cup"
        assert data.fmt.race_time_limit == 12
        assert data.curve is not None and data.placement is not None
        assert data.prep is not None and data.prep.sessions == 3
        assert len(data.slots) > 0
        assert data.user_irating == 1300

    def test_api_failure_degrades_with_warning(self, tmp_path):
        from core.benchmark.iracing_api import RaceWeek, SeasonSchedule

        class ExplodingAPI:
            def search_series_results(self, **kwargs):
                raise RuntimeError("api down")

        season = SeasonSchedule(
            series_id=100, series_name="M2 Cup", season_id=100,
            season_name="M2 Cup S3", race_week=2, max_weeks=12,
            weeks=[RaceWeek(
                race_week_num=2, track_id=9,
                track_name="Summit Point Raceway", config_name="",
                start_date="2026-07-14", race_time_limit=12,
                race_lap_limit=None, start_type="Standing",
                standing_start=True, max_pct_fuel_fill=None,
            )],
        )
        data = build_briefing(
            api=ExplodingAPI(), season=season, sessions=[], laps={},
            car="BMW M2 CS Racing", user_irating=None,
            now_utc=__import__("datetime").datetime(
                2026, 7, 15, tzinfo=__import__("datetime").timezone.utc
            ),
            cache_dir=tmp_path,
        )
        assert data.curve is None
        assert any("field data" in w for w in data.warnings)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_ingest.py`
Expected: FAIL — `ImportError: cannot import name 'harvest_field'`

- [ ] **Step 3: Implement**

Append to `core/briefing/ingest.py`:

```python
from statistics import median as _median

from core.briefing.curve import build_curve, place_on_curve
from core.briefing.models import (
    BriefingData,
    ComboPrep,
    FieldStats,
    PaceCurve,
    RaceFormat,
    RaceSlot,
)
from core.briefing.slots import infer_window, upcoming_slots
from core.profile.pace import build_readiness
from core.race.ingest import _cached_fetch, parse_results
from core.track.track_db import LapRow


def harvest_field(
    api,
    season_id: int,
    race_week: int,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> tuple[PaceCurve, FieldStats | None]:
    """Fetch the week's subsessions -> (iR, best_lap) points + field norms.

    The search call is never disk-cached (the week is still growing);
    per-subsession results are cached forever (results are immutable).
    """
    rows = api.search_series_results(
        season_id=season_id, race_week_num=race_week
    )
    rows = sorted(rows, key=lambda r: r.start_time)
    capped = len(rows) > HARVEST_CAP
    if capped:
        logger.info(
            "Harvest capped: %d of %d subsessions used", HARVEST_CAP, len(rows)
        )
    used = rows[-HARVEST_CAP:]

    points: list[tuple[int, float]] = []
    week_dir = cache_dir / str(season_id) / str(race_week)
    for row in used:
        payload = _cached_fetch(
            week_dir / f"{row.subsession_id}.json",
            lambda row=row: api.get_subsession_results(row.subsession_id),
        )
        if not payload:
            continue
        for r in parse_results(payload):
            if r.oldi_rating > 0 and r.best_lap_time > 0:
                points.append((r.oldi_rating, r.best_lap_time))

    curve = build_curve(points, subsessions_used=len(used), capped=capped)
    if not used:
        return curve, None
    sofs = sorted(r.strength_of_field for r in used)
    splits: dict[int, int] = {}
    for r in used:
        splits[r.session_id] = splits.get(r.session_id, 0) + 1
    stats = FieldStats(
        sof_p25=sofs[len(sofs) // 4],
        sof_median=int(_median(sofs)),
        sof_p75=sofs[(3 * len(sofs)) // 4],
        field_size_median=int(_median(sorted(r.num_drivers for r in used))),
        splits_median=int(_median(sorted(splits.values()))),
    )
    return curve, stats


def build_briefing(
    api,
    season: SeasonSchedule,
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
    car: str,
    user_irating: int | None,
    now_utc: datetime,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> BriefingData:
    """Assemble the full deterministic briefing. Never raises: every
    failure downgrades to a warning + missing section (spec degradation
    ladder)."""
    week = next(
        (w for w in season.weeks if w.race_week_num == season.race_week),
        None,
    )
    if week is None:
        raise ValueError(
            f"season {season.season_id} has no schedule for week "
            f"{season.race_week}"
        )
    data = BriefingData(
        series_name=season.series_name,
        season_id=season.season_id,
        race_week=season.race_week,
        fmt=RaceFormat(
            track_name=week.track_name,
            config_name=week.config_name,
            race_time_limit=week.race_time_limit,
            race_lap_limit=week.race_lap_limit,
            standing_start=week.standing_start,
            max_pct_fuel_fill=week.max_pct_fuel_fill,
        ),
        user_irating=user_irating,
    )

    try:
        data.curve, data.field_stats = harvest_field(
            api, season.season_id, season.race_week, cache_dir
        )
    except Exception:
        logger.warning("Field harvest failed", exc_info=True)
        data.warnings.append(
            "Couldn't fetch this week's field data — briefing is "
            "format-and-history only."
        )

    # Prep ledger + placement from the user's own practice at this combo.
    combo = next(
        (
            c
            for c in build_readiness(sessions, laps)
            if c.track_id == str(week.track_id) and c.car == car
        ),
        None,
    )
    if combo is not None:
        data.prep = ComboPrep(
            car=car,
            sessions=combo.sessions,
            representative_laps=combo.valid_laps,
            best_lap_s=combo.best_lap,
            trend_s=combo.pb_trend_s,
        )
        if data.curve is not None and combo.best_lap is not None:
            data.placement = place_on_curve(
                data.curve, combo.best_lap, user_irating
            )

    window = infer_window([s.session_date for s in sessions])
    for slot in upcoming_slots(
        week.race_time_descriptors, now_utc, count=4
    ):
        local_hour = slot.astimezone().hour
        fits = window is not None and window[0] <= local_hour <= window[1]
        data.slots.append(
            RaceSlot(start_utc=slot.isoformat(), fits_window=fits)
        )
    return data
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_ingest.py`
Expected: all pass. The `splits_median` assertion documents Python's `int(1.5) == 1` truncation — that is the intended contract.

- [ ] **Step 5: Commit**

```bash
git add core/briefing/ingest.py tests/test_briefing_ingest.py
git commit -m "feat(briefing): field harvest with immutable-results cache + build_briefing assembly"
```

---

### Task 7: `core/briefing/render.py` — deterministic markdown + exact-string verdicts

**Files:**
- Create: `core/briefing/render.py`
- Test: `tests/test_briefing_render.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_briefing_render.py`:

```python
"""Exact-string verdict tests (nudges/profile precedent) + markdown shape."""

from core.briefing.models import (
    BriefingData,
    ComboPrep,
    CurvePlacement,
    FieldStats,
    RaceFormat,
    RaceSlot,
)
from core.briefing.render import render_briefing, verdict_line


def _fmt():
    return RaceFormat(
        track_name="Summit Point Raceway", config_name="",
        race_time_limit=12, race_lap_limit=None,
        standing_start=True, max_pct_fuel_fill=None,
    )


class TestVerdictLine:
    def test_over_curve(self):
        p = CurvePlacement(
            lap_s=82.18, implied_ir_lo=1400, implied_ir_hi=1650,
            delta_to_own_band_s=-0.15,
        )
        assert verdict_line(p, user_ir=1300) == (
            "Your 1:22.180 runs like a 1,400-1,650 iR driver in this "
            "series this week - your pace is worth more iRating than you "
            "have. Racing is how you collect it."
        )

    def test_under_curve(self):
        p = CurvePlacement(
            lap_s=83.40, implied_ir_lo=1000, implied_ir_hi=1250,
            delta_to_own_band_s=0.42,
        )
        assert verdict_line(p, user_ir=1400) == (
            "The median at your rating runs 0.4s quicker this week - "
            "mid-pack is a strong result here, and practice has a clear "
            "target."
        )

    def test_on_curve(self):
        p = CurvePlacement(
            lap_s=82.5, implied_ir_lo=1300, implied_ir_hi=1550,
            delta_to_own_band_s=0.03,
        )
        assert verdict_line(p, user_ir=1400) == (
            "You're right on the pace for your rating - a clean race "
            "converts it to a solid finish."
        )

    def test_no_placement_invites(self):
        assert verdict_line(None, user_ir=1400) == (
            "Run a practice session at this combo and I'll place you on "
            "this week's curve."
        )

    def test_no_user_ir_reports_band_only(self):
        p = CurvePlacement(
            lap_s=82.18, implied_ir_lo=1400, implied_ir_hi=1650,
            delta_to_own_band_s=None,
        )
        assert verdict_line(p, user_ir=None) == (
            "Your 1:22.180 runs like a 1,400-1,650 iR driver in this "
            "series this week."
        )


class TestRenderBriefing:
    def test_full_render_contains_sections(self):
        data = BriefingData(
            series_name="M2 Cup", season_id=100, race_week=2, fmt=_fmt(),
            placement=CurvePlacement(
                lap_s=82.18, implied_ir_lo=1400, implied_ir_hi=1650,
                delta_to_own_band_s=-0.15,
            ),
            field_stats=FieldStats(
                sof_p25=1200, sof_median=1400, sof_p75=1600,
                field_size_median=14, splits_median=1,
            ),
            prep=ComboPrep(
                car="BMW M2 CS Racing", sessions=3,
                representative_laps=28, best_lap_s=82.18, trend_s=0.4,
            ),
            slots=[RaceSlot(start_utc="2026-07-16T00:15:00+00:00",
                            fits_window=True)],
            user_irating=1300,
        )
        md = render_briefing(data)
        assert "# Race Briefing - M2 Cup" in md
        assert "Summit Point Raceway" in md
        assert "12 minutes" in md
        assert "standing start" in md
        assert "SoF ~1,400 (typ. 1,200-1,600)" in md
        assert "worth more iRating" in md
        assert "28 representative laps" in md
        assert "fits your usual window" in md

    def test_warning_and_empty_sections_render(self):
        data = BriefingData(
            series_name="M2 Cup", season_id=100, race_week=2, fmt=_fmt(),
            warnings=["Couldn't fetch this week's field data - briefing "
                      "is format-and-history only."],
        )
        md = render_briefing(data)
        assert "Couldn't fetch" in md
        assert "Run a practice session" in md  # invitation verdict
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_render.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.briefing.render'`

- [ ] **Step 3: Implement**

Create `core/briefing/render.py`:

```python
"""PURE deterministic BriefingData -> markdown. Owns ALL verdict wording
(profile/render.py precedent: exact strings live here and are pinned by
exact-string tests). HARD RULE (v3 addendum section 1): the verdict never
gates - no wording may tell the driver not to race."""

from core.briefing.models import BriefingData, CurvePlacement

ON_CURVE_BAND_S = 0.15  # |delta| under this = "on the pace"

INVITE_LINE = (
    "Run a practice session at this combo and I'll place you on this "
    "week's curve."
)


def _fmt_lap(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m}:{seconds - 60 * m:06.3f}"


def verdict_line(placement: CurvePlacement | None, user_ir: int | None) -> str:
    """The curve verdict - race-positive in both directions, never a gate."""
    if placement is None or placement.implied_ir_lo is None:
        return INVITE_LINE
    band = (
        f"{placement.implied_ir_lo:,}-{placement.implied_ir_hi:,} iR"
    )
    if user_ir is None or placement.delta_to_own_band_s is None:
        return (
            f"Your {_fmt_lap(placement.lap_s)} runs like a {band} driver "
            "in this series this week."
        )
    delta = placement.delta_to_own_band_s
    if delta < -ON_CURVE_BAND_S:
        return (
            f"Your {_fmt_lap(placement.lap_s)} runs like a {band} driver "
            "in this series this week - your pace is worth more iRating "
            "than you have. Racing is how you collect it."
        )
    if delta > ON_CURVE_BAND_S:
        return (
            f"The median at your rating runs {delta:.1f}s quicker this "
            "week - mid-pack is a strong result here, and practice has "
            "a clear target."
        )
    return (
        "You're right on the pace for your rating - a clean race "
        "converts it to a solid finish."
    )


def render_briefing(data: BriefingData) -> str:
    """Assemble the week-plan-ordered deterministic briefing."""
    fmt = data.fmt
    lines: list[str] = [f"# Race Briefing - {data.series_name}", ""]
    for w in data.warnings:
        lines += [f"> {w}", ""]

    track = fmt.track_name + (f" ({fmt.config_name})" if fmt.config_name else "")
    lines += [f"## This week: {track}", ""]
    cost = (
        f"{fmt.race_time_limit} minutes"
        if fmt.race_time_limit
        else f"{fmt.race_lap_limit} laps" if fmt.race_lap_limit else "length n/a"
    )
    start = "standing start" if fmt.standing_start else "rolling start"
    fuel = (
        f", fuel capped at {fmt.max_pct_fuel_fill:.0f}%"
        if fmt.max_pct_fuel_fill
        else ""
    )
    lines += [f"This race costs you **{cost}** - {start}{fuel}.", ""]

    lines += ["## Where you stand", ""]
    lines += [verdict_line(data.placement, data.user_irating), ""]
    if data.field_stats is not None:
        s = data.field_stats
        lines += [
            f"Field this week: SoF ~{s.sof_median:,} "
            f"(typ. {s.sof_p25:,}-{s.sof_p75:,}), "
            f"~{s.field_size_median} cars per split, "
            f"{s.splits_median} split(s) per slot.",
            "",
        ]
    if data.curve is not None and data.curve.capped:
        lines += [
            f"(Curve built from the most recent "
            f"{data.curve.subsessions_used} races this week.)",
            "",
        ]
    if data.placement is not None and data.prep is not None:
        lines += [
            "*Field laps are race laps; yours is a practice best - "
            "clean air flatters slightly.*",
            "",
        ]

    if data.prep is not None:
        p = data.prep
        lines += ["## Your preparation", ""]
        trend = (
            f", session best down {p.trend_s:.1f}s since your first visit"
            if p.trend_s is not None and p.trend_s > 0
            else ""
        )
        best = f" - best {_fmt_lap(p.best_lap_s)}" if p.best_lap_s else ""
        lines += [
            f"{p.sessions} practice sessions, {p.representative_laps} "
            f"representative laps in the {p.car}{best}{trend}.",
            "",
        ]

    if data.slots:
        lines += ["## When to run it", ""]
        for slot in data.slots:
            tag = " - fits your usual window" if slot.fits_window else ""
            lines += [f"- {slot.start_utc}{tag}"]
        lines += [""]
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_render.py`
Expected: all pass. Exact strings are the contract — if an assertion fails, fix the code to match the test, not vice versa (unless the wording itself is being deliberately changed, which requires updating BOTH).

- [ ] **Step 5: Commit**

```bash
git add core/briefing/render.py tests/test_briefing_render.py
git commit -m "feat(briefing): deterministic render + never-gates curve verdict (exact-string pinned)"
```

---

### Task 8: AI layer — briefing prompts + Synthesizer methods

**Files:**
- Create: `core/coaching/prompts/briefing.py`
- Modify: `core/coaching/synthesizer.py` (append two methods after `race_debrief_chat`)
- Test: `tests/test_briefing_prompts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_briefing_prompts.py`:

```python
"""Prompt builders are pure - test content assembly, not the API."""

from core.coaching.prompts.briefing import (
    BRIEFING_SYSTEM_PROMPT,
    build_briefing_chat_system,
    build_briefing_prompt,
)


def test_system_prompt_carries_tone_contract():
    assert "never" in BRIEFING_SYSTEM_PROMPT.lower()
    assert "not to race" in BRIEFING_SYSTEM_PROMPT.lower()


def test_build_briefing_prompt_embeds_json_and_profile():
    prompt = build_briefing_prompt('{"series_name": "M2 Cup"}', "PROFILE_BLOCK")
    assert '{"series_name": "M2 Cup"}' in prompt
    assert "PROFILE_BLOCK" in prompt


def test_build_briefing_prompt_without_profile():
    prompt = build_briefing_prompt('{"a": 1}', "")
    assert "PROFILE" not in prompt


def test_chat_system_grounds_in_briefing_and_narrative():
    sys = build_briefing_chat_system('{"a": 1}', "The narrative text")
    assert '{"a": 1}' in sys
    assert "The narrative text" in sys
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_prompts.py`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `core/coaching/prompts/briefing.py`:

```python
"""Prompt templates for the AI race-briefing narrative + chat."""

BRIEFING_SYSTEM_PROMPT = """You are a personal race engineer delivering a \
pre-race briefing to your driver. You are opinionated, specific, and on \
their side. Rules:
1. Ground every claim in the briefing JSON. Never invent pace numbers, \
SoF figures, or field facts.
2. NEVER tell the driver not to race, and never imply they are not \
ready. Under-curve pace is framed as expectation-setting plus a clear \
practice target - racing is always worth it.
3. Confidence comes from evidence: cite their preparation (sessions, \
laps, trend) back to them.
4. Include a short decision matrix - two or three pre-made in-race \
decisions (start goes badly, early contact ahead, fading pace late).
5. Keep it under 300 words. Radio discipline: an engineer who mostly \
shuts up is a feature.
6. Driver-profile facts (when provided) are cross-race tendencies - \
cite them as such, never as facts about this race."""


def build_briefing_prompt(briefing_json: str, profile_block: str = "") -> str:
    parts = [
        "Deliver the pre-race briefing for this data:",
        "",
        "--- BRIEFING DATA (JSON) ---",
        briefing_json,
    ]
    if profile_block:
        parts += ["", "--- DRIVER PROFILE (cross-race tendencies) ---",
                  profile_block]
    return "\n".join(parts)


def build_briefing_chat_system(briefing_json: str, narrative: str) -> str:
    return (
        BRIEFING_SYSTEM_PROMPT
        + "\n\nYou already delivered this briefing:\n\n"
        + narrative
        + "\n\nThe underlying data:\n\n"
        + briefing_json
        + "\n\nAnswer follow-up questions grounded in that data only."
    )
```

Append to `core/coaching/synthesizer.py` (inside the `Synthesizer` class, after `race_debrief_chat`; add the import at the top of the file with the other prompt imports):

```python
from core.coaching.prompts.briefing import (
    BRIEFING_SYSTEM_PROMPT,
    build_briefing_chat_system,
    build_briefing_prompt,
)
```

```python
    def generate_briefing_narrative(
        self, briefing_json: str, profile_block: str = ""
    ) -> str:
        """AI pre-race briefing from the deterministic BriefingData JSON."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=800,
            system=BRIEFING_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": build_briefing_prompt(briefing_json, profile_block),
            }],
        )
        return self._extract_text(response)

    def briefing_chat(
        self,
        briefing_json: str,
        narrative: str,
        history: list[dict],
    ) -> str:
        """One follow-up chat turn grounded in the briefing (ephemeral -
        v1 does not persist briefing chat)."""
        msgs = history[-self.MAX_CHAT_HISTORY:]
        if msgs and msgs[0]["role"] != "user":
            msgs = msgs[1:]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=600,
            system=build_briefing_chat_system(briefing_json, narrative),
            messages=msgs,
        )
        return self._extract_text(response)
```

Note: `MAX_CHAT_HISTORY` already exists on the class (used by `race_debrief_chat`). If the class constant is module-level instead, match whatever `race_debrief_chat` uses.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_prompts.py tests/test_synthesizer.py`
Expected: all pass (existing synthesizer tests must not break)

- [ ] **Step 5: Commit**

```bash
git add core/coaching/prompts/briefing.py core/coaching/synthesizer.py tests/test_briefing_prompts.py
git commit -m "feat(briefing): AI narrative + ephemeral chat - tone contract forbids gating"
```

---

### Task 9: Briefing page + navigation registration

**Files:**
- Create: `app/pages/briefing.py`
- Modify: `app/streamlit_app.py` (PAGES dict + dispatch)
- Modify: `.gitignore` (add `data/briefing_cache/`)
- Test: `tests/test_briefing_page_helpers.py`

- [ ] **Step 1: Write the failing test (pure helper only — pages have no business logic)**

Create `tests/test_briefing_page_helpers.py`:

```python
"""The page's one pure helper: candidate labels for the selectbox."""

from core.briefing.ingest import SeriesCandidate
from app.pages.briefing import candidate_label


def test_label_shows_practice_depth():
    c = SeriesCandidate(
        season_id=1, series_name="M2 Cup", season_name="M2 Cup S3",
        race_week=2, track_id=9, track_name="Summit Point Raceway",
        practice_sessions=3,
    )
    assert candidate_label(c) == (
        "M2 Cup - Summit Point Raceway (3 practice sessions)"
    )


def test_label_unpracticed():
    c = SeriesCandidate(
        season_id=1, series_name="FF1600", season_name="FF S3",
        race_week=4, track_id=439, track_name="Winton",
        practice_sessions=0,
    )
    assert candidate_label(c) == "FF1600 - Winton (new track for you)"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_page_helpers.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pages.briefing'`

- [ ] **Step 3: Implement the page**

> **Correction applied during execution:** the code below gates all rendering behind `if not st.button(...): return`, which breaks the AI-narrative button and chat (any rerun collapses the page). The implemented page uses race_debrief.py's data-presence guard instead: the Build button only writes session state; rendering is gated on `briefing_data` presence. See commit history.

Create `app/pages/briefing.py`:

```python
"""Race Briefing page (week-plan slice 1). Display only - all logic in
core/briefing. Spinner phases per the UX-review finding (no bare spinners)."""

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from core.benchmark.iracing_api import LiveIRacingAPI
from core.briefing.ingest import (
    SeriesCandidate,
    build_briefing,
    rank_series_candidates,
)
from core.briefing.render import render_briefing
from core.track.track_db import TrackDB

DB_PATH = Path("data/tracks.db")


def candidate_label(c: SeriesCandidate) -> str:
    depth = (
        f"{c.practice_sessions} practice sessions"
        if c.practice_sessions
        else "new track for you"
    )
    return f"{c.series_name} - {c.track_name} ({depth})"


def _get_api() -> LiveIRacingAPI | None:
    cid = os.environ.get("IRACING_CLIENT_ID")
    secret = os.environ.get("IRACING_CLIENT_SECRET")
    user = os.environ.get("IRACING_USERNAME")
    pw = os.environ.get("IRACING_PASSWORD")
    if not all([cid, secret, user, pw]):
        return None
    return LiveIRacingAPI(
        client_id=cid, client_secret=secret, username=user, password=pw
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _load_seasons_cached():
    api = _get_api()
    if api is None:
        return []
    try:
        return api.get_series_seasons()
    finally:
        api.close()


def render_briefing_page() -> None:
    st.title("Race Briefing")
    st.caption(
        "Where your pace sits in this week's field - and when to run "
        "the race."
    )

    api_probe = _get_api()
    if api_probe is None:
        st.warning(
            "The briefing needs iRacing Data API credentials "
            "(IRACING_CLIENT_ID / SECRET / USERNAME / PASSWORD in .env). "
            "Unlike the debrief, it can't work from an upload."
        )
        return
    api_probe.close()

    with st.spinner("Loading this week's series calendar..."):
        seasons = _load_seasons_cached()
    if not seasons:
        st.error("Couldn't load the season calendar - check credentials.")
        return

    db = TrackDB(DB_PATH)
    sessions = db.list_session_history()
    candidates = rank_series_candidates(seasons, sessions)
    if not candidates:
        st.error("No series with a current-week schedule found.")
        return

    pick = st.selectbox(
        "Series", candidates, format_func=candidate_label, index=0
    )
    season = next(s for s in seasons if s.season_id == pick.season_id)

    cars_at_track = sorted(
        {
            s.car
            for s in sessions
            if s.track_id == str(pick.track_id) and s.session_type != "Race"
        }
    )
    car = (
        st.selectbox("Your car", cars_at_track)
        if cars_at_track
        else st.text_input(
            "Your car (no practice history at this track yet)", ""
        )
    )

    user_ir = st.number_input(
        "Your iRating (sport)", min_value=0, max_value=12000,
        value=st.session_state.get("briefing_ir", 1350), step=25,
    )
    st.session_state["briefing_ir"] = user_ir

    if not st.button("Build briefing", type="primary"):
        return

    cache_key = (pick.season_id, pick.race_week, car, user_ir)
    if st.session_state.get("briefing_key") != cache_key:
        laps = {}
        with st.spinner("Reading your practice history..."):
            for s in sessions:
                laps[s.session_id] = db.get_session_laps(s.session_id)
        api = _get_api()
        try:
            with st.spinner(
                "Fetching this week's races (first build for a series "
                "takes ~30s; cached after)..."
            ):
                data = build_briefing(
                    api=api, season=season, sessions=sessions, laps=laps,
                    car=car, user_irating=user_ir or None,
                    now_utc=datetime.now(timezone.utc),
                )
        finally:
            api.close()
        st.session_state["briefing_key"] = cache_key
        st.session_state["briefing_data"] = data
        st.session_state.pop("briefing_narrative", None)
        st.session_state.pop("briefing_chat", None)

    data = st.session_state["briefing_data"]

    if data.curve is not None and data.curve.points:
        irs = [p[0] for p in data.curve.points]
        lapss = [p[1] for p in data.curve.points]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=irs, y=lapss, mode="markers", name="Field",
            marker=dict(size=5, opacity=0.45),
        ))
        fig.add_trace(go.Scatter(
            x=[b.ir_center for b in data.curve.bins],
            y=[b.median_lap_s for b in data.curve.bins],
            mode="lines+markers", name="Median",
        ))
        if data.placement is not None:
            fig.add_hline(
                y=data.placement.lap_s, line_dash="dash",
                annotation_text="You (practice best)",
            )
        if data.user_irating:
            fig.add_vline(
                x=data.user_irating, line_dash="dot",
                annotation_text=f"Your iR {data.user_irating:,}",
            )
        fig.update_layout(
            xaxis_title="Driver iRating",
            yaxis_title="Best race lap (s)",
            height=420, showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown(render_briefing(data))

    # --- optional AI layer (mirrors the debrief page pattern) ---
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return
    from core.coaching.synthesizer import Synthesizer

    briefing_json = json.dumps(asdict(data), default=str)
    if st.button("Engineer's briefing (AI)"):
        synth = Synthesizer(api_key=os.environ["ANTHROPIC_API_KEY"])
        with st.spinner("Your engineer is preparing the briefing..."):
            st.session_state["briefing_narrative"] = (
                synth.generate_briefing_narrative(briefing_json)
            )
    narrative = st.session_state.get("briefing_narrative")
    if narrative:
        st.markdown(narrative)
        st.divider()
        history = st.session_state.setdefault("briefing_chat", [])
        for m in history:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        if q := st.chat_input("Ask your engineer about this race..."):
            history.append({"role": "user", "content": q})
            synth = Synthesizer(api_key=os.environ["ANTHROPIC_API_KEY"])
            with st.spinner("..."):
                reply = synth.briefing_chat(briefing_json, narrative, history)
            history.append({"role": "assistant", "content": reply})
            st.rerun()
```

In `app/streamlit_app.py`, add to `PAGES` after the Race Debrief entry:

```python
    "\U0001f4cb Race Briefing": "briefing",
```

and add the dispatch branch (before the `guide` branch):

```python
elif page == "briefing":
    from app.pages.briefing import render_briefing_page

    render_briefing_page()
```

Append to `.gitignore`:

```
data/briefing_cache/
```

- [ ] **Step 4: Run tests + import smoke**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_briefing_page_helpers.py`
Expected: 2 passed

Run: `.venv/Scripts/python.exe -c "import app.pages.briefing"` from the repo root.
Expected: no output (import clean). If Streamlit complains about `set_page_config`, that's a page-import side effect — the page module must NOT call any `st.` function at import time (only inside `render_briefing_page`).

- [ ] **Step 5: Commit**

```bash
git add app/pages/briefing.py app/streamlit_app.py .gitignore tests/test_briefing_page_helpers.py
git commit -m "feat(briefing): Race Briefing page - curve chart, deterministic briefing, optional AI layer"
```

---

### Task 10: Fixture recorder script

**Files:**
- Create: `scripts/record_briefing_fixture.py`

No test (I/O script by repo convention — same as `scripts/record_race_fixture.py`).

- [ ] **Step 1: Implement**

Create `scripts/record_briefing_fixture.py`:

```python
"""Record a real briefing harvest as test fixtures.

Usage: .venv/Scripts/python.exe scripts/record_briefing_fixture.py <season_id> <race_week>

Runs harvest_field against the live Data API with the briefing cache
pointed at tests/fixtures/briefing/ - the cached subsession JSONs ARE the
fixtures (race-fixture precedent; gitignored except README).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

from dotenv import load_dotenv

load_dotenv()

from core.benchmark.iracing_api import LiveIRacingAPI
from core.briefing.ingest import harvest_field

FIXTURE_DIR = Path("tests/fixtures/briefing")


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(1)
    season_id, race_week = int(sys.argv[1]), int(sys.argv[2])
    api = LiveIRacingAPI(
        client_id=os.environ["IRACING_CLIENT_ID"],
        client_secret=os.environ["IRACING_CLIENT_SECRET"],
        username=os.environ["IRACING_USERNAME"],
        password=os.environ["IRACING_PASSWORD"],
    )
    try:
        curve, stats = harvest_field(
            api, season_id, race_week, cache_dir=FIXTURE_DIR
        )
    finally:
        api.close()
    print(f"Recorded {curve.subsessions_used} subsessions, "
          f"{len(curve.points)} pace points -> {FIXTURE_DIR}")
    if stats:
        print(f"SoF median {stats.sof_median}, "
              f"field ~{stats.field_size_median}")


if __name__ == "__main__":
    main()
```

Create `tests/fixtures/briefing/README.md`:

```markdown
# Briefing fixtures

Recorded from the live Data API with
`scripts/record_briefing_fixture.py <season_id> <race_week>`.
JSON files are gitignored (results contain other drivers' names);
re-record freely - subsession results are immutable.
```

Ensure `.gitignore` covers the JSONs — append:

```
tests/fixtures/briefing/**/*.json
```

- [ ] **Step 2: Verify script parses**

Run: `.venv/Scripts/python.exe -c "import scripts.record_briefing_fixture" 2>&1 || .venv/Scripts/python.exe scripts/record_briefing_fixture.py`
Expected: usage text + exit 1 (no args)

- [ ] **Step 3: Commit**

```bash
git add scripts/record_briefing_fixture.py tests/fixtures/briefing/README.md .gitignore
git commit -m "feat(briefing): fixture recorder - cached harvest doubles as fixtures"
```

---

### Task 11: Full suite + docs

**Files:**
- Modify: `CLAUDE.md` (Phase 4 section)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (642 baseline + ~25 new), same skip count as baseline. Fix any cross-module breakage before proceeding — do NOT skip failing tests.

- [ ] **Step 2: Update CLAUDE.md**

In the `**Phase 4 (revised): Pre-Race Briefing / Field Scouting**` section, replace the unchecked list with:

```markdown
**Phase 4 (revised): Pre-Race Briefing / Field Scouting** (v1 shipped 2026-07, branch phase4-briefing-v1 — spec docs/superpowers/specs/2026-07-15-phase4-briefing-v1-design.md, strategy docs/race-engineer-v3-confidence-arc.md)
- [x] core/briefing/ package: models (BriefingData contract), curve (pure pace-vs-iR binning + monotone implied-iR placement, BIN_WIDTH 250 / MIN_BIN_N 5), slots (repeating + explicit descriptors, usual-window inference from watcher session_date), ingest (search_series harvest, HARVEST_CAP 30, per-subsession results cached to data/briefing_cache — search NEVER cached, the week is still growing), render (week-plan-ordered markdown; verdict exact-string pinned; NEVER gates — "you're not ready" is a sentence the product does not say)
- [x] RaceWeek.race_time_descriptors retained by parse_season_schedules (was dropped)
- [x] Race Briefing page: series picker ranked by practice depth at the week's track, car picker from user history, curve chart (field scatter + median line + you), optional AI narrative + ephemeral chat (BRIEFING_SYSTEM_PROMPT tone contract)
- [x] Reuses parse_results/_cached_fetch (race ingest) + build_readiness (profile) — no duplicated parsing
- [ ] Grid briefing v1.5: reg_drivers roster + opponent cards (plumbing merged, unwired)
- [ ] Field analysis extensions: SoF/split prediction per timeslot, opponent profiles
- [ ] Series calendar awareness → proactive briefings (week-plan push layer)
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: Phase 4 briefing v1 shipped - CLAUDE.md status"
```

---

### Task 12: Founder smoke test (manual, with the real API)

- [ ] **Step 1:** Start the app (`Race Engineer` desktop shortcut or `streamlit run app/streamlit_app.py`), open **Race Briefing**.
- [ ] **Step 2:** Confirm the series picker leads with the most-practiced current-week track; pick a real series (M2 Cup if scheduled), build the briefing.
- [ ] **Step 3:** Verify against ground truth: curve shape sane vs Series Insights for the same series/week; SoF band plausible; slot times match the iRacing UI; verdict wording race-positive.
- [ ] **Step 4:** Record fixtures for the harvested week: `.venv/Scripts/python.exe scripts/record_briefing_fixture.py <season_id> <week>`.
- [ ] **Step 5:** Note tuning observations (BIN_WIDTH, HARVEST_CAP, window ±2h) in the session notes — constants live in `core/briefing/curve.py`, `ingest.py`, `slots.py`.

---

## Self-Review (completed at write time)

- **Spec coverage:** D1 (pre-reg only — no live-session code anywhere), D2 (page order = week plan), D3 (curve centerpiece, Task 3/7/9), D4 (deterministic core Tasks 2–7; AI optional Task 8), D5 (format facts Task 7; decision matrix in prompt Task 8), D6 (no opponent code), D7 (separate page Task 9), D8 (ComboPrep Tasks 6–7), D9 (no SR code), series-agnostic picker (Tasks 5/9), slots+window (Tasks 1/4/6), degradation ladder (no-creds Task 9, API-failure Task 6, thin-week Task 7 capped note, empty-uncached via reused `_cached_fetch`, no-practice invite Task 7, no-key Task 9 early return), caching (Task 6 + recorder Task 10), testing strategy (pure-function tests throughout, fixtures Task 10).
- **Placeholder scan:** clean — every code step has complete code.
- **Type consistency:** `FieldStats.splits_median`/`field_size_median` names consistent across Tasks 2/6/7; `SeriesCandidate` fields consistent across 5/9; `RaceTimeDescriptor` consistent across 1/4/6; `render_briefing_page` name matches the streamlit_app dispatch.
