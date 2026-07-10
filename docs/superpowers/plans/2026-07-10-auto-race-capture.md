# Auto Race-Capture (Watcher SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the telemetry watcher to auto-capture finished race sessions into `races.db` (full or partial `RaceNarrative`) while the IBT still exists, durability-first.

**Architecture:** A new `core/watcher/race_processor.py` classifies each IBT (race vs lap), and for races runs the existing `ingest_race → build_narrative → RaceStore.save_race` flow with an age-gated retry (wait a few minutes for official results, then persist partial). The watcher CLI parses each new IBT once (`parse_session_only`), routes races to the new processor and everything else to the unchanged lap processor. Race laps are never promoted as PB references. A small `_cached_fetch` hardening stops a not-ready API response from poisoning retries.

**Tech Stack:** Python 3.11+, pytest, SQLite, the existing `core/race/*` pipeline. Run tests with `.venv/Scripts/python.exe -m pytest`.

## Spec

See `docs/superpowers/specs/2026-07-10-auto-race-capture-design.md`.

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `core/race/ingest.py` | Race ingestion | `_cached_fetch` skips caching falsy (not-ready) fetches |
| `core/watcher/race_processor.py` | Race detection + capture | **new** — `classify_ibt`, `decide_capture`, `RaceReport`, `process_race_ibt` |
| `scripts/watch_telemetry.py` | Watcher CLI | build API once; route race vs lap per file; print race reports |
| `tests/test_race_ingest.py` | | + `_cached_fetch` empty-guard test |
| `tests/test_race_processor.py` | | **new** — classify/decide (pure) + process_race_ibt (fixture-gated) |
| `tests/test_watch_telemetry_helpers.py` | | + routing test |

Reused unchanged: `core/race/ingest.py::ingest_race`/`load_race_ibt`, `core/race/narrative.py::build_narrative`, `core/race/race_store.py::RaceStore`, `core/track/track_db.py`, `core/watcher/processor.py::process_ibt`, `core/watcher/scanner.py`.

---

## Task 1: `_cached_fetch` poisoning guard

Stop an empty/not-ready API response from being written to `data/race_cache`, which would strand a race as partial on every later retry.

**Files:**
- Modify: `core/race/ingest.py` (function `_cached_fetch`, ~line 131)
- Test: `tests/test_race_ingest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_race_ingest.py` (near the other `_cached_fetch` tests):

```python
def test_cached_fetch_does_not_cache_empty_result(tmp_path):
    """A falsy (not-ready) fetch result must not be persisted, so a later
    non-empty fetch re-fetches instead of reading a poisoned empty cache."""
    path = tmp_path / "sub" / "results.json"
    calls = {"n": 0}

    def empty_then_full():
        calls["n"] += 1
        return {} if calls["n"] == 1 else {"session_results": [1]}

    assert _cached_fetch(path, empty_then_full) == {}
    assert not path.exists()  # empty result NOT written to disk
    assert _cached_fetch(path, empty_then_full) == {"session_results": [1]}
    assert calls["n"] == 2  # re-fetched, not served from a poisoned cache
    assert path.exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_ingest.py::test_cached_fetch_does_not_cache_empty_result -v`
Expected: FAIL — the current code writes `{}` to disk, so `path.exists()` is True after the first call.

- [ ] **Step 3: Add the guard**

In `core/race/ingest.py`, in `_cached_fetch`, replace:
```python
    data = fetch()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data), encoding="utf-8")
    tmp_path.replace(cache_path)
    return data
```
with:
```python
    data = fetch()
    # A falsy result means the API had nothing yet (e.g. official results not
    # posted). Do NOT cache it — a persisted empty would poison every later
    # retry, stranding the race as partial forever. Return it uncached so the
    # next attempt re-fetches. A legitimately-empty payload simply re-fetches
    # next time — negligible cost, never incorrect.
    if not data:
        return data
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data), encoding="utf-8")
    tmp_path.replace(cache_path)
    return data
```

- [ ] **Step 4: Run the ingest tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_ingest.py -v`
Expected: PASS (the new test plus all existing `_cached_fetch`/ingest tests — the pre-existing `test_cached_fetch_writes_then_reads_cache` still passes because `{"value": 42}` is truthy).

- [ ] **Step 5: Commit**

```bash
git add core/race/ingest.py tests/test_race_ingest.py
git commit -m "fix(race-ingest): don't cache empty fetches (would poison race-results retries)"
```

---

## Task 2: `classify_ibt`, `decide_capture`, `RaceReport` (pure logic)

**Files:**
- Create: `core/watcher/race_processor.py`
- Test: `tests/test_race_processor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_race_processor.py`:

```python
"""Tests for the watcher's race-capture processor."""

from core.watcher.race_processor import (
    RaceReport,
    classify_ibt,
    decide_capture,
)


def test_classify_race():
    assert classify_ibt({"EventType": "Race", "SubSessionID": 12345}) == "race"


def test_classify_practice_is_lap():
    assert classify_ibt({"EventType": "Practice", "SubSessionID": 12345}) == "lap"


def test_classify_race_without_subsession_is_lap():
    assert classify_ibt({"EventType": "Race", "SubSessionID": 0}) == "lap"


def test_classify_missing_fields_is_lap():
    assert classify_ibt({}) == "lap"


def test_decide_full_when_results_ready():
    assert decide_capture(results_ready=True, have_creds=True, file_age_s=1.0) == "full"


def test_decide_defer_when_young_with_creds():
    assert decide_capture(results_ready=False, have_creds=True,
                          file_age_s=10.0, grace_s=300.0) == "defer"


def test_decide_partial_when_old():
    assert decide_capture(results_ready=False, have_creds=True,
                          file_age_s=600.0, grace_s=300.0) == "partial"


def test_decide_partial_when_no_creds():
    assert decide_capture(results_ready=False, have_creds=False,
                          file_age_s=1.0) == "partial"


def test_race_report_defaults():
    r = RaceReport(path="x")
    assert not r.captured and not r.partial and not r.deferred and r.error is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_processor.py -v`
Expected: FAIL — `ModuleNotFoundError: core.watcher.race_processor`.

- [ ] **Step 3: Create the module with the pure pieces**

Create `core/watcher/race_processor.py`:

```python
"""Per-file race capture for the telemetry watcher.

Detects race IBTs and captures a (full or partial) RaceNarrative into
races.db while the source IBT still exists. Durability-first: wait a few
minutes for official results to settle, then persist a partial narrative
(the ephemeral IBT-only signals) rather than risk losing the IBT.

Like core.watcher.processor, process_race_ibt never raises — any error is
captured into the returned report so one bad file never aborts a scan.
"""

from dataclasses import dataclass
from pathlib import Path

from core.race.ingest import DEFAULT_CACHE_DIR, ingest_race
from core.race.narrative import build_narrative
from core.race.race_store import RaceStore
from core.track.lovely_seeder import seed_track_from_lovely
from core.track.models import Track, TrackType
from core.track.track_db import TrackDB

GRACE_MINUTES = 5.0  # how long to wait for official results before saving partial
RACE_RESULTS_GRACE_S = GRACE_MINUTES * 60.0


@dataclass
class RaceReport:
    """What one race IBT produced this scan; the CLI prints it, tests assert it."""

    path: Path
    subsession_id: int = 0
    track: str = ""
    car: str = ""
    start_position: int = 0
    finish_position: int = 0
    incidents: int = 0
    captured: bool = False   # narrative saved to races.db this scan
    partial: bool = False    # saved without Data API results
    deferred: bool = False   # results not ready + file young -> retry next scan
    error: str | None = None


def classify_ibt(weekend_info: dict) -> str:
    """'race' when this IBT is an official race, else 'lap'. Pure — reads the
    already-parsed WeekendInfo dict."""
    if weekend_info.get("EventType") == "Race" and weekend_info.get("SubSessionID"):
        return "race"
    return "lap"


def decide_capture(
    results_ready: bool,
    have_creds: bool,
    file_age_s: float,
    grace_s: float = RACE_RESULTS_GRACE_S,
) -> str:
    """'full' | 'partial' | 'defer'. Durability-first: wait for results only
    while the file is young and we actually have creds to fetch them."""
    if results_ready:
        return "full"
    if not have_creds:
        return "partial"
    if file_age_s >= grace_s:
        return "partial"
    return "defer"
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_processor.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add core/watcher/race_processor.py tests/test_race_processor.py
git commit -m "feat(watcher): race classify + capture-decision + RaceReport"
```

---

## Task 3: `process_race_ibt` (capture flow)

**Files:**
- Modify: `core/watcher/race_processor.py`
- Test: `tests/test_race_processor.py`

- [ ] **Step 1: Write the failing tests (fixture-gated + partial + defer + idempotent)**

Add to `tests/test_race_processor.py`:

```python
from pathlib import Path

import pytest

from core.race.race_store import RaceStore
from core.track.track_db import TrackDB
from core.watcher.race_processor import process_race_ibt

FIXTURE_IBT = Path("tests/fixtures/race/race.ibt")
FIXTURE_CACHE = Path("tests/fixtures/race/cache")
needs_fixture = pytest.mark.skipif(
    not FIXTURE_IBT.exists() or not FIXTURE_CACHE.exists(),
    reason="race fixtures not recorded (scripts/record_race_fixture.py)",
)


class _ExplodingAPI:
    """Serves entirely from recorded cache; any network call is a bug."""

    def __getattr__(self, name):
        raise AssertionError(f"network call attempted: {name}")

    def close(self):
        pass


@needs_fixture
def test_process_race_full_capture_from_cache(tmp_path):
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")
    report = process_race_ibt(
        FIXTURE_IBT, _ExplodingAPI(), race_store, track_db,
        now=1000.0, file_mtime=1000.0, cache_dir=FIXTURE_CACHE,
    )
    assert report.error is None
    assert report.captured and not report.partial and not report.deferred
    assert report.subsession_id == 86748877
    # Oulton MX-5 fixture: gridded P7, finished P4 (adjust if the recorded
    # fixture differs — TDD will reveal the real values).
    assert report.start_position == 7
    assert report.finish_position == 4
    # Persisted and deduped
    assert len(race_store.list_races()) == 1
    assert str(FIXTURE_IBT) in track_db.processed_ibt_paths()


@needs_fixture
def test_process_race_idempotent(tmp_path):
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")
    for _ in range(2):
        process_race_ibt(
            FIXTURE_IBT, _ExplodingAPI(), race_store, track_db,
            now=1000.0, file_mtime=1000.0, cache_dir=FIXTURE_CACHE,
        )
    assert len(race_store.list_races()) == 1  # INSERT OR REPLACE, no duplicate


@needs_fixture
def test_process_race_partial_when_no_results(tmp_path):
    """api=None + empty cache -> partial narrative persisted (file old)."""
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")
    report = process_race_ibt(
        FIXTURE_IBT, None, race_store, track_db,
        now=10_000.0, file_mtime=0.0, cache_dir=tmp_path / "emptycache",
    )
    assert report.error is None
    assert report.captured and report.partial
    assert len(race_store.list_races()) == 1


@needs_fixture
def test_process_race_defers_when_young_and_not_ready(tmp_path):
    """Creds present but results empty + young file -> defer, save nothing."""
    track_db = TrackDB(tmp_path / "tracks.db")
    race_store = RaceStore(tmp_path / "races.db")

    class EmptyAPI:
        def get_subsession_results(self, *a):
            return {}  # not ready yet

        def close(self):
            pass

    report = process_race_ibt(
        FIXTURE_IBT, EmptyAPI(), race_store, track_db,
        now=100.0, file_mtime=99.0, cache_dir=tmp_path / "c", grace_s=300.0,
    )
    assert report.deferred and not report.captured
    assert race_store.list_races() == []
    assert track_db.processed_ibt_paths() == set()  # not marked -> retries
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_processor.py -k process_race -v`
Expected: FAIL — `ImportError: cannot import name 'process_race_ibt'` (or all skip if fixtures are absent; if they skip, note it and continue — the implementer must confirm on a machine with the fixtures).

- [ ] **Step 3: Implement `process_race_ibt` + helpers**

Append to `core/watcher/race_processor.py`:

```python
def _load_corners(track_db: TrackDB, data) -> list:
    """Named corners for incident/place-change labeling, lazy-seeding from
    lovely-track-data. Creates the track row when missing (a race may be the
    first time this track is seen). Corner names are enhancement only — any
    failure returns an empty list and the narrative uses position fallbacks."""
    track_id = data.track_id
    if not track_id:
        return []
    try:
        if track_db.get_track(str(track_id)) is None:
            track_db.upsert_track(Track(
                track_id=str(track_id),
                name=data.track_name,
                config=None,
                length_meters=data.track_length_m,
                track_type=TrackType.ROAD,
                character=None,
            ))
        corners = track_db.get_corners(str(track_id))
        if not corners:
            seed_track_from_lovely(
                track_db, str(track_id), data.track_directory, data.track_length_m
            )
            corners = track_db.get_corners(str(track_id))
        return corners
    except Exception:  # noqa: BLE001 — corner names are enhancement only
        return []


def _record_race_history(track_db: TrackDB, path: Path, data) -> None:
    """Record a 'Race' session row (marks the IBT processed via the path-based
    dedupe set) and the player's race laps for the pace layer. NO PB promotion
    — race laps (traffic, fuel) must never become reference laps."""
    player_laps = data.driver_laps.get(data.player_cust_id, [])
    valid_times = [
        l.lap_time for l in player_laps if l.lap_time > 0 and not l.incident
    ]
    best = min(valid_times) if valid_times else None
    track_db.record_session(
        session_id=path.stem,
        track_id=str(data.track_id),
        car=data.car_name,
        session_type="Race",
        session_date=path.stem[-19:],
        best_lap_time=best,
        lap_count=len(player_laps),
        ibt_file_path=str(path),
    )
    if player_laps:
        track_db.record_laps(
            path.stem,
            [
                (l.lap_number, l.lap_time, l.lap_time > 0 and not l.incident)
                for l in player_laps
            ],
        )


def process_race_ibt(
    path: Path,
    api,
    race_store: RaceStore,
    track_db: TrackDB,
    *,
    now: float,
    file_mtime: float,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    grace_s: float = RACE_RESULTS_GRACE_S,
) -> RaceReport:
    """Capture one race IBT into races.db. Never raises."""
    report = RaceReport(path=path)
    try:
        data = ingest_race(path, api, cache_dir=cache_dir)
        report.subsession_id = data.subsession_id
        report.track = data.track_name
        report.car = data.car_name

        results_ready = len(data.results) > 0
        decision = decide_capture(
            results_ready, api is not None, now - file_mtime, grace_s
        )
        if decision == "defer":
            report.deferred = True
            return report

        corners = _load_corners(track_db, data)
        narrative = build_narrative(data, corners)
        race_store.save_race(narrative, ibt_file_path=str(path))
        _record_race_history(track_db, path, data)

        h = narrative.header
        report.start_position = h.start_position
        report.finish_position = h.finish_position
        report.incidents = h.incidents
        report.captured = True
        report.partial = not results_ready
        return report
    except Exception as exc:  # noqa: BLE001 — a bad file must never abort a scan
        report.error = f"{type(exc).__name__}: {exc}"
        return report
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_processor.py -v`
Expected: PASS (the pure tests plus the four fixture tests; fixture tests SKIP only if `tests/fixtures/race/` is absent). On the founder's machine the fixtures exist — confirm they pass, not skip.

- [ ] **Step 5: Commit**

```bash
git add core/watcher/race_processor.py tests/test_race_processor.py
git commit -m "feat(watcher): process_race_ibt — capture race narrative, age-gated partial, no PB promotion"
```

---

## Task 4: Wire routing into the watcher CLI

**Files:**
- Modify: `scripts/watch_telemetry.py`
- Test: `tests/test_watch_telemetry_helpers.py`

- [ ] **Step 1: Write the failing routing test**

Add to `tests/test_watch_telemetry_helpers.py`:

```python
def test_process_candidate_routes_race_to_race_processor(monkeypatch, tmp_path):
    """A race IBT goes to process_race_ibt; a lap IBT goes to process_ibt.
    Proves races never hit the PB-promoting lap path."""
    import scripts.watch_telemetry as wt
    from core.watcher.scanner import IbtCandidate

    called = {"race": 0, "lap": 0}

    class _FakeSession:
        def __init__(self, event_type):
            self.raw = {"WeekendInfo": {"EventType": event_type,
                                        "SubSessionID": 42}}

    monkeypatch.setattr(
        wt.IBTParser, "parse_session_only",
        lambda self, p: _FakeSession(_FakeSession.event),
    )
    monkeypatch.setattr(
        wt, "process_race_ibt",
        lambda *a, **k: called.__setitem__("race", called["race"] + 1) or wt.RaceReport(path="r"),
    )
    monkeypatch.setattr(
        wt, "process_ibt",
        lambda *a, **k: called.__setitem__("lap", called["lap"] + 1) or wt.SessionReport(path="l"),
    )

    cand = IbtCandidate(path=tmp_path / "x.ibt", mtime=0.0)

    _FakeSession.event = "Race"
    wt._process_candidate(cand, api=None, track_db=None, ref_store=None,
                          race_store=None, now=1.0)
    assert called == {"race": 1, "lap": 0}

    _FakeSession.event = "Practice"
    wt._process_candidate(cand, api=None, track_db=None, ref_store=None,
                          race_store=None, now=1.0)
    assert called == {"race": 1, "lap": 1}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watch_telemetry_helpers.py::test_process_candidate_routes_race_to_race_processor -v`
Expected: FAIL — `AttributeError: module 'scripts.watch_telemetry' has no attribute '_process_candidate'`.

- [ ] **Step 3: Add routing + race reporting + API to the CLI**

In `scripts/watch_telemetry.py`:

Add imports (with the existing `# noqa: E402` block):
```python
import os  # noqa: E402
from core.race.race_store import RaceStore  # noqa: E402
from core.telemetry.ibt_parser import IBTParser  # noqa: E402
from core.watcher.race_processor import (  # noqa: E402
    RaceReport,
    classify_ibt,
    process_race_ibt,
)
```

Add the races DB constant next to the others:
```python
RACES_DB = Path("data/races.db")
```

Add the API builder (mirrors the debrief page's `_make_api`):
```python
def _make_api():
    """LiveIRacingAPI from env creds, or None (partial-capture mode)."""
    client_id = os.environ.get("IRACING_CLIENT_ID", "")
    client_secret = os.environ.get("IRACING_CLIENT_SECRET", "")
    username = os.environ.get("IRACING_USERNAME", "")
    password = os.environ.get("IRACING_PASSWORD", "")
    if not all([client_id, client_secret, username, password]):
        return None
    from core.benchmark.iracing_api import LiveIRacingAPI
    return LiveIRacingAPI(client_id, client_secret, username, password)
```

Add a race-report formatter:
```python
def _format_race_report(r: RaceReport) -> str:
    if r.error is not None:
        return f"FAILED {r.path.name}: {r.error} (will retry next scan)"
    if r.deferred:
        return (f"{r.path.name}\n  Race {r.track} — results not ready, "
                f"will retry (subsession {r.subsession_id})")
    tag = " (partial — no results yet)" if r.partial else ""
    return (f"{r.path.name}\n  Race captured{tag}: {r.track}, {r.car}, "
            f"P{r.start_position}→P{r.finish_position} "
            f"(subsession {r.subsession_id})")
```

Add the per-candidate router:
```python
def _process_candidate(cand, api, track_db, ref_store, race_store, now) -> str:
    """Route one candidate to the race or lap processor; return a print block."""
    try:
        session = IBTParser().parse_session_only(cand.path)
        weekend = (session.raw or {}).get("WeekendInfo", {}) or {}
    except Exception as exc:  # noqa: BLE001 — unreadable/half-written file, retry
        return (f"FAILED {cand.path.name}: {type(exc).__name__}: {exc} "
                "(will retry next scan)")
    if classify_ibt(weekend) == "race":
        return _format_race_report(process_race_ibt(
            cand.path, api, race_store, track_db,
            now=now, file_mtime=cand.mtime,
        ))
    return _format_report(process_ibt(cand.path, track_db, ref_store))
```

Replace `_scan_once` with a version that takes the stores + api and routes:
```python
def _scan_once(folder, track_db, ref_store, race_store, api) -> int:
    """One pass. Returns number of files processed (0 is fine)."""
    candidates = _gather_candidates(folder)
    if candidates is None:
        print(f"Telemetry folder not found: {folder}")
        raise SystemExit(1)
    new = find_new_ibts(
        candidates, processed=track_db.processed_ibt_paths(), now=time.time(),
    )
    for cand in new:
        print(_process_candidate(cand, api, track_db, ref_store, race_store,
                                 time.time()))
        print()
    return len(new)
```

Replace `main` so the stores + API are built once and reused across scans:
```python
def main() -> None:
    args = _parse_args()
    folder = Path(args.folder)
    track_db = TrackDB(DB_PATH)
    ref_store = ReferenceStore(REFERENCE_DB)
    race_store = RaceStore(RACES_DB)
    api = _make_api()
    if api is None:
        print("No iRacing API creds — races will be captured partial "
              "(positions/results absent); practice unaffected.")
    try:
        n = _scan_once(folder, track_db, ref_store, race_store, api)
        if not args.watch:
            print(f"Processed {n} new file(s).")
            return
        print(f"Watching {folder} (every {POLL_SECONDS:.0f}s, Ctrl-C to stop)...")
        while True:
            time.sleep(POLL_SECONDS)
            _scan_once(folder, track_db, ref_store, race_store, api)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if api is not None:
            api.close()
```

(Delete the old `_scan_once`/`main` bodies these replace. `TrackDB`, `ReferenceStore`, `find_new_ibts`, `_gather_candidates`, `_format_report`, `process_ibt` imports already exist.)

- [ ] **Step 4: Run the routing test + syntax + help**

Run: `.venv/Scripts/python.exe -m pytest tests/test_watch_telemetry_helpers.py -v`
Expected: PASS (new routing test + existing helper tests).

Run: `.venv/Scripts/python.exe -c "import ast; ast.parse(open('scripts/watch_telemetry.py').read()); print('ok')"`
Expected: `ok`

Run: `.venv/Scripts/python.exe scripts/watch_telemetry.py --help`
Expected: help prints with `--folder` and `--watch` (unchanged args).

- [ ] **Step 5: Commit**

```bash
git add scripts/watch_telemetry.py tests/test_watch_telemetry_helpers.py
git commit -m "feat(watcher): route race IBTs to race capture; build Data API once per run"
```

---

## Task 5: Full suite + manual verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass. New: ~9 pure race-processor tests, 4 fixture-gated (pass on the founder's machine, skip elsewhere), 1 `_cached_fetch` test, 1 routing test. No prior tests break.

- [ ] **Step 2: Manual scan against the real telemetry folder**

Run: `.venv/Scripts/python.exe scripts/watch_telemetry.py`
Confirm: practice/qual/test files still process as before (lap reports, PB lines); any race IBT prints a `Race captured: ... P?→P?` line; check `races.db` gained the row:
`.venv/Scripts/python.exe -c "import sqlite3; print(sqlite3.connect('data/races.db').execute('SELECT subsession_id, track_name, start_position, finish_position FROM races').fetchall())"`
And confirm no race lap polluted references (spot-check `reference_laps.db` sources are still `g61`/`personal_best` from real practice combos, not race laps).

- [ ] **Step 3: Finalize the branch**

Use the finishing-a-development-branch skill to merge `auto-race-capture` to master. Then: update the Atlas manifest (SP1 shipped; next = Driver Profile SP2), update CLAUDE.md's watcher section (races now auto-captured; race laps no longer PB-eligible), and update the project memory.

---

## Self-Review

- **Spec coverage:** Detection/routing → Task 2 (`classify_ibt`) + Task 4 (CLI). `process_race_ibt` → Task 3. Age-gated durability (`decide_capture`, full/partial/defer) → Task 2 + Task 3. Cache-poisoning guard → Task 1. No PB promotion from races → Task 3 (`process_race_ibt` takes no ref_store; `_record_race_history` never promotes) + Task 4 routing test. Creds-absent → Task 4 (`_make_api` None → partial). No AI on capture path → Task 3 (only `build_narrative` + `save_race`, no synthesizer). Reporting → Task 4 (`_format_race_report`). Dedupe → Task 3 (`_record_race_history` writes the session row into `processed_ibt_paths()`).
- **Type consistency:** `classify_ibt(dict) -> "race"|"lap"`, `decide_capture(results_ready, have_creds, file_age_s, grace_s) -> "full"|"partial"|"defer"`, `process_race_ibt(path, api, race_store, track_db, *, now, file_mtime, cache_dir, grace_s) -> RaceReport`, `_process_candidate(cand, api, track_db, ref_store, race_store, now) -> str`. `RaceReport` fields used identically across Task 3 and Task 4. `ingest_race(path, api, cache_dir=...)` and `build_narrative(data, corners)` match their real signatures.
- **No placeholders:** every code step is complete. The one soft spot — exact Oulton P7→P4 numbers — is flagged inline as TDD-confirmable.
