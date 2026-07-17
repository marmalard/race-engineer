# Week Plan — Design

**Date:** 2026-07-17
**Status:** Approved design.
**Origin:** v3 confidence arc §3 (docs/race-engineer-v3-confidence-arc.md) — "the unifying artifact." The curriculum's weekly unit; prescriptions (§4, shipped 2026-07-17 as `core/profile/prescriptions.py`) are its lessons; progression (§5, shipped 2026-07-17) is its report card. Delivery model was decided in the v3 doc: **scheduled push, architected toward conversational** — this spec implements the v1 push.

## Decisions locked during brainstorm

1. **v1 scope = race half + practice half.** No prep-ledger block, no run sheet, no mental-lap rehearsal in v1 (all remain roadmap).
2. **Push mechanics = watcher generates, tray notifies, Start page leads.** The watcher's poll loop gains a weekly check; the tray's existing watchdog thread fires one Windows toast via a marker-file handshake; the Start page shows a lead card.
3. **AI placement = deterministic push, AI on page.** The scheduled path is fully deterministic (exact-string testable, no API key required to build the plan text — the race-capture precedent). The Week Plan page offers optional AI narrative + ephemeral chat grounded in the plan JSON (the briefing precedent).
4. **Practice fallback = race-combo practice.** No technique unlock or no prescription match → prescribe time at this week's race combo, goal seeded from the most recent session's top loss region. The practice half always has content.
5. **Surface = new Week Plan page** (Race nav group, right after Start), with plan history and the AI layer; Start card is a teaser.
6. **Architecture = approach A**: `core/weekplan/` package; generation in the watcher (has creds + DBs), notification in the tray (owns the user's attention), living-artifact refresh.

## 1. The artifact: `core/weekplan/models.py`

```python
@dataclass
class RaceHalf:
    series_name: str
    season_id: int
    race_week: int                  # target week number within the season
    track_id: str
    track_name: str
    config_name: str
    car: str                        # user's most-practiced car at this track
    slots: list[PlanSlot]           # next starts + fits_window flags
    race_time_limit: int | None     # minutes (None = lap-limited)
    race_lap_limit: int | None
    standing_start: bool
    # curve verdict — None until backfilled post-flip
    implied_ir_lo: int | None = None
    implied_ir_hi: int | None = None
    delta_to_own_band_s: float | None = None
    sof_median: int | None = None
    splits_median: int | None = None
    prep_sessions: int = 0          # practice depth at the combo (context line)
    prep_best_lap_s: float | None = None

@dataclass
class PlanSlot:
    start_utc: str                  # ISO 8601
    fits_window: bool

@dataclass
class PracticeHalf:
    kind: str                       # 'prescription' | 'race_combo'
    minutes: int                    # PRACTICE_MINUTES = 20 (constant, v1 fixed)
    # prescription kind
    fault: str | None = None        # FaultKind.value
    combo: str | None = None        # human name from the Prescription row
    skill_line: str = ""
    transfer_line: str = ""
    # race_combo kind
    goal_label: str = ""            # loss-region label from the latest diagnosis
    goal_fault: str = ""            # FAULT_LABELS human name
    goal_time_lost_s: float | None = None
    # both kinds
    ttp_line: str = ""              # time-to-pace sentence, "" when no data

@dataclass
class SRCheck:
    license_class: str              # e.g. "C"
    safety_rating: float
    comfortable: bool               # sr >= SR_COMFORT (2.5, named constant)

@dataclass
class WeekPlan:
    week_start: str                 # ISO date of the target Tuesday
    created_at: str                 # ISO UTC — set once
    updated_at: str                 # ISO UTC — bumped on every refresh
    race: RaceHalf | None = None
    practice: PracticeHalf | None = None
    sr: SRCheck | None = None
    curve_filled: bool = False
    warnings: list[str] = field(default_factory=list)
```

Every section is optional; a missing section is a warning, never an exception. The plan always exists once generated — no blank-page failure mode.

## 2. Build: `core/weekplan/build.py`

`build_week_plan(api, seasons, sessions, laps, diagnoses, technique, time_to_pace, now_utc) -> WeekPlan`

**Target week.** `target_week_start(today) -> date`: the Tuesday of the week the plan is FOR — today's week if today is Tue–Sat, the upcoming Tuesday if today is Sun/Mon. Reuses `core.progression.streak.iracing_week_start`.

**Race half.**
- Candidate ranking reuses the briefing logic extended for target-week selection: when generating pre-flip, each season's target `RaceWeek` is `race_week + 1` looked up in `season.weeks` (the plan decides the exact form: either an optional parameter on `rank_series_candidates` or a sibling function in weekplan/build — either way the ranking-by-practice-depth logic must not be duplicated).
- Car = most-practiced car at the target track from session history (readiness ordering); no practice at the track → most-practiced car overall, with a warning line.
- Slots: `upcoming_slots(week.race_time_descriptors, now_utc, count=4)` + `infer_window` fits — both reused as-is.
- Curve verdict: `harvest_field` for the target (season_id, race_week). Pre-flip this returns an empty/thin curve → `curve_filled=False`, verdict text says the curve builds after Tuesday night. Placement via `place_on_curve` with the user's practice best at the combo — RAW, never smoothed (locked curve rule). Honesty rails identical to progression ingest: no bins or `< MIN_BIN_N` points → not filled.
- No candidate series at any practiced track → `race = None` + warning naming the closest scheduled thing ("no current-week series at a track you've practiced — briefing page lists the full calendar").

**Practice half — selection ladder (locked):**
1. `technique.enough_data` AND the dominant fault has a `PRESCRIPTIONS` row → `kind='prescription'` with that row's combo/skill/transfer lines. Multiple rows for the fault → first row wins (table order is curated).
2. Otherwise → `kind='race_combo'`: this week's race combo, goal from the most recent session's rank-1 region diagnosis (label, `FAULT_LABELS` name of its top fault via `fault_kinds_from_diagnosis` + `diagnosis_from_row` — the one ladder, no re-implementation, coupling-tested). No diagnoses at all → goal lines empty, generic "bank laps at the race combo" sentence.
3. Both kinds: `ttp_line` filled when `time_to_pace.enough_data` ("You need ~6 laps to reach pace — races give you zero. Arrive early.").

**SR check.** `api.get_member_info()` → sports-car license `group_id` (existing `max_license_group` heuristics) + `safety_rating`. `comfortable = sr >= SR_COMFORT` (2.5, named constant in models). Two deterministic render sentences (see §3). Missing creds/field → `sr = None` + warning. **Never a gate** — the near-the-line sentence still says race, just pick the calm slot.

`build_week_plan` never raises; every failed sub-build degrades to `None` + warning (the `build_briefing` precedent).

## 3. Render: `core/weekplan/render.py`

`render_week_plan(plan: WeekPlan) -> str` — deterministic markdown in the §3 v3-doc voice:

> "You're ready to race the M2 at Summit — your practice best beats this split's median. Tuesday 9:15pm fits your window; the race costs 12 minutes and your SR survives a bad night. Thursday, spend 20 minutes in the Porsche at Spa — it'll force the trail-brake modulation I keep seeing you lose time on."

- Verdict sentences exact-string pinned in tests, including: the three curve-verdict bands (reuse the briefing's `ON_CURVE_BAND_S` semantics — over/on/under, all race-positive), the pre-backfill line ("The field curve builds after Tuesday night — I'll fill this in."), the two SR sentences ("Even a bad night keeps you above the line." / "This is the low-stakes week to bank SR — race anyway, pick the calm slot."), and the practice-half templates for both kinds.
- Slots render machine-local (the briefing precedent).
- **HARD RULE (v3 §1): no gating language anywhere.** "You're not ready" is a sentence the product does not say. Pinned by the exact-string tests.

## 4. Store: `core/weekplan/store.py`

`WeekPlanStore` on `data/progression.db` (shares the DB file with `implied_ir_history`; separate class, separate table):

```sql
CREATE TABLE IF NOT EXISTS week_plans (
    week_start TEXT PRIMARY KEY,   -- ISO date of the target Tuesday
    plan_json TEXT NOT NULL,       -- asdict(WeekPlan) — document-shaped, the narrative_json precedent
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

- `save(plan)` — INSERT OR REPLACE; **preserves the existing row's `created_at`** when the week already exists (refresh, not rebirth), bumps `updated_at`.
- `get(week_start) -> WeekPlan | None`, `latest() -> WeekPlan | None`, `history() -> list[WeekPlan]` (week-descending for the page).
- Deserialization is defaulted-field tolerant (the stored-narrative precedent — old plans keep loading as the dataclass grows).

## 5. Watcher tick (generation)

In `scripts/watch_telemetry.py`'s poll loop, AFTER IBT processing, inside the existing per-scan try/except (a plan failure must never block telemetry work):

Two PURE decision functions in `core/weekplan/build.py` (unit-tested without the loop):
- `should_generate(today, latest_plan_week) -> bool` — true when `today >= target_week_start(today) - 2 days` (i.e. Sunday onward) AND no stored plan for the target week.
- `should_refresh(plan, now) -> bool` — true when a plan exists for the target week AND (`not plan.curve_filled` OR `updated_at` older than `REFRESH_MAX_AGE_S` = 24h) AND `updated_at` older than `REFRESH_MIN_INTERVAL_S` = 1h (hourly throttle — the 30s scan cadence must not hammer the API).

Flow: generate → `store.save(plan)` → **on create only**, write the toast marker (§6). Refresh saves silently (no marker, no toast — one push per week, radio discipline). No creds → skip quietly, log once per process. Generation failure → logged, retried next scan.

## 6. Toast handshake (notification)

- Marker file: `data/run/weekplan_ready.json` — `{"week_start": "...", "created_at": "..."}` (the PID-file directory precedent). Written by the watcher on plan CREATE only.
- The tray's existing 120s watchdog thread checks the marker: fires ONE `pystray` `Icon.notify` ("Week plan's ready — the week flips Tuesday. Open Race Engineer."), then deletes the marker.
- Tray down when the marker is written → marker persists → toast on next tray start (durable push).
- **Coupling test required**: one test imports both the watcher-side writer and the tray-side reader and pins the marker path + JSON shape (the Toolbox flag-drift lesson, applied in advance).
- This is the product's ONLY notification. The marker-on-create-only structure pins one-toast-per-week structurally.

## 7. Page: `app/pages/week_plan.py`

"Week Plan" in the Race nav group, second entry (right after Start). Display-only:
- Latest plan rendered from `render_week_plan` (slots local time); `curve_filled=False` shows the pending line + a `st.page_link` to the Race Briefing page (the live chart lives there — not duplicated).
- History expander: past plans, read-only markdown.
- Optional AI narrative + ephemeral chat (the briefing pattern): `WEEKPLAN_SYSTEM_PROMPT` tone contract — engineer voice, never gates, profile facts cited as cross-session tendencies with stated counts, 2–3 item cap. Grounded in `asdict(plan)` JSON. Requires `ANTHROPIC_API_KEY`; absent → deterministic plan renders fully (no dead page).
- Empty state (no plan yet): explains when the first plan lands ("Sunday before the Tuesday flip") — informative, not apologetic.

Start page: lead card when a plan exists for the current target week — headline sentence + `st.page_link` to the Week Plan page. (Placement mirrors the undebriefed-race lead card.)

## 8. Testing

- **Build**: pure, fake seasons/sessions/laps (the briefing test-fixture pattern). Target-week math on the Sun/Mon/Tue boundaries. Candidate selection for week N+1. Practice ladder: prescription hit, race-combo fallback with goal seeding, no-diagnoses generic, TTP line gating. Curve backfill state transitions. Every degradation path → warning, never raise.
- **Render**: exact-string verdicts (curve bands, SR sentences, pre-backfill line, both practice templates). Gating-language absence pinned by the exact strings.
- **Store**: round-trip, created_at preservation on re-save, tolerant deserialization of a stale plan_json missing new fields.
- **Decision functions**: should_generate/should_refresh boundary cases (Saturday no, Sunday yes; hourly throttle; filled-and-fresh no-op).
- **Coupling**: marker writer/reader path + shape; practice-half fault classification via the one ladder (`fault_kinds_from_diagnosis`); structural test that `core/weekplan/build.py` and the watcher path import no AI module.
- **Nav**: Week Plan pinned in the Race group exact list; render function importable.

## 9. Out of scope / guard rails

- Prep ledger, run sheet, mental-lap rehearsal, email/Discord channels, per-timeslot split prediction, mid-week conversational adjustment ("you're ready a day early") — all later passes; the store + living-artifact refresh are architected so conversational can land on top.
- No gating language anywhere (v3 §1 hard rule) — exact-string pinned.
- No AI on the scheduled path — structurally tested.
- The watcher tick must never block or crash IBT processing — it runs last, inside the per-scan guard.
- One toast per week, on create only. No other notifications ride along.
- No new writes to tracks.db / races.db / reference_laps.db; the plan lives in progression.db.
