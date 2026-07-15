# Phase 4 — Pre-Race Briefing v1 (Week Plan Slice 1) — Design

**Date:** 2026-07-15
**Status:** Approved design, pending implementation plan.
**Inputs:** `docs/race-engineer-v3-confidence-arc.md` (the arc, curve verdict, prep ledger), `docs/superpowers/specs/2026-07-13-phase4-briefing-brainstorm-prep.md` (D1–D7 menu), `2026-07-13-phase4-api-spike-findings.md`, API plumbing merged to master 2026-07-15 (b3a9194, 642 tests).

## Decisions (D1–D9 + open questions, resolved with the founder 2026-07-15)

- **D1 — Pre-registration briefing only.** Grid briefing (roster via `reg_drivers_list`, opponent cards) is v1.5; the data layer must not preclude it.
- **D2 — New Streamlit page, week-plan-shaped.** Nav: "Race Briefing". Content order is the week plan's: *this week's race → where you stand → what it costs → when to run it*. The future scheduled-push layer lands on this page without redesign.
- **D3 — The curve verdict is the centerpiece.** The user's practice PB placed on the week's pace-vs-iRating curve (Series Insights shape). Race-positive in both directions; **never gates** (v3 §1 hard rule).
- **D4 — Mirror the debrief architecture.** Deterministic `BriefingData → render` core that works with no Anthropic key; optional AI narrative + chat on top (same Synthesizer, tone contract, profile injection).
- **D5 — Strategy depth: format facts** (duration, start type, fuel cap) **+ time-cost framing.** The AI narrative may add a mini decision matrix ("if the start goes badly → bank lap 1"); prompt-level only, no new data.
- **D6 — No opponent content in v1.**
- **D7 — Separate from the Scouting page**; converge later.
- **D8 — Prep ledger, minimal:** session count, representative-lap count, session-best trend at the combo (reuse `core/profile/pace.py` readiness computations).
- **D9 — SR-threshold awareness deferred** to the week plan proper.
- **Series selection: series-agnostic engine + smart default.** Founder races many cars (Porsche, M2, MX-5, FF/Vee, SF Light, F4); v1 must not hard-code a series. The picker ranks this week's schedule by the user's local practice depth (tracks.db sessions matching car+track), defaulting to the top match. "Optimize where we have the most data," automated.
- **Timeslot view: in, kept cheap** (founder: "nice to have, not mission critical — but parsing the week's schedule to find a good time is genuinely hard"). Next few race slots in local time, tagged when they fit the user's usual window (inferred from session-history timestamps). No notification, no per-timeslot split prediction in v1.

## Package layout (mirrors `core/race/`)

```
core/briefing/
├── models.py      # BriefingData + component dataclasses (pure data)
├── ingest.py      # Data API harvest + disk cache + local tracks.db pace — the package's only I/O
├── curve.py       # PURE: (iR, best_lap) points → binned curve, implied-iR band, verdict
└── render.py      # PURE: BriefingData → deterministic markdown
app/pages/briefing.py            # display only
core/coaching/prompts/briefing.py  # AI narrative + chat prompt templates
data/briefing_cache/             # raw API JSON per (season_id, week) — gitignored
```

## Data flow

1. **Series picker.** `get_series_seasons()` → active seasons + current `race_week`. Rank candidates: join each week's `(track_id, car)` against tracks.db session history; sort by session count descending. Selectbox defaults to rank 1; remember last pick in `st.session_state`.
2. **Field harvest** for (season_id, race_week): `search_series_results()` → race subsessions (split ladder = group by `session_id`, sort SoF desc). Take the most recent `HARVEST_CAP = 30` subsessions (log when capped). For each, `get_subsession_results()` (disk-cached) → per-driver `(oldi_rating, best_lap_time)` points + per-subsession SoF and field size.
3. **Curve fit** (`curve.py`, pure): filter invalid laps (≤0) and unrated drivers; bin by iRating (`BIN_WIDTH = 250` iR); median best-lap per bin, min `MIN_BIN_N = 5` points per bin, else merge neighbors. **Implied iR** = interpolation of the user's lap onto the binned medians, reported as a band (± one bin). SoF band = IQR of subsession SoFs; typical field size = median.
4. **Your side** (local): fastest *representative* lap at the combo from tracks.db (same 110% filter as the profile), session count, session-best trend — the prep-ledger inputs. Clean-lap discipline inherited (dirty laps were never promoted).
5. **Slots:** extend `parse_season_schedules` to retain the raw payload's `race_time_descriptors` (repeating cadence + session times) on `RaceWeek`. Render the next 3–4 slots in local time. User's usual window = median start-hour ± 2h over tracks.db session history; matching slots get a "fits your usual window" tag. Fallback if descriptors prove unreliable: infer cadence from observed `SeriesResultRow.start_time` values.
6. **Render** (`render.py`, pure): deterministic markdown in week-plan order. Verdict lines exact-string tested (nudges/profile precedent).
7. **AI layer (optional):** narrative + ephemeral chat over `BriefingData` JSON, existing Synthesizer + tone contract + `profile_prompt_block`. Chat is NOT persisted in v1 (unlike race debrief) — no briefing store exists and none is added.

## The curve verdict (contract)

- Over the curve: lead with the gain — "Your 82.18 is faster than the median for ~1,500 iR drivers in this series this week. Your pace is worth more iRating than you have — racing is how you collect it."
- Under the curve: expectation-setting + purpose, never discouragement — "The median at your rating runs 81.9; mid-pack is a strong result this week. Extra practice here has a clear target: 0.4s."
- No practice data at the combo: curve renders without a "you" marker + invitation — "Run a practice session and I'll place you on this curve."
- Copy must carry the honesty caveat once, briefly: field laps are race-session laps; yours is a practice PB (clean-air advantage acknowledged, not belabored).

## Degradation ladder (honest at every rung)

| Condition | Behavior |
|---|---|
| No iRacing creds | Page explains the briefing needs Data API creds (this surface, unlike the debrief, cannot work from an upload) |
| API failure mid-harvest | Serve whatever the disk cache has + warning banner; never raise |
| Thin week (few subsessions early in the week) | Render with sample-size disclosure ("from 6 races so far this week"); no minimum gate |
| Empty API response | Returned uncached (race-cache lesson 2026-07-10: never poison the cache) |
| No local practice at combo | Curve + field facts render; verdict becomes the invitation line |
| No Anthropic key | Deterministic briefing renders fully; AI expander absent |

## Caching

`data/briefing_cache/{season_id}/{race_week}/` — raw JSON per endpoint call (subsession results shared with `data/race_cache` format but kept separate; a race debrief cache hit is a different lifecycle). Atomic `.tmp` + replace writes. Cached files double as test fixtures (race-fixture precedent). Harvest is idempotent and resumable — a re-open completes missing subsessions only.

## Testing

- `curve.py` and `render.py` are pure: unit tests with synthetic point clouds (known medians → known implied-iR band), exact-string verdict tests, degenerate inputs (empty, single bin, all-unrated).
- `ingest.py` against recorded fixtures (record one real harvest via a `scripts/record_briefing_fixture.py` sibling of the race recorder; fixtures gitignored except README).
- Slot inference: pure function over synthetic session-history timestamps.
- Page: no business logic to test (display only); series-ranking helper is pure and tested.
- `StubIRacingAPI` additions keep the no-creds path exercised in CI.

## Out of scope (v1)

Grid briefing + opponent cards (v1.5, `reg_drivers_list` plumbing already merged); SR-threshold math; per-timeslot split prediction; push delivery (week plan layer); briefing persistence/chat history; prior-season pace blending; G61 tier-2 enrichment ("what the fast guys do differently" — v1.5+ per v3 §6).

## Open tuning items (build-time, not blockers)

`HARVEST_CAP` (30), `BIN_WIDTH` (250 iR), `MIN_BIN_N` (5), window inference (±2h) — all named constants, tuned against the founder's real series after first render.
