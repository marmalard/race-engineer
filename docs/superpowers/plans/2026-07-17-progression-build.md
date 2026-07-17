# Progression Build Implementation Plan (spec §6–8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Progression page (race streak, per-combo pace trend, PB timeline, iR/SR chart, technique trends, pace-implied iR), the pace-implied-iR compute + weekly snapshot store, and the prescription seed table — spec §6–8 of `docs/superpowers/specs/2026-07-17-progression-loss-region-persistence-design.md`.

**Architecture:** New `core/progression/` package mirroring `core/briefing/` (pure math modules + one I/O ingest module + one small SQLite store on `data/progression.db`), a `core/profile/prescriptions.py` literal table, and one display-only Streamlit page registered in NAV_SPEC (Practice group). Everything reuses existing machinery: `build_curve`/`place_on_curve`/`harvest_field`/`rank_series_candidates` (briefing), `build_readiness` (profile), `fault_kinds_from_diagnosis` via the technique adapter (one fault ranking, now four consumers), `get_member_chart_data` (already in the API client), `_cached_fetch` (race ingest).

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), Plotly, Streamlit, pytest. No new dependencies. **No AI calls anywhere in this build.**

**Locked rules (from spec §10 + curve rules):**
- Implied iR is ALWAYS a band, never a point. Placement math stays raw (never smoothed). NEVER gating language — progression informs, never permits.
- Technique trend classification MUST go through `core.profile.technique._diagnosis_from_row` + `fault_kinds_from_diagnosis` — no threshold re-implementation (coupling test required).
- Watcher/live-coach write paths untouched. No new writes to tracks.db / races.db / reference_laps.db.

**Verification command:** `.venv/Scripts/python.exe -m pytest -q` (run from repo root; full suite must stay green — 957 tests on master as of 2026-07-17).

**Worktree note:** The production app hot-reloads the main checkout — execute this plan in a fresh worktree (e.g. `C:\Users\antho\Documents\Coding\race-engineer-progression`), branch `progression-build`, per superpowers:using-git-worktrees. Two stale locked worktree dirs (`race-engineer-exit-verdict`, `race-engineer-loss-persistence`) exist — ignore them, pick a fresh dir name.

---

### Task 1: Race-week streak math (`core/progression/streak.py`)

**Files:**
- Create: `core/progression/__init__.py` (empty)
- Create: `core/progression/models.py`
- Create: `core/progression/streak.py`
- Test: `tests/test_progression_streak.py`

**Context:** iRacing race weeks flip on Tuesday. Race timestamps come from `RaceStore.list_races()` → `RaceMeta.session_date` (API `start_time`, ISO like `"2026-07-12T18:04:00Z"` — **empty string for partial captures**) with `RaceMeta.created_at` (`datetime.now(timezone.utc).isoformat()`) as fallback.

**Streak definition (locked here):** bucket races by week start (most recent Tuesday). `races_this_week` = count in the current week. `streak_weeks` = consecutive weeks with ≥1 race counting backward from the current week; if the current week has zero races, count backward from the previous week instead (the week in progress never breaks a streak). `total_races` = all captured races, including ones with unparseable dates.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_progression_streak.py
"""Race-week streak math — iRacing weeks flip on Tuesday."""

from datetime import date

from core.progression.models import StreakSummary
from core.progression.streak import build_streak, iracing_week_start, parse_race_date


class TestWeekStart:
    def test_tuesday_maps_to_itself(self):
        assert iracing_week_start(date(2026, 7, 14)) == date(2026, 7, 14)  # a Tuesday

    def test_monday_maps_to_previous_tuesday(self):
        assert iracing_week_start(date(2026, 7, 13)) == date(2026, 7, 7)

    def test_wednesday_maps_back_one_day(self):
        assert iracing_week_start(date(2026, 7, 15)) == date(2026, 7, 14)


class TestParseRaceDate:
    def test_iso_with_z(self):
        assert parse_race_date("2026-07-12T18:04:00Z", "") == date(2026, 7, 12)

    def test_empty_falls_back_to_created_at(self):
        assert parse_race_date("", "2026-07-13T09:00:00+00:00") == date(2026, 7, 13)

    def test_both_unparseable_returns_none(self):
        assert parse_race_date("", "garbage") is None


class TestBuildStreak:
    # today = Fri 2026-07-17; current week starts Tue 2026-07-14
    TODAY = date(2026, 7, 17)

    def test_empty_is_zeroes(self):
        s = build_streak([], self.TODAY)
        assert s == StreakSummary(races_this_week=0, streak_weeks=0, total_races=0)

    def test_current_and_previous_week_streak_of_two(self):
        races = [
            ("2026-07-16T01:00:00Z", ""),   # this week
            ("2026-07-08T01:00:00Z", ""),   # last week (Tue 7/7 window)
        ]
        s = build_streak(races, self.TODAY)
        assert s.races_this_week == 1
        assert s.streak_weeks == 2
        assert s.total_races == 2

    def test_empty_current_week_does_not_break_streak(self):
        races = [("2026-07-08T01:00:00Z", ""), ("2026-07-01T01:00:00Z", "")]
        s = build_streak(races, self.TODAY)
        assert s.races_this_week == 0
        assert s.streak_weeks == 2  # counted from last week backward

    def test_gap_week_breaks_streak(self):
        races = [("2026-07-16T01:00:00Z", ""), ("2026-07-01T01:00:00Z", "")]
        s = build_streak(races, self.TODAY)
        assert s.streak_weeks == 1  # 7/7 week empty -> streak is current week only

    def test_unparseable_dates_count_in_total_only(self):
        races = [("", ""), ("2026-07-16T01:00:00Z", "")]
        s = build_streak(races, self.TODAY)
        assert s.total_races == 2
        assert s.races_this_week == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_streak.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.progression'`

- [ ] **Step 3: Implement**

```python
# core/progression/__init__.py
```
(empty file)

```python
# core/progression/models.py
"""Dataclasses for the progression layer (Strava layer, v3 §5)."""

from dataclasses import dataclass

IMPLIED_IR_MAX_SERIES = 3  # bound the weekly harvest cost (30 fetches/series)


@dataclass
class StreakSummary:
    """Official-race volume — the product's leading metric as the user's own stat."""

    races_this_week: int = 0
    streak_weeks: int = 0
    total_races: int = 0


@dataclass
class ComboImplied:
    """One combo's placement on this week's field curve."""

    track_id: str
    track_name: str
    car: str
    series_name: str        # the series whose curve was used (honesty label)
    lap_s: float            # the practice PB placed on the curve
    implied_lo: int
    implied_hi: int
    weight: float           # representative-lap count (more practice = more signal)


@dataclass
class DriverImpliedIR:
    """Weighted roll-up of per-combo bands. ALWAYS a band, never a point."""

    lo: int
    hi: int
    combo_count: int
```

```python
# core/progression/streak.py
"""PURE race-week streak math. iRacing weeks flip on Tuesday."""

from datetime import date, datetime, timedelta

from core.progression.models import StreakSummary


def iracing_week_start(d: date) -> date:
    """Most recent Tuesday on or before d (Tuesday = weekday 1)."""
    return d - timedelta(days=(d.weekday() - 1) % 7)


def parse_race_date(session_date: str, created_at: str) -> date | None:
    """Race date from the API start_time; capture time as fallback.

    Partial captures store an empty session_date — created_at (always set)
    keeps them in the streak. Unparseable rows return None and count only
    toward the total.
    """
    for raw in (session_date, created_at):
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            continue
    return None


def build_streak(races: list[tuple[str, str]], today: date) -> StreakSummary:
    """races = (session_date, created_at) per captured race.

    streak_weeks counts consecutive weeks with >= 1 race backward from the
    current week; an empty current week never breaks the streak (it is
    still in progress) — counting starts from the previous week instead.
    """
    weeks: set[date] = set()
    for session_date, created_at in races:
        d = parse_race_date(session_date, created_at)
        if d is not None:
            weeks.add(iracing_week_start(d))

    current = iracing_week_start(today)
    races_this_week = sum(
        1 for sd, ca in races
        if (d := parse_race_date(sd, ca)) is not None
        and iracing_week_start(d) == current
    )

    cursor = current if current in weeks else current - timedelta(days=7)
    streak = 0
    while cursor in weeks:
        streak += 1
        cursor -= timedelta(days=7)

    return StreakSummary(
        races_this_week=races_this_week,
        streak_weeks=streak,
        total_races=len(races),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_streak.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/progression tests/test_progression_streak.py
git commit -m "feat(progression): race-week streak math (Tuesday flip, partial-capture fallback)"
```

---

### Task 2: Trend series builders (`core/progression/trends.py`)

**Files:**
- Create: `core/progression/trends.py`
- Test: `tests/test_progression_trends.py`

**Context:** Three pure builders the page will chart. `fault_trend_series` MUST classify through the technique adapter (`core.profile.technique._diagnosis_from_row` + `core.live.nudges.fault_kinds_from_diagnosis`) — the coupling test compares against a direct call, so any threshold re-implementation fails.

Inputs (existing types, do not modify):
- `SessionRow` (`core/track/track_db.py:21`): session_id, track_id, track_name, car, session_type, session_date (`"YYYY-MM-DD HH-MM-SS"`, lexicographically sortable), best_lap_time (may be None), lap_count, ibt_file_path.
- `DiagnosisRow` (`core/track/track_db.py:56`): the 23-field joined row.
- `ReferenceLapMeta` (`core/benchmark/reference_store.py:26`): ref_id, track_id, car, source (`'g61' | 'personal_best'`), lap_time, driver_name, imported_at (ISO).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_progression_trends.py
"""Pure trend-series builders for the Progression page."""

from core.benchmark.reference_store import ReferenceLapMeta
from core.live.nudges import fault_kinds_from_diagnosis
from core.profile.technique import _diagnosis_from_row
from core.progression.trends import combo_pace_series, fault_trend_series, pb_timeline
from core.track.track_db import DiagnosisRow, SessionRow


def _session(sid, track_id, car, stype, sdate, best):
    return SessionRow(
        session_id=sid, track_id=track_id, track_name=f"Track {track_id}",
        car=car, session_type=stype, session_date=sdate,
        best_lap_time=best, lap_count=10,
    )


def _diag_row(sid, sdate, label="Turn 1", braking=-15.0, time_lost=0.8):
    """A row whose braking delta is far past the live nudge threshold."""
    return DiagnosisRow(
        session_id=sid, track_id="525", track_name="Spa", car="M2",
        session_type="Practice", session_date=sdate, region_rank=1,
        label=label, distance_start_m=100.0, distance_end_m=300.0,
        time_lost_s=time_lost, braking_delta_m=braking,
        min_speed_delta_ms=0.0, throttle_delta_m=None,
        brake_release_delta_m=None, exit_speed_delta_ms=0.0,
        driver_min_speed_ms=40.0, reference_min_speed_ms=40.0,
        driver_lap_number=3, driver_lap_time=160.0,
        reference_source="personal_best", reference_lap_time=158.0,
        total_time_delta_s=2.0,
    )


class TestComboPaceSeries:
    def test_groups_by_combo_sorted_by_date(self):
        sessions = [
            _session("b", "525", "M2", "Practice", "2026-07-02 10-00-00", 160.0),
            _session("a", "525", "M2", "Practice", "2026-07-01 10-00-00", 161.5),
            _session("c", "18", "F4", "Practice", "2026-07-03 10-00-00", 130.0),
        ]
        series = combo_pace_series(sessions)
        assert series[("525", "M2")] == [
            ("2026-07-01 10-00-00", 161.5), ("2026-07-02 10-00-00", 160.0)]
        assert series[("18", "F4")] == [("2026-07-03 10-00-00", 130.0)]

    def test_race_sessions_and_missing_best_excluded(self):
        sessions = [
            _session("r", "525", "M2", "Race", "2026-07-01 10-00-00", 159.0),
            _session("n", "525", "M2", "Practice", "2026-07-02 10-00-00", None),
        ]
        assert combo_pace_series(sessions) == {}


class TestFaultTrendSeries:
    def test_classification_matches_live_ladder(self):
        """COUPLING: the series must contain exactly the kinds the live
        fault ladder produces for the same row — no re-implementation."""
        row = _diag_row("s1", "2026-07-01 10-00-00")
        expected = {k.value for k in fault_kinds_from_diagnosis(_diagnosis_from_row(row))}
        series = fault_trend_series([row])
        assert set(series.keys()) == expected
        assert "braking" in series  # sanity: -15m is far past any brake threshold

    def test_per_session_time_lost_summed_and_date_sorted(self):
        rows = [
            _diag_row("s2", "2026-07-02 10-00-00", time_lost=0.5),
            _diag_row("s1", "2026-07-01 10-00-00", time_lost=0.8),
            _diag_row("s1", "2026-07-01 10-00-00", label="Turn 5", time_lost=0.3),
        ]
        series = fault_trend_series(rows)
        assert series["braking"] == [
            ("2026-07-01 10-00-00", 1.1), ("2026-07-02 10-00-00", 0.5)]

    def test_empty_rows_empty_series(self):
        assert fault_trend_series([]) == {}


class TestPbTimeline:
    def test_personal_best_only_sorted_by_imported_at(self):
        metas = [
            ReferenceLapMeta(1, "525", "M2", "g61", 159.1, "Borsuk", "2026-06-01T00:00:00"),
            ReferenceLapMeta(2, "525", "M2", "personal_best", 161.3, None, "2026-07-02T00:00:00"),
            ReferenceLapMeta(3, "18", "F4", "personal_best", 130.2, None, "2026-07-01T00:00:00"),
        ]
        out = pb_timeline(metas)
        assert [m.ref_id for m in out] == [3, 2]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_trends.py -q`
Expected: FAIL — `ImportError: cannot import name 'combo_pace_series'`

- [ ] **Step 3: Implement**

```python
# core/progression/trends.py
"""PURE trend-series builders for the Progression page.

Fault classification goes through the technique adapter and the live
FaultKind ladder — one ranking function, four consumers (cue, verdict,
profile tendencies, progression trends). Never re-implement thresholds.
"""

from collections import defaultdict

from core.benchmark.reference_store import ReferenceLapMeta
from core.live.nudges import fault_kinds_from_diagnosis
from core.profile.technique import _diagnosis_from_row
from core.track.track_db import DiagnosisRow, SessionRow


def combo_pace_series(
    sessions: list[SessionRow],
) -> dict[tuple[str, str], list[tuple[str, float]]]:
    """(track_id, car) -> [(session_date, session_best_s)] date-ascending.

    Race sessions are excluded (traffic/fuel pace is not practice pace),
    as are sessions with no recorded best lap.
    """
    series: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for s in sessions:
        if s.session_type == "Race" or s.best_lap_time is None:
            continue
        series[(s.track_id, s.car)].append((s.session_date, s.best_lap_time))
    return {k: sorted(v) for k, v in series.items()}


def fault_trend_series(
    rows: list[DiagnosisRow],
) -> dict[str, list[tuple[str, float]]]:
    """FaultKind.value -> [(session_date, summed time_lost_s)] date-ascending.

    Per session, time_lost of every region where the fault crossed its
    live threshold is summed — 'how much did this habit cost per outing'.
    """
    per_kind: dict[str, dict[tuple[str, str], float]] = defaultdict(
        lambda: defaultdict(float)
    )
    for r in rows:
        for kind in fault_kinds_from_diagnosis(_diagnosis_from_row(r)):
            per_kind[kind.value][(r.session_date, r.session_id)] += r.time_lost_s
    return {
        k: [(d, round(t, 6)) for (d, _sid), t in sorted(buckets.items())]
        for k, buckets in per_kind.items()
    }


def pb_timeline(metas: list[ReferenceLapMeta]) -> list[ReferenceLapMeta]:
    """personal_best references only, oldest first by imported_at."""
    return sorted(
        (m for m in metas if m.source == "personal_best"),
        key=lambda m: m.imported_at,
    )
```

Note: `fault_trend_series` keys per-session buckets by `(session_date, session_id)` so two sessions sharing a date string can't merge; the emitted tuple keeps only the date (chart x-axis). If the coupling test's `set(series.keys())` differs from expected, the bug is in THIS module — never adjust the expectation.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_trends.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/progression/trends.py tests/test_progression_trends.py
git commit -m "feat(progression): pace/fault/PB trend series (fault ladder coupling-tested)"
```

---

### Task 3: Implied-iR aggregation (`core/progression/implied_ir.py`)

**Files:**
- Create: `core/progression/implied_ir.py`
- Test: `tests/test_progression_implied_ir.py`

**Context:** Pure roll-up of per-combo `ComboImplied` bands into one `DriverImpliedIR`. Spec §7: weighted mean of band midpoints, weighted by representative-lap count; presented as a band ± the mean bin half-width. With the current curve code every band is `BIN_WIDTH/2 = 125` wide (hi − center), but compute the mean half-width from the rows anyway — the curve module owns that constant.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_progression_implied_ir.py
"""Weighted roll-up of per-combo implied-iR bands."""

from core.progression.implied_ir import aggregate_implied_ir
from core.progression.models import ComboImplied, DriverImpliedIR


def _combo(lo, hi, weight, car="M2"):
    return ComboImplied(
        track_id="525", track_name="Spa", car=car, series_name="S",
        lap_s=160.0, implied_lo=lo, implied_hi=hi, weight=weight,
    )


class TestAggregate:
    def test_empty_returns_none(self):
        assert aggregate_implied_ir([]) is None

    def test_single_combo_passes_through(self):
        out = aggregate_implied_ir([_combo(1400, 1650, 10.0)])
        assert out == DriverImpliedIR(lo=1400, hi=1650, combo_count=1)

    def test_weighted_mean_of_midpoints(self):
        # midpoints 1525 (w=30) and 1275 (w=10) -> 1462.5; half-width 125
        out = aggregate_implied_ir([
            _combo(1400, 1650, 30.0), _combo(1150, 1400, 10.0, car="F4")])
        assert out.combo_count == 2
        assert out.lo == 1338  # round(1462.5 - 125)
        assert out.hi == 1588  # round(1462.5 + 125)

    def test_lo_clamped_to_zero(self):
        out = aggregate_implied_ir([_combo(0, 150, 5.0)])
        assert out.lo >= 0

    def test_zero_total_weight_falls_back_to_unweighted(self):
        out = aggregate_implied_ir([_combo(1000, 1250, 0.0)])
        assert out == DriverImpliedIR(lo=1000, hi=1250, combo_count=1)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_implied_ir.py -q`
Expected: FAIL — `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Implement**

```python
# core/progression/implied_ir.py
"""PURE roll-up of per-combo implied-iR bands (spec §7).

ALWAYS a band, never a point — bands-not-false-precision is the locked
curve rule. This number informs, it never gates.
"""

from core.progression.models import ComboImplied, DriverImpliedIR


def aggregate_implied_ir(rows: list[ComboImplied]) -> DriverImpliedIR | None:
    """Weighted mean of band midpoints +/- the mean band half-width.

    Weight = the combo's representative-lap count (more practice = more
    signal). Zero total weight degrades to an unweighted mean.
    """
    if not rows:
        return None
    total_w = sum(r.weight for r in rows)
    if total_w > 0:
        mid = sum(((r.implied_lo + r.implied_hi) / 2) * r.weight for r in rows) / total_w
    else:
        mid = sum((r.implied_lo + r.implied_hi) / 2 for r in rows) / len(rows)
    half = sum((r.implied_hi - r.implied_lo) / 2 for r in rows) / len(rows)
    return DriverImpliedIR(
        lo=max(0, round(mid - half)),
        hi=round(mid + half),
        combo_count=len(rows),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_implied_ir.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/progression/implied_ir.py tests/test_progression_implied_ir.py
git commit -m "feat(progression): weighted implied-iR band aggregation"
```

---

### Task 4: Weekly snapshot store (`core/progression/store.py`)

**Files:**
- Create: `core/progression/store.py`
- Modify: `.gitignore` (add `data/progression.db`)
- Test: `tests/test_progression_store.py`

**Context:** Spec §7 defers the `implied_ir_history` schema to this plan. Decision: its own tiny SQLite DB `data/progression.db` (tracks.db is watcher-owned session domain; races.db is race domain — a weekly derived snapshot is neither). DELETE+INSERT per week keyed by `week_start` (the `record_region_diagnoses` idempotency precedent) so recomputing a week overwrites it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_progression_store.py
"""implied_ir_history persistence — weekly snapshots survive cache expiry."""

import pytest

from core.progression.models import ComboImplied
from core.progression.store import ImpliedIRStore


def _combo(car="M2", lo=1400, hi=1650, weight=30.0):
    return ComboImplied(
        track_id="525", track_name="Spa", car=car, series_name="PCup",
        lap_s=160.5, implied_lo=lo, implied_hi=hi, weight=weight,
    )


@pytest.fixture
def store(tmp_path):
    return ImpliedIRStore(tmp_path / "progression.db")


class TestImpliedIRStore:
    def test_round_trip(self, store):
        store.save_week("2026-07-14", [_combo(), _combo(car="F4", lo=1200, hi=1450)])
        rows = store.get_week("2026-07-14")
        assert len(rows) == 2
        assert rows[0].track_name == "Spa"
        assert rows[0].lap_s == 160.5

    def test_missing_week_empty(self, store):
        assert store.get_week("2026-01-06") == []

    def test_save_week_is_idempotent_overwrite(self, store):
        store.save_week("2026-07-14", [_combo(), _combo(car="F4")])
        store.save_week("2026-07-14", [_combo()])
        assert len(store.get_week("2026-07-14")) == 1

    def test_empty_list_clears_week(self, store):
        store.save_week("2026-07-14", [_combo()])
        store.save_week("2026-07-14", [])
        assert store.get_week("2026-07-14") == []

    def test_history_ascending_by_week(self, store):
        store.save_week("2026-07-14", [_combo()])
        store.save_week("2026-07-07", [_combo(lo=1300, hi=1550)])
        weeks = [w for w, _ in store.history()]
        assert weeks == ["2026-07-07", "2026-07-14"]

    def test_latest_week(self, store):
        assert store.latest_week() is None
        store.save_week("2026-07-07", [_combo()])
        store.save_week("2026-07-14", [_combo(car="F4")])
        week, rows = store.latest_week()
        assert week == "2026-07-14"
        assert rows[0].car == "F4"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_store.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement**

```python
# core/progression/store.py
"""SQLite store for weekly implied-iR snapshots (data/progression.db).

The field curve is week-scoped and the briefing cache is expendable —
snapshots make the implied-iR trend line durable. save_week is
DELETE+INSERT keyed by week_start (the region_diagnoses idempotency
pattern): recomputing a week overwrites it.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from core.progression.models import ComboImplied

DEFAULT_DB_PATH = Path("data/progression.db")


class ImpliedIRStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS implied_ir_history (
                    week_start TEXT NOT NULL,      -- ISO date of the Tuesday flip
                    track_id TEXT NOT NULL,
                    track_name TEXT NOT NULL,
                    car TEXT NOT NULL,
                    series_name TEXT NOT NULL,
                    lap_s REAL NOT NULL,
                    implied_lo INTEGER NOT NULL,
                    implied_hi INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (week_start, track_id, car)
                )
                """
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_week(self, week_start: str, rows: list[ComboImplied]) -> None:
        """Replace the snapshot rows for one race week (empty list clears)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM implied_ir_history WHERE week_start = ?", (week_start,)
            )
            conn.executemany(
                """
                INSERT INTO implied_ir_history (
                    week_start, track_id, track_name, car, series_name,
                    lap_s, implied_lo, implied_hi, weight, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (week_start, r.track_id, r.track_name, r.car, r.series_name,
                     r.lap_s, r.implied_lo, r.implied_hi, r.weight, now)
                    for r in rows
                ],
            )

    def get_week(self, week_start: str) -> list[ComboImplied]:
        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT track_id, track_name, car, series_name, lap_s,
                       implied_lo, implied_hi, weight
                FROM implied_ir_history WHERE week_start = ?
                ORDER BY weight DESC, track_name, car
                """,
                (week_start,),
            )
            return [self._row(r) for r in cur.fetchall()]

    def history(self) -> list[tuple[str, list[ComboImplied]]]:
        """All snapshots grouped per week, week-ascending (trend-line input)."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT week_start, track_id, track_name, car, series_name,
                       lap_s, implied_lo, implied_hi, weight
                FROM implied_ir_history
                ORDER BY week_start, weight DESC, track_name, car
                """
            )
            grouped: dict[str, list[ComboImplied]] = {}
            for r in cur.fetchall():
                grouped.setdefault(r["week_start"], []).append(self._row(r))
        return sorted(grouped.items())

    def latest_week(self) -> tuple[str, list[ComboImplied]] | None:
        hist = self.history()
        return hist[-1] if hist else None

    @staticmethod
    def _row(r: sqlite3.Row) -> ComboImplied:
        return ComboImplied(
            track_id=r["track_id"], track_name=r["track_name"], car=r["car"],
            series_name=r["series_name"], lap_s=r["lap_s"],
            implied_lo=r["implied_lo"], implied_hi=r["implied_hi"],
            weight=r["weight"],
        )
```

Also append to `.gitignore` (with the Edit tool, near the other `data/` entries):

```
data/progression.db
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_store.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/progression/store.py tests/test_progression_store.py .gitignore
git commit -m "feat(progression): implied_ir_history weekly snapshot store (data/progression.db)"
```

---

### Task 5: Progression ingest (`core/progression/ingest.py`)

**Files:**
- Create: `core/progression/ingest.py`
- Test: `tests/test_progression_ingest.py`

**Context:** The package's only I/O module (the `core/briefing/ingest.py` precedent). Two jobs:

1. **`fetch_rating_history`** — the member's iR (chart_type 1) and SR (chart_type 3) time series via the EXISTING `LiveIRacingAPI.get_member_chart_data(cust_id, category_id=5, chart_type=...)` (`core/benchmark/iracing_api.py:759`), cached **per day** under `data/briefing_cache/chart_data/` using `_cached_fetch` from `core/race/ingest.py:210` (atomic writes, empty responses never cached — an API hiccup today retries today, and tomorrow gets a fresh file anyway). SR chart values come back ×100 (e.g. 351 = SR 3.51) — `normalize_sr` divides by 100 when values look scaled.
2. **`compute_week_implied_ir`** — spec §7 per-combo placement: `rank_series_candidates` (briefing) picks the top `IMPLIED_IR_MAX_SERIES` current-week series where the user has practice; per series, `harvest_field` builds the week's curve (results cached per subsession, reused from any briefing-page harvest of the same week); every user combo at that track with a practice best (`build_readiness`) is placed with `place_on_curve(curve, best_lap, None)`. Honesty rails: skip curves with no bins or fewer than `MIN_BIN_N` total points; dedupe combos across series (first candidate = deepest practice wins); every skip appends a warning. Car-vs-series-curve approximation note: the curve is series-scoped, not car-filtered — the same approximation the shipped briefing page makes; the `series_name` on each row is the honesty label.

**Testing approach:** `harvest_field`, `rank_series_candidates`, `build_readiness`, and `place_on_curve` are imported INTO `core.progression.ingest`'s namespace, so tests monkeypatch `core.progression.ingest.harvest_field` (standard monkeypatch-the-consumer pattern). `fetch_rating_history` is tested with a minimal fake API object.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_progression_ingest.py
"""Progression ingest — rating history caching + weekly implied-iR compute."""

from datetime import date

import pytest

import core.progression.ingest as ingest
from core.benchmark.iracing_api import (
    IRatingPoint, RaceWeek, SeasonSchedule,
)
from core.briefing.curve import build_curve
from core.progression.ingest import (
    compute_week_implied_ir, fetch_rating_history, normalize_sr,
)
from core.track.track_db import LapRow, SessionRow


class _FakeChartAPI:
    def __init__(self, points_by_type, fail=False):
        self.points_by_type = points_by_type
        self.fail = fail
        self.calls = []

    def get_member_chart_data(self, cust_id, category_id=5, chart_type=1):
        if self.fail:
            raise RuntimeError("network down")
        self.calls.append(chart_type)
        return self.points_by_type.get(chart_type, [])


class TestFetchRatingHistory:
    def test_fetches_both_series_and_caches(self, tmp_path):
        api = _FakeChartAPI({
            1: [IRatingPoint("2026-07-01", 1350)],
            3: [IRatingPoint("2026-07-01", 351)],
        })
        ir, sr = fetch_rating_history(api, 123, cache_dir=tmp_path,
                                      today=date(2026, 7, 17))
        assert ir == [IRatingPoint("2026-07-01", 1350)]
        assert sr == [IRatingPoint("2026-07-01", 351)]
        # second call same day: served from cache, API not touched
        dead = _FakeChartAPI({}, fail=True)
        ir2, sr2 = fetch_rating_history(dead, 123, cache_dir=tmp_path,
                                        today=date(2026, 7, 17))
        assert ir2 == ir and sr2 == sr

    def test_api_failure_degrades_to_empty(self, tmp_path):
        dead = _FakeChartAPI({}, fail=True)
        ir, sr = fetch_rating_history(dead, 123, cache_dir=tmp_path,
                                      today=date(2026, 7, 17))
        assert ir == [] and sr == []


class TestNormalizeSr:
    def test_scaled_values_divided(self):
        pts = [IRatingPoint("2026-07-01", 351)]
        assert normalize_sr(pts) == [("2026-07-01", 3.51)]

    def test_small_values_untouched(self):
        pts = [IRatingPoint("2026-07-01", 3)]
        assert normalize_sr(pts) == [("2026-07-01", 3.0)]

    def test_empty(self):
        assert normalize_sr([]) == []


def _season(season_id, track_id, week=5):
    return SeasonSchedule(
        series_id=season_id, series_name=f"Series {season_id}",
        season_id=season_id, season_name="S3", race_week=week, max_weeks=12,
        season_year=2026, season_quarter=3,
        weeks=[RaceWeek(
            race_week_num=week, track_id=track_id, track_name=f"Track {track_id}",
            config_name="", start_date="2026-07-14", race_time_limit=None,
            race_lap_limit=None, start_type="Standing", standing_start=True,
            max_pct_fuel_fill=None,
        )],
    )


def _practice(sid, track_id, car, best=160.0):
    return SessionRow(
        session_id=sid, track_id=track_id, track_name=f"Track {track_id}",
        car=car, session_type="Practice",
        session_date=f"2026-07-0{sid[-1]} 10-00-00",
        best_lap_time=best, lap_count=12,
    )


def _laps(n=12, base=160.0):
    return [LapRow(lap_number=i + 1, lap_time=base + 0.1 * i, is_valid=True)
            for i in range(n)]


def _dense_curve():
    pts = [(1000 + 50 * i, 165.0 - 0.5 * i) for i in range(20)]
    return build_curve(pts, subsessions_used=10, capped=False)


class TestComputeWeekImpliedIr:
    def _fixtures(self):
        seasons = [_season(100, 525)]
        sessions = [_practice("s1", "525", "M2"), _practice("s2", "525", "M2")]
        laps = {s.session_id: _laps() for s in sessions}
        return seasons, sessions, laps

    def test_places_combo_on_harvested_curve(self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._fixtures()
        monkeypatch.setattr(ingest, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))
        rows, warnings = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert (r.track_id, r.car) == ("525", "M2")
        assert r.series_name == "Series 100"
        assert r.implied_lo is not None and r.implied_hi > r.implied_lo
        assert r.weight > 0

    def test_thin_curve_skipped_with_warning(self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._fixtures()
        thin = build_curve([(1500, 160.0)], subsessions_used=1, capped=False)
        monkeypatch.setattr(ingest, "harvest_field", lambda *a, **k: (thin, None))
        rows, warnings = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert rows == []
        assert warnings

    def test_harvest_failure_is_a_warning_not_a_raise(self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._fixtures()

        def boom(*a, **k):
            raise RuntimeError("API down")

        monkeypatch.setattr(ingest, "harvest_field", boom)
        rows, warnings = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert rows == [] and warnings

    def test_combo_deduped_across_series(self, monkeypatch, tmp_path):
        seasons = [_season(100, 525), _season(200, 525)]
        sessions = [_practice("s1", "525", "M2"), _practice("s2", "525", "M2")]
        laps = {s.session_id: _laps() for s in sessions}
        monkeypatch.setattr(ingest, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))
        rows, _ = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert len(rows) == 1  # same (track, car) placed once

    def test_no_practice_at_week_tracks_yields_nothing(self, monkeypatch, tmp_path):
        seasons = [_season(100, 219)]  # Bathurst — user practiced Spa only
        sessions = [_practice("s1", "525", "M2")]
        laps = {"s1": _laps()}
        monkeypatch.setattr(ingest, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))
        rows, _ = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert rows == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_ingest.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement**

```python
# core/progression/ingest.py
"""Progression I/O: member rating history + weekly implied-iR compute.

The package's only networked module (the briefing-ingest precedent).
Everything degrades: API failures return empty series or warnings, never
raise to the page.
"""

from dataclasses import asdict
from datetime import date
import logging
from pathlib import Path

from core.benchmark.iracing_api import IRatingPoint
from core.briefing.curve import MIN_BIN_N, place_on_curve
from core.briefing.ingest import harvest_field, rank_series_candidates
from core.profile.pace import build_readiness
from core.progression.models import IMPLIED_IR_MAX_SERIES, ComboImplied
from core.race.ingest import _cached_fetch
from core.track.track_db import LapRow, SessionRow

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/briefing_cache")

_CHART_IRATING = 1
_CHART_SR = 3
_CATEGORY_SPORTS_CAR = 5


def fetch_rating_history(
    api,
    cust_id: int,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    today: date | None = None,
) -> tuple[list[IRatingPoint], list[IRatingPoint]]:
    """(iRating series, SR series) for the member, cached per day.

    The day stamp in the filename IS the cache policy: today's file is
    reused all day, tomorrow misses and re-fetches. Empty API responses
    are never cached (_cached_fetch rule), so a hiccup retries same-day.
    """
    stamp = (today or date.today()).isoformat()

    def _series(chart_type: int) -> list[IRatingPoint]:
        path = cache_dir / "chart_data" / f"{cust_id}_{chart_type}_{stamp}.json"
        try:
            raw = _cached_fetch(
                path,
                lambda: [
                    asdict(p)
                    for p in api.get_member_chart_data(
                        cust_id,
                        category_id=_CATEGORY_SPORTS_CAR,
                        chart_type=chart_type,
                    )
                ],
            )
        except Exception:
            logger.exception("chart_data fetch failed (type %s)", chart_type)
            return []
        return [IRatingPoint(when=p["when"], value=p["value"]) for p in raw or []]

    return _series(_CHART_IRATING), _series(_CHART_SR)


def normalize_sr(points: list[IRatingPoint]) -> list[tuple[str, float]]:
    """SR chart values arrive x100 (351 = 3.51) — scale for display."""
    if not points:
        return []
    scale = 100.0 if max(p.value for p in points) > 10 else 1.0
    return [(p.when, p.value / scale) for p in points]


def compute_week_implied_ir(
    api,
    seasons,
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
    cache_dir: Path = DEFAULT_CACHE_DIR,
    max_series: int = IMPLIED_IR_MAX_SERIES,
) -> tuple[list[ComboImplied], list[str]]:
    """Place every qualifying practice combo on this week's field curves.

    A combo qualifies when its track is run by a current-week series the
    user has practiced at (rank_series_candidates order = practice depth)
    and it has a practice best. Placement math stays raw (locked rule).
    Curve honesty: no bins or < MIN_BIN_N total points -> skip + warning.
    The curve is series-scoped, not car-filtered — the same approximation
    the briefing page ships; series_name on the row is the honesty label.
    """
    warnings: list[str] = []
    candidates = [
        c for c in rank_series_candidates(seasons, sessions)
        if c.practice_sessions > 0
    ][:max_series]
    if not candidates:
        return [], ["No current-week series at a track you've practiced."]

    seasons_by_id = {s.season_id: s for s in seasons}
    readiness = build_readiness(sessions, laps)
    rows: list[ComboImplied] = []
    placed: set[tuple[str, str]] = set()

    for cand in candidates:
        combos = [
            r for r in readiness
            if r.track_id == str(cand.track_id)
            and r.best_lap is not None
            and (r.track_id, r.car) not in placed
        ]
        if not combos:
            continue
        season = seasons_by_id.get(cand.season_id)
        try:
            curve, _stats = harvest_field(
                api, cand.season_id, cand.race_week, cache_dir,
                season_year=season.season_year if season else None,
                season_quarter=season.season_quarter if season else None,
            )
        except Exception as exc:
            warnings.append(f"{cand.series_name}: field harvest failed ({exc})")
            continue
        if not curve.bins or len(curve.points) < MIN_BIN_N:
            warnings.append(
                f"{cand.series_name} at {cand.track_name}: field sample too "
                f"thin to place you honestly."
            )
            continue
        for r in combos:
            placement = place_on_curve(curve, r.best_lap, None)
            if placement.implied_ir_lo is None or placement.implied_ir_hi is None:
                continue
            rows.append(ComboImplied(
                track_id=r.track_id, track_name=r.track_name, car=r.car,
                series_name=cand.series_name, lap_s=r.best_lap,
                implied_lo=placement.implied_ir_lo,
                implied_hi=placement.implied_ir_hi,
                weight=float(r.valid_laps),
            ))
            placed.add((r.track_id, r.car))
    return rows, warnings
```

Check before running: `MIN_BIN_N` must be importable from `core.briefing.curve` (it is defined there); if the curve module exposes it elsewhere adjust the import, never inline the number.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_ingest.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/progression/ingest.py tests/test_progression_ingest.py
git commit -m "feat(progression): rating-history fetch (per-day cache) + weekly implied-iR compute"
```

---

### Task 6: Prescription seed table + public fault labels

**Files:**
- Create: `core/profile/prescriptions.py`
- Modify: `core/profile/render.py` (promote `_FAULT_LABEL` → public `FAULT_LABELS`)
- Test: `tests/test_prescriptions.py`

**Context:** Spec §8 — a hand-curated literal table, NO consumer in this phase (the week-plan build consumes it later; this ships the input contract). Tone rule: capability-framed ("teaches", "forces", "rewards"), never "you're bad at X". Also promote the fault-label dict in `core/profile/render.py` from `_FAULT_LABEL` to public `FAULT_LABELS` (keep a `_FAULT_LABEL = FAULT_LABELS` alias so existing internal references keep working) — the Progression page's technique-trend legend needs it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prescriptions.py
"""Prescription seed table — the week plan's future input contract."""

import dataclasses

import pytest

from core.live.nudges import FaultKind
from core.profile.prescriptions import PRESCRIPTIONS, Prescription
from core.profile.render import FAULT_LABELS


class TestPrescriptions:
    def test_seeded_with_six_to_ten_rows(self):
        assert 6 <= len(PRESCRIPTIONS) <= 10

    def test_every_fault_is_a_real_fault_kind(self):
        valid = {k.value for k in FaultKind}
        for p in PRESCRIPTIONS:
            assert p.fault in valid, p

    def test_rows_are_complete(self):
        for p in PRESCRIPTIONS:
            assert p.combo and p.skill_line and p.transfer_line

    def test_rows_are_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            PRESCRIPTIONS[0].fault = "braking"

    def test_capability_framed_never_scolding(self):
        for p in PRESCRIPTIONS:
            text = (p.skill_line + " " + p.transfer_line).lower()
            assert "you're bad" not in text
            assert "you are bad" not in text


class TestFaultLabels:
    def test_public_labels_cover_every_fault_kind(self):
        assert set(FAULT_LABELS) == {k.value for k in FaultKind}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prescriptions.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement**

In `core/profile/render.py`, rename the dict `_FAULT_LABEL` to `FAULT_LABELS` and add a backward alias directly below it (use the Edit tool; do not reorder the dict):

```python
FAULT_LABELS = {
    "lift": "Apex speed",
    "braking": "Brake point",
    "release": "Brake release",
    "exit_speed": "Corner exit speed",
    "throttle": "Throttle pickup",
}
_FAULT_LABEL = FAULT_LABELS  # internal alias, existing call sites unchanged
```

(If `FaultKind` gains members later, `TestFaultLabels` fails and the dict must grow — that coupling is the point.)

```python
# core/profile/prescriptions.py
"""Curated combo prescriptions (spec §8) — a knowledge layer, not data mining.

Each row names a combo that TEACHES a fault-ladder skill and what that
skill transfers to (v3 transfer principle: hard cars teach skills that
transfer DOWN). Capability-framed, never scolding — tone is part of the
contract. Grows by hand. No consumer in this phase: the week-plan build
reads it later; this file is its input contract.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Prescription:
    fault: str            # FaultKind.value it teaches
    combo: str            # human name, e.g. "Porsche 992 Cup at Spa"
    skill_line: str       # what practicing this combo builds
    transfer_line: str    # where the skill pays off elsewhere


PRESCRIPTIONS: tuple[Prescription, ...] = (
    Prescription(
        fault="release",
        combo="Porsche 992 Cup at Spa",
        skill_line=(
            "teaches trail-brake bite — the car rotates on release into "
            "Les Combes and the Bus Stop, so your left foot learns to steer"
        ),
        transfer_line=(
            "sharper release control transfers to every heavy-braking "
            "corner in every car you drive"
        ),
    ),
    Prescription(
        fault="throttle",
        combo="Porsche 992 Cup at Spa",
        skill_line=(
            "forces throttle discipline through Eau Rouge and Pouhon — "
            "early throttle here is a spin, not a tenth"
        ),
        transfer_line="unlocks every high-speed commitment corner",
    ),
    Prescription(
        fault="braking",
        combo="BMW M2 at Spa",
        skill_line=(
            "rewards patient brake points — the M2 telegraphs its weight "
            "transfer, so you can feel the limit build instead of guessing"
        ),
        transfer_line=(
            "calibrated brake points carry up to faster machinery where "
            "the window is smaller"
        ),
    ),
    Prescription(
        fault="release",
        combo="BMW M2 at Bathurst",
        skill_line=(
            "teaches weight management across the Mountain — release "
            "timing is what sets the car through Skyline and the Dipper"
        ),
        transfer_line=(
            "elevation-change composure transfers to any track that "
            "moves under you"
        ),
    ),
    Prescription(
        fault="lift",
        combo="Formula 4 at Road America",
        skill_line=(
            "a momentum car on a flowing track — carrying apex speed "
            "through the Carousel IS the lap time"
        ),
        transfer_line=(
            "apex-speed trust built here shows up in every momentum "
            "corner, tin-tops included"
        ),
    ),
    Prescription(
        fault="exit_speed",
        combo="Formula 4 at Road America",
        skill_line=(
            "long straights amplify every exit — the stopwatch teaches "
            "exit-first priority by itself"
        ),
        transfer_line=(
            "exit-first thinking pays on every straight-after-corner on "
            "the calendar"
        ),
    ),
    Prescription(
        fault="braking",
        combo="Porsche 992 Cup at Bathurst",
        skill_line=(
            "the Chase demands absolute brake-point precision — there is "
            "no runoff to hide a long one"
        ),
        transfer_line=(
            "precision under commitment transfers down to every car with "
            "more margin"
        ),
    ),
    Prescription(
        fault="throttle",
        combo="BMW M2 at Road America",
        skill_line=(
            "teaches progressive throttle out of Canada Corner and Turn 5 "
            "— patience converts directly to drive off the corner"
        ),
        transfer_line="throttle patience is the cheapest lap time in any RWD car",
    ),
)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prescriptions.py tests/test_profile_render.py -q`
Expected: all PASS (test_profile_render guards the rename)

- [ ] **Step 5: Commit**

```bash
git add core/profile/prescriptions.py core/profile/render.py tests/test_prescriptions.py
git commit -m "feat(profile): prescription seed table + public FAULT_LABELS"
```

---

### Task 7: Progression page + navigation registration

**Files:**
- Create: `app/pages/progression.py`
- Modify: `app/navigation.py` (add PageSpec to the Practice group, FIRST entry)
- Modify: `tests/test_navigation.py` (pin the new Practice page list)
- Test: `tests/test_progression_page.py` (helper-level; Streamlit rendering itself is untested by house convention)

**Context:** Display-only page (house rule: no business logic in `app/`). Six blocks top-to-bottom, cheapest first, every block with a collecting/empty state (progressive enhancement — useful at any corpus size). Reuses page-level helpers from sibling pages: `_get_api` and `_load_seasons_cached` from `app/pages/briefing.py` (lines 62/75), `_resolve_cust_id` from `app/pages/driver_profile.py:38`, `fmt_lap` from `core/briefing/render.py`. NEVER gating language anywhere on this page.

The implied-iR block renders the LAST SNAPSHOT on load (fast, offline) and recomputes only on button click (first-time compute = up to 30 subsession fetches × 3 series; cached per week thereafter). Snapshot save is keyed to `iracing_week_start(today)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_progression_page.py
"""Page-level pure helpers + nav registration for the Progression page."""

from app.navigation import NAV_SPEC
from app.pages.progression import _lap_axis_ticks, _week_band_series
from core.progression.models import ComboImplied


class TestNavRegistration:
    def test_progression_first_in_practice_group(self):
        practice = dict(NAV_SPEC)["Practice"]
        assert practice[0].title == "Progression"
        assert practice[0].url_path == "progression"


class TestLapAxisTicks:
    def test_five_formatted_ticks_spanning_range(self):
        vals, texts = _lap_axis_ticks([90.0, 95.0, 100.0])
        assert len(vals) == 5 and len(texts) == 5
        assert vals[0] == 90.0 and vals[-1] == 100.0
        assert texts[0] == "1:30.000"

    def test_flat_series_still_renders(self):
        vals, texts = _lap_axis_ticks([100.0])
        assert len(vals) == 5


class TestWeekBandSeries:
    def test_aggregates_each_week(self):
        history = [
            ("2026-07-07", [ComboImplied("525", "Spa", "M2", "S", 160.0,
                                         1300, 1550, 10.0)]),
            ("2026-07-14", [ComboImplied("525", "Spa", "M2", "S", 159.5,
                                         1400, 1650, 12.0)]),
        ]
        weeks, los, his = _week_band_series(history)
        assert weeks == ["2026-07-07", "2026-07-14"]
        assert los == [1300, 1400]
        assert his == [1550, 1650]

    def test_empty_history(self):
        assert _week_band_series([]) == ([], [], [])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_page.py -q`
Expected: FAIL — `ImportError` (no app.pages.progression; NAV_SPEC missing the page)

- [ ] **Step 3: Register the page in navigation**

In `app/navigation.py`, add to the Practice group as the FIRST entry (chart-increasing icon):

```python
    (
        "Practice",
        [
            PageSpec("Progression", "\U0001f4c8", "progression",
                     "app.pages.progression", "render_progression_page"),
            PageSpec("Lap Coaching", "⏱️", "coaching",
                     "app.pages.coaching", "render_coaching_page"),
            PageSpec("Scouting Report", "\U0001f52d", "scouting",
                     "app.pages.scouting", "render_scouting_page"),
        ],
    ),
```

In `tests/test_navigation.py`, update the pinned Practice page-title list to `["Progression", "Lap Coaching", "Scouting Report"]` (find the existing exact-list assertion and extend it — do not weaken it to a subset check).

- [ ] **Step 4: Write the page**

```python
# app/pages/progression.py
"""Progression page — the Strava layer (spec §6).

Display only: streak, pace trends, PB timeline, iR/SR history, technique
trends, pace-implied iR. Every block renders a collecting state below
threshold — the page is useful at any corpus size. These numbers inform;
nothing here gates.
"""

from datetime import date
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from app.pages.briefing import _get_api, _load_seasons_cached
from app.pages.driver_profile import _resolve_cust_id
from core.benchmark.reference_store import ReferenceStore
from core.briefing.render import fmt_lap
from core.profile.models import TECHNIQUE_MIN_SESSIONS
from core.profile.pace import build_readiness
from core.profile.render import FAULT_LABELS
from core.progression.implied_ir import aggregate_implied_ir
from core.progression.ingest import (
    compute_week_implied_ir, fetch_rating_history, normalize_sr,
)
from core.progression.store import ImpliedIRStore
from core.progression.streak import build_streak, iracing_week_start
from core.progression.trends import (
    combo_pace_series, fault_trend_series, pb_timeline,
)
from core.race.race_store import RaceStore
from core.track.track_db import TrackDB

RACES_DB = Path("data/races.db")
TRACKS_DB = Path("data/tracks.db")
REFS_DB = Path("data/reference_laps.db")


def _lap_axis_ticks(values: list[float]) -> tuple[list[float], list[str]]:
    """Five evenly spaced y ticks formatted m:ss.mmm (briefing fmt_lap)."""
    lo, hi = min(values), max(values)
    if hi == lo:
        lo, hi = lo - 0.5, hi + 0.5
    vals = [lo + (hi - lo) * i / 4 for i in range(5)]
    return vals, [fmt_lap(v) for v in vals]


def _week_band_series(
    history: list[tuple[str, list]],
) -> tuple[list[str], list[int], list[int]]:
    """Weekly aggregated implied-iR bands for the trend chart."""
    weeks, los, his = [], [], []
    for week, rows in history:
        agg = aggregate_implied_ir(rows)
        if agg is None:
            continue
        weeks.append(week)
        los.append(agg.lo)
        his.append(agg.hi)
    return weeks, los, his


def render_progression_page() -> None:
    st.title("Progression")
    st.markdown(
        "Your season at a glance — race volume, pace trends, and what the "
        "numbers say about where you're heading."
    )

    store = RaceStore(RACES_DB)
    track_db = TrackDB(TRACKS_DB)

    # ---- 1. Race-volume streak -------------------------------------------
    st.subheader("Race streak")
    try:
        races = store.list_races()
    except Exception:
        races = []
    streak = build_streak(
        [(r.session_date, r.created_at) for r in races], date.today()
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Current streak", f"{streak.streak_weeks} wk")
    c2.metric("Races this week", streak.races_this_week)
    c3.metric("Races captured", streak.total_races)
    if streak.total_races == 0:
        st.caption(
            "No races captured yet — race, and the watcher fills this in "
            "automatically."
        )

    # ---- 2. Per-combo pace trend -----------------------------------------
    st.subheader("Pace trend")
    try:
        sessions = track_db.list_session_history()
    except Exception:
        sessions = []
    series = combo_pace_series(sessions)
    if not series:
        st.caption("Collecting — practice sessions build this chart.")
    else:
        laps = {}
        try:
            laps = {s.session_id: track_db.get_session_laps(s.session_id)
                    for s in sessions}
        except Exception:
            pass
        ordered = [
            (r.track_id, r.car, r.track_name)
            for r in build_readiness(sessions, laps)
            if (r.track_id, r.car) in series
        ]
        # readiness may exclude thin combos — append the rest, practiced-first
        seen = {(t, c) for t, c, _ in ordered}
        names = {s.track_id: s.track_name for s in sessions}
        rest = sorted(
            (k for k in series if k not in seen),
            key=lambda k: -len(series[k]),
        )
        options = ordered + [(t, c, names.get(t, t)) for t, c in rest]
        choice = st.selectbox(
            "Combo", options,
            format_func=lambda o: f"{o[2]} — {o[1]}",
        )
        pts = series[(choice[0], choice[1])]
        fig = go.Figure(go.Scatter(
            x=[d for d, _ in pts], y=[v for _, v in pts],
            mode="lines+markers", line=dict(color="#00cc66", width=2),
            customdata=[[fmt_lap(v)] for _, v in pts],
            hovertemplate="%{x}<br>%{customdata[0]}<extra></extra>",
        ))
        vals, texts = _lap_axis_ticks([v for _, v in pts])
        fig.update_layout(
            height=320, margin=dict(l=60, r=20, t=10, b=40),
            yaxis=dict(tickvals=vals, ticktext=texts, title="Session best"),
            xaxis=dict(title=""),
        )
        st.plotly_chart(fig, use_container_width=True)
        if len(pts) < 2:
            st.caption("One session so far at this combo — trends need two.")

    # ---- 3. PB timeline --------------------------------------------------
    st.subheader("Personal bests")
    try:
        pbs = pb_timeline(ReferenceStore(REFS_DB).list_all())
    except Exception:
        pbs = []
    if not pbs:
        st.caption(
            "No personal-best references yet — the watcher promotes your "
            "fastest clean lap per combo automatically."
        )
    else:
        names = {s.track_id: s.track_name for s in sessions}
        st.table([
            {
                "Set": m.imported_at[:10],
                "Combo": f"{names.get(m.track_id, m.track_id)} — {m.car}",
                "Lap": fmt_lap(m.lap_time),
            }
            for m in reversed(pbs)  # newest first for reading
        ])

    # ---- 4. iRating / Safety Rating over time ----------------------------
    st.subheader("iRating & Safety Rating")
    api = _get_api()
    cust_id = _resolve_cust_id(store)
    if api is None or cust_id is None:
        st.caption(
            "Needs iRacing credentials and at least one captured race — "
            "then your official rating history appears here."
        )
    else:
        ir_pts, sr_pts = fetch_rating_history(api, cust_id)
        if not ir_pts:
            st.caption("Rating history unavailable right now — it'll retry.")
        else:
            fig = go.Figure(go.Scatter(
                x=[p.when for p in ir_pts], y=[p.value for p in ir_pts],
                mode="lines", line=dict(color="#00cc66", width=2),
                name="iRating",
            ))
            fig.update_layout(height=280, margin=dict(l=50, r=20, t=10, b=30),
                              yaxis_title="iRating")
            st.plotly_chart(fig, use_container_width=True)
        sr = normalize_sr(sr_pts)
        if sr:
            fig = go.Figure(go.Scatter(
                x=[w for w, _ in sr], y=[v for _, v in sr],
                mode="lines", line=dict(color="#4aa3ff", width=2),
                name="Safety Rating",
            ))
            fig.update_layout(height=220, margin=dict(l=50, r=20, t=10, b=30),
                              yaxis_title="SR")
            st.plotly_chart(fig, use_container_width=True)

    # ---- 5. Technique trends ---------------------------------------------
    st.subheader("Technique trends")
    try:
        diag_rows = track_db.list_region_diagnoses()
    except Exception:
        diag_rows = []
    fault_series = fault_trend_series(diag_rows)
    n_sessions = len({r.session_id for r in diag_rows})
    if not fault_series:
        st.caption(
            f"Technique trends unlock as diagnosed sessions accrue "
            f"(0 of {TECHNIQUE_MIN_SESSIONS})."
        )
    else:
        fig = go.Figure()
        for kind, pts in sorted(fault_series.items()):
            fig.add_trace(go.Scatter(
                x=[d for d, _ in pts], y=[t for _, t in pts],
                mode="lines+markers", name=FAULT_LABELS.get(kind, kind),
            ))
        fig.update_layout(
            height=340, margin=dict(l=50, r=20, t=10, b=40),
            yaxis_title="Time lost per session (s)",
            legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"Time lost per session by habit, across {n_sessions} diagnosed "
            f"sessions — down and to the right is the goal. Measured against "
            f"the reference of the day: a new PB can make later losses look "
            f"bigger."
        )

    # ---- 6. Pace-implied iRating -----------------------------------------
    st.subheader("Pace-implied iRating")
    ir_store = ImpliedIRStore()
    latest = ir_store.latest_week()
    if latest is not None:
        week, rows = latest
        agg = aggregate_implied_ir(rows)
        if agg is not None:
            st.markdown(
                f"### {agg.lo:,}–{agg.hi:,}"
            )
            st.caption(
                f"Where your practice pace sits on this week's field curves, "
                f"across {agg.combo_count} combo"
                f"{'s' if agg.combo_count != 1 else ''} (week of {week}). "
                f"A progress stat, not a permission slip."
            )
            st.table([
                {
                    "Combo": f"{r.track_name} — {r.car}",
                    "Series curve": r.series_name,
                    "Your lap": fmt_lap(r.lap_s),
                    "Implied iR": f"{r.implied_lo:,}–{r.implied_hi:,}",
                }
                for r in rows
            ])
        weeks, los, his = _week_band_series(ir_store.history())
        if len(weeks) >= 2:
            fig = go.Figure([
                go.Scatter(x=weeks, y=his, mode="lines", line=dict(width=0),
                           showlegend=False, hoverinfo="skip"),
                go.Scatter(x=weeks, y=los, mode="lines", fill="tonexty",
                           line=dict(color="#00cc66", width=1),
                           fillcolor="rgba(0,204,102,0.2)", name="Implied iR"),
            ])
            fig.update_layout(height=260, margin=dict(l=50, r=20, t=10, b=30),
                              yaxis_title="Implied iR band")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(
            "Not computed yet — this places your practice pace on this "
            "week's field curves, the same math as the Race Briefing."
        )
    if api is None:
        st.caption("Computing needs iRacing credentials (Settings & Keys).")
    elif st.button("Recompute for this week"):
        with st.spinner("Harvesting this week's fields…"):
            seasons = _load_seasons_cached()
            try:
                sessions = track_db.list_session_history()
                laps = {s.session_id: track_db.get_session_laps(s.session_id)
                        for s in sessions}
            except Exception:
                sessions, laps = [], {}
            rows, warnings = compute_week_implied_ir(
                api, seasons, sessions, laps)
            ir_store.save_week(
                iracing_week_start(date.today()).isoformat(), rows)
        for w in warnings:
            st.caption(f"Note: {w}")
        st.rerun()
```

Adjustment latitude for the executor: if `_load_seasons_cached()` or `_get_api()` have different exact return handling than shown (check `app/pages/briefing.py:62-83`), match the briefing page's usage — but the block structure, empty-state sentences, and never-gating captions are fixed. **Do not** gate later blocks behind earlier ones with `return` (the 2026-07-15 Streamlit lesson: never `if not st.button(): return`).

- [ ] **Step 5: Run tests + import smoke**

Run: `.venv/Scripts/python.exe -m pytest tests/test_progression_page.py tests/test_navigation.py -q`
Expected: all PASS (test_navigation's `test_every_render_function_exists` imports the new page — an import error fails here, not at app startup)

- [ ] **Step 6: Commit**

```bash
git add app/pages/progression.py app/navigation.py tests/test_progression_page.py tests/test_navigation.py
git commit -m "feat(app): Progression page — streak, pace/PB/technique trends, iR-SR history, implied iR"
```

---

### Task 8: Full suite, docs, and wrap-up

**Files:**
- Modify: `CLAUDE.md` (architecture tree + new status section)

- [ ] **Step 1: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: everything green (957 pre-existing + ~35 new). Skips for missing gitignored fixtures are normal.

- [ ] **Step 2: Update CLAUDE.md** (Edit tool ONLY — never PowerShell text ops)

1. Architecture tree: add under `core/`:

```
│   ├── progression/
│   │   ├── models.py             # StreakSummary / ComboImplied / DriverImpliedIR
│   │   ├── streak.py             # PURE: race-week streak math (Tuesday flip)
│   │   ├── trends.py             # PURE: pace / fault / PB trend series (fault ladder reused)
│   │   ├── implied_ir.py         # PURE: weighted implied-iR band roll-up
│   │   ├── ingest.py             # I/O: chart_data per-day cache + weekly implied-iR compute
│   │   └── store.py              # data/progression.db — implied_ir_history weekly snapshots
```

add under `app/pages/`: `│   │   ├── progression.py        # Progression page: streak, trends, PB timeline, iR/SR, implied iR`
add under `core/profile/`: `│   ├── prescriptions.py      # Curated combo→skill prescription seed table (week-plan input)`
add to the data list: `data/progression.db` (gitignored), and the new test files to the tests list.

2. New status section (place after the Loss-Region Persistence section):

```
**Progression Build** (complete, branch progression-build — spec §6-8 of docs/superpowers/specs/2026-07-17-progression-loss-region-persistence-design.md, plan docs/superpowers/plans/2026-07-17-progression-build.md)
- [x] core/progression/ package: streak (Tuesday-flip race weeks, partial-capture created_at fallback), trends (combo pace series / per-FaultKind time-lost-per-session via the technique adapter — fourth consumer of fault_kinds_from_diagnosis, coupling-tested / PB timeline), implied_ir (weighted band roll-up, ALWAYS a band), store (data/progression.db implied_ir_history, DELETE+INSERT per week), ingest (member_chart_data iR+SR per-day cache via _cached_fetch; compute_week_implied_ir = rank_series_candidates top-3 practice-depth series → harvest_field → place_on_curve raw, MIN_BIN_N honesty rail, cross-series combo dedupe)
- [x] Progression page (Practice nav, first entry): six blocks cheapest-first, every block has a collecting state; implied-iR renders last snapshot on load, recomputes only on button (30 fetches/series first time, week-cached after); snapshot keyed to iracing_week_start
- [x] core/profile/prescriptions.py — 8 curated rows (Porsche/Spa release+throttle, M2 braking+release, F4 lift+exit_speed), capability-framed, no consumer yet (week-plan input contract); FAULT_LABELS promoted public in render.py
- Known limits: implied-iR curve is series-scoped not car-filtered (same approximation as the shipped briefing page; series_name is the honesty label per row); SR chart assumes x100 scaling (normalize_sr heuristic); only combos at CURRENT-week series tracks get placed — coverage varies week to week by design
- [ ] Founder validation: open the page with real data, click Recompute for this week, sanity-check the implied band against felt pace
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: progression build status + architecture"
```

- [ ] **Step 4: Requesting code review** (superpowers:requesting-code-review), then merge per superpowers:finishing-a-development-branch. After merging to master: restart the app (a running Streamlit serves NEW page code against OLD cached core modules — the hybrid ImportError has bitten three times; use the tray or stop/start .bats), and push.

---

## Self-review notes

- **Spec coverage:** §6.1 streak → Task 1+7; §6.2 pace trend → Task 2+7; §6.3 PB timeline → Task 2+7; §6.4 iR/SR chart → Task 5+7 (endpoint already existed); §6.5 technique trends → Task 2+7; §6.6+§7 implied iR → Tasks 3,4,5,7; §8 prescriptions → Task 6; §9 testing → per-task TDD + coupling tests; §10 guard rails → no new writes to existing DBs, no AI calls, no gating language (pinned in captions), placement raw.
- **Type consistency:** `ComboImplied`/`DriverImpliedIR`/`StreakSummary` defined once in Task 1's models.py and imported everywhere; `fault_trend_series` returns `dict[str, list[tuple[str, float]]]` consumed as such in Task 7; `history()` returns `list[tuple[str, list[ComboImplied]]]` consumed by `_week_band_series`.
- **Known simplification:** the streak's `races_this_week` re-parses dates (small N, pure function — clarity over micro-optimization).
