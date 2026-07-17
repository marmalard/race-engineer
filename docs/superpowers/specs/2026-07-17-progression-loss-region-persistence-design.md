# Progression + Loss-Region Persistence — Design

**Date:** 2026-07-17
**Status:** Approved design. Fulfills the Fable-window obligation from `docs/race-engineer-v3-confidence-arc.md` §9 item 5 (spec) and builds the persistence foundation same-day.
**Origin:** v3 addendum §4 (loss-region persistence promoted to load-bearing), §4b (diagnostic taxonomy), §5 (progression / Strava layer).

## Scope

**Built today (in order):**
1. `region_diagnoses` table + TrackDB API (§1)
2. Watcher processor persistence wiring (§2)
3. History back-fill script (§3)
4. Technique tendencies v1 in the driver profile (§4)
5. Time-to-pace behavioral diagnosis (§5)

**Spec-only (post-Fable execution):**
6. Progression page (§6)
7. Pace-implied iRating (§7)
8. Prescription seed table (§8)

**Decisions locked during brainstorm:**
- Storage = typed rows in tracks.db (approach A). No blobs, no cumulative-delta traces.
- Write path = **watcher only**. Coaching-page uploads and the live coach stay read-only. The live coach's per-lap debriefs are deliberately NOT persisted (noise + DB writes on the rig path).
- Back-fill measures history against the **current** reference per combo — one consistent yardstick makes magnitude trends comparable; `reference_source`/`reference_lap_time` per row keep it honest.
- Technique vocabulary = the existing `FaultKind` ladder (`fault_kinds_from_diagnosis` in `core/live/nudges.py`). One ranking function, three consumers (cue, verdict, tendencies). No new taxonomy.

## 1. Schema: `region_diagnoses` in tracks.db

One row per diagnosed loss region of a session's best lap (top 3 by time lost, the existing `build_debrief` default).

```sql
CREATE TABLE IF NOT EXISTS region_diagnoses (
    diagnosis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    region_rank INTEGER NOT NULL,          -- 1..N, ordered by time_lost desc
    label TEXT NOT NULL,                   -- corner name or position fallback (annotate_region output)
    distance_start_m REAL NOT NULL,
    distance_end_m REAL NOT NULL,
    time_lost_s REAL NOT NULL,
    braking_delta_m REAL,                  -- NULL mirrors RegionDiagnosis None
    min_speed_delta_ms REAL NOT NULL,
    throttle_delta_m REAL,
    brake_release_delta_m REAL,
    exit_speed_delta_ms REAL NOT NULL,
    driver_min_speed_ms REAL NOT NULL,
    reference_min_speed_ms REAL NOT NULL,
    driver_lap_number INTEGER NOT NULL,
    driver_lap_time REAL NOT NULL,
    reference_source TEXT NOT NULL,        -- 'personal_best' | 'g61'
    reference_lap_time REAL NOT NULL,
    total_time_delta_s REAL NOT NULL,      -- whole-lap delta of the debrief
    created_at TEXT NOT NULL               -- ISO 8601, diagnosis run time
);
CREATE INDEX IF NOT EXISTS idx_region_diagnoses_session
    ON region_diagnoses(session_id);
```

The four live-prompt reference absolutes on `RegionDiagnosis` (`reference_brake_onset_m`, `reference_release_m`, `reference_throttle_on_m`, `reference_exit_speed_ms`) are **not** persisted — they exist for in-car cues; tendencies need deltas only. YAGNI.

### TrackDB API

```python
@dataclass
class DiagnosisContext:
    """What was compared, recorded alongside every region row."""
    driver_lap_number: int
    driver_lap_time: float
    reference_source: str
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

def record_region_diagnoses(
    self, session_id: str, context: DiagnosisContext,
    diagnoses: list[RegionDiagnosis],
) -> None:
    """Replace the diagnosis rows for a session (idempotent on rerun) —
    the record_laps DELETE+INSERT pattern. Empty list clears the rows."""

def list_region_diagnoses(self) -> list[DiagnosisRow]:
    """All diagnosis rows joined with session context (track name via
    LEFT JOIN tracks, like list_session_history), ordered by
    session_date then region_rank."""
```

`record_region_diagnoses` takes `RegionDiagnosis` objects directly, duck-typed: the runtime import of `core.coaching.debrief` stays out of track_db (TYPE_CHECKING-only annotation), keeping the layering clean with no cycle risk and no duplicated field list.

`created_at` = `datetime.now(timezone.utc).isoformat()` at write time.

## 2. Processor wiring

In `core/watcher/processor.py` `process_ibt`, immediately after the existing `build_debrief` call succeeds:

```python
result = build_debrief(best, ref.lap, corners)
track_db.record_region_diagnoses(
    session_id,
    DiagnosisContext(
        driver_lap_number=best.lap_number,
        driver_lap_time=best.lap_time,
        reference_source=ref.source,
        reference_lap_time=ref.lap_time,
        total_time_delta_s=result.total_time_delta,
    ),
    result.diagnoses,
)
report.diagnoses_recorded = len(result.diagnoses)
```

- `SessionReport` gains `diagnoses_recorded: int = 0`.
- No change to promotion, cleanliness, or debrief-gating logic. Sessions with no reference, or whose best lap is its own freshly promoted PB, write no rows — same conditions under which no debrief text is produced today.
- The write sits inside the existing catch-all try; a DB failure surfaces as `report.error` and the file retries next scan (unprocessed), consistent with current semantics.
- The CLI (`scripts/watch_telemetry.py`) prints a one-line note when `diagnoses_recorded > 0` (e.g. `  3 region diagnoses recorded`).

## 3. Back-fill script: `scripts/backfill_diagnoses.py`

Seeds the corpus from the existing telemetry history (~66 files already in the sessions table).

Flow per session row (oldest first):
1. Skip `session_type == "Race"` (the race path never debriefs laps; race telemetry is traffic-polluted).
2. Skip rows whose `ibt_file_path` no longer exists on disk (log a count).
3. Parse + normalize (same as processor), select the best **plausible** lap via a shared helper (see below).
4. Look up the **current** reference for (track_id, car) from the ReferenceStore. No reference → skip.
5. `build_debrief(best, ref.lap, corners)` → `record_region_diagnoses(...)` (overwrites — idempotent on rerun).
6. Log one line per file: recorded N / skipped (reason).

Rules:
- NEVER promotes, never touches sessions/laps rows, never writes to the ReferenceStore.
- The session that produced the current PB debriefs against its own lap → ~0 delta → zero regions → zero rows. Harmless; no special-casing.
- `--dry-run` flag prints what would be recorded without writing.

**Shared helper (small refactor):** extract the processor's parse→normalize→plausible-filter→best-selection block into `select_best_lap(path, parser, normalizer) -> tuple[SessionMeta, NormalizedLap | None, ...]` or similar in `core/watcher/processor.py`, used by both `process_ibt` and the back-fill. Exact signature is the plan's call; the invariant is that the plausibility/coverage gates are defined ONCE.

**TrackDB addition:** the back-fill needs `ibt_file_path` per session. Extend `SessionRow` with a defaulted `ibt_file_path: str = ""` field and add it to the `list_session_history` SELECT — single query, backward-compatible for every existing consumer.

## 4. Technique tendencies v1: `core/profile/technique.py`

PURE module (no I/O), mirroring `racecraft.py` / `pace.py`.

### Input adapter

`DiagnosisRow` → lightweight `RegionDiagnosis` (region span/time_lost into a `LossRegion`, deltas mapped 1:1, reference absolutes left None) → `fault_kinds_from_diagnosis(diag)`. **Coupling test required:** a row with a known fault pattern must yield the same `FaultKind` list as the live path — the adapter may not re-implement thresholds.

### Output model (`core/profile/models.py`)

```python
TECHNIQUE_MIN_SESSIONS = 5   # diagnosed sessions before tendencies speak
TECHNIQUE_TREND_WINDOW = 5   # recent sessions vs everything before
TTP_FACTOR = 1.01            # time-to-pace: within 101% of session best
TTP_MIN_LAPS = 5             # sessions shorter than this don't count

@dataclass
class FaultAggregate:
    kind: str                       # FaultKind.value
    occurrences: int                # regions where this fault crossed threshold
    combos: int                     # distinct (track_id, car) it appears in
    mean_time_lost_s: float         # mean time_lost of those regions
    trend_time_lost_s: float | None # recent-window mean minus earlier mean
                                    # (negative = shrinking = improving);
                                    # None until both pools are non-empty

@dataclass
class TechniqueTendencies:
    dominant: str | None = None     # FaultKind.value with most occurrences
    faults: list[FaultAggregate] = field(default_factory=list)  # occurrence desc
    recurring_corners: list[tuple[str, int]] = field(default_factory=list)
                                    # (label, count) with count >= RECURRING_CORNER_MIN,
                                    # position-fallback labels ("~4.4 km ...") excluded
    sessions_diagnosed: int = 0
    enough_data: bool = False       # sessions_diagnosed >= TECHNIQUE_MIN_SESSIONS
```

`build_technique(rows: list[DiagnosisRow]) -> TechniqueTendencies`:
- Group rows by session_id; `sessions_diagnosed` = distinct sessions.
- Per region row, compute fault kinds via the adapter; count occurrences per kind, distinct combos, mean `time_lost_s`.
- Trend: sessions ordered by `session_date`; recent = last `TECHNIQUE_TREND_WINDOW` sessions, earlier = the rest. Per kind, `trend = mean(time_lost, recent) - mean(time_lost, earlier)`; None if either pool has no occurrences of that kind.
- Recurring corners: `label` counts across all rows, ≥ `RECURRING_CORNER_MIN` (reuse the existing constant, 2), excluding labels starting with `"~"` (the position fallback is not a corner identity).
- Dominant = highest occurrences (ties broken by mean_time_lost desc).

### Wiring

- `DriverProfile` gains `technique: TechniqueTendencies` (default empty).
- `builder.load_profile`: load `track_db.list_region_diagnoses()` in its own try/except (degrades to `[]`, logger.exception — same pattern as the other loads); pass to `build_technique`.
- `render.py`: `verdict_technique(t: TechniqueTendencies) -> str` — exact-string tested, e.g.
  `"Brake release is your recurring loss — 9 regions across 4 combos, avg 0.4s each, shrinking (-0.1s recent)."`
  Human names per kind: lift → "Carrying apex speed", braking → "Brake point", release → "Brake release", exit_speed → "Corner exit speed", throttle → "Throttle pickup". Below threshold → collecting line (`"Technique tendencies unlock at 5 diagnosed sessions (2 of 5)."`).
- Profile page: new "Technique" section between racecraft and readiness — dominant verdict line, per-fault table (fault, occurrences, combos, avg loss, trend arrow), recurring corners line.
- `profile_prompt_block`: technique joins `_tendency_payloads` (enough_data-gated like the others), so debrief/chat synthesis can cite it — as cross-session tendencies with the stated session count, per the existing tone-contract amendment.

## 5. Time-to-pace (`core/profile/pace.py`)

The first behavioral diagnosis (v3 §4b): a long warm-up curve is a hidden race-anxiety driver — races give zero warm-up laps.

```python
@dataclass
class TimeToPace:
    median_laps: float | None = None    # median ordinal of first on-pace lap
    sample_sessions: int = 0            # sessions that qualified
    trend_laps: float | None = None     # recent-window median minus earlier median
                                        # (negative = reaching pace sooner)
    enough_data: bool = False           # sample_sessions >= READINESS_MIN_SESSIONS
```

`build_time_to_pace(sessions, laps) -> TimeToPace` (same inputs as `build_readiness`):
- Practice sessions only (`session_type != "Race"`), with ≥ `TTP_MIN_LAPS` valid laps.
- Per session: laps ordered by `lap_number`; session best = min valid lap time; time-to-pace = 1-based ordinal (among that session's valid laps) of the first lap ≤ `session_best * TTP_FACTOR`.
- Aggregate: median across sessions; trend = median(last `TECHNIQUE_TREND_WINDOW` sessions by date) − median(earlier), None if either pool empty.
- Known caveat (accepted): ordinals count telemetry-valid laps only — true out-laps are usually normalizer-invalid and drop out, so "lap 3" means the third recorded flying-ish lap. Good enough for a trendable habit metric.

Wiring: `DriverProfile.time_to_pace`, computed in `load_profile` from the already-loaded sessions/laps (no new I/O). `render.py` verdict, e.g. `"You need ~4 laps to reach pace (78 sessions) — races give you zero. Trending down (-1 lap recent)."` Profile page line in the new Technique section (it is a habit, not a combo stat). Included in the prompt block payload when enough_data.

## 6. Progression page (SPEC-ONLY — post-Fable)

New page "Progression" in the Practice nav group (`app/navigation.py` NAV_SPEC + render function, display-only per house rules). Content top to bottom, cheapest first (v3 §5):

1. **Race-volume streak** — official races per iRacing week (Tue flip) from races.db timestamps; current streak + races-this-week + total. The product's leading metric shown as the user's own stat.
2. **Per-combo pace trend** — session-best over time per combo (selectbox, most-practiced first — reuse `build_readiness` ordering); Plotly line, m:ss axis via the briefing `fmt_lap` public helper.
3. **PB timeline** — ReferenceStore `list_all()` personal_best rows over `imported_at`, annotated by combo.
4. **iRating / SR over time** — Data API `member_chart_data` endpoint (category road; the plumbing exists on the phase4 branch families). Cache per day under `data/briefing_cache`.
5. **Technique trends** — per-FaultKind time-lost-per-session line over `session_date` from `list_region_diagnoses()` (the §4 corpus), Strava segment-style "your brake-release losses are shrinking".
6. **Pace-implied iR** — the §7 number, with its per-combo breakdown.

Empty states: every block renders a one-line "collecting" message below threshold; the page must be useful at any corpus size (progressive enhancement rule).

## 7. Pace-implied iRating (SPEC-ONLY — post-Fable)

The Strava fitness score (v3 §5, founder 2026-07-15). Formula:

- Per combo with a practice PB and a buildable field curve: harvest the week's field via the existing briefing ingest (`search_series` + results cache), `build_curve(points, ...)`, then `place_on_curve(curve, user_pb_lap_s, user_ir)` → implied-iR band (all existing `core/briefing/curve.py` machinery; **placement math stays raw, never smoothed** — locked 2026-07-15).
- Driver-level number = weighted mean of per-combo implied-iR midpoints, weighted by that combo's representative-lap count (more practice = more signal). Present as a **band** (± the mean bin half-width), never a point — bands-not-false-precision is the locked curve rule.
- Trend: recompute weekly (the curve is week-scoped by nature); persist snapshots to a small `implied_ir_history` table (date, combo, implied_low, implied_high, weight) so the trend line survives cache expiry. Schema detail deferred to that build's plan.
- Honesty rails: only combos whose curve met `MIN_BIN_N` sampling; label the number with its combo count ("across 3 combos"); NEVER a gate (§1 hard rule — this is a progress stat, not a permission slip).

## 8. Prescription seed table (SPEC-ONLY — post-Fable)

Hand-written curated knowledge layer (v3 §4 — "a curated knowledge layer, not a data-mining problem"): `core/profile/prescriptions.py` holding a literal table:

```python
@dataclass(frozen=True)
class Prescription:
    fault: str            # FaultKind.value it teaches
    combo: str            # human name, e.g. "Porsche 992 Cup at Spa"
    skill_line: str       # "forces throttle discipline through Eau Rouge"
    transfer_line: str    # "unlocks every high-speed commitment corner"
```

Seed rows from the founder's lived examples: Porsche/Spa → throttle discipline + trail-brake bite (release, throttle); M2 → weight management (braking, release); F4 → transfer beneficiary (named in transfer lines, not prescribed as teacher). Consumed later by the week plan's practice half; tone rule: capability-framed, never "you're bad at X". The table ships with ~6-10 rows and grows by hand; no consumer is built in this phase — the artifact exists so the week-plan build has its input contract.

## 9. Testing

TDD throughout (RED → GREEN per task):
- **test_track_db**: region_diagnoses round-trip (all fields incl. NULLs), DELETE+INSERT idempotency, empty-list clears, join fields in `list_region_diagnoses`, ordering.
- **test_watcher_processor**: processing a fixture with an existing reference records rows with correct context; no-reference and own-new-PB sessions record zero rows; `diagnoses_recorded` on the report.
- **test_backfill_diagnoses**: helper-level — Race rows skipped, missing files skipped, no promotion (ReferenceStore untouched — assert by construction), idempotent rerun, dry-run writes nothing.
- **test_technique**: adapter coupling test vs `fault_kinds_from_diagnosis` (no threshold re-implementation), aggregates, trend math (both-pool gate), recurring-corner exclusion of `~` labels, threshold gating, exact-string verdicts in test_profile_render (or wherever verdict strings are pinned today).
- **test_profile_pace** (or existing pace test file): time-to-pace ordinal math, TTP_MIN_LAPS gate, Race exclusion, trend, enough_data.
- Existing suite stays green; profile builder degradation test (diagnosis load failure → empty technique, page renders).

## 10. Out of scope / guard rails

- Live coach and coaching-page persistence (decided: watcher only).
- Re-rendering historical debrief charts (no blobs stored).
- Any gating language anywhere: progression and readiness inform, never permit (§1 hard rule).
- Technique tendencies do NOT feed the live voice path in this phase — cues/verdicts stay per-lap deterministic.
- No new AI calls anywhere in this build; tendencies reach the AI only through the existing prompt block.
