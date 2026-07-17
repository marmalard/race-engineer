# Loss-Region Persistence + Technique Tendencies + Time-to-Pace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the watcher's per-session loss-region diagnoses to tracks.db, back-fill history, and derive technique tendencies + time-to-pace into the driver profile.

**Architecture:** New `region_diagnoses` table in tracks.db written by the watcher processor right after `build_debrief` (DELETE+INSERT idempotent, the `record_laps` pattern). A back-fill script re-debriefs recorded history against each combo's CURRENT reference. Pure `core/profile/technique.py` classifies stored rows through the live coach's `fault_kinds_from_diagnosis` (one ranking, three consumers); time-to-pace is a pure addition to `core/profile/pace.py`. Both surface via builder → render → Driver Profile page → prompt block.

**Tech Stack:** Python 3.11+/sqlite3 stdlib, pytest, existing core modules only. No new dependencies, no AI calls.

**Spec:** `docs/superpowers/specs/2026-07-17-progression-loss-region-persistence-design.md`

**Execution environment:** Work in a dedicated git worktree — the production Streamlit app hot-reloads the main checkout (locked lesson 2026-07-15). Tests: `.venv/Scripts/python.exe -m pytest -q` from the worktree (create the worktree venv with `uv sync` if needed; uv hardlinks from a global cache).

---

### Task 1: `region_diagnoses` table + TrackDB API

**Files:**
- Modify: `core/track/track_db.py` (schema in `_init_db`, `SessionRow`, new dataclasses + methods)
- Test: `tests/test_track_db.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_track_db.py` (it already imports `TrackDB`; add the new imports at the top of the file alongside existing ones):

```python
from core.coaching.debrief import RegionDiagnosis
from core.telemetry.loss_regions import LossRegion
from core.track.track_db import DiagnosisContext, DiagnosisRow


def _diag(label="Eau Rouge", time_lost=1.2, braking=-12.0, release=None):
    """A RegionDiagnosis as build_debrief produces it (absolutes default None)."""
    return RegionDiagnosis(
        region=LossRegion(distance_start=100.0, distance_end=250.0,
                          time_lost=time_lost),
        label=label,
        braking_delta_m=braking,
        min_speed_delta_ms=-2.5,
        throttle_delta_m=15.0,
        driver_min_speed_ms=30.0,
        reference_min_speed_ms=32.5,
        brake_release_delta_m=release,
        exit_speed_delta_ms=-1.0,
    )


def _ctx():
    return DiagnosisContext(
        driver_lap_number=3,
        driver_lap_time=150.5,
        reference_source="personal_best",
        reference_lap_time=148.2,
        total_time_delta_s=2.3,
    )


def _record_session(db, session_id="sess1", track_id="523",
                    session_type="practice", date="2026-07-01 10-00-00"):
    db.record_session(
        session_id=session_id, track_id=track_id, car="BMW M2",
        session_type=session_type, session_date=date,
        best_lap_time=150.5, lap_count=8, ibt_file_path=f"C:/t/{session_id}.ibt",
    )


class TestRegionDiagnoses:
    def test_round_trip_all_fields(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db)
        db.record_region_diagnoses(
            "sess1", _ctx(), [_diag(), _diag(label="Pouhon", time_lost=0.4,
                                          braking=None, release=-8.0)],
        )
        rows = db.list_region_diagnoses()
        assert len(rows) == 2
        r = rows[0]
        assert isinstance(r, DiagnosisRow)
        assert r.session_id == "sess1"
        assert r.region_rank == 1
        assert r.label == "Eau Rouge"
        assert r.distance_start_m == 100.0
        assert r.distance_end_m == 250.0
        assert r.time_lost_s == 1.2
        assert r.braking_delta_m == -12.0
        assert r.min_speed_delta_ms == -2.5
        assert r.throttle_delta_m == 15.0
        assert r.brake_release_delta_m is None
        assert r.exit_speed_delta_ms == -1.0
        assert r.driver_min_speed_ms == 30.0
        assert r.reference_min_speed_ms == 32.5
        assert r.driver_lap_number == 3
        assert r.driver_lap_time == 150.5
        assert r.reference_source == "personal_best"
        assert r.reference_lap_time == 148.2
        assert r.total_time_delta_s == 2.3
        # NULL round-trip on the second row
        assert rows[1].braking_delta_m is None
        assert rows[1].brake_release_delta_m == -8.0
        assert rows[1].region_rank == 2

    def test_session_context_joined(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db)
        db.record_region_diagnoses("sess1", _ctx(), [_diag()])
        r = db.list_region_diagnoses()[0]
        assert r.track_id == "523"
        assert r.car == "BMW M2"
        assert r.session_type == "practice"
        assert r.session_date == "2026-07-01 10-00-00"

    def test_rerun_is_idempotent(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db)
        db.record_region_diagnoses("sess1", _ctx(), [_diag(), _diag()])
        db.record_region_diagnoses("sess1", _ctx(), [_diag()])
        assert len(db.list_region_diagnoses()) == 1

    def test_empty_list_clears(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db)
        db.record_region_diagnoses("sess1", _ctx(), [_diag()])
        db.record_region_diagnoses("sess1", _ctx(), [])
        assert db.list_region_diagnoses() == []

    def test_ordered_by_date_then_rank(self, tmp_path):
        db = TrackDB(tmp_path / "t.db")
        _record_session(db, "b", date="2026-07-02 10-00-00")
        _record_session(db, "a", date="2026-07-01 10-00-00")
        db.record_region_diagnoses("b", _ctx(), [_diag(label="B1")])
        db.record_region_diagnoses("a", _ctx(), [_diag(label="A1"),
                                                 _diag(label="A2")])
        labels = [r.label for r in db.list_region_diagnoses()]
        assert labels == ["A1", "A2", "B1"]


def test_session_row_carries_ibt_file_path(tmp_path):
    db = TrackDB(tmp_path / "t.db")
    _record_session(db)
    row = db.list_session_history()[0]
    assert row.ibt_file_path == "C:/t/sess1.ibt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_db.py -q`
Expected: FAIL — `ImportError: cannot import name 'DiagnosisContext'`

- [ ] **Step 3: Implement in `core/track/track_db.py`**

At the top of the file, extend the imports (keep existing ones):

```python
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # duck-typed at runtime — keeps track_db below core.coaching
    from core.coaching.debrief import RegionDiagnosis
```

Add `ibt_file_path` to `SessionRow` (defaulted — backward-compatible):

```python
@dataclass
class SessionRow:
    """One sessions-table row for profile/history reads (no laps payload)."""

    session_id: str
    track_id: str
    track_name: str
    car: str
    session_type: str
    session_date: str
    best_lap_time: float | None
    lap_count: int
    ibt_file_path: str = ""
```

Add the two new dataclasses right after `LapRow`:

```python
@dataclass
class DiagnosisContext:
    """What was compared, recorded alongside every region row."""

    driver_lap_number: int
    driver_lap_time: float
    reference_source: str        # 'personal_best' | 'g61'
    reference_lap_time: float
    total_time_delta_s: float


@dataclass
class DiagnosisRow:
    """One region_diagnoses row joined with its session context."""

    session_id: str
    track_id: str
    track_name: str
    car: str
    session_type: str
    session_date: str
    region_rank: int
    label: str
    distance_start_m: float
    distance_end_m: float
    time_lost_s: float
    braking_delta_m: float | None
    min_speed_delta_ms: float
    throttle_delta_m: float | None
    brake_release_delta_m: float | None
    exit_speed_delta_ms: float
    driver_min_speed_ms: float
    reference_min_speed_ms: float
    driver_lap_number: int
    driver_lap_time: float
    reference_source: str
    reference_lap_time: float
    total_time_delta_s: float
```

In `_init_db`'s `executescript`, append after the `laps` table:

```sql
                CREATE TABLE IF NOT EXISTS region_diagnoses (
                    diagnosis_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    region_rank INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    distance_start_m REAL NOT NULL,
                    distance_end_m REAL NOT NULL,
                    time_lost_s REAL NOT NULL,
                    braking_delta_m REAL,
                    min_speed_delta_ms REAL NOT NULL,
                    throttle_delta_m REAL,
                    brake_release_delta_m REAL,
                    exit_speed_delta_ms REAL NOT NULL,
                    driver_min_speed_ms REAL NOT NULL,
                    reference_min_speed_ms REAL NOT NULL,
                    driver_lap_number INTEGER NOT NULL,
                    driver_lap_time REAL NOT NULL,
                    reference_source TEXT NOT NULL,
                    reference_lap_time REAL NOT NULL,
                    total_time_delta_s REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_region_diagnoses_session
                    ON region_diagnoses(session_id);
```

(`CREATE TABLE IF NOT EXISTS` inside the existing executescript means existing databases gain the table on next `TrackDB.__init__` — no migration step.)

In `list_session_history`, add `s.ibt_file_path` to the SELECT column list and `ibt_file_path=r["ibt_file_path"] or ""` to the `SessionRow(...)` construction.

Add the two methods next to `record_laps` / `get_session_laps`:

```python
    def record_region_diagnoses(
        self,
        session_id: str,
        context: DiagnosisContext,
        diagnoses: "list[RegionDiagnosis]",
    ) -> None:
        """Replace the diagnosis rows for a session (idempotent on rerun).

        Takes RegionDiagnosis objects duck-typed (attribute access only) —
        no runtime import of core.coaching. Empty list clears the rows.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "DELETE FROM region_diagnoses WHERE session_id = ?",
                (session_id,),
            )
            conn.executemany(
                """
                INSERT INTO region_diagnoses (
                    session_id, region_rank, label,
                    distance_start_m, distance_end_m, time_lost_s,
                    braking_delta_m, min_speed_delta_ms, throttle_delta_m,
                    brake_release_delta_m, exit_speed_delta_ms,
                    driver_min_speed_ms, reference_min_speed_ms,
                    driver_lap_number, driver_lap_time,
                    reference_source, reference_lap_time,
                    total_time_delta_s, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_id, rank, d.label,
                        d.region.distance_start, d.region.distance_end,
                        d.region.time_lost,
                        d.braking_delta_m, d.min_speed_delta_ms,
                        d.throttle_delta_m, d.brake_release_delta_m,
                        d.exit_speed_delta_ms,
                        d.driver_min_speed_ms, d.reference_min_speed_ms,
                        context.driver_lap_number, context.driver_lap_time,
                        context.reference_source, context.reference_lap_time,
                        context.total_time_delta_s, now,
                    )
                    for rank, d in enumerate(diagnoses, start=1)
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def list_region_diagnoses(self) -> list[DiagnosisRow]:
        """All diagnosis rows joined with session context, ordered by
        session_date then region_rank."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT d.*, s.track_id AS s_track_id,
                       COALESCE(t.name, s.track_id) AS track_name,
                       s.car, s.session_type, s.session_date
                FROM region_diagnoses d
                JOIN sessions s ON s.session_id = d.session_id
                LEFT JOIN tracks t ON t.track_id = s.track_id
                ORDER BY s.session_date, d.region_rank
                """
            ).fetchall()
            return [
                DiagnosisRow(
                    session_id=r["session_id"],
                    track_id=r["s_track_id"] or "",
                    track_name=r["track_name"] or "",
                    car=r["car"] or "",
                    session_type=r["session_type"] or "",
                    session_date=r["session_date"] or "",
                    region_rank=r["region_rank"],
                    label=r["label"],
                    distance_start_m=r["distance_start_m"],
                    distance_end_m=r["distance_end_m"],
                    time_lost_s=r["time_lost_s"],
                    braking_delta_m=r["braking_delta_m"],
                    min_speed_delta_ms=r["min_speed_delta_ms"],
                    throttle_delta_m=r["throttle_delta_m"],
                    brake_release_delta_m=r["brake_release_delta_m"],
                    exit_speed_delta_ms=r["exit_speed_delta_ms"],
                    driver_min_speed_ms=r["driver_min_speed_ms"],
                    reference_min_speed_ms=r["reference_min_speed_ms"],
                    driver_lap_number=r["driver_lap_number"],
                    driver_lap_time=r["driver_lap_time"],
                    reference_source=r["reference_source"],
                    reference_lap_time=r["reference_lap_time"],
                    total_time_delta_s=r["total_time_delta_s"],
                )
                for r in rows
            ]
        finally:
            conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_db.py -q`
Expected: PASS (all, including pre-existing)

- [ ] **Step 5: Commit**

```bash
git add core/track/track_db.py tests/test_track_db.py
git commit -m 'feat(track-db): region_diagnoses table + SessionRow.ibt_file_path'
```

---

### Task 2: Processor persistence wiring + `parse_best_lap` extraction

**Files:**
- Modify: `core/watcher/processor.py`
- Modify: `scripts/watch_telemetry.py` (`_format_report`)
- Test: `tests/test_watcher_processor.py` (append), `tests/test_watch_telemetry_helpers.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_watcher_processor.py`:

```python
def test_no_reference_records_no_diagnoses(sample_ibt_path, dbs):
    track_db, ref_store = dbs
    report = process_ibt(sample_ibt_path, track_db, ref_store)
    assert report.error is None
    assert report.diagnoses_recorded == 0
    assert track_db.list_region_diagnoses() == []


def test_process_persists_diagnoses_when_reference_exists(sample_ibt_path, dbs):
    """With a faster stored reference, the debrief runs and its region
    diagnoses land in tracks.db with the comparison context."""
    import dataclasses

    from core.watcher.processor import parse_best_lap

    track_db, ref_store = dbs
    parsed = parse_best_lap(sample_ibt_path)
    assert parsed.best is not None
    # Uniformly 5% faster copy of the fixture's own best lap: identical
    # speed trace (alignment offset 0) but every metre costs less time,
    # so the driver "loses" everywhere -> loss regions exist.
    factor = 0.95
    faster = dataclasses.replace(
        parsed.best,
        lap_time=parsed.best.lap_time * factor,
        elapsed_time=parsed.best.elapsed_time * factor,
    )
    ref_store.save(
        str(parsed.session.track_id), parsed.session.car_name, faster,
        source="personal_best", driver_name="Ref Driver",
    )

    report = process_ibt(sample_ibt_path, track_db, ref_store)
    assert report.error is None
    assert report.debrief_text is not None
    assert report.diagnoses_recorded >= 1
    rows = track_db.list_region_diagnoses()
    assert len(rows) == report.diagnoses_recorded
    r0 = rows[0]
    assert r0.region_rank == 1
    assert r0.reference_source == "personal_best"
    assert r0.driver_lap_time == pytest.approx(parsed.best.lap_time)
    assert r0.reference_lap_time == pytest.approx(faster.lap_time)
    assert r0.time_lost_s > 0
```

Append to `tests/test_watch_telemetry_helpers.py` (it already imports `_format_report` and `SessionReport` — follow the existing import style in that file):

```python
def test_format_report_mentions_diagnoses_recorded():
    from pathlib import Path

    from core.watcher.processor import SessionReport
    from scripts.watch_telemetry import _format_report

    r = SessionReport(path=Path("x.ibt"), track="Spa", car="M2",
                      laps_found=5, valid_laps=4, best_lap_time=150.0,
                      diagnoses_recorded=3)
    assert "3 region diagnoses recorded" in _format_report(r)


def test_format_report_silent_when_no_diagnoses():
    from pathlib import Path

    from core.watcher.processor import SessionReport
    from scripts.watch_telemetry import _format_report

    r = SessionReport(path=Path("x.ibt"), track="Spa", car="M2",
                      laps_found=5, valid_laps=4, best_lap_time=150.0)
    assert "diagnoses" not in _format_report(r)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watcher_processor.py tests/test_watch_telemetry_helpers.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_best_lap'` / `TypeError: unexpected keyword argument 'diagnoses_recorded'`

- [ ] **Step 3: Implement**

In `core/watcher/processor.py`:

Add to imports: `from core.track.track_db import DiagnosisContext, TrackDB` (TrackDB is already imported — just add `DiagnosisContext`).

Add `diagnoses_recorded: int = 0` to `SessionReport` (after `promoted`).

Add the extracted helper ABOVE `process_ibt` (and delete the now-duplicated block inside `process_ibt`, replacing it with a call):

```python
@dataclass
class ParsedBestLap:
    """parse -> normalize -> plausibility, shared by watcher and back-fill.

    The plausibility/coverage gates are defined ONCE here; see
    test_short_coverage_lap_not_promoted for why they exist.
    """

    session: object            # IBT session metadata (track/car/driver)
    track_length_m: float
    lap_dfs: list
    valid: list                # normalizer-valid NormalizedLaps
    plausible: list            # valid + plausible time + full coverage
    best: object | None        # fastest plausible NormalizedLap


def parse_best_lap(path: Path) -> ParsedBestLap:
    """Parse an IBT and select its best plausible lap. Raises on parse
    failure — callers own their error policy."""
    parser = IBTParser()
    ibt = parser.parse(path)
    session = ibt.session
    track_length_m = session.track_length_km * 1000.0
    lap_dfs = parser.get_laps(ibt)
    lap_numbers = [int(df["Lap"].iloc[0]) for df in lap_dfs]
    laps = Normalizer().normalize_session(lap_dfs, lap_numbers, track_length_m)
    valid = [l for l in laps if l.is_valid]
    plausible = [
        l for l in valid
        if is_plausible_lap(l.lap_time, track_length_m)
        and covers_full_lap(
            float(l.distance[-1]) if len(l.distance) > 0 else 0.0,
            track_length_m,
        )
    ]
    best = min(plausible, key=lambda l: l.lap_time) if plausible else None
    return ParsedBestLap(
        session=session, track_length_m=track_length_m, lap_dfs=lap_dfs,
        valid=valid, plausible=plausible, best=best,
    )
```

In `process_ibt`, replace the block from `parser = IBTParser()` down to `report.best_lap_time = best.lap_time if best else None` with:

```python
        parsed = parse_best_lap(path)
        session = parsed.session
        track_id = str(session.track_id)
        track_length_m = parsed.track_length_m
        report.track = session.track_name
        report.car = session.car_name

        lap_dfs = parsed.lap_dfs
        report.laps_found = len(lap_dfs)
        valid = parsed.valid
        report.valid_laps = len(valid)
        plausible = parsed.plausible
        best = parsed.best
        report.best_lap_time = best.lap_time if best else None
```

(The rest of `process_ibt` — cleanliness, upsert, history, promotion, dirty note, debrief — is unchanged except the next edit. The `test_short_coverage_lap_not_promoted` monkeypatches of `proc_mod.IBTParser` / `proc_mod.Normalizer` keep working because `parse_best_lap` lives in the same module and resolves those names at call time.)

In the debrief block at the end, add persistence right after `result = build_debrief(...)`:

```python
        if ref is not None and not is_own_new_pb:
            corners = _load_corners(
                track_db, track_id, session.track_directory,
                track_length_m,
            )
            result = build_debrief(best, ref.lap, corners)
            track_db.record_region_diagnoses(
                session_id,
                DiagnosisContext(
                    driver_lap_number=best.lap_number,
                    driver_lap_time=best.lap_time,
                    reference_source=ref.source,
                    reference_lap_time=ref.meta.lap_time,
                    total_time_delta_s=result.total_time_delta,
                ),
                result.diagnoses,
            )
            report.diagnoses_recorded = len(result.diagnoses)
            report.debrief_text = format_lap_block(
                best.lap_number, best.lap_time,
                result.total_time_delta, result.diagnoses, top_n=3,
            )
        return report
```

In `scripts/watch_telemetry.py` `_format_report`, after the `if r.promoted:` block:

```python
    if r.diagnoses_recorded:
        lines.append(f"  {r.diagnoses_recorded} region diagnoses recorded")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watcher_processor.py tests/test_watch_telemetry_helpers.py -q`
Expected: PASS (new + all pre-existing; the fixture-dependent tests skip without sample.ibt)

- [ ] **Step 5: Commit**

```bash
git add core/watcher/processor.py scripts/watch_telemetry.py tests/test_watcher_processor.py tests/test_watch_telemetry_helpers.py
git commit -m 'feat(watcher): persist region diagnoses per session'
```

---

### Task 3: Back-fill script

**Files:**
- Create: `scripts/backfill_diagnoses.py`
- Test: `tests/test_backfill_diagnoses.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backfill_diagnoses.py`:

```python
"""Back-fill: re-debrief recorded history vs the CURRENT reference.

Pure-logic tests need no IBT; the end-to-end test uses the sample fixture
(skips gracefully when absent, like the processor tests).
"""

import dataclasses

import pytest

from core.benchmark.reference_store import ReferenceStore
from core.track.track_db import TrackDB
from scripts.backfill_diagnoses import backfill


@pytest.fixture
def dbs(tmp_path):
    return TrackDB(tmp_path / "tracks.db"), ReferenceStore(tmp_path / "refs.db")


def _record(db, session_id, session_type="practice", path="C:/nope/missing.ibt"):
    db.record_session(
        session_id=session_id, track_id="523", car="BMW M2",
        session_type=session_type, session_date="2026-07-01 10-00-00",
        best_lap_time=150.0, lap_count=5, ibt_file_path=path,
    )


def test_race_sessions_skipped(dbs):
    track_db, ref_store = dbs
    _record(track_db, "r1", session_type="Race")
    counts = backfill(track_db, ref_store)
    assert counts["skipped_race"] == 1
    assert counts["recorded"] == 0


def test_missing_files_skipped(dbs):
    track_db, ref_store = dbs
    _record(track_db, "p1")  # path does not exist
    counts = backfill(track_db, ref_store)
    assert counts["skipped_missing"] == 1
    assert counts["recorded"] == 0
    assert track_db.list_region_diagnoses() == []


def test_backfill_end_to_end(sample_ibt_path, dbs):
    from core.watcher.processor import parse_best_lap

    track_db, ref_store = dbs
    parsed = parse_best_lap(sample_ibt_path)
    assert parsed.best is not None
    track_id = str(parsed.session.track_id)
    car = parsed.session.car_name
    # The recorded session row must match the IBT's combo for the
    # reference lookup (record_session is INSERT OR REPLACE — idempotent).
    track_db.record_session(
        session_id="s1", track_id=track_id, car=car,
        session_type="practice", session_date="2026-07-01 10-00-00",
        best_lap_time=parsed.best.lap_time, lap_count=2,
        ibt_file_path=str(sample_ibt_path),
    )
    factor = 0.95
    faster = dataclasses.replace(
        parsed.best,
        lap_time=parsed.best.lap_time * factor,
        elapsed_time=parsed.best.elapsed_time * factor,
    )
    ref_store.save(track_id, car, faster, source="personal_best")

    # Dry run writes nothing
    counts = backfill(track_db, ref_store, dry_run=True)
    assert counts["recorded"] == 1
    assert track_db.list_region_diagnoses() == []

    # Real run writes rows; ReferenceStore untouched
    refs_before = ref_store.list_all()
    counts = backfill(track_db, ref_store)
    assert counts["recorded"] == 1
    rows = track_db.list_region_diagnoses()
    assert len(rows) >= 1
    assert rows[0].reference_source == "personal_best"
    assert ref_store.list_all() == refs_before

    # Idempotent rerun: same row count
    backfill(track_db, ref_store)
    assert len(track_db.list_region_diagnoses()) == len(rows)
```

NOTE (verified): `record_session` is `INSERT OR REPLACE` — idempotent per session_id. Same-PK replace is FK-safe for child rows (the laps table already relies on this; region_diagnoses children behave identically on watcher reruns).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backfill_diagnoses.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_diagnoses'`

- [ ] **Step 3: Implement `scripts/backfill_diagnoses.py`**

```python
"""Back-fill region diagnoses for recorded practice history.

Re-debriefs each recorded session's best plausible lap against the
CURRENT reference for its combo and persists the diagnoses (overwriting
any prior rows for that session — idempotent). Never promotes, never
touches sessions/laps rows, never writes to the ReferenceStore.

Measuring history against the current reference is deliberate: one
consistent yardstick per combo makes magnitude trends comparable;
reference_source/reference_lap_time on every row keep it honest.

    .venv/Scripts/python.exe scripts/backfill_diagnoses.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.benchmark.reference_store import ReferenceStore
from core.coaching.debrief import build_debrief
from core.track.track_db import DiagnosisContext, TrackDB
from core.watcher.processor import _load_corners, parse_best_lap

TRACKS_DB = Path("data/tracks.db")
REFS_DB = Path("data/reference_laps.db")


def backfill(
    track_db: TrackDB, ref_store: ReferenceStore, dry_run: bool = False
) -> dict[str, int]:
    """One pass over all recorded sessions. Returns skip/record counters."""
    counts = {
        "recorded": 0, "skipped_race": 0, "skipped_missing": 0,
        "skipped_no_ref": 0, "skipped_no_lap": 0, "failed": 0,
    }
    for row in track_db.list_session_history():
        name = Path(row.ibt_file_path).name if row.ibt_file_path else row.session_id
        if row.session_type == "Race":
            counts["skipped_race"] += 1
            continue
        if not row.ibt_file_path or not Path(row.ibt_file_path).exists():
            counts["skipped_missing"] += 1
            continue
        try:
            parsed = parse_best_lap(Path(row.ibt_file_path))
            if parsed.best is None:
                counts["skipped_no_lap"] += 1
                print(f"skip {name}: no plausible lap")
                continue
            ref = ref_store.get(row.track_id, row.car)
            if ref is None:
                counts["skipped_no_ref"] += 1
                print(f"skip {name}: no reference for combo")
                continue
            corners = _load_corners(
                track_db, row.track_id, parsed.session.track_directory,
                parsed.track_length_m,
            )
            result = build_debrief(parsed.best, ref.lap, corners)
            if not dry_run:
                track_db.record_region_diagnoses(
                    row.session_id,
                    DiagnosisContext(
                        driver_lap_number=parsed.best.lap_number,
                        driver_lap_time=parsed.best.lap_time,
                        reference_source=ref.source,
                        reference_lap_time=ref.meta.lap_time,
                        total_time_delta_s=result.total_time_delta,
                    ),
                    result.diagnoses,
                )
            counts["recorded"] += 1
            verb = "would record" if dry_run else "recorded"
            print(f"{verb} {len(result.diagnoses)} regions for {name}")
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the run
            counts["failed"] += 1
            print(f"FAILED {name}: {type(exc).__name__}: {exc}")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be recorded without writing")
    args = ap.parse_args()
    counts = backfill(TrackDB(TRACKS_DB), ReferenceStore(REFS_DB),
                      dry_run=args.dry_run)
    print()
    print("  ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backfill_diagnoses.py -q`
Expected: PASS (end-to-end test skips without the sample fixture)

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_diagnoses.py tests/test_backfill_diagnoses.py
git commit -m 'feat(watcher): history back-fill script for region diagnoses'
```

---

### Task 4: Technique tendencies (models + pure engine)

**Files:**
- Modify: `core/profile/models.py`
- Create: `core/profile/technique.py`
- Test: `tests/test_profile_technique.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_technique.py`:

```python
"""PURE technique-tendency engine over persisted diagnosis rows.

The coupling test is the contract: the adapter must classify a stored
row EXACTLY as the live coach classifies the equivalent RegionDiagnosis —
thresholds are imported from nudges, never re-implemented.
"""

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import (
    BRAKING_THRESHOLD_M,
    MIN_SPEED_THRESHOLD_MS,
    RELEASE_THRESHOLD_M,
    FaultKind,
    fault_kinds_from_diagnosis,
)
from core.profile.models import TECHNIQUE_MIN_SESSIONS, TechniqueTendencies
from core.profile.technique import _diagnosis_from_row, build_technique
from core.telemetry.loss_regions import LossRegion
from core.track.track_db import DiagnosisRow


def _row(session_id="s1", session_date="2026-07-01 10-00-00", track_id="523",
         car="M2", label="Eau Rouge", time_lost=0.5, braking=None,
         min_speed=0.0, throttle=None, release=None, exit_speed=0.0):
    return DiagnosisRow(
        session_id=session_id, track_id=track_id, track_name="Spa", car=car,
        session_type="practice", session_date=session_date,
        region_rank=1, label=label, distance_start_m=100.0,
        distance_end_m=250.0, time_lost_s=time_lost,
        braking_delta_m=braking, min_speed_delta_ms=min_speed,
        throttle_delta_m=throttle, brake_release_delta_m=release,
        exit_speed_delta_ms=exit_speed, driver_min_speed_ms=30.0,
        reference_min_speed_ms=32.0, driver_lap_number=3,
        driver_lap_time=150.0, reference_source="personal_best",
        reference_lap_time=148.0, total_time_delta_s=2.0,
    )


def test_adapter_matches_live_fault_ladder():
    """Same values through the adapter and through a hand-built
    RegionDiagnosis must classify identically."""
    row = _row(braking=BRAKING_THRESHOLD_M,
               min_speed=-MIN_SPEED_THRESHOLD_MS,
               release=-RELEASE_THRESHOLD_M)
    direct = RegionDiagnosis(
        region=LossRegion(100.0, 250.0, 0.5),
        label="Eau Rouge",
        braking_delta_m=BRAKING_THRESHOLD_M,
        min_speed_delta_ms=-MIN_SPEED_THRESHOLD_MS,
        throttle_delta_m=None,
        driver_min_speed_ms=30.0,
        reference_min_speed_ms=32.0,
        brake_release_delta_m=-RELEASE_THRESHOLD_M,
        exit_speed_delta_ms=0.0,
    )
    assert (fault_kinds_from_diagnosis(_diagnosis_from_row(row))
            == fault_kinds_from_diagnosis(direct))
    assert FaultKind.LIFT in fault_kinds_from_diagnosis(_diagnosis_from_row(row))


def test_empty_rows_gives_empty_tendencies():
    t = build_technique([])
    assert t == TechniqueTendencies()
    assert not t.enough_data


def test_dominant_fault_and_aggregates():
    rows = [
        _row(session_id=f"s{i}", session_date=f"2026-07-{i:02d} 10-00-00",
             car="M2" if i % 2 else "992", release=-RELEASE_THRESHOLD_M,
             time_lost=0.4)
        for i in range(1, 7)
    ]
    t = build_technique(rows)
    assert t.sessions_diagnosed == 6
    assert t.enough_data  # >= TECHNIQUE_MIN_SESSIONS (5)
    assert t.dominant == "release"
    f = t.faults[0]
    assert f.occurrences == 6
    assert f.combos == 2
    assert abs(f.mean_time_lost_s - 0.4) < 1e-9


def test_trend_requires_both_pools():
    # 5 sessions = all inside the recent window -> earlier pool empty -> None
    rows = [
        _row(session_id=f"s{i}", session_date=f"2026-07-{i:02d} 10-00-00",
             release=-RELEASE_THRESHOLD_M)
        for i in range(1, 6)
    ]
    assert build_technique(rows).faults[0].trend_time_lost_s is None
    # 7 sessions with shrinking losses -> negative trend
    rows = [
        _row(session_id=f"s{i}", session_date=f"2026-07-{i:02d} 10-00-00",
             release=-RELEASE_THRESHOLD_M,
             time_lost=1.0 if i <= 2 else 0.3)
        for i in range(1, 8)
    ]
    trend = build_technique(rows).faults[0].trend_time_lost_s
    assert trend is not None and trend < 0


def test_recurring_corners_exclude_position_fallback():
    rows = [
        _row(session_id="s1", label="Bruxelles", release=-RELEASE_THRESHOLD_M),
        _row(session_id="s2", label="Bruxelles", release=-RELEASE_THRESHOLD_M),
        _row(session_id="s3", label="~4.4 km from start/finish",
             release=-RELEASE_THRESHOLD_M),
        _row(session_id="s4", label="~4.4 km from start/finish",
             release=-RELEASE_THRESHOLD_M),
    ]
    t = build_technique(rows)
    assert ("Bruxelles", 2) in t.recurring_corners
    assert all(not label.startswith("~") for label, _ in t.recurring_corners)


def test_below_session_threshold_not_enough_data():
    rows = [
        _row(session_id=f"s{i}", session_date=f"2026-07-{i:02d} 10-00-00",
             release=-RELEASE_THRESHOLD_M)
        for i in range(1, TECHNIQUE_MIN_SESSIONS)
    ]
    t = build_technique(rows)
    assert not t.enough_data
    assert t.sessions_diagnosed == TECHNIQUE_MIN_SESSIONS - 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_technique.py -q`
Expected: FAIL — `ImportError: cannot import name 'TECHNIQUE_MIN_SESSIONS'`

- [ ] **Step 3: Implement**

In `core/profile/models.py`, add constants after `REPRESENTATIVE_FACTOR`:

```python
TECHNIQUE_MIN_SESSIONS = 5   # diagnosed sessions before technique speaks
TECHNIQUE_TREND_WINDOW = 5   # recent sessions vs everything before
TTP_FACTOR = 1.01            # time-to-pace: within 101% of session best
TTP_MIN_LAPS = 5             # sessions with fewer valid laps don't count
```

Add dataclasses after `ComboReadiness`:

```python
@dataclass
class FaultAggregate:
    """Cross-session aggregate for one FaultKind."""

    kind: str                        # FaultKind.value
    occurrences: int                 # regions where this fault crossed threshold
    combos: int                      # distinct (track_id, car) it appears in
    mean_time_lost_s: float
    trend_time_lost_s: float | None  # recent mean minus earlier mean
                                     # (negative = shrinking = improving);
                                     # None until both pools are non-empty


@dataclass
class TechniqueTendencies:
    """What the persisted loss-region corpus says about technique."""

    dominant: str | None = None
    faults: list[FaultAggregate] = field(default_factory=list)
    recurring_corners: list[tuple[str, int]] = field(default_factory=list)
    sessions_diagnosed: int = 0
    enough_data: bool = False


@dataclass
class TimeToPace:
    """Warm-up habit: how many laps until the driver is on pace."""

    median_laps: float | None = None
    sample_sessions: int = 0
    trend_laps: float | None = None  # negative = reaching pace sooner
    enough_data: bool = False
```

Add to `DriverProfile`:

```python
    technique: TechniqueTendencies = field(default_factory=TechniqueTendencies)
    time_to_pace: TimeToPace = field(default_factory=TimeToPace)
```

Create `core/profile/technique.py`:

```python
"""PURE cross-session technique tendencies from persisted region diagnoses.

The vocabulary is the live coach's FaultKind ladder: the adapter rebuilds
RegionDiagnosis objects from stored rows and classifies them with the SAME
fault_kinds_from_diagnosis used by cues and exit verdicts — the profile
can never disagree with the radio.
"""

from collections import Counter, defaultdict

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import fault_kinds_from_diagnosis
from core.profile.models import (
    RECURRING_CORNER_MIN,
    TECHNIQUE_MIN_SESSIONS,
    TECHNIQUE_TREND_WINDOW,
    FaultAggregate,
    TechniqueTendencies,
)
from core.telemetry.loss_regions import LossRegion
from core.track.track_db import DiagnosisRow


def _diagnosis_from_row(row: DiagnosisRow) -> RegionDiagnosis:
    """Rebuild the analysis dataclass from a stored row (deltas mapped 1:1;
    the live-prompt reference absolutes stay None — tendencies don't use
    them, and they were never persisted)."""
    return RegionDiagnosis(
        region=LossRegion(
            distance_start=row.distance_start_m,
            distance_end=row.distance_end_m,
            time_lost=row.time_lost_s,
        ),
        label=row.label,
        braking_delta_m=row.braking_delta_m,
        min_speed_delta_ms=row.min_speed_delta_ms,
        throttle_delta_m=row.throttle_delta_m,
        driver_min_speed_ms=row.driver_min_speed_ms,
        reference_min_speed_ms=row.reference_min_speed_ms,
        brake_release_delta_m=row.brake_release_delta_m,
        exit_speed_delta_ms=row.exit_speed_delta_ms,
    )


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def build_technique(rows: list[DiagnosisRow]) -> TechniqueTendencies:
    """Aggregate stored diagnosis rows into technique tendencies."""
    if not rows:
        return TechniqueTendencies()

    session_dates: dict[str, str] = {}
    for r in rows:
        session_dates.setdefault(r.session_id, r.session_date)
    ordered = sorted(session_dates, key=lambda s: session_dates[s])
    recent_ids = set(ordered[-TECHNIQUE_TREND_WINDOW:])
    earlier_ids = set(ordered[:-TECHNIQUE_TREND_WINDOW])

    occurrences: Counter = Counter()
    combos: dict[str, set] = defaultdict(set)
    losses: dict[str, list[float]] = defaultdict(list)
    recent_losses: dict[str, list[float]] = defaultdict(list)
    earlier_losses: dict[str, list[float]] = defaultdict(list)
    labels: Counter = Counter()

    for r in rows:
        # Position-fallback labels ("~4.4 km from start/finish") are not
        # a corner identity — never a "recurring corner".
        if not r.label.startswith("~"):
            labels[r.label] += 1
        for kind in fault_kinds_from_diagnosis(_diagnosis_from_row(r)):
            k = kind.value
            occurrences[k] += 1
            combos[k].add((r.track_id, r.car))
            losses[k].append(r.time_lost_s)
            if r.session_id in recent_ids:
                recent_losses[k].append(r.time_lost_s)
            elif r.session_id in earlier_ids:
                earlier_losses[k].append(r.time_lost_s)

    faults = [
        FaultAggregate(
            kind=k,
            occurrences=n,
            combos=len(combos[k]),
            mean_time_lost_s=_mean(losses[k]),
            trend_time_lost_s=(
                _mean(recent_losses[k]) - _mean(earlier_losses[k])
                if recent_losses[k] and earlier_losses[k] else None
            ),
        )
        for k, n in occurrences.items()
    ]
    faults.sort(key=lambda f: (-f.occurrences, -f.mean_time_lost_s))
    recurring = [(label, c) for label, c in labels.most_common()
                 if c >= RECURRING_CORNER_MIN]
    n_sessions = len(ordered)
    return TechniqueTendencies(
        dominant=faults[0].kind if faults else None,
        faults=faults,
        recurring_corners=recurring,
        sessions_diagnosed=n_sessions,
        enough_data=n_sessions >= TECHNIQUE_MIN_SESSIONS,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_technique.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/profile/models.py core/profile/technique.py tests/test_profile_technique.py
git commit -m 'feat(profile): technique tendencies from persisted diagnoses'
```

---

### Task 5: Time-to-pace

**Files:**
- Modify: `core/profile/pace.py`
- Test: `tests/test_profile_pace.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_pace.py` (reuse/extend the file's existing helpers for SessionRow/LapRow construction if present; otherwise these local helpers):

```python
from core.profile.models import TTP_MIN_LAPS, TimeToPace
from core.profile.pace import build_time_to_pace
from core.track.track_db import LapRow, SessionRow


def _session(sid, stype="practice", date="2026-07-01 10-00-00"):
    return SessionRow(
        session_id=sid, track_id="523", track_name="Spa", car="M2",
        session_type=stype, session_date=date, best_lap_time=110.0,
        lap_count=5,
    )


def _laps(times):
    return [LapRow(lap_number=i + 1, lap_time=t, is_valid=True)
            for i, t in enumerate(times)]


class TestTimeToPace:
    def test_ordinal_of_first_on_pace_lap(self):
        # best 110.0 -> cutoff 111.1; first lap <= cutoff is #3 (111.0)
        sessions = [_session("s1")]
        laps = {"s1": _laps([130.0, 115.0, 111.0, 110.0, 112.0])}
        t = build_time_to_pace(sessions, laps)
        assert t.median_laps == 3.0
        assert t.sample_sessions == 1

    def test_short_sessions_excluded(self):
        sessions = [_session("s1")]
        laps = {"s1": _laps([130.0, 110.0])}  # < TTP_MIN_LAPS
        assert len(laps["s1"]) < TTP_MIN_LAPS
        t = build_time_to_pace(sessions, laps)
        assert t.sample_sessions == 0
        assert t.median_laps is None

    def test_race_sessions_excluded(self):
        sessions = [_session("r1", stype="Race")]
        laps = {"r1": _laps([130.0, 115.0, 111.0, 110.0, 112.0])}
        t = build_time_to_pace(sessions, laps)
        assert t.sample_sessions == 0

    def test_invalid_laps_ignored_in_ordinal(self):
        sessions = [_session("s1")]
        rows = _laps([130.0, 115.0, 111.0, 110.0, 112.0])
        # An invalid crawl lap before everything must not shift ordinals
        rows.insert(0, LapRow(lap_number=0, lap_time=300.0, is_valid=False))
        t = build_time_to_pace(sessions, {"s1": rows})
        assert t.median_laps == 3.0

    def test_trend_needs_both_pools(self):
        # 5 qualifying sessions -> all recent, no earlier pool -> None
        sessions = [_session(f"s{i}", date=f"2026-07-{i:02d} 10-00-00")
                    for i in range(1, 6)]
        laps = {f"s{i}": _laps([130.0, 115.0, 111.0, 110.0, 112.0])
                for i in range(1, 6)}
        t = build_time_to_pace(sessions, laps)
        assert t.trend_laps is None
        assert t.enough_data  # sample 5 >= READINESS_MIN_SESSIONS

    def test_trend_negative_when_reaching_pace_sooner(self):
        # 7 sessions: early ones reach pace on lap 4, recent on lap 1
        sessions = [_session(f"s{i}", date=f"2026-07-{i:02d} 10-00-00")
                    for i in range(1, 8)]
        slow_warmup = _laps([130.0, 125.0, 120.0, 110.5, 110.0])
        fast_warmup = _laps([110.5, 110.0, 111.0, 112.0, 111.0])
        laps = {f"s{i}": (slow_warmup if i <= 2 else fast_warmup)
                for i in range(1, 8)}
        t = build_time_to_pace(sessions, laps)
        assert t.trend_laps is not None and t.trend_laps < 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_pace.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_time_to_pace'`

- [ ] **Step 3: Implement in `core/profile/pace.py`**

Extend the models import with `TTP_FACTOR, TTP_MIN_LAPS, TECHNIQUE_TREND_WINDOW, TimeToPace` and add `from statistics import median, stdev` (stdev already imported — extend it). Append:

```python
def build_time_to_pace(
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
) -> TimeToPace:
    """Median laps until the driver first laps within TTP_FACTOR of the
    session best. Practice sessions only; sessions shorter than
    TTP_MIN_LAPS valid laps don't count.

    Known caveat (accepted): ordinals count telemetry-valid laps only —
    true out-laps are usually normalizer-invalid and drop out, so
    "lap 3" means the third recorded flying-ish lap.
    """
    practice = [s for s in sessions if s.session_type != "Race"]
    ordinals: list[int] = []   # in session_date order
    for s in sorted(practice, key=lambda s: s.session_date):
        valid = sorted(
            (l for l in laps.get(s.session_id, []) if l.is_valid),
            key=lambda l: l.lap_number,
        )
        if len(valid) < TTP_MIN_LAPS:
            continue
        cutoff = min(l.lap_time for l in valid) * TTP_FACTOR
        for i, lap in enumerate(valid, start=1):
            if lap.lap_time <= cutoff:
                ordinals.append(i)
                break
    if not ordinals:
        return TimeToPace()
    recent = ordinals[-TECHNIQUE_TREND_WINDOW:]
    earlier = ordinals[:-TECHNIQUE_TREND_WINDOW]
    return TimeToPace(
        median_laps=float(median(ordinals)),
        sample_sessions=len(ordinals),
        trend_laps=(
            float(median(recent)) - float(median(earlier))
            if earlier else None
        ),
        enough_data=len(ordinals) >= READINESS_MIN_SESSIONS,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_pace.py -q`
Expected: PASS (new + pre-existing)

- [ ] **Step 5: Commit**

```bash
git add core/profile/pace.py tests/test_profile_pace.py
git commit -m 'feat(profile): time-to-pace warm-up diagnosis'
```

---

### Task 6: Render — verdicts, markdown, prompt block

**Files:**
- Modify: `core/profile/render.py`
- Test: `tests/test_profile_render.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_render.py`:

```python
from core.profile.models import (
    FaultAggregate,
    TechniqueTendencies,
    TimeToPace,
)
from core.profile.render import verdict_technique, verdict_time_to_pace


def _tech(trend=-0.12):
    return TechniqueTendencies(
        dominant="release",
        faults=[FaultAggregate(kind="release", occurrences=9, combos=4,
                               mean_time_lost_s=0.42,
                               trend_time_lost_s=trend)],
        recurring_corners=[("Bruxelles", 3)],
        sessions_diagnosed=12,
        enough_data=True,
    )


class TestVerdictTechnique:
    def test_shrinking(self):
        assert verdict_technique(_tech()) == (
            "Brake release is your recurring loss — 9 regions across "
            "4 combos, avg 0.4s each, shrinking (-0.1s recent). "
            "Repeat corners: Bruxelles (3x)."
        )

    def test_growing(self):
        assert "growing (+0.2s recent)" in verdict_technique(_tech(trend=0.2))

    def test_flat_trend_omitted(self):
        out = verdict_technique(_tech(trend=0.01))
        assert "shrinking" not in out and "growing" not in out

    def test_no_faults_empty(self):
        assert verdict_technique(TechniqueTendencies()) == ""


class TestVerdictTimeToPace:
    def test_basic(self):
        t = TimeToPace(median_laps=4.0, sample_sessions=78,
                       trend_laps=None, enough_data=True)
        assert verdict_time_to_pace(t) == (
            "You need ~4 laps to reach pace (78 sessions) — races give "
            "you zero warm-up."
        )

    def test_improving_trend(self):
        t = TimeToPace(median_laps=3.0, sample_sessions=10,
                       trend_laps=-1.5, enough_data=True)
        assert "Reaching pace sooner lately (-2 laps)." in verdict_time_to_pace(t)

    def test_empty(self):
        assert verdict_time_to_pace(TimeToPace()) == ""


def test_prompt_block_includes_technique_and_ttp():
    from core.profile.models import DriverProfile
    from core.profile.render import profile_prompt_block

    p = DriverProfile(
        cust_id=1, driver_name="A", races_captured=3,
        technique=_tech(),
        time_to_pace=TimeToPace(median_laps=4.0, sample_sessions=20,
                                enough_data=True),
    )
    block = profile_prompt_block(p)
    assert '"technique"' in block
    assert '"time_to_pace"' in block


def test_markdown_has_technique_section():
    from core.profile.models import DriverProfile
    from core.profile.render import profile_markdown

    md = profile_markdown(DriverProfile())
    assert "## Technique" in md
    assert "collecting data (0 of 5 diagnosed sessions)" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_render.py -q`
Expected: FAIL — `ImportError: cannot import name 'verdict_technique'`

- [ ] **Step 3: Implement in `core/profile/render.py`**

Extend the models import with `TECHNIQUE_MIN_SESSIONS, TechniqueTendencies, TimeToPace`. Add constants after `FADE_BAND_S`:

```python
TREND_BAND_S = 0.05          # |technique trend| below this = not worth saying
TTP_TREND_BAND_LAPS = 1.0    # |time-to-pace trend| below this = flat

_FAULT_LABEL = {
    "lift": "Carrying apex speed",
    "braking": "Brake point",
    "release": "Brake release",
    "exit_speed": "Corner exit speed",
    "throttle": "Throttle pickup",
}
```

Add verdicts after `verdict_readiness`:

```python
def verdict_technique(t: TechniqueTendencies) -> str:
    if not t.faults:
        return ""
    f = t.faults[0]
    line = (
        f"{_FAULT_LABEL.get(f.kind, f.kind)} is your recurring loss — "
        f"{_plural(f.occurrences, 'region')} across "
        f"{_plural(f.combos, 'combo')}, avg {f.mean_time_lost_s:.1f}s each"
    )
    trend = f.trend_time_lost_s
    if trend is not None and trend <= -TREND_BAND_S:
        line += f", shrinking ({trend:+.1f}s recent)"
    elif trend is not None and trend >= TREND_BAND_S:
        line += f", growing ({trend:+.1f}s recent)"
    line += "."
    if t.recurring_corners:
        repeats = ", ".join(f"{c} ({k}x)" for c, k in t.recurring_corners[:3])
        line += f" Repeat corners: {repeats}."
    return line


def verdict_time_to_pace(t: TimeToPace) -> str:
    if t.median_laps is None:
        return ""
    line = (
        f"You need ~{t.median_laps:.0f} laps to reach pace "
        f"({_plural(t.sample_sessions, 'session')}) — races give "
        "you zero warm-up."
    )
    trend = t.trend_laps
    if trend is not None and trend <= -TTP_TREND_BAND_LAPS:
        line += f" Reaching pace sooner lately ({trend:+.0f} laps)."
    elif trend is not None and trend >= TTP_TREND_BAND_LAPS:
        line += f" Taking longer lately ({trend:+.0f} laps)."
    return line
```

In `_tendency_payloads`, after the trajectory entry:

```python
    if p.technique.enough_data:
        out["technique"] = {"verdict": verdict_technique(p.technique),
                            "dominant": p.technique.dominant,
                            "sessions": p.technique.sessions_diagnosed}
    if p.time_to_pace.enough_data:
        out["time_to_pace"] = {"verdict": verdict_time_to_pace(p.time_to_pace),
                               "median_laps": p.time_to_pace.median_laps,
                               "sample": p.time_to_pace.sample_sessions}
    return out
```

(These are cross-SESSION facts, not race facts — same citation contract as readiness; the existing tone-contract wording already covers it because the payload states its own sample.)

In `profile_markdown`, before the `lines += ["", "## Practice readiness"]` line:

```python
    lines += ["", "## Technique"]
    if p.technique.enough_data:
        lines.append(f"- {verdict_technique(p.technique)}")
    else:
        lines.append(
            f"- Collecting data ({p.technique.sessions_diagnosed} of "
            f"{TECHNIQUE_MIN_SESSIONS} diagnosed sessions)."
        )
    if p.time_to_pace.enough_data:
        lines.append(f"- {verdict_time_to_pace(p.time_to_pace)}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_render.py -q`
Expected: PASS (new + pre-existing)

- [ ] **Step 5: Commit**

```bash
git add core/profile/render.py tests/test_profile_render.py
git commit -m 'feat(profile): technique + time-to-pace verdicts, prompt block, markdown'
```

---

### Task 7: Builder + Driver Profile page wiring

**Files:**
- Modify: `core/profile/builder.py`
- Modify: `app/pages/driver_profile.py`
- Test: `tests/test_profile_builder.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_builder.py` (follow the file's existing fixture style for stores; the tests below use real tmp DBs):

```python
from core.coaching.debrief import RegionDiagnosis
from core.race.race_store import RaceStore
from core.telemetry.loss_regions import LossRegion
from core.track.track_db import DiagnosisContext, TrackDB


def _seed_diagnosed_sessions(track_db, n):
    for i in range(1, n + 1):
        track_db.record_session(
            session_id=f"s{i}", track_id="523", car="M2",
            session_type="practice",
            session_date=f"2026-07-{i:02d} 10-00-00",
            best_lap_time=150.0, lap_count=5, ibt_file_path="",
        )
        track_db.record_region_diagnoses(
            f"s{i}",
            DiagnosisContext(driver_lap_number=2, driver_lap_time=150.0,
                             reference_source="personal_best",
                             reference_lap_time=148.0, total_time_delta_s=2.0),
            [RegionDiagnosis(
                region=LossRegion(100.0, 250.0, 0.8),
                label="Eau Rouge", braking_delta_m=None,
                min_speed_delta_ms=-3.0, throttle_delta_m=None,
                driver_min_speed_ms=30.0, reference_min_speed_ms=33.0,
                brake_release_delta_m=None, exit_speed_delta_ms=0.0,
            )],
        )


def test_profile_includes_technique_and_ttp(tmp_path):
    from core.profile.builder import load_profile

    track_db = TrackDB(tmp_path / "t.db")
    store = RaceStore(tmp_path / "r.db")
    _seed_diagnosed_sessions(track_db, 6)
    p = load_profile(store, track_db, cust_id=1)
    assert p.technique.enough_data
    assert p.technique.dominant == "lift"   # -3.0 m/s min-speed deficit
    assert p.technique.sessions_diagnosed == 6
    # No lap rows recorded -> time_to_pace stays empty but present
    assert p.time_to_pace.sample_sessions == 0


def test_diagnosis_load_failure_degrades_to_empty(tmp_path, monkeypatch):
    from core.profile.builder import load_profile

    track_db = TrackDB(tmp_path / "t.db")
    store = RaceStore(tmp_path / "r.db")

    def _boom(self):
        raise RuntimeError("db locked")

    monkeypatch.setattr(TrackDB, "list_region_diagnoses", _boom)
    p = load_profile(store, track_db, cust_id=1)
    assert p.technique.sessions_diagnosed == 0
    assert not p.technique.enough_data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_builder.py -q`
Expected: FAIL — `AttributeError` / assertion on `p.technique` (builder doesn't populate it yet)

- [ ] **Step 3: Implement**

In `core/profile/builder.py`, add imports:

```python
from core.profile.pace import build_readiness, build_time_to_pace
from core.profile.technique import build_technique
```

In `load_profile`, add a third guarded load after the session-history load:

```python
    try:
        diagnoses = track_db.list_region_diagnoses()
    except Exception:  # noqa: BLE001
        logger.exception("Profile: diagnosis load failed")
        diagnoses = []
```

Extend the return:

```python
    return DriverProfile(
        cust_id=cust_id,
        driver_name=(narratives[0].header.driver_name if narratives else ""),
        races_captured=len(narratives),
        combos_tracked=len(readiness),
        racecraft=build_racecraft(narratives),
        readiness=readiness,
        technique=build_technique(diagnoses),
        time_to_pace=build_time_to_pace(sessions, laps),
    )
```

In `app/pages/driver_profile.py` (display only, house rule), add imports `TECHNIQUE_MIN_SESSIONS` from `core.profile.models` and `verdict_technique, verdict_time_to_pace` from `core.profile.render`. Insert between the Racecraft loop and `st.subheader("Practice readiness")`:

```python
    st.subheader("Technique")
    tech = profile.technique
    with st.container(border=True):
        st.markdown("**Recurring loss**")
        if tech.enough_data:
            st.write(verdict_technique(tech))
            st.caption(f"Across {tech.sessions_diagnosed} diagnosed sessions.")
        else:
            st.caption(
                f"Collecting data — {tech.sessions_diagnosed} of "
                f"{TECHNIQUE_MIN_SESSIONS} diagnosed sessions. Practice "
                "sessions are diagnosed automatically by the telemetry "
                "watcher once a reference lap exists for the combo."
            )
    ttp = profile.time_to_pace
    if ttp.enough_data:
        with st.container(border=True):
            st.markdown("**Warm-up**")
            st.write(verdict_time_to_pace(ttp))
            st.caption(f"Across {ttp.sample_sessions} practice sessions.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_builder.py -q`
Expected: PASS (new + pre-existing)

- [ ] **Step 5: Commit**

```bash
git add core/profile/builder.py app/pages/driver_profile.py tests/test_profile_builder.py
git commit -m 'feat(profile): wire technique + time-to-pace into builder and page'
```

---

### Task 8: Full suite, docs, wrap-up

**Files:**
- Modify: `CLAUDE.md` (status section)

- [ ] **Step 1: Run the FULL test suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (fixture-dependent tests may skip). Fix any regression before proceeding — likely suspects: `SessionRow` construction sites missing the new field (it's defaulted, so none expected), profile page imports.

- [ ] **Step 2: Update CLAUDE.md**

Add a status section after the "Exit Verdict Cues" block:

```markdown
**Loss-Region Persistence + Technique Tendencies** (complete, branch loss-region-persistence — spec docs/superpowers/specs/2026-07-17-progression-loss-region-persistence-design.md, plan docs/superpowers/plans/2026-07-17-loss-region-persistence.md)
- [x] region_diagnoses table in tracks.db (typed rows, no blobs; DELETE+INSERT idempotent keyed session_id; reference_source/lap_time context per row) + SessionRow.ibt_file_path
- [x] Watcher persists the best-lap debrief's diagnoses (`diagnoses_recorded` on SessionReport; CLI prints it); watcher-only write path — coaching page + live coach stay read-only (locked)
- [x] scripts/backfill_diagnoses.py — re-debriefs recorded practice history vs the CURRENT reference per combo (consistent yardstick, deliberate); never promotes, idempotent, --dry-run
- [x] core/profile/technique.py — PURE; adapter row→RegionDiagnosis classified by the live FaultKind ladder (fault_kinds_from_diagnosis — one ranking, three consumers, coupling-tested); dominant fault + per-fault aggregates/trends + recurring corners (position-fallback "~" labels excluded); unlocks at TECHNIQUE_MIN_SESSIONS=5
- [x] Time-to-pace in core/profile/pace.py — median laps to reach 101% of session best (TTP_FACTOR, TTP_MIN_LAPS=5); the first behavioral diagnosis (races give zero warm-up laps)
- [x] Profile wiring: DriverProfile.technique/.time_to_pace, Technique section on the page, prompt-block payloads (enough_data-gated)
- [ ] Run the back-fill on the rig (founder: `.venv/Scripts/python.exe scripts/backfill_diagnoses.py --dry-run` first)
- [ ] Post-Fable: progression page, pace-implied iR, prescription seed table (spec §6–8)
```

Also update the tests list in CLAUDE.md's architecture tree (add `test_backfill_diagnoses.py`, `test_profile_technique.py`) and the `scripts/` tree entry for `backfill_diagnoses.py`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m 'docs: loss-region persistence status'
```

---

## Self-review notes (already applied)

- Spec coverage: §1→Task 1, §2→Task 2, §3→Task 3, §4→Task 4 (+6/7 wiring), §5→Task 5 (+6/7 wiring), §9 testing→embedded per task. §6–8 are spec-only by design.
- Type consistency: `DiagnosisContext`/`DiagnosisRow`/`parse_best_lap`/`ParsedBestLap`/`build_technique`/`build_time_to_pace` names used identically across tasks.
- Task 3's `record_session` semantics verified against the real SQL (INSERT OR REPLACE).
```
