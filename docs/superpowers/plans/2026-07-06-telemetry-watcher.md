# Telemetry Watcher (Stage 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A scan command (`--watch` optional) that processes new IBT files: records session/lap history, auto-promotes personal bests into the ReferenceStore, and prints a debrief of each session's best lap.

**Architecture:** Pure discovery/promotion logic in `core/watcher/scanner.py`; per-file pipeline (parse → normalize → record → promote → debrief) in `core/watcher/processor.py`; thin CLI in `scripts/watch_telemetry.py`. Three new TrackDB methods activate the dormant `sessions`/`laps` tables.

**Tech Stack:** Python 3.14, existing project modules only — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-06-telemetry-watcher-design.md` (read it first)

**Run tests with:** `.venv/Scripts/python.exe -m pytest <file> -q` (uv is NOT on PATH; the venv has NO pip — if you ever need to install something, use `%APPDATA%\Python\Python314\Scripts\uv.exe`, but this plan needs no installs).

**Environment notes for the implementer:**
- Windows. Never run `git checkout`/`git switch`; work on the branch you are given.
- Key existing interfaces (verify by reading, signatures current as of 2026-07-06):
  - `IBTParser().parse(path) -> IBTFile` with `.session` (`track_id: int`, `track_name`, `track_directory` — the slug source, `track_length_km`, `car_name`, `driver_name`, `session_type`) and `parser.get_laps(ibt) -> list[pd.DataFrame]` (`core/telemetry/ibt_parser.py`)
  - `Normalizer().normalize_session(lap_dfs, lap_numbers, track_length_m) -> list[NormalizedLap]` (`core/telemetry/normalizer.py`); lap numbers come from `int(df["Lap"].iloc[0])`
  - `ReferenceStore(db_path)`: `.get(track_id, car) -> ReferenceLap | None` (prefers g61), `.save(track_id, car, lap, source, driver_name)` upserts per source, `.list_all() -> list[ReferenceLapMeta]` (`core/benchmark/reference_store.py`)
  - `build_debrief(driver, reference, corners) -> DebriefAnalysis`; `format_lap_block(lap_number, lap_time, total_delta, diagnoses, top_n=2, is_baseline=False) -> str`
  - `TrackDB(db_path)`: `get_track`, `upsert_track`, `get_corners`; `seed_track_from_lovely(db, track_id=..., ibt_track_name=..., track_length_m=...) -> int` (raises/returns 0 on failure)
  - `Track(track_id, name, config, length_meters, track_type=TrackType.ROAD, character=None)` (`core/track/models.py`)

---

### Task 0: Branch

- [ ] **Step 1:**

```bash
git checkout -b telemetry-watcher
```

(This is the ONLY permitted checkout — creating the feature branch at the very start.)

---

### Task 1: TrackDB session-history methods

**Files:**
- Modify: `core/track/track_db.py`
- Test: `tests/test_track_db.py`

The `sessions`/`laps` tables exist in `_init_db` (lines 55–75) but have no methods. Add three.

- [ ] **Step 1: Write the failing tests.** Read `tests/test_track_db.py` first and match its fixture style (it uses a tmp_path DB). Append:

```python
def test_record_session_and_processed_paths(tmp_path):
    db = TrackDB(tmp_path / "t.db")
    db.record_session(
        session_id="bmwm2g87_spa 2026-07-05 16-32-53",
        track_id="525", car="BMW M2 Racing (G87)", session_type="Practice",
        session_date="2026-07-05T16:32:53", best_lap_time=161.384,
        lap_count=16, ibt_file_path="C:/tel/bmwm2g87_spa.ibt",
    )
    assert db.processed_ibt_paths() == {"C:/tel/bmwm2g87_spa.ibt"}


def test_record_session_is_idempotent(tmp_path):
    db = TrackDB(tmp_path / "t.db")
    for best in (161.384, 160.9):  # rerun with updated data replaces
        db.record_session(
            session_id="s1", track_id="525", car="M2", session_type="Practice",
            session_date="2026-07-05T16:32:53", best_lap_time=best,
            lap_count=16, ibt_file_path="C:/tel/a.ibt",
        )
    assert db.processed_ibt_paths() == {"C:/tel/a.ibt"}  # one row, not two


def test_record_laps_replaces_on_rerun(tmp_path):
    db = TrackDB(tmp_path / "t.db")
    db.record_session(
        session_id="s1", track_id="525", car="M2", session_type="Practice",
        session_date="d", best_lap_time=100.0, lap_count=2,
        ibt_file_path="p",
    )
    db.record_laps("s1", [(1, 101.0, True), (2, 100.0, True)])
    db.record_laps("s1", [(1, 101.0, True), (2, 100.0, True), (3, 99.5, True)])
    conn = db._get_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM laps WHERE session_id = 's1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 3  # replaced, not appended to 5


def test_processed_paths_empty_on_fresh_db(tmp_path):
    assert TrackDB(tmp_path / "t.db").processed_ibt_paths() == set()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_db.py -q`
Expected: 4 new FAIL (`no attribute 'record_session'`), existing PASS.

- [ ] **Step 3: Implement** — add a new section after the corner methods in `core/track/track_db.py`:

```python
    # --- Session history (populated by the telemetry watcher) ---

    def record_session(
        self,
        session_id: str,
        track_id: str,
        car: str,
        session_type: str,
        session_date: str,
        best_lap_time: float | None,
        lap_count: int,
        ibt_file_path: str,
    ) -> None:
        """Insert or replace one session-history row (idempotent per id)."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions
                    (session_id, track_id, car, session_type, session_date,
                     best_lap_time, lap_count, ibt_file_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, track_id, car, session_type, session_date,
                 best_lap_time, lap_count, ibt_file_path),
            )
            conn.commit()
        finally:
            conn.close()

    def record_laps(
        self, session_id: str, laps: list[tuple[int, float, bool]]
    ) -> None:
        """Replace the lap rows for a session (idempotent on rerun).

        Args:
            laps: (lap_number, lap_time, is_valid) tuples.
        """
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM laps WHERE session_id = ?", (session_id,))
            conn.executemany(
                "INSERT INTO laps (session_id, lap_number, lap_time, is_valid)"
                " VALUES (?, ?, ?, ?)",
                [(session_id, n, t, v) for n, t, v in laps],
            )
            conn.commit()
        finally:
            conn.close()

    def processed_ibt_paths(self) -> set[str]:
        """Every ibt_file_path already recorded — the watcher's dedupe set."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT ibt_file_path FROM sessions"
                " WHERE ibt_file_path IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows}
```

- [ ] **Step 4: Run to green**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_db.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/track/track_db.py tests/test_track_db.py
git commit -m "feat: session-history methods on TrackDB (record_session, record_laps, processed paths)"
```

---

### Task 2: Scanner — discovery, stability, dedupe, promotion decision (pure)

**Files:**
- Create: `core/watcher/__init__.py` (empty)
- Create: `core/watcher/scanner.py`
- Test: `tests/test_watcher_scanner.py`

- [ ] **Step 1: Create `tests/test_watcher_scanner.py`:**

```python
"""Tests for the pure watcher discovery/promotion logic."""

from pathlib import Path

from core.watcher.scanner import IbtCandidate, find_new_ibts, should_promote

NOW = 1_000_000.0


def _c(name: str, age_s: float) -> IbtCandidate:
    return IbtCandidate(path=Path(f"C:/tel/{name}"), mtime=NOW - age_s)


def test_fresh_file_excluded_by_stability_window():
    out = find_new_ibts([_c("a.ibt", 30.0)], processed=set(), now=NOW)
    assert out == []


def test_old_file_included():
    out = find_new_ibts([_c("a.ibt", 120.0)], processed=set(), now=NOW)
    assert [c.path.name for c in out] == ["a.ibt"]


def test_stability_boundary_is_min_age():
    exactly = find_new_ibts([_c("a.ibt", 90.0)], processed=set(), now=NOW)
    just_under = find_new_ibts([_c("a.ibt", 89.9)], processed=set(), now=NOW)
    assert [c.path.name for c in exactly] == ["a.ibt"]  # >= min_age is stable
    assert just_under == []


def test_processed_paths_deduped():
    cand = _c("a.ibt", 120.0)
    out = find_new_ibts([cand], processed={str(cand.path)}, now=NOW)
    assert out == []


def test_results_ordered_oldest_first():
    out = find_new_ibts(
        [_c("new.ibt", 100.0), _c("old.ibt", 5000.0)], processed=set(), now=NOW
    )
    assert [c.path.name for c in out] == ["old.ibt", "new.ibt"]


def test_should_promote_when_no_existing_pb():
    assert should_promote(best_lap_time=100.0, existing_pb_time=None)


def test_should_promote_when_faster():
    assert should_promote(best_lap_time=99.9, existing_pb_time=100.0)


def test_no_promote_when_slower_or_equal():
    assert not should_promote(best_lap_time=100.1, existing_pb_time=100.0)
    assert not should_promote(best_lap_time=100.0, existing_pb_time=100.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watcher_scanner.py -q`
Expected: FAIL — `No module named 'core.watcher'`.

- [ ] **Step 3: Create `core/watcher/__init__.py`** (empty file) **and `core/watcher/scanner.py`:**

```python
"""Pure discovery and promotion logic for the telemetry watcher.

No filesystem access here — the CLI gathers (path, mtime) tuples and the
sessions-table dedupe set; this module only decides. That keeps the whole
risk surface (stability windows, ordering, promotion policy) unit-testable.
"""

from dataclasses import dataclass
from pathlib import Path

# A file modified in the last MIN_AGE_S seconds is assumed still being
# written by iRacing (it appends to the .ibt for the whole session).
MIN_AGE_S = 90.0


@dataclass
class IbtCandidate:
    """One .ibt file as seen by the CLI's folder listing."""

    path: Path
    mtime: float


def find_new_ibts(
    candidates: list[IbtCandidate],
    processed: set[str],
    now: float,
    min_age_s: float = MIN_AGE_S,
) -> list[IbtCandidate]:
    """Unprocessed, write-stable candidates, oldest first."""
    fresh = [
        c for c in candidates
        if str(c.path) not in processed and (now - c.mtime) >= min_age_s
    ]
    return sorted(fresh, key=lambda c: c.mtime)


def should_promote(
    best_lap_time: float, existing_pb_time: float | None
) -> bool:
    """Promote when there is no personal_best yet, or this lap is strictly
    faster. (g61 rows are untouchable by construction — the watcher only
    ever writes source='personal_best'.)"""
    return existing_pb_time is None or best_lap_time < existing_pb_time
```

- [ ] **Step 4: Run to green**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watcher_scanner.py -q`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/watcher/__init__.py core/watcher/scanner.py tests/test_watcher_scanner.py
git commit -m "feat: watcher scanner - stability window, dedupe, promotion policy"
```

---

### Task 3: Processor — per-file pipeline

**Files:**
- Create: `core/watcher/processor.py`
- Test: `tests/test_watcher_processor.py`

- [ ] **Step 1: Create `tests/test_watcher_processor.py`.** These use the real sample IBT fixture and skip when absent — read `tests/conftest.py` first to find the existing `sample_ibt_path` fixture and reuse it (do NOT invent a new fixture-discovery mechanism):

```python
"""End-to-end tests for the watcher's per-file pipeline.

Uses the real sample IBT fixture (skips gracefully when absent),
with throwaway tmp databases.
"""

import numpy as np
import pytest

from core.benchmark.reference_store import ReferenceStore
from core.telemetry.normalizer import NormalizedLap
from core.track.track_db import TrackDB
from core.watcher.processor import SessionReport, process_ibt


@pytest.fixture
def dbs(tmp_path):
    return TrackDB(tmp_path / "tracks.db"), ReferenceStore(tmp_path / "refs.db")


def test_corrupt_file_returns_error_report(tmp_path, dbs):
    track_db, ref_store = dbs
    bad = tmp_path / "bad.ibt"
    bad.write_bytes(b"not an ibt file")
    report = process_ibt(bad, track_db, ref_store)
    assert isinstance(report, SessionReport)
    assert report.error is not None
    # A failed file must NOT be marked processed (it retries next scan)
    assert track_db.processed_ibt_paths() == set()


def test_process_records_promotes_and_reports(sample_ibt_path, dbs):
    track_db, ref_store = dbs
    report = process_ibt(sample_ibt_path, track_db, ref_store)

    assert report.error is None
    assert report.valid_laps >= 1
    assert report.best_lap_time is not None and report.best_lap_time > 0
    # Session recorded -> path is now deduped
    assert str(sample_ibt_path) in track_db.processed_ibt_paths()
    # First session at this combo -> PB promoted
    assert report.promoted
    metas = ref_store.list_all()
    assert len(metas) == 1
    assert metas[0].source == "personal_best"
    assert metas[0].lap_time == pytest.approx(report.best_lap_time)
    # First-ever reference is the lap itself -> baseline wording, no debrief
    assert report.debrief_text is None


def test_rerun_does_not_repromote(sample_ibt_path, dbs):
    track_db, ref_store = dbs
    process_ibt(sample_ibt_path, track_db, ref_store)
    second = process_ibt(sample_ibt_path, track_db, ref_store)
    assert second.error is None
    assert not second.promoted  # equal time is not strictly faster


def test_debrief_against_preseeded_faster_reference(sample_ibt_path, dbs):
    track_db, ref_store = dbs
    # Pre-seed a faster synthetic g61 reference for the same combo.
    from core.telemetry.ibt_parser import IBTParser

    session = IBTParser().parse(sample_ibt_path).session
    n = int(session.track_length_km * 1000)
    z = np.zeros(n)
    fast = NormalizedLap(
        lap_number=0, lap_time=1.0, track_length=float(n),
        distance=np.arange(n, dtype=float), speed=np.full(n, 80.0),
        throttle=np.ones(n), brake=z, steering=z, gear=np.full(n, 5),
        rpm=np.full(n, 7000.0), lat=z, lon=z,
        elapsed_time=np.cumsum(np.full(n, 1.0 / 80.0)), is_valid=True,
    )
    ref_store.save(str(session.track_id), session.car_name, fast,
                   source="g61", driver_name="Synthetic")

    report = process_ibt(sample_ibt_path, track_db, ref_store)
    assert report.error is None
    assert report.debrief_text is not None
    assert "Lap" in report.debrief_text
    # PB still promoted alongside (separate source row, g61 untouched)
    sources = {m.source for m in ref_store.list_all()}
    assert sources == {"g61", "personal_best"}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watcher_processor.py -q`
Expected: FAIL — `No module named 'core.watcher.processor'`.

- [ ] **Step 3: Create `core/watcher/processor.py`:**

```python
"""Per-file watcher pipeline: parse -> normalize -> record -> promote -> debrief.

One IBT file in, one SessionReport out. Any exception is caught into the
report — a corrupt or half-written file must never abort a folder scan,
and a failed file is NOT recorded as processed, so it retries next scan.
"""

from dataclasses import dataclass
from pathlib import Path

from core.benchmark.reference_store import ReferenceStore
from core.coaching.debrief import build_debrief
from core.live.nudges import format_lap_block
from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer
from core.track.lovely_seeder import seed_track_from_lovely
from core.track.models import Track, TrackType
from core.track.track_db import TrackDB
from core.watcher.scanner import should_promote


@dataclass
class SessionReport:
    """What one processed IBT produced; the CLI prints it, tests assert it."""

    path: Path
    track: str = ""
    car: str = ""
    laps_found: int = 0
    valid_laps: int = 0
    best_lap_time: float | None = None
    promoted: bool = False
    debrief_text: str | None = None
    error: str | None = None


def _load_corners(
    track_db: TrackDB,
    track_id: str,
    track_directory: str,
    track_length_m: float,
    track_display: str,
) -> list:
    """Named corners, creating the track row and lazy-seeding on first use.

    Mirrors the live coach's connect-time behavior: lovely-track-data
    first (slug from the directory string), silently degrading to
    whatever the DB already has.
    """
    if not track_id:
        return []
    if track_db.get_track(track_id) is None:
        track_db.upsert_track(Track(
            track_id=track_id, name=track_display, config=None,
            length_meters=track_length_m, track_type=TrackType.ROAD,
            character=None,
        ))
    corners = track_db.get_corners(track_id)
    if not corners:
        try:
            seed_track_from_lovely(
                track_db, track_id=track_id,
                ibt_track_name=track_directory,
                track_length_m=track_length_m,
            )
            corners = track_db.get_corners(track_id)
        except Exception:
            corners = []
    return corners


def process_ibt(
    path: Path, track_db: TrackDB, ref_store: ReferenceStore
) -> SessionReport:
    """Process one IBT file end-to-end. Never raises."""
    report = SessionReport(path=path)
    try:
        parser = IBTParser()
        ibt = parser.parse(path)
        session = ibt.session
        track_id = str(session.track_id)
        track_length_m = session.track_length_km * 1000.0
        report.track = session.track_name
        report.car = session.car_name

        lap_dfs = parser.get_laps(ibt)
        lap_numbers = [int(df["Lap"].iloc[0]) for df in lap_dfs]
        laps = Normalizer().normalize_session(
            lap_dfs, lap_numbers, track_length_m
        )
        report.laps_found = len(laps)
        valid = [l for l in laps if l.is_valid]
        report.valid_laps = len(valid)

        best = min(valid, key=lambda l: l.lap_time) if valid else None
        report.best_lap_time = best.lap_time if best else None

        # History rows first — recording marks the file processed even for
        # an empty session (so it doesn't rescan forever).
        session_id = path.stem
        track_db.record_session(
            session_id=session_id,
            track_id=track_id,
            car=session.car_name,
            session_type=session.session_type or "unknown",
            session_date=path.stem[-19:],  # iRacing stamps the filename
            best_lap_time=report.best_lap_time,
            lap_count=len(valid),
            ibt_file_path=str(path),
        )
        track_db.record_laps(
            session_id,
            [(l.lap_number, l.lap_time, bool(l.is_valid)) for l in valid],
        )

        if best is None:
            return report

        # Promotion: compare against the existing personal_best ONLY —
        # a faster g61 lap must not block recording the driver's own PB.
        existing_pb = next(
            (m for m in ref_store.list_all()
             if m.track_id == track_id and m.car == session.car_name
             and m.source == "personal_best"),
            None,
        )
        if should_promote(
            best.lap_time,
            existing_pb.lap_time if existing_pb else None,
        ):
            ref_store.save(
                track_id, session.car_name, best,
                source="personal_best", driver_name=session.driver_name,
            )
            report.promoted = True

        # Debrief the best lap against the best available reference —
        # unless that reference IS the lap we just promoted (first session
        # at a combo: nothing meaningful to compare against).
        ref = ref_store.get(track_id, session.car_name)
        is_own_new_pb = (
            report.promoted and ref is not None
            and ref.source == "personal_best"
        )
        if ref is not None and not is_own_new_pb:
            corners = _load_corners(
                track_db, track_id, session.track_directory,
                track_length_m, session.track_name,
            )
            result = build_debrief(best, ref.lap, corners)
            report.debrief_text = format_lap_block(
                best.lap_number, best.lap_time,
                result.total_time_delta, result.diagnoses, top_n=3,
            )
        return report
    except Exception as exc:
        report.error = f"{type(exc).__name__}: {exc}"
        return report
```

- [ ] **Step 4: Run to green**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watcher_processor.py -q`
Expected: 4 PASS (or 3 SKIP + 1 PASS if the sample fixture is absent — the corrupt-file test never skips).

NOTE for the implementer: `test_rerun_does_not_repromote` depends on equal-time laps not re-promoting; if the debrief in the rerun compares the lap against its own promoted copy and produces a spurious `debrief_text`, that is ACCEPTABLE (aligned identical laps produce ~zero delta and no diagnoses) — the assertion is only about `promoted`.

- [ ] **Step 5: Commit**

```bash
git add core/watcher/processor.py tests/test_watcher_processor.py
git commit -m "feat: watcher processor - record history, promote PBs, debrief vs reference"
```

---

### Task 4: CLI — scan once or watch

**Files:**
- Create: `scripts/watch_telemetry.py`
- Test: `tests/test_watch_telemetry_helpers.py`

- [ ] **Step 1: Create `tests/test_watch_telemetry_helpers.py`** (importlib pattern copied from `tests/test_live_coach_helpers.py`):

```python
"""Tests for the pure helpers in scripts/watch_telemetry.py."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "watch_telemetry",
    Path(__file__).resolve().parent.parent / "scripts" / "watch_telemetry.py",
)
watch_telemetry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch_telemetry)


def test_gather_candidates_lists_only_ibt(tmp_path):
    (tmp_path / "a.ibt").write_bytes(b"x")
    (tmp_path / "b.txt").write_bytes(b"x")
    (tmp_path / "c.ibt").write_bytes(b"x")
    cands = watch_telemetry._gather_candidates(tmp_path)
    assert sorted(c.path.name for c in cands) == ["a.ibt", "c.ibt"]
    assert all(c.mtime > 0 for c in cands)


def test_gather_candidates_missing_folder_returns_none(tmp_path):
    assert watch_telemetry._gather_candidates(tmp_path / "nope") is None


def test_format_report_success():
    from core.watcher.processor import SessionReport

    r = SessionReport(path=Path("C:/tel/x.ibt"), track="Spa", car="M2",
                      laps_found=8, valid_laps=6, best_lap_time=161.384,
                      promoted=True, debrief_text="Lap 7  (2:41.384, +2.2s)")
    text = watch_telemetry._format_report(r)
    assert "Spa" in text and "M2" in text
    assert "2:41.384" in text
    assert "PB promoted" in text


def test_format_report_error():
    from core.watcher.processor import SessionReport

    r = SessionReport(path=Path("C:/tel/bad.ibt"), error="ValueError: nope")
    text = watch_telemetry._format_report(r)
    assert "bad.ibt" in text and "nope" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watch_telemetry_helpers.py -q`
Expected: FAIL — script missing.

- [ ] **Step 3: Create `scripts/watch_telemetry.py`:**

```python
"""Telemetry watcher — Stage 3.

Scan the iRacing telemetry folder for new IBT files; for each one:
record session/lap history, auto-promote a personal best into the
ReferenceStore, and print a debrief of the session's best lap.

    .venv/Scripts/python.exe scripts/watch_telemetry.py            # scan once
    .venv/Scripts/python.exe scripts/watch_telemetry.py --watch    # keep polling

All real logic lives in tested modules under core/watcher/; this file
only does argv, folder listing, and printing.
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure project root on path when run as a script.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.benchmark.reference_store import ReferenceStore  # noqa: E402
from core.track.track_db import TrackDB  # noqa: E402
from core.watcher.processor import SessionReport, process_ibt  # noqa: E402
from core.watcher.scanner import IbtCandidate, find_new_ibts  # noqa: E402

TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")
DB_PATH = Path("data/tracks.db")
REFERENCE_DB = Path("data/reference_laps.db")
POLL_SECONDS = 30.0


def _gather_candidates(folder: Path) -> "list[IbtCandidate] | None":
    """(path, mtime) for every .ibt in the folder; None if folder missing."""
    if not folder.is_dir():
        return None
    return [
        IbtCandidate(path=p, mtime=p.stat().st_mtime)
        for p in folder.glob("*.ibt")
    ]


def _format_report(r: SessionReport) -> str:
    """One printable block per processed file."""
    if r.error is not None:
        return f"FAILED {r.path.name}: {r.error} (will retry next scan)"
    lines = [
        f"{r.path.name}",
        f"  {r.track} - {r.car}: "
        f"{r.valid_laps}/{r.laps_found} valid laps"
        + (
            f", best {int(r.best_lap_time // 60)}:"
            f"{r.best_lap_time % 60:06.3f}"
            if r.best_lap_time is not None else ", no valid laps"
        ),
    ]
    if r.promoted:
        lines.append("  PB promoted to ReferenceStore")
    if r.debrief_text:
        lines.append("")
        lines.append(r.debrief_text)
    return "\n".join(lines)


def _scan_once(folder: Path) -> int:
    """One pass. Returns number of files processed (0 is fine)."""
    candidates = _gather_candidates(folder)
    if candidates is None:
        print(f"Telemetry folder not found: {folder}")
        raise SystemExit(1)
    track_db = TrackDB(DB_PATH)
    ref_store = ReferenceStore(REFERENCE_DB)
    new = find_new_ibts(
        candidates, processed=track_db.processed_ibt_paths(),
        now=time.time(),
    )
    for cand in new:
        print(_format_report(process_ibt(cand.path, track_db, ref_store)))
        print()
    return len(new)


def main() -> None:
    args = _parse_args()
    folder = Path(args.folder)
    n = _scan_once(folder)
    if not args.watch:
        print(f"Processed {n} new file(s).")
        return
    print(f"Watching {folder} (every {POLL_SECONDS:.0f}s, Ctrl-C to stop)...")
    try:
        while True:
            time.sleep(POLL_SECONDS)
            _scan_once(folder)
    except KeyboardInterrupt:
        print("\nStopped.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process new IBT telemetry into history + references"
    )
    parser.add_argument("--folder", default=str(TELEMETRY_DIR),
                        help="telemetry folder to scan")
    parser.add_argument("--watch", action="store_true",
                        help="keep polling instead of exiting after one scan")
    return parser.parse_args()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to green**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watch_telemetry_helpers.py -q`
Expected: 4 PASS.

- [ ] **Step 5: Real-world smoke test (folder exists on this machine):**

Run: `.venv/Scripts/python.exe scripts/watch_telemetry.py --folder "C:\Users\antho\Documents\iRacing\telemetry"`
Expected: processes the back-log of real IBT files (may take a few minutes — 200MB files), prints a report per file, promotes PBs for each track/car combo, exits with "Processed N new file(s)." Rerunning immediately prints "Processed 0 new file(s)."
This is the back-fill described in the spec's rollout — running it IS the deliverable working.

- [ ] **Step 6: Commit**

```bash
git add scripts/watch_telemetry.py tests/test_watch_telemetry_helpers.py
git commit -m "feat: watch_telemetry CLI - scan once or poll, back-fill history and PBs"
```

---

### Task 5: Full suite, docs, wrap-up

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: everything passes (371+ passed as of plan-writing, plus this plan's ~20 new tests).

- [ ] **Step 2: Update CLAUDE.md**

1. Architecture tree — add under `core/`:
```
│   ├── watcher/
│   │   ├── scanner.py            # Pure discovery: stability window, dedupe, promotion policy
│   │   └── processor.py          # Per-IBT pipeline: history + PB promotion + debrief
```
and `scripts/watch_telemetry.py  # Telemetry folder scan CLI (--watch to poll)` under scripts/, and the three new test files in the tests listing.

2. Current Status — add after the Live Voice Coaching block:

```markdown
**Stage 3: Telemetry Watcher** (complete, branch telemetry-watcher)
- [x] TrackDB session-history methods — sessions/laps tables activated (`core/track/track_db.py`)
- [x] Scanner — 90s write-stability window, sessions-table dedupe, strictly-faster promotion policy (`core/watcher/scanner.py`)
- [x] Processor — parse → normalize → record history → promote personal_best (never touches g61) → debrief vs best reference (`core/watcher/processor.py`)
- [x] CLI — scan once or --watch poll every 30s; failures retry next scan (`scripts/watch_telemetry.py`)
- [ ] Back-fill run over the real telemetry folder + spot-check promoted references
```

3. Update the test count in the Test Suite section to the new total.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: telemetry watcher status"
```

- [ ] **Step 4:** Verify clean tree with `git status`, then use superpowers:finishing-a-development-branch to present merge options.

---

## Post-implementation notes for the (possibly less capable) executing model

- Do NOT redesign the promotion policy, the stability window, or the debrief-vs-own-PB rule — they are spec decisions.
- If `normalize_session` doesn't exist or has a different signature than shown, STOP and check how `tests/test_g61_validation_gate.py` builds laps from an IBT — copy that exact pattern.
- If the sample-fixture tests fail on lap counts or times, the fixture differs from assumptions — loosen only the specific numeric assertion, never delete a test.
- The real-folder smoke test (Task 4 Step 5) processes the user's actual telemetry; it writes to the real `data/tracks.db` and `data/reference_laps.db`. That is intended (it's the rollout back-fill), but NEVER delete or overwrite existing g61 rows — if you see `source='g61'` rows changing, stop immediately.
