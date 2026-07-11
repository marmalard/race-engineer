# Driver Profile v1 (SP2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deterministic driver profile — 4 racecraft tendencies from stored `RaceNarrative`s + per-combo practice readiness from the watcher's session history — rendered on a new Streamlit page and injected compactly into the race-debrief prompt.

**Architecture:** New pure package `core/profile/` (`models.py` dataclasses/constants, `racecraft.py` + `pace.py` pure math, `render.py` verdicts/markdown/prompt-block, `builder.py` the only I/O). Two store read-methods are added (`TrackDB` session-history reads, `RaceStore.get_narratives`). Prompt injection threads through optional `profile_block=""` params on the existing prompt builders and `Synthesizer` methods, with a tone-contract amendment permitting profile facts as a cited cross-race source.

**Tech Stack:** Python 3.11+, pytest, SQLite, `statistics` stdlib, Streamlit (display only). Run tests with `.venv/Scripts/python.exe -m pytest`.

## Spec

See `docs/superpowers/specs/2026-07-10-driver-profile-v1-design.md`.

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `core/track/track_db.py` | + `SessionRow`, `LapRow`, `list_session_history()`, `get_session_laps()` | modify |
| `core/race/race_store.py` | + `get_narratives(cust_id)` | modify |
| `core/profile/__init__.py` | package marker (empty) | **new** |
| `core/profile/models.py` | tendency/readiness/profile dataclasses + thresholds | **new** |
| `core/profile/racecraft.py` | PURE: narratives → 4 tendencies | **new** |
| `core/profile/pace.py` | PURE: session history → per-combo readiness | **new** |
| `core/profile/render.py` | verdict lines, page markdown, prompt block | **new** |
| `core/profile/builder.py` | stores → `DriverProfile` (only I/O module) | **new** |
| `core/coaching/prompts/race_debrief.py` | optional `profile_block`; tone amendment | modify |
| `core/coaching/synthesizer.py` | thread `profile_block` through both race methods | modify |
| `app/pages/driver_profile.py` | profile page (display only) | **new** |
| `app/streamlit_app.py` | register the page | modify |
| `app/pages/race_debrief.py` | build + pass the profile block | modify |
| Tests | `test_profile_racecraft.py`, `test_profile_pace.py`, `test_profile_render.py`, `test_profile_builder.py`, `test_race_prompts.py` (new); `test_track_db.py`, `test_race_store.py` (extend) | |

---

## Task 1: TrackDB session-history read methods

**Files:**
- Modify: `core/track/track_db.py`
- Test: `tests/test_track_db.py`

- [ ] **Step 1: Write the failing tests**

Read `tests/test_track_db.py` first to match its fixture style, then add:

```python
def test_list_session_history_and_laps_roundtrip(tmp_path):
    from core.track.track_db import LapRow, SessionRow, TrackDB

    db = TrackDB(tmp_path / "t.db")
    db.record_session(
        session_id="s1", track_id="525", car="M2",
        session_type="practice", session_date="2026-07-01 10-00-00",
        best_lap_time=100.5, lap_count=3, ibt_file_path="x.ibt",
    )
    db.record_laps("s1", [(1, 101.0, True), (2, 100.5, True), (3, 130.0, False)])
    db.record_session(
        session_id="s2", track_id="525", car="M2",
        session_type="Race", session_date="2026-07-02 10-00-00",
        best_lap_time=99.9, lap_count=1, ibt_file_path="y.ibt",
    )

    sessions = db.list_session_history()
    assert [s.session_id for s in sessions] == ["s1", "s2"]  # date order
    s1 = sessions[0]
    assert isinstance(s1, SessionRow)
    assert (s1.track_id, s1.car, s1.session_type) == ("525", "M2", "practice")
    assert s1.best_lap_time == 100.5 and s1.lap_count == 3
    assert s1.session_date == "2026-07-01 10-00-00"

    laps = db.get_session_laps("s1")
    assert [(l.lap_number, l.lap_time, l.is_valid) for l in laps] == [
        (1, 101.0, True), (2, 100.5, True), (3, 130.0, False),
    ]
    assert isinstance(laps[0], LapRow)
    assert db.get_session_laps("nope") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_db.py::test_list_session_history_and_laps_roundtrip -v`
Expected: FAIL — `ImportError: cannot import name 'LapRow'`.

- [ ] **Step 3: Implement**

Read `core/track/track_db.py`'s `record_session`/`record_laps` first (exact column names). Add near the top (after imports, following the file's dataclass conventions — check whether `dataclass` is already imported; add `from dataclasses import dataclass` if not):

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


@dataclass
class LapRow:
    """One laps-table row."""

    lap_number: int
    lap_time: float
    is_valid: bool
```

Add methods to `TrackDB` (following the class's `_get_conn`/try/finally style):

```python
    def list_session_history(self) -> list[SessionRow]:
        """All recorded sessions, oldest first, with the track name joined."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT s.session_id, s.track_id,
                       COALESCE(t.name, s.track_id) AS track_name,
                       s.car, s.session_type, s.session_date,
                       s.best_lap_time, s.lap_count
                FROM sessions s
                LEFT JOIN tracks t ON t.track_id = s.track_id
                ORDER BY s.session_date
                """
            ).fetchall()
            return [
                SessionRow(
                    session_id=r[0], track_id=r[1] or "", track_name=r[2] or "",
                    car=r[3] or "", session_type=r[4] or "",
                    session_date=str(r[5] or ""),
                    best_lap_time=r[6], lap_count=r[7] or 0,
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_session_laps(self, session_id: str) -> list[LapRow]:
        """Lap rows for one session, in lap order. Empty when unknown."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT lap_number, lap_time, is_valid FROM laps "
                "WHERE session_id = ? ORDER BY lap_number",
                (session_id,),
            ).fetchall()
            return [
                LapRow(lap_number=r[0], lap_time=r[1], is_valid=bool(r[2]))
                for r in rows
            ]
        finally:
            conn.close()
```

(If `TrackDB` uses `sqlite3.Row` access by name, index access still works; keep whichever the file's other readers use.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_db.py -v`
Expected: PASS (new + all existing).

- [ ] **Step 5: Commit**

```bash
git add core/track/track_db.py tests/test_track_db.py
git commit -m "feat(track-db): session-history read methods (SessionRow/LapRow)"
```

---

## Task 2: `RaceStore.get_narratives(cust_id)`

**Files:**
- Modify: `core/race/race_store.py`
- Test: `tests/test_race_store.py`

- [ ] **Step 1: Write the failing test**

Read `tests/test_race_store.py` first — it already builds narratives for `save_race` tests; reuse its helper if one exists, else this minimal builder. Add:

```python
def test_get_narratives_filters_and_orders(tmp_path):
    from core.race.race_store import RaceStore

    store = RaceStore(tmp_path / "races.db")
    n1 = _make_narrative(subsession_id=1, cust_id=100)   # reuse the file's helper
    n2 = _make_narrative(subsession_id=2, cust_id=100)
    other = _make_narrative(subsession_id=3, cust_id=999)
    store.save_race(n1, ibt_file_path="a")
    store.save_race(n2, ibt_file_path="b")
    store.save_race(other, ibt_file_path="c")

    got = store.get_narratives(100)
    assert [n.header.subsession_id for n in got] == [2, 1]  # newest first
    assert store.get_narratives(12345) == []
```

If `tests/test_race_store.py` has no narrative factory, add one at module level (mirror how its existing tests construct a `RaceNarrative` — read them and copy the construction, parameterizing `subsession_id`/`cust_id`).

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_store.py::test_get_narratives_filters_and_orders -v`
Expected: FAIL — `AttributeError: 'RaceStore' object has no attribute 'get_narratives'`.

- [ ] **Step 3: Implement**

Add to `RaceStore` (next to `get_race`):

```python
    def get_narratives(self, cust_id: int) -> list[RaceNarrative]:
        """All stored narratives for one driver, newest first.

        Dozens of rows at most for a personal store — loading them all is
        the profile engine's intended access pattern (derive on demand).
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT narrative_json FROM races "
                "WHERE cust_id = ? ORDER BY created_at DESC",
                (cust_id,),
            ).fetchall()
        return [
            RaceNarrative.from_dict(json.loads(r["narrative_json"]))
            for r in rows
        ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_store.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add core/race/race_store.py tests/test_race_store.py
git commit -m "feat(race-store): get_narratives(cust_id) for the profile engine"
```

---

## Task 3: `core/profile` models + racecraft engine

**Files:**
- Create: `core/profile/__init__.py` (empty), `core/profile/models.py`, `core/profile/racecraft.py`
- Test: `tests/test_profile_racecraft.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_racecraft.py`:

```python
"""Tests for the pure racecraft-tendency engine (synthetic narratives)."""

from core.race.models import (
    IncidentEvent,
    IRatingAttribution,
    Lap1Story,
    NarrativeHeader,
    RaceNarrative,
    Stint,
)
from core.profile.racecraft import build_racecraft


def _header(**kw) -> NarrativeHeader:
    base = dict(
        subsession_id=1, cust_id=100, driver_name="D", track_id=1,
        track_name="Oulton", track_config="", car_name="MX-5",
        series_name="S", session_date="2026-07-01", sof=1500,
        field_size=20, start_position=7, finish_position=4, incidents=2,
        irating_old=1400, irating_new=1420,
    )
    base.update(kw)
    return NarrativeHeader(**base)


def _lap1(grid=7, after1=9, after2=8) -> Lap1Story:
    return Lap1Story(grid_position=grid, position_after_lap1=after1,
                     position_after_lap2=after2)


def _attr(actual=6, deserved=4, time_lost=8.0) -> IRatingAttribution:
    return IRatingAttribution(
        irating_old=1400, irating_new=1410, irating_delta=10,
        pace_deserved_position=deserved, actual_position=actual,
        incident_time_lost_s=time_lost, lap1_net_positions=0,
    )


def _incident(lap=1, corner="Old Hall") -> IncidentEvent:
    return IncidentEvent(
        lap=lap, lap_dist_pct=0.1, corner_name=corner, delta_incidents=2,
        position_before=5, position_after=7, time_lost_estimate_s=4.0,
    )


def _narr(lap1=None, attribution=None, incidents=(), stints=(), **header_kw):
    return RaceNarrative(
        header=_header(**header_kw), lap1=lap1, attribution=attribution,
        incidents=list(incidents), stints=list(stints),
    )


def test_starts_math_and_sign():
    """grid 7 -> P9 after lap1 = -2 (positive = gained)."""
    t = build_racecraft([_narr(lap1=_lap1(7, 9, 8)) for _ in range(3)])
    s = t.starts
    assert s.sample == 3 and s.enough_data
    assert s.mean_lap1_net == -2.0
    assert s.mean_lap2_net == 1.0          # P9 -> P8 = +1
    assert s.races_lost_ground == 3


def test_starts_skips_races_without_lap1():
    t = build_racecraft([_narr(lap1=_lap1()), _narr(lap1=None), _narr(lap1=None)])
    assert t.starts.sample == 1
    assert not t.starts.enough_data        # 1 < 3


def test_pace_vs_result_positive_means_finishing_worse():
    t = build_racecraft([_narr(attribution=_attr(actual=6, deserved=4))
                         for _ in range(3)])
    p = t.pace_vs_result
    assert p.sample == 3 and p.enough_data
    assert p.mean_positions_left == 2.0
    assert p.mean_incident_time_lost_s == 8.0


def test_pace_vs_result_skips_none_deserved():
    t = build_racecraft([
        _narr(attribution=_attr()),
        _narr(attribution=_attr(deserved=None)),
        _narr(attribution=None),
    ])
    assert t.pace_vs_result.sample == 1


def test_incidents_rate_lap1_share_and_recurring():
    races = [
        _narr(incidents=[_incident(lap=1, corner="Old Hall")], incidents_count=4),
        _narr(incidents=[_incident(lap=5, corner="Old Hall")], incidents_count=2),
        _narr(incidents=[_incident(lap=1, corner=None)], incidents_count=0),
    ]
    # header incidents comes via header_kw: rename to avoid clash
    races = [
        _narr(incidents=[_incident(lap=1, corner="Old Hall")], incidents=4),
    ]
    # (See implementation note: header incidents kw is `incidents` on the header)


def test_trajectory_net_and_fade():
    races = [
        _narr(stints=[Stint(1, 10, 100.0, 0.3)], start_position=8, finish_position=5),
        _narr(stints=[Stint(1, 10, 100.0, 0.1)], start_position=6, finish_position=6),
        _narr(stints=[Stint(1, 10, 100.0, None)], start_position=10, finish_position=7),
    ]
    t = build_racecraft(races)
    tr = t.trajectory
    assert tr.sample == 3 and tr.enough_data
    assert tr.mean_race_net == 3.0         # +3, 0, +3 -> mean 2.0? see note
    assert tr.mean_stint_fade_s == 0.2     # (0.3 + 0.1) / 2


def test_trajectory_skips_partial_headers():
    t = build_racecraft([_narr(start_position=0, finish_position=0)])
    assert t.trajectory.sample == 0 and not t.trajectory.enough_data
```

**Implementer note on the two flagged tests:** `test_incidents_...` above is left half-written deliberately in this plan draft — write it properly as follows (the header field is `incidents`, passed through `header_kw`):

```python
def test_incidents_rate_lap1_share_and_recurring():
    races = [
        _narr(incidents=[_incident(lap=1, corner="Old Hall")], **{"incidents": 4}),
        _narr(incidents=[_incident(lap=5, corner="Old Hall")], **{"incidents": 2}),
        _narr(incidents=[_incident(lap=1, corner=None)], **{"incidents": 0}),
    ]
```
— this collides (`incidents` is both the event-list param and the header kw). Resolve by renaming `_narr`'s event-list parameter to `events`:

```python
def _narr(lap1=None, attribution=None, events=(), stints=(), **header_kw):
    return RaceNarrative(
        header=_header(**header_kw), lap1=lap1, attribution=attribution,
        incidents=list(events), stints=list(stints),
    )
```
Then:
```python
def test_incidents_rate_lap1_share_and_recurring():
    races = [
        _narr(events=[_incident(lap=1, corner="Old Hall")], incidents=4),
        _narr(events=[_incident(lap=5, corner="Old Hall")], incidents=2),
        _narr(events=[_incident(lap=1, corner=None)], incidents=0),
    ]
    t = build_racecraft(races)
    i = t.incidents
    assert i.sample == 3 and i.enough_data
    assert i.mean_incident_points == 2.0          # (4+2+0)/3
    assert i.lap1_share == 2 / 3                  # 2 of 3 events on lap 1
    assert i.recurring_corners == [("Old Hall", 2)]
```
And fix `test_trajectory_net_and_fade`'s arithmetic: nets are +3, 0, +3 → `mean_race_net == 2.0`. Use the corrected value. (Update every test in this file to the `events=` parameter name.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_racecraft.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.profile'`.

- [ ] **Step 3: Implement**

Create `core/profile/__init__.py` (empty). Create `core/profile/models.py`:

```python
"""Dataclasses and thresholds for the driver profile.

Thresholds answer one question: at what sample does an aggregate stop
being noise and become a claim the engineer can say out loud? They are
judgment calls, kept as named constants for tuning.
"""

from dataclasses import dataclass, field

RACECRAFT_MIN_RACES = 3      # tendencies unlock at 3 races with the relevant data
READINESS_MIN_SESSIONS = 2   # per-combo readiness unlocks at 2 sessions...
READINESS_MIN_LAPS = 10      # ...and 10 valid laps
RECURRING_CORNER_MIN = 2     # a corner is "recurring trouble" at 2+ incidents
CONSISTENCY_WINDOW_SESSIONS = 3
CONSISTENCY_MIN_LAPS = 5


@dataclass
class StartsTendency:
    """Lap-1/2 racecraft. Positive net = gained places."""

    mean_lap1_net: float | None = None
    mean_lap2_net: float | None = None
    races_lost_ground: int = 0
    sample: int = 0
    enough_data: bool = False


@dataclass
class PaceVsResultTendency:
    """The headline: do results match pace? Positive = finishing worse."""

    mean_positions_left: float | None = None
    mean_incident_time_lost_s: float | None = None
    mean_actual_position: float | None = None
    mean_deserved_position: float | None = None
    sample: int = 0
    enough_data: bool = False


@dataclass
class IncidentTendency:
    mean_incident_points: float | None = None
    lap1_share: float | None = None            # fraction of events on lap 1
    recurring_corners: list[tuple[str, int]] = field(default_factory=list)
    sample: int = 0
    enough_data: bool = False


@dataclass
class TrajectoryTendency:
    """Start->finish net (positive = gained) and late-race fade."""

    mean_race_net: float | None = None
    mean_stint_fade_s: float | None = None      # positive = slower 2nd half
    sample: int = 0
    enough_data: bool = False


@dataclass
class RacecraftTendencies:
    starts: StartsTendency = field(default_factory=StartsTendency)
    pace_vs_result: PaceVsResultTendency = field(default_factory=PaceVsResultTendency)
    incidents: IncidentTendency = field(default_factory=IncidentTendency)
    trajectory: TrajectoryTendency = field(default_factory=TrajectoryTendency)


@dataclass
class ComboReadiness:
    """Practice-based confidence signals for one (track, car) combo."""

    track_id: str
    track_name: str
    car: str
    sessions: int = 0
    valid_laps: int = 0
    last_driven: str = ""
    best_lap: float | None = None
    pb_trend_s: float | None = None             # positive = getting faster
    consistency_s: float | None = None          # stdev, recent sessions
    enough_data: bool = False


@dataclass
class DriverProfile:
    cust_id: int = 0
    driver_name: str = ""
    races_captured: int = 0
    combos_tracked: int = 0
    racecraft: RacecraftTendencies = field(default_factory=RacecraftTendencies)
    readiness: list[ComboReadiness] = field(default_factory=list)
```

Create `core/profile/racecraft.py`:

```python
"""PURE racecraft-tendency engine: list[RaceNarrative] -> tendencies.

No I/O, no AI. Sign convention: positive = gained places. Sample sizes
are PER TENDENCY — a partial narrative (auto-captured without API
results) contributes to whichever tendencies its data supports.
"""

from collections import Counter
from statistics import mean

from core.profile.models import (
    RACECRAFT_MIN_RACES,
    RECURRING_CORNER_MIN,
    IncidentTendency,
    PaceVsResultTendency,
    RacecraftTendencies,
    StartsTendency,
    TrajectoryTendency,
)
from core.race.models import RaceNarrative


def _starts(narratives: list[RaceNarrative]) -> StartsTendency:
    lap1s = [n.lap1 for n in narratives if n.lap1 is not None]
    if not lap1s:
        return StartsTendency()
    nets1 = [l.grid_position - l.position_after_lap1 for l in lap1s]
    nets2 = [l.position_after_lap1 - l.position_after_lap2 for l in lap1s]
    return StartsTendency(
        mean_lap1_net=mean(nets1),
        mean_lap2_net=mean(nets2),
        races_lost_ground=sum(1 for x in nets1 if x < 0),
        sample=len(lap1s),
        enough_data=len(lap1s) >= RACECRAFT_MIN_RACES,
    )


def _pace_vs_result(narratives: list[RaceNarrative]) -> PaceVsResultTendency:
    attrs = [
        n.attribution for n in narratives
        if n.attribution is not None
        and n.attribution.pace_deserved_position is not None
    ]
    if not attrs:
        return PaceVsResultTendency()
    return PaceVsResultTendency(
        mean_positions_left=mean(
            a.actual_position - a.pace_deserved_position for a in attrs
        ),
        mean_incident_time_lost_s=mean(a.incident_time_lost_s for a in attrs),
        mean_actual_position=mean(a.actual_position for a in attrs),
        mean_deserved_position=mean(a.pace_deserved_position for a in attrs),
        sample=len(attrs),
        enough_data=len(attrs) >= RACECRAFT_MIN_RACES,
    )


def _incidents(narratives: list[RaceNarrative]) -> IncidentTendency:
    if not narratives:
        return IncidentTendency()
    events = [e for n in narratives for e in n.incidents]
    corners = Counter(
        e.corner_name for e in events if e.corner_name
    )
    recurring = sorted(
        ((c, k) for c, k in corners.items() if k >= RECURRING_CORNER_MIN),
        key=lambda x: (-x[1], x[0]),
    )
    return IncidentTendency(
        mean_incident_points=mean(n.header.incidents for n in narratives),
        lap1_share=(
            sum(1 for e in events if e.lap <= 1) / len(events)
            if events else None
        ),
        recurring_corners=recurring,
        sample=len(narratives),
        enough_data=len(narratives) >= RACECRAFT_MIN_RACES,
    )


def _trajectory(narratives: list[RaceNarrative]) -> TrajectoryTendency:
    # Partial captures without results have 0/absent positions — skip them.
    with_pos = [
        n.header for n in narratives
        if n.header.start_position >= 1 and n.header.finish_position >= 1
    ]
    trends = [
        s.trend_s for n in narratives for s in n.stints if s.trend_s is not None
    ]
    if not with_pos and not trends:
        return TrajectoryTendency()
    return TrajectoryTendency(
        mean_race_net=(
            mean(h.start_position - h.finish_position for h in with_pos)
            if with_pos else None
        ),
        mean_stint_fade_s=mean(trends) if trends else None,
        sample=len(with_pos),
        enough_data=len(with_pos) >= RACECRAFT_MIN_RACES,
    )


def build_racecraft(narratives: list[RaceNarrative]) -> RacecraftTendencies:
    """All four tendencies from the driver's stored race narratives."""
    return RacecraftTendencies(
        starts=_starts(narratives),
        pace_vs_result=_pace_vs_result(narratives),
        incidents=_incidents(narratives),
        trajectory=_trajectory(narratives),
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_racecraft.py -v`
Expected: PASS (7 tests, after the implementer-note fixes to the two flagged tests).

- [ ] **Step 5: Commit**

```bash
git add core/profile/ tests/test_profile_racecraft.py
git commit -m "feat(profile): models + pure racecraft-tendency engine"
```

---

## Task 4: pace/readiness engine

**Files:**
- Create: `core/profile/pace.py`
- Test: `tests/test_profile_pace.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_pace.py`:

```python
"""Tests for the pure per-combo readiness engine (synthetic history)."""

from core.profile.pace import build_readiness
from core.track.track_db import LapRow, SessionRow


def _sess(sid, date, best=100.0, track="525", name="Spa", car="M2",
          stype="practice"):
    return SessionRow(session_id=sid, track_id=track, track_name=name,
                      car=car, session_type=stype, session_date=date,
                      best_lap_time=best, lap_count=0)


def _laps(times, valid=True):
    return [LapRow(lap_number=i + 1, lap_time=t, is_valid=valid)
            for i, t in enumerate(times)]


def test_grouping_and_thresholds():
    sessions = [
        _sess("a", "2026-07-01", best=101.0),
        _sess("b", "2026-07-02", best=100.0),
        _sess("c", "2026-07-03", best=99.5, track="219", name="Bathurst"),
    ]
    laps = {
        "a": _laps([101.0, 101.5, 102.0, 101.2, 101.1]),
        "b": _laps([100.0, 100.4, 100.2, 100.6, 100.3]),
        "c": _laps([99.5, 99.9]),
    }
    combos = build_readiness(sessions, laps)
    assert len(combos) == 2
    spa = next(c for c in combos if c.track_id == "525")
    assert spa.sessions == 2 and spa.valid_laps == 10
    assert spa.enough_data                      # 2 sessions, 10 laps — exactly at threshold
    assert spa.best_lap == 100.0
    assert spa.pb_trend_s == 1.0                # 101.0 -> 100.0 = 1.0s faster
    assert spa.last_driven == "2026-07-02"
    bathurst = next(c for c in combos if c.track_id == "219")
    assert not bathurst.enough_data             # 1 session, 2 laps


def test_race_sessions_excluded():
    sessions = [
        _sess("a", "2026-07-01"),
        _sess("r", "2026-07-02", stype="Race"),
    ]
    laps = {"a": _laps([100.0] * 10), "r": _laps([99.0] * 10)}
    combos = build_readiness(sessions, laps)
    assert combos[0].sessions == 1
    assert combos[0].valid_laps == 10
    assert combos[0].best_lap == 100.0          # race best ignored


def test_invalid_laps_dont_count():
    sessions = [_sess("a", "2026-07-01"), _sess("b", "2026-07-02")]
    laps = {
        "a": _laps([100.0] * 5) + _laps([130.0] * 5, valid=False),
        "b": _laps([100.0] * 4),
    }
    combos = build_readiness(sessions, laps)
    assert combos[0].valid_laps == 9
    assert not combos[0].enough_data            # 9 < 10


def test_sessions_without_best_count_laps_but_not_sessions():
    sessions = [
        _sess("a", "2026-07-01"),
        _sess("stub", "2026-07-02", best=None),
        _sess("b", "2026-07-03"),
    ]
    laps = {"a": _laps([100.0] * 5), "stub": [], "b": _laps([100.0] * 5)}
    combos = build_readiness(sessions, laps)
    assert combos[0].sessions == 2              # stub excluded from session count


def test_consistency_uses_recent_window():
    # 4 sessions; early ones wild, last 3 tight -> consistency from last 3 only
    sessions = [_sess(s, f"2026-07-0{i+1}")
                for i, s in enumerate(["a", "b", "c", "d"])]
    laps = {
        "a": _laps([100.0, 108.0, 95.0, 103.0, 99.0]),
        "b": _laps([100.0, 100.2]),
        "c": _laps([100.1, 100.3]),
        "d": _laps([100.0, 100.2]),
    }
    combos = build_readiness(sessions, laps)
    c = combos[0]
    assert c.consistency_s is not None
    assert c.consistency_s < 0.5                # tight window, wild session excluded


def test_consistency_none_below_min_laps():
    sessions = [_sess("a", "2026-07-01"), _sess("b", "2026-07-02")]
    laps = {"a": _laps([100.0, 100.1]), "b": _laps([100.2, 100.0])}
    combos = build_readiness(sessions, laps)
    assert combos[0].consistency_s is None      # 4 < CONSISTENCY_MIN_LAPS


def test_sorted_by_valid_laps_desc():
    sessions = [
        _sess("a", "2026-07-01"),
        _sess("b", "2026-07-02", track="219", name="Bathurst"),
    ]
    laps = {"a": _laps([100.0] * 3), "b": _laps([99.0] * 8)}
    combos = build_readiness(sessions, laps)
    assert [c.track_id for c in combos] == ["219", "525"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_pace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.profile.pace'`.

- [ ] **Step 3: Implement**

Create `core/profile/pace.py`:

```python
"""PURE per-combo readiness engine: watcher session history -> readiness.

Race-type sessions are EXCLUDED — race pace (traffic, fuel) would pollute
practice consistency; race tendencies live in racecraft.py instead.
Verdicts are benchmark-free: own progression + consistency only.
"""

from statistics import stdev

from core.profile.models import (
    CONSISTENCY_MIN_LAPS,
    CONSISTENCY_WINDOW_SESSIONS,
    READINESS_MIN_LAPS,
    READINESS_MIN_SESSIONS,
    ComboReadiness,
)
from core.track.track_db import LapRow, SessionRow


def build_readiness(
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
) -> list[ComboReadiness]:
    """Per-combo readiness, most-practiced first. `laps` maps session_id ->
    that session's lap rows (missing keys = no laps recorded)."""
    practice = [s for s in sessions if s.session_type != "Race"]
    by_combo: dict[tuple[str, str], list[SessionRow]] = {}
    for s in sorted(practice, key=lambda s: s.session_date):
        by_combo.setdefault((s.track_id, s.car), []).append(s)

    combos: list[ComboReadiness] = []
    for (track_id, car), rows in by_combo.items():
        with_best = [s for s in rows if s.best_lap_time is not None]
        valid_lap_times: list[float] = []
        for s in rows:
            valid_lap_times.extend(
                l.lap_time for l in laps.get(s.session_id, []) if l.is_valid
            )
        recent = rows[-CONSISTENCY_WINDOW_SESSIONS:]
        recent_valid = [
            l.lap_time
            for s in recent
            for l in laps.get(s.session_id, [])
            if l.is_valid
        ]
        combos.append(ComboReadiness(
            track_id=track_id,
            track_name=rows[-1].track_name,
            car=car,
            sessions=len(with_best),
            valid_laps=len(valid_lap_times),
            last_driven=rows[-1].session_date,
            best_lap=(
                min(s.best_lap_time for s in with_best) if with_best else None
            ),
            pb_trend_s=(
                with_best[0].best_lap_time - with_best[-1].best_lap_time
                if len(with_best) >= 2 else None
            ),
            consistency_s=(
                stdev(recent_valid)
                if len(recent_valid) >= CONSISTENCY_MIN_LAPS else None
            ),
            enough_data=(
                len(with_best) >= READINESS_MIN_SESSIONS
                and len(valid_lap_times) >= READINESS_MIN_LAPS
            ),
        ))
    combos.sort(key=lambda c: -c.valid_laps)
    return combos
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_pace.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add core/profile/pace.py tests/test_profile_pace.py
git commit -m "feat(profile): pure per-combo readiness engine"
```

---

## Task 5: render — verdicts, markdown, prompt block

**Files:**
- Create: `core/profile/render.py`
- Test: `tests/test_profile_render.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_render.py`:

```python
"""Exact-string tests for verdicts and the prompt block (like nudges)."""

import json

from core.profile.models import (
    ComboReadiness,
    DriverProfile,
    IncidentTendency,
    PaceVsResultTendency,
    RacecraftTendencies,
    StartsTendency,
    TrajectoryTendency,
)
from core.profile.render import (
    profile_prompt_block,
    verdict_incidents,
    verdict_pace_vs_result,
    verdict_readiness,
    verdict_starts,
    verdict_trajectory,
)


def test_verdict_starts_losing():
    t = StartsTendency(mean_lap1_net=-1.4, mean_lap2_net=0.2,
                       races_lost_ground=5, sample=6, enough_data=True)
    assert verdict_starts(t) == (
        "You lose ground at the start — avg -1.4 places on lap 1 "
        "across 6 races (lost ground in 5 of 6)."
    )


def test_verdict_starts_gaining_and_neutral():
    g = StartsTendency(mean_lap1_net=1.2, mean_lap2_net=0.0,
                       races_lost_ground=1, sample=4, enough_data=True)
    assert verdict_starts(g).startswith("You gain ground at the start")
    n = StartsTendency(mean_lap1_net=0.1, mean_lap2_net=0.0,
                       races_lost_ground=2, sample=4, enough_data=True)
    assert verdict_starts(n).startswith("Starts are roughly neutral")


def test_verdict_pace_vs_result_leaving_positions():
    t = PaceVsResultTendency(mean_positions_left=2.0,
                             mean_incident_time_lost_s=8.5,
                             mean_actual_position=6.0,
                             mean_deserved_position=4.0,
                             sample=5, enough_data=True)
    assert verdict_pace_vs_result(t) == (
        "Your pace deserves ~P4 but you finish ~P6 — the gap is incidents "
        "and decisions, not speed (avg 8.5s/race lost to incidents)."
    )


def test_verdict_incidents_with_recurring():
    t = IncidentTendency(mean_incident_points=3.2, lap1_share=0.4,
                         recurring_corners=[("Old Hall", 3), ("Lodge", 2)],
                         sample=5, enough_data=True)
    assert verdict_incidents(t) == (
        "3.2 incident points/race, 40% of incidents on lap 1. "
        "Repeat trouble: Old Hall (3x), Lodge (2x)."
    )


def test_verdict_trajectory_gains_but_fades():
    t = TrajectoryTendency(mean_race_net=1.8, mean_stint_fade_s=0.3,
                           sample=4, enough_data=True)
    assert verdict_trajectory(t) == (
        "You gain +1.8 places over a race on average, but fade late "
        "(+0.3s second-half pace)."
    )


def test_verdict_readiness():
    c = ComboReadiness(track_id="525", track_name="Spa", car="M2",
                       sessions=14, valid_laps=89, last_driven="2026-07-08",
                       best_lap=159.2, pb_trend_s=1.2, consistency_s=0.4,
                       enough_data=True)
    assert verdict_readiness(c) == (
        "Spa / M2: 14 sessions, 89 clean laps. PB down 1.2s over the run; "
        "recent laps within ±0.4s."
    )


def _full_profile() -> DriverProfile:
    return DriverProfile(
        cust_id=100, driver_name="D", races_captured=6, combos_tracked=2,
        racecraft=RacecraftTendencies(
            starts=StartsTendency(mean_lap1_net=-1.4, mean_lap2_net=0.2,
                                  races_lost_ground=5, sample=6,
                                  enough_data=True),
            pace_vs_result=PaceVsResultTendency(
                mean_positions_left=2.0, mean_incident_time_lost_s=8.5,
                mean_actual_position=6.0, mean_deserved_position=4.0,
                sample=5, enough_data=True),
            incidents=IncidentTendency(mean_incident_points=3.2,
                                       lap1_share=0.4,
                                       recurring_corners=[("Old Hall", 3)],
                                       sample=6, enough_data=True),
            trajectory=TrajectoryTendency(sample=2, enough_data=False),
        ),
        readiness=[
            ComboReadiness(track_id="525", track_name="Spa", car="M2",
                           sessions=14, valid_laps=89,
                           last_driven="2026-07-08", best_lap=159.2,
                           pb_trend_s=1.2, consistency_s=0.4,
                           enough_data=True),
            ComboReadiness(track_id="219", track_name="Bathurst", car="992",
                           sessions=1, valid_laps=4, enough_data=False),
        ],
    )


def test_prompt_block_includes_only_enough_data():
    block = profile_prompt_block(_full_profile())
    assert block.startswith("--- DRIVER PROFILE")
    assert block.rstrip().endswith("--- END DRIVER PROFILE ---")
    payload = json.loads(block.split("---")[2])
    assert set(payload["tendencies"]) == {"starts", "pace_vs_result", "incidents"}
    assert "trajectory" not in payload["tendencies"]     # below threshold
    assert len(payload["readiness"]) == 1                # Bathurst excluded
    assert payload["races"] == 6


def test_prompt_block_empty_when_nothing_crosses_threshold():
    assert profile_prompt_block(DriverProfile(races_captured=1)) == ""


def test_prompt_block_respects_char_cap():
    p = _full_profile()
    p.readiness = [
        ComboReadiness(track_id=str(i), track_name="T" * 40, car="C" * 40,
                       sessions=5, valid_laps=50, last_driven="2026-07-08",
                       best_lap=100.0, pb_trend_s=0.5, consistency_s=0.3,
                       enough_data=True)
        for i in range(50)
    ]
    block = profile_prompt_block(p)
    assert len(block) <= 2000
    assert block.rstrip().endswith("--- END DRIVER PROFILE ---")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.profile.render'`.

- [ ] **Step 3: Implement**

Create `core/profile/render.py`:

```python
"""Deterministic presentation of the driver profile.

Verdict one-liners (exact-string tested, like nudges), the page markdown,
and the compact prompt block injected into the race debrief. No AI here —
the AI only ever consumes this output as context.
"""

import json

from core.profile.models import (
    ComboReadiness,
    DriverProfile,
    IncidentTendency,
    PaceVsResultTendency,
    StartsTendency,
    TrajectoryTendency,
)

PROMPT_BLOCK_MAX_CHARS = 2000
PROMPT_BLOCK_MAX_COMBOS = 5
NEUTRAL_BAND = 0.5          # |mean| below this = "roughly neutral"
FADE_BAND_S = 0.15          # |fade| below this = not worth mentioning


def verdict_starts(t: StartsTendency) -> str:
    m = t.mean_lap1_net or 0.0
    if m <= -NEUTRAL_BAND:
        head = "You lose ground at the start"
    elif m >= NEUTRAL_BAND:
        head = "You gain ground at the start"
    else:
        head = "Starts are roughly neutral"
    return (
        f"{head} — avg {m:+.1f} places on lap 1 across {t.sample} races "
        f"(lost ground in {t.races_lost_ground} of {t.sample})."
    ).replace("+-", "-")


def verdict_pace_vs_result(t: PaceVsResultTendency) -> str:
    left = t.mean_positions_left or 0.0
    act = round(t.mean_actual_position or 0)
    des = round(t.mean_deserved_position or 0)
    lost = t.mean_incident_time_lost_s or 0.0
    if left >= NEUTRAL_BAND:
        return (
            f"Your pace deserves ~P{des} but you finish ~P{act} — the gap "
            f"is incidents and decisions, not speed "
            f"(avg {lost:.1f}s/race lost to incidents)."
        )
    if left <= -NEUTRAL_BAND:
        return (
            f"You finish ~P{act} on ~P{des} pace — strong racecraft is "
            "earning you positions."
        )
    return f"You finish about where your pace deserves (~P{act})."


def verdict_incidents(t: IncidentTendency) -> str:
    parts = [f"{t.mean_incident_points:.1f} incident points/race"]
    if t.lap1_share is not None:
        parts.append(f"{t.lap1_share:.0%} of incidents on lap 1")
    line = ", ".join(parts) + "."
    if t.recurring_corners:
        repeats = ", ".join(f"{c} ({k}x)" for c, k in t.recurring_corners)
        line += f" Repeat trouble: {repeats}."
    return line


def verdict_trajectory(t: TrajectoryTendency) -> str:
    net = t.mean_race_net or 0.0
    if net >= NEUTRAL_BAND:
        head = f"You gain {net:+.1f} places over a race on average"
    elif net <= -NEUTRAL_BAND:
        head = f"You lose {net:+.1f} places over a race on average"
    else:
        head = "You finish about where you start"
    fade = t.mean_stint_fade_s
    if fade is not None and fade >= FADE_BAND_S:
        return f"{head}, but fade late ({fade:+.1f}s second-half pace)."
    if fade is not None and fade <= -FADE_BAND_S:
        return f"{head}, and get quicker late ({fade:+.1f}s second-half pace)."
    return f"{head}."


def verdict_readiness(c: ComboReadiness) -> str:
    line = (
        f"{c.track_name} / {c.car}: {c.sessions} sessions, "
        f"{c.valid_laps} clean laps."
    )
    if c.pb_trend_s is not None:
        direction = "down" if c.pb_trend_s >= 0 else "up"
        line += f" PB {direction} {abs(c.pb_trend_s):.1f}s over the run;"
    if c.consistency_s is not None:
        line += f" recent laps within ±{c.consistency_s:.1f}s."
    return line.rstrip(";") + ("" if line.endswith(".") else "")


def _tendency_payloads(p: DriverProfile) -> dict:
    r = p.racecraft
    out: dict[str, dict] = {}
    if r.starts.enough_data:
        out["starts"] = {"verdict": verdict_starts(r.starts),
                         "mean_lap1_net": r.starts.mean_lap1_net,
                         "sample": r.starts.sample}
    if r.pace_vs_result.enough_data:
        out["pace_vs_result"] = {
            "verdict": verdict_pace_vs_result(r.pace_vs_result),
            "mean_positions_left": r.pace_vs_result.mean_positions_left,
            "sample": r.pace_vs_result.sample}
    if r.incidents.enough_data:
        out["incidents"] = {"verdict": verdict_incidents(r.incidents),
                            "lap1_share": r.incidents.lap1_share,
                            "recurring": r.incidents.recurring_corners,
                            "sample": r.incidents.sample}
    if r.trajectory.enough_data:
        out["trajectory"] = {"verdict": verdict_trajectory(r.trajectory),
                             "mean_race_net": r.trajectory.mean_race_net,
                             "sample": r.trajectory.sample}
    return out


def profile_prompt_block(p: DriverProfile) -> str:
    """Compact grounded context for the debrief prompt; "" when nothing
    crosses threshold. Hard-capped: drops readiness combos first, then
    trailing tendencies."""
    tendencies = _tendency_payloads(p)
    ready = [c for c in p.readiness if c.enough_data][:PROMPT_BLOCK_MAX_COMBOS]
    if not tendencies and not ready:
        return ""

    def _assemble(tend: dict, combos: list[ComboReadiness]) -> str:
        payload = {
            "races": p.races_captured,
            "tendencies": tend,
            "readiness": [verdict_readiness(c) for c in combos],
        }
        return (
            f"--- DRIVER PROFILE (tendencies across {p.races_captured} "
            "prior races; computed deterministically) ---\n"
            + json.dumps(payload)
            + "\n--- END DRIVER PROFILE ---"
        )

    block = _assemble(tendencies, ready)
    while len(block) > PROMPT_BLOCK_MAX_CHARS and ready:
        ready = ready[:-1]
        block = _assemble(tendencies, ready)
    keys = list(tendencies)
    while len(block) > PROMPT_BLOCK_MAX_CHARS and keys:
        keys = keys[:-1]
        block = _assemble({k: tendencies[k] for k in keys}, ready)
    return block if (keys or ready) else ""


def profile_markdown(p: DriverProfile) -> str:
    """Page body / export text. Sub-threshold items show progress."""
    from core.profile.models import RACECRAFT_MIN_RACES

    lines = [
        f"**{p.races_captured}** races captured · "
        f"**{p.combos_tracked}** combos tracked",
        "",
        "## Racecraft",
    ]
    r = p.racecraft
    for label, t, verdict in [
        ("Pace vs result", r.pace_vs_result, verdict_pace_vs_result),
        ("Starts", r.starts, verdict_starts),
        ("Incidents", r.incidents, verdict_incidents),
        ("Race trajectory", r.trajectory, verdict_trajectory),
    ]:
        if t.enough_data:
            lines.append(f"- **{label}** — {verdict(t)}")
        else:
            lines.append(
                f"- **{label}** — collecting data "
                f"({t.sample} of {RACECRAFT_MIN_RACES} races captured)."
            )
    lines += ["", "## Practice readiness"]
    if not p.readiness:
        lines.append("_No practice history yet — sessions accrue "
                     "automatically via the telemetry watcher._")
    for c in p.readiness:
        if c.enough_data:
            lines.append(f"- {verdict_readiness(c)}")
        else:
            lines.append(
                f"- {c.track_name} / {c.car} — collecting data "
                f"({c.sessions} sessions, {c.valid_laps} clean laps)."
            )
    return "\n".join(lines)
```

**Implementer note:** run the exact-string tests and adjust the f-string details until they pass **as written in the tests** (the tests are the contract; e.g. `-1.4` renders via `{m:+.1f}` as `+-1.4` → the `.replace("+-", "-")` handles it; verify `verdict_readiness` produces the exact expected string incl. punctuation — simplify the trailing-punctuation logic if needed to match the test exactly).

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_render.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add core/profile/render.py tests/test_profile_render.py
git commit -m "feat(profile): verdict lines, page markdown, capped prompt block"
```

---

## Task 6: builder (`load_profile`)

**Files:**
- Create: `core/profile/builder.py`
- Test: `tests/test_profile_builder.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_builder.py`:

```python
"""Builder integration: temp stores -> DriverProfile (the only I/O path)."""

from core.profile.builder import load_profile
from core.race.race_store import RaceStore
from core.track.track_db import TrackDB

# Reuse the synthetic narrative helpers from the racecraft tests.
from tests.test_profile_racecraft import _attr, _lap1, _narr


def test_load_profile_assembles_both_layers(tmp_path):
    race_store = RaceStore(tmp_path / "races.db")
    for i in range(3):
        race_store.save_race(
            _narr(lap1=_lap1(), attribution=_attr(), subsession_id=i + 1),
            ibt_file_path=f"{i}.ibt",
        )
    track_db = TrackDB(tmp_path / "tracks.db")
    track_db.record_session(
        session_id="s1", track_id="525", car="M2", session_type="practice",
        session_date="2026-07-01", best_lap_time=100.0, lap_count=5,
        ibt_file_path="p.ibt",
    )
    track_db.record_laps("s1", [(i + 1, 100.0 + i * 0.1, True) for i in range(5)])

    profile = load_profile(race_store, track_db, cust_id=100)
    assert profile.cust_id == 100
    assert profile.races_captured == 3
    assert profile.racecraft.starts.enough_data
    assert profile.combos_tracked == 1
    assert profile.readiness[0].track_id == "525"


def test_load_profile_empty_stores(tmp_path):
    profile = load_profile(
        RaceStore(tmp_path / "r.db"), TrackDB(tmp_path / "t.db"), cust_id=1
    )
    assert profile.races_captured == 0
    assert profile.readiness == []
    assert not profile.racecraft.starts.enough_data


def test_load_profile_store_failure_degrades_to_empty(tmp_path):
    class ExplodingStore:
        def get_narratives(self, cust_id):
            raise RuntimeError("boom")

    profile = load_profile(
        ExplodingStore(), TrackDB(tmp_path / "t.db"), cust_id=1
    )
    assert profile.races_captured == 0        # degraded, not raised
```

Note: `_narr(...)` must accept `subsession_id` through `header_kw` — it does (kwargs pass through to `_header`).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.profile.builder'`.

- [ ] **Step 3: Implement**

Create `core/profile/builder.py`:

```python
"""Assemble the DriverProfile from the stores — the package's only I/O.

Derive-on-demand: dozens of narratives + hundreds of lap rows, cheap to
recompute every render; no profile table, no staleness. Any store failure
degrades to an empty profile — the profile must never break a page.
"""

import logging

from core.profile.models import DriverProfile
from core.profile.pace import build_readiness
from core.profile.racecraft import build_racecraft
from core.race.race_store import RaceStore
from core.track.track_db import TrackDB

logger = logging.getLogger(__name__)


def load_profile(
    race_store: RaceStore, track_db: TrackDB, cust_id: int
) -> DriverProfile:
    """The driver's current profile, derived fresh from both stores."""
    try:
        narratives = race_store.get_narratives(cust_id)
    except Exception:  # noqa: BLE001 — profile must never break a page
        logger.exception("Profile: narrative load failed")
        narratives = []
    try:
        sessions = track_db.list_session_history()
        laps = {s.session_id: track_db.get_session_laps(s.session_id)
                for s in sessions}
    except Exception:  # noqa: BLE001
        logger.exception("Profile: session-history load failed")
        sessions, laps = [], {}

    readiness = build_readiness(sessions, laps)
    return DriverProfile(
        cust_id=cust_id,
        driver_name=(narratives[0].header.driver_name if narratives else ""),
        races_captured=len(narratives),
        combos_tracked=len(readiness),
        racecraft=build_racecraft(narratives),
        readiness=readiness,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_builder.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/profile/builder.py tests/test_profile_builder.py
git commit -m "feat(profile): load_profile builder (derive-on-demand, degrades to empty)"
```

---

## Task 7: prompt integration + tone amendment

**Files:**
- Modify: `core/coaching/prompts/race_debrief.py`
- Modify: `core/coaching/synthesizer.py` (methods `generate_race_debrief` ~line 168, `race_chat_reply` ~line 196)
- Test: Create `tests/test_race_prompts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_race_prompts.py`:

```python
"""Prompt-builder tests: profile injection + tone-contract amendment."""

from core.coaching.prompts.race_debrief import (
    RACE_DEBRIEF_SYSTEM_PROMPT,
    build_race_chat_system,
    build_race_debrief_prompt,
)
from tests.test_profile_racecraft import _narr


def test_debrief_prompt_without_block_unchanged():
    p = build_race_debrief_prompt(_narr())
    assert "DRIVER PROFILE" not in p
    assert "--- RACE DATA (JSON) ---" in p


def test_debrief_prompt_with_block_inserts_before_race_data():
    block = "--- DRIVER PROFILE ---\n{}\n--- END DRIVER PROFILE ---"
    p = build_race_debrief_prompt(_narr(), profile_block=block)
    assert block in p
    assert p.index(block) < p.index("--- RACE DATA (JSON) ---")


def test_chat_system_with_block():
    p = build_race_chat_system(_narr(), "debrief text",
                               profile_block="--- DRIVER PROFILE X ---")
    assert "--- DRIVER PROFILE X ---" in p


def test_tone_contract_permits_profile_as_cited_source():
    assert "driver-profile block" in RACE_DEBRIEF_SYSTEM_PROMPT
    assert "cross-race" in RACE_DEBRIEF_SYSTEM_PROMPT
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_prompts.py -v`
Expected: FAIL — `TypeError: build_race_debrief_prompt() got an unexpected keyword argument 'profile_block'` (and the tone assertion fails).

- [ ] **Step 3: Implement**

In `core/coaching/prompts/race_debrief.py`:

(a) Amend rule 2 of `RACE_DEBRIEF_SYSTEM_PROMPT`. Replace:
```
2. Every factual claim (positions, gaps, lap times, incidents, iRating)
   MUST come from the race data JSON you are given. Never invent or
   extrapolate facts. If the data doesn't contain something, don't
   claim it.
```
with:
```
2. Every factual claim (positions, gaps, lap times, incidents, iRating)
   MUST come from the race data JSON you are given, or from the
   driver-profile block when one is provided. Profile facts are
   cross-race tendencies — cite them as such ("across your last 6
   races"), never as facts about this race. Never invent or
   extrapolate facts. If the data doesn't contain something, don't
   claim it.
```

(b) Extend the builders:
```python
def build_race_debrief_prompt(
    narrative: RaceNarrative, profile_block: str = ""
) -> str:
    """User message for the one-shot debrief generation."""
    h = narrative.header
    profile_part = f"{profile_block}\n\n" if profile_block else ""
    return (
        f"Debrief this race for {h.driver_name} "
        f"({h.car_name}, {h.series_name}).\n\n"
        + profile_part
        + "--- RACE DATA (JSON) ---\n"
        f"{json.dumps(narrative.to_dict(), indent=2)}\n"
        "--- END RACE DATA ---\n\n"
        "Write the debrief."
    )


def build_race_chat_system(
    narrative: RaceNarrative, debrief_text: str, profile_block: str = ""
) -> str:
    """System prompt for follow-up chat, grounded in the same data."""
    profile_part = (
        "\n\nThe driver's cross-race profile:\n" + profile_block
        if profile_block else ""
    )
    return (
        RACE_DEBRIEF_SYSTEM_PROMPT
        + profile_part
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

(c) In `core/coaching/synthesizer.py`, thread the param through:
- `def generate_race_debrief(self, narrative: "RaceNarrative", profile_block: str = "") -> RaceDebriefReport:` and pass `build_race_debrief_prompt(narrative, profile_block)`.
- `def race_chat_reply(self, narrative, debrief_text, history, profile_block: str = "") -> str:` and pass `build_race_chat_system(narrative, debrief_text, profile_block)`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_race_prompts.py tests/test_synthesizer.py -v`
Expected: PASS (new tests + existing synthesizer tests unaffected by the default params).

- [ ] **Step 5: Commit**

```bash
git add core/coaching/prompts/race_debrief.py core/coaching/synthesizer.py tests/test_race_prompts.py
git commit -m "feat(prompts): profile block injection + tone-contract amendment"
```

---

## Task 8: profile page + wiring

No unit tests (display only; business logic all lives in tested core modules). Verified by ast + import + a smoke run in Task 9.

**Files:**
- Create: `app/pages/driver_profile.py`
- Modify: `app/streamlit_app.py` (PAGES dict + dispatch)
- Modify: `app/pages/race_debrief.py` (build + pass the block)

- [ ] **Step 1: Create the page**

Create `app/pages/driver_profile.py` (READ `app/pages/race_debrief.py`'s top matter first — mirror its constants/imports style):

```python
"""Driver Profile page — racecraft tendencies + practice readiness.

Display only: everything is computed by core/profile (deterministic,
tested); this file renders it. No AI on this page.
"""

from collections import Counter
from pathlib import Path

import streamlit as st

from core.profile.builder import load_profile
from core.profile.models import RACECRAFT_MIN_RACES
from core.profile.render import (
    verdict_incidents,
    verdict_pace_vs_result,
    verdict_readiness,
    verdict_starts,
    verdict_trajectory,
)
from core.race.race_store import RaceStore
from core.track.track_db import TrackDB

RACES_DB = Path("data/races.db")
TRACKS_DB = Path("data/tracks.db")


def _resolve_cust_id(store: RaceStore) -> int | None:
    """Most-frequent cust_id in races.db; selectbox when several exist."""
    races = store.list_races()
    if not races:
        return None
    counts = Counter(r.cust_id for r in races)
    if len(counts) == 1:
        return next(iter(counts))
    names = {r.cust_id: r.driver_name for r in races}
    options = [c for c, _ in counts.most_common()]
    return st.selectbox(
        "Driver", options,
        format_func=lambda c: f"{names.get(c, c)} ({c})",
    )


def render_driver_profile_page() -> None:
    st.title("Driver Profile")
    store = RaceStore(RACES_DB)
    track_db = TrackDB(TRACKS_DB)

    cust_id = _resolve_cust_id(store)
    profile = load_profile(store, track_db, cust_id or 0)

    if profile.races_captured == 0 and not profile.readiness:
        st.info(
            "No data yet. Races are captured automatically by the telemetry "
            "watcher after every official race, and practice sessions accrue "
            "the same way — drive, and this page fills itself in."
        )
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Races captured", profile.races_captured)
    c2.metric("Combos tracked", profile.combos_tracked)
    c3.metric("Clean practice laps",
              sum(c.valid_laps for c in profile.readiness))

    st.subheader("Racecraft")
    r = profile.racecraft
    for label, t, verdict in [
        ("Pace vs result", r.pace_vs_result, verdict_pace_vs_result),
        ("Starts", r.starts, verdict_starts),
        ("Incidents", r.incidents, verdict_incidents),
        ("Race trajectory", r.trajectory, verdict_trajectory),
    ]:
        with st.container(border=True):
            st.markdown(f"**{label}**")
            if t.enough_data:
                st.write(verdict(t))
                st.caption(f"Across {t.sample} races.")
            else:
                st.caption(
                    f"Collecting data — {t.sample} of "
                    f"{RACECRAFT_MIN_RACES} races captured."
                )

    st.subheader("Practice readiness")
    if not profile.readiness:
        st.caption("No practice history yet.")
    for combo in profile.readiness:
        if combo.enough_data:
            st.markdown(f"- {verdict_readiness(combo)}")
        else:
            st.markdown(
                f"- {combo.track_name} / {combo.car} — collecting data "
                f"({combo.sessions} sessions, {combo.valid_laps} clean laps)."
            )
```

- [ ] **Step 2: Register the page**

In `app/streamlit_app.py`, add to the `PAGES` dict (after Race Debrief):
```python
    "\U0001f464 Driver Profile": "driver_profile",
```
and add the dispatch branch (matching the existing pattern):
```python
elif page == "driver_profile":
    from app.pages.driver_profile import render_driver_profile_page

    render_driver_profile_page()
```

- [ ] **Step 3: Wire injection into the debrief page**

In `app/pages/race_debrief.py`: find where the AI debrief is generated (`synth.generate_race_debrief(narrative)` ~line 195) and where the chat reply is produced (`race_chat_reply(...)`, in `_render_debrief_and_chat`). Add a helper near the other module helpers:

```python
def _profile_block(cust_id: int) -> str:
    """Compact cross-race profile context for the AI; "" on any failure."""
    try:
        from core.profile.builder import load_profile
        from core.profile.render import profile_prompt_block

        profile = load_profile(RaceStore(RACES_DB), TrackDB(TRACKS_DB), cust_id)
        return profile_prompt_block(profile)
    except Exception:  # noqa: BLE001 — profile must never break the debrief
        return ""
```

(Check the file's actual constant names for the two DB paths — it defines `TRACKS_DB`; it constructs `RaceStore` with its races-db path constant or default. Reuse exactly what exists; add a `RACES_DB` constant only if the file doesn't already have one.)

Then pass it at both call sites:
```python
report = synth.generate_race_debrief(
    narrative, profile_block=_profile_block(narrative.header.cust_id)
)
```
and in the chat turn:
```python
reply = synth.race_chat_reply(
    narrative, debrief_text, history,
    profile_block=_profile_block(narrative.header.cust_id),
)
```
(Match the actual local variable names at those call sites — read the surrounding code.)

- [ ] **Step 4: Verify**

Run: `.venv/Scripts/python.exe -c "import ast; [ast.parse(open(f).read()) for f in ['app/pages/driver_profile.py','app/streamlit_app.py','app/pages/race_debrief.py']]; print('ok')"`
Expected: `ok`

Run: `.venv/Scripts/python.exe -c "import app.pages.driver_profile; print('ok')"`
Expected: `ok` (streamlit imports fine outside a run context).

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: full suite passes.

- [ ] **Step 5: Commit**

```bash
git add app/pages/driver_profile.py app/streamlit_app.py app/pages/race_debrief.py
git commit -m "feat(app): Driver Profile page + profile injection into race debrief"
```

---

## Task 9: full suite + manual verification + finalize

**Files:** none (verification only)

- [ ] **Step 1: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (~+28 new tests over the 501/9 baseline; no regressions).

- [ ] **Step 2: Manual check against real data**

Run: `.venv/Scripts/python.exe -c "from core.profile.builder import load_profile; from core.race.race_store import RaceStore; from core.track.track_db import TrackDB; from core.profile.render import profile_markdown, profile_prompt_block; p = load_profile(RaceStore('data/races.db'), TrackDB('data/tracks.db'), 1226848); print(profile_markdown(p)); print(); print('PROMPT BLOCK:', repr(profile_prompt_block(p))[:400])"`
Expected with today's data: 1 race captured → all racecraft cards "collecting data (1 of 3)"; readiness list populated from the 68 practice sessions (several combos over threshold); prompt block likely non-empty from readiness alone. Sanity-check a couple of combo lap counts against the watcher history.

Then open the running Streamlit app → the new Driver Profile page renders; the Race Debrief page still generates (with the block silently included).

- [ ] **Step 3: Finalize**

Use the finishing-a-development-branch skill (merge `driver-profile-v1` to master). Then: CLAUDE.md (architecture tree + a Driver Profile v1 section + test count), Atlas manifest (SP2 shipped; next actions), memory update.

---

## Self-Review

- **Spec coverage:** store reads → Tasks 1–2. Engine (models/racecraft/pace) → Tasks 3–4 (incl. per-tendency partial-narrative skips, Race-session exclusion, thresholds). Render/verdicts/prompt block+cap → Task 5. Builder + degrade-to-empty → Task 6. Prompt injection + tone amendment + synthesizer threading → Task 7. Page + registration + debrief wiring + cust_id resolution → Task 8. Edge cases: 1-race today → Task 9 manual check; two testers → `_resolve_cust_id`; sessions-without-best → pace.py `with_best` + test.
- **Type consistency:** `SessionRow`/`LapRow` (Task 1) consumed by `pace.py` (Task 4) and `builder.py` (Task 6); `build_readiness(sessions, laps)` signature identical in Tasks 4/6; `profile_prompt_block(p) -> str` used in Tasks 5/8; `load_profile(race_store, track_db, cust_id)` in Tasks 6/8; `profile_block: str = ""` param name identical across prompts/synthesizer/page.
- **Known soft spots (flagged inline, not placeholders):** Task 3's test file contains an explicitly-marked implementer note fixing the `incidents` kwarg collision and the trajectory arithmetic; Task 5's verdict strings are contracts — the implementer adjusts the f-strings to the tests, not vice versa; Task 8 tells the implementer to read actual constant/variable names at the debrief call sites rather than assume.
