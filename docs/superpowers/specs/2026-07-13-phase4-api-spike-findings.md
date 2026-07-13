# Phase 4 API Spike — Pre-Race Field Briefing Feasibility (2026-07-13)

Read-only spike against the live iRacing Data API using the existing
`LiveIRacingAPI` client (Password Limited OAuth, creds from `.env` — auth worked
first try). Spike script: `scripts/spike_phase4_api.py` (staged, disk-cached).
Raw JSON samples: `data/api_spike/` (huge payloads truncated to representative
samples; `_note` field marks truncation). ~20 endpoint calls total, sequential,
no rate limiting encountered.

Demo combo used throughout: **BMW M2 Cup (series_id 571, season_id 6266),
2026 S3 week 3 at Summit Point** — the user drove exactly this combo on
2026-07-12 (M2 G87 practice PB 82.183s in local `tracks.db`), and his sports_car
iRating is **1409** (from `/data/member/info` licenses).

---

## Q1. Race guide / upcoming sessions — `/data/season/race_guide`

**Endpoint:** `GET /data/season/race_guide` — params `from` (ISO time),
`include_end_after_from`. Sample: `data/api_spike/race_guide.json`.

**Returns:** `{block_begin_time, block_end_time, sessions[], subscribed, success}`.
Each session:

```json
{"season_id": 6266, "series_id": 571, "race_week_num": 3,
 "start_time": "2026-07-13T14:15:00Z", "end_time": "2026-07-13T14:41:00Z",
 "session_id": 315364654, "entry_count": 153, "super_session": false}
```

**Key facts:**
- The guide returns a **3-hour block** (`block_begin_time` → `block_end_time`).
  The `from` param accepts any future time — fetching `from=2026-07-14T18:00Z`
  returned tomorrow's 3-hour block fine. So the lookahead is pageable but the
  window per call is 3 hours (~340 sessions across all official series).
- `entry_count` is a **live registration count** — but it only populates for
  sessions whose registration is currently open (~30 min before start). In the
  "now" block, 36 of 342 sessions had entry_count > 0 (max 153, the imminent
  M2 Cup slot); in tomorrow's block **all 343 were 0**.
- `session_id` similarly appears only once the session is created (52 of 342 in
  the now-block, none tomorrow). No per-session roster here — just the count.
- Far-future timeslots are better derived from `series/seasons`
  `race_time_descriptors` (repeat_minutes etc.) than by paging the guide.

**VERDICT: feasible.** Upcoming sessions + live registration counts for
imminent sessions; no registration data beyond ~30 min out, no names.

---

## Q2. Pre-race roster — earliest moment entrants are visible

**The expected "no" is actually a qualified YES.** The doc index
(`/data/doc`, saved to `doc_index.json`) exposes a `session` group with exactly
one endpoint:

- `GET /data/session/reg_drivers_list` — param `subsession_id`

Probes (all cached in `data/api_spike/reg_drivers_*.json`):
- **Completed subsession** (87047287): `{"entries": [], "success": true}` — empty.
- **Upcoming race_guide `session_id`** (wrong id kind): empty, no error.
- **LIVE subsession** (87170269, from `/data/season/spectator_subsessionids_detail?event_types=5`):
  **returns real entries** — per driver: `cust_id`, `display_name`, `car_id`/
  `car_name`, `reg_status` ("reg_joined"), helmet/livery, and a **full license
  block: irating, safety_rating, cpi, license_level, group_name, mpr_num_races**.

So the timeline is:
1. **Before session launch** (registration open, up to start_time): only the
   aggregate `entry_count` from the race guide. **No names.**
2. **At session launch** (splits formed; subsession_ids exist and appear in
   `spectator_subsessionids_detail`): full roster with iRating/SR via
   `reg_drivers_list`. For sprint series with attached qualifying this is the
   session start itself — i.e. the user is already (or should already be) in
   the sim. Useful for a "field briefing" delivered during practice/grid, not
   before registering.
3. **After completion:** `reg_drivers_list` goes empty again; roster comes from
   `/data/results/get`.

Gotcha: `spectator_subsessionids_detail` lists live subsessions with
`session_id`, `season_id`, `start_time` — join season_id → series to find the
user's session. `reg_drivers_list` returns `success: true` with empty entries
for any id it doesn't like (no 4xx), so emptiness is ambiguous.

**VERDICT: feasible-with-caveats.** No entrant names pre-registration; full
roster incl. iRating the moment the session launches (during practice/qual —
in time for an "at the grid" briefing, not a "should I register" one).

---

## Q3. Split/SoF structure from history — `/data/results/search_series`

**Params that worked:** `season_year=2026, season_quarter=3, series_id=571,
race_week_num=3, official_only=true, event_types=5`. Response is **chunked**
with `chunk_info` nested under `data` (one level deeper than
lap_chart_data — `_fetch_chunked` needed `payload["data"]`). 4,425 race
subsessions for one week of one series (4.2 MB). Sample (2 full timeslots):
`search_series_571_wk3.json`.

**Per-subsession fields:** `session_id` (shared per timeslot — this is the
split-group key), `subsession_id`, `start_time`, `event_strength_of_field`,
`num_drivers`, `event_best_lap_time` / `event_average_lap` (1/10000s),
`num_cautions`, `num_lead_changes`, `winner_name`, track, week. **No explicit
split number** — reconstruct by grouping on `session_id` and sorting by SoF
descending. (Also: `/data/results/get` returns a `session_splits` array — the
full sibling-split SoF ladder — for free with any one subsession.)

**Demonstrated for the user (iR 1409, M2 Cup wk3 Summit):**
- 316 timeslots in the week; **6–22 splits per slot, median 14.5**.
- Matching his iR to the nearest-SoF split across all slots: **median split ~4
  of ~14.5 in absolute terms is wrong framing — by SoF he lands mid-ladder**;
  landing-split SoF min 1291 / **median 1408** / max 1499, field size median 12.
- Example 22-split slot (2026-07-07T18:45Z): split 1 SoF 2528 → split 22
  SoF 481; his SoF-1400 neighborhood is splits 7–8.
- Top-split SoF median across slots: 2339.

**VERDICT: feasible.** One search_series call per series-week fully
reconstructs split structure and SoF bands; split prediction for a given
iRating is a simple nearest-SoF lookup with real historical spread.

---

## Q4. Population pace — "is my pace ready for that split?"

From the same `search_series` rows: `event_best_lap_time` and
`event_average_lap` per split (1/10000s). For finer grain,
`/data/results/get?subsession_id=...` (sample: `results_get_87047287.json`)
gives per-driver `best_lap_time`, `average_lap`, `qual_lap_time`, `incidents`,
`oldi_rating/newi_rating` for the whole field.

**Concrete demonstration (real SoF-1400 split, subsession 87047287):**
- Split race-best laps: winner-best **81.896**, median **82.334**, slowest 83.798.
- User's Summit M2 practice PB (local `tracks.db`, session 2026-07-12): **82.183**.
- **His PB is 0.15s faster than the split's median best lap and 0.29s off the
  fastest lap in the race.** Honest claim: "your practice pace is mid-pack-or-
  better for an SoF-1400 split at Summit."

Gotchas:
- All results/search lap times are 1/10000s (consistent with race debrief code).
- `best_qual_lap_time` can be `-0.000` (attached-qual, no time set).
- Some drivers show `oldi_rating: -1` (unrated/rookie) — filter before math.
- `/data/stats/member_bests` (tried for car 4108) returned an **empty `bests`
  array** — it only covers official-session bests, so the user's own pace must
  come from local `tracks.db` (practice telemetry), which we already have.
- Aggregating a whole week's pace = the one search_series call; per-split
  detail = one results/get per sampled subsession (sample 3–5, don't fetch 4,425).

**VERDICT: feasible.** Real pace ladder per SoF band from one call; the
comparison demo above is exactly the briefing sentence the product wants.

---

## Q5. Opponent profiling

Tested on a real opponent (cust_id 1523425, winner of the SoF-1400 split).
All samples in `data/api_spike/*_1523425.json`.

- `/data/member/profile?cust_id=` — `member_info` (display name, licenses),
  `license_history`, `activity`, `recent_awards`, `follow_counts`.
- `/data/member/chart_data?cust_id=&category_id=5&chart_type=1` — iRating
  time series (sports_car category_id=5, formula=6; chart_type 1=iR).
  Returned e.g. `[{"when": "2026-07-13", "value": 1528}, ...]` — trajectory
  (climbing fast: 1380→1528 in 9 days = alt/improving account signal).
- `/data/stats/member_recent_races?cust_id=` — last 10 official races WITH
  `incidents`, `strength_of_field`, start/finish position, `oldi_rating/newi_rating`,
  series, track. This is the aggression/form source.
- `/data/stats/member_career?cust_id=` — per-category starts, wins, top5,
  win%, **avg_incidents**, laps led.
- `/data/lookup/drivers?search_term=` exists for name→cust_id (not needed when
  the roster gives cust_ids directly).

**A realistic opponent card:** name, iRating + 90-day trend, SR/license class,
career starts + win% (category), avg incidents/race, last-10 form (avg finish
vs start, incident spikes), experience at this week's track (from recent_races
track matches — only last 10, so shallow). All from 2–3 calls per opponent —
budget matters for a 12-car field (24–36 calls); cache aggressively.

**VERDICT: feasible.** Rich cards post-roster (i.e., at session launch or from
past-results reconnaissance of the SoF band's regulars).

---

## Q6. Series calendar — `/data/series/seasons?include_series=true`

One call, 153 active seasons (7 MB — cache it daily). Sample (user-relevant
series): `series_seasons.json`. Per season: `series_id`, `season_id`,
**`race_week` (current week)**, `max_weeks`, `reg_user_count`, and
`schedules[]` per week with:

- `track` (track_id/name/config), `start_date`, `race_week_num`
- `race_lap_limit` / `race_time_limit` (M2 Cup wk3: **12 minutes**, lap limit null)
- `race_time_descriptors` (repeat_minutes 30 — timeslot cadence)
- `weather` (forecast_options incl. precipitation flag), `track_state`
  (leave_marbles), `start_type` ("Standing"), `qual_attached`,
- `car_restrictions` (max_pct_fuel_fill — fuel-strategy input)

Demonstrated: "What's this week's track for the user's series?" —
Global MX-5 (139): Summit Point wk3; BMW M2 Cup (571): Summit Point wk3;
Porsche Cup (299/476): **Mount Panorama** wk3; GT4 Falken (491): CTMP wk3.
Remaining M2 Cup weeks list cleanly (wk4 VIR North → wk11 Ledenon).

**VERDICT: feasible.** Everything the briefing needs for calendar + race
format (length, standing start, fuel-fill cap, weather flags) is in one cached
call.

---

## Cross-cutting gotchas

- **Auth:** existing `LiveIRacingAPI` worked unchanged; `_api_get` handled
  every endpoint including direct-return ones (`/data/doc` has no link step).
- **Chunking inconsistency:** `search_series` nests `chunk_info` under `data`;
  `lap_chart_data`/`lap_data` have it at top level. A Phase 4 wrapper should
  normalize (`payload.get("data", payload)`).
- **No rate limiting observed** at ~20 sequential calls, but search_series for
  a popular series-week is 4+ MB — fetch once per week per series and cache
  (same pattern as `data/race_cache/`).
- **Empty-but-success responses everywhere** (`reg_drivers_list`,
  `member_bests`): absence of data is not an error signal; don't cache empties
  (same lesson as the race-capture `_cached_fetch` fix).
- Lap times 1/10000s; positions in `results/get` zero-based; `oldi_rating=-1`
  for unrated drivers.

## What briefing v1 can honestly promise

**Can promise (pre-registration, real data):**
- "This week series X runs at TRACK (config), race is N minutes, standing
  start, fixed setup, fuel fill capped at Y%, rain flag on/off, sessions every
  30/60/120 min" — series/seasons, one cached call.
- "At your iRating (~1409 sports car), you'll likely land in an SoF ~1300–1500
  split; last week that series formed 6–22 splits per slot (median ~14), your
  split's field is ~12 cars" — search_series history.
- "Winner's best lap in your likely split runs ~81.9s, median driver ~82.3s;
  your practice PB is 82.2s → you're mid-pack-or-better on pure pace" — split
  results + local tracks.db.
- "Busiest timeslots / biggest top splits are at these hours" — search_series
  grouped by start_time (participation heatmap).
- "Right now 153 are registered for the 14:15 slot" — race guide, imminent
  sessions only.
- Post-launch (grid briefing): full opponent list with iRating/SR + opponent
  cards (career win%, avg incidents, last-10 form, iR trend).

**Cannot promise:**
- The actual opponent list before the session launches — registration names
  simply are not exposed pre-launch (only the aggregate entry_count, and only
  ~30 min out).
- "You will be in split N of M" as a certainty — split count varies 6–22 by
  timeslot; we can only give an SoF band with historical spread.
- Opponent pace at this week's track from `member_bests` (empty unless they've
  raced it officially in that car) — opponent track-specific pace has to come
  from their appearance in past subsession results, which is a heavier lookup.
- Anything about unofficial/hosted sessions with these endpoints (search_hosted
  exists but untested).
