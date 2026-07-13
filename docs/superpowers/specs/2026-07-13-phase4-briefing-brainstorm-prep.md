# Phase 4 Pre-Race Briefing — Brainstorm Prep

**Date:** 2026-07-13
**Status:** Decision menu for the spec brainstorm (user + Claude). Not a spec.
**Inputs:** `2026-07-13-phase4-api-spike-findings.md` (all six data questions verified
feasible against the live Data API), v2 strategy §4.2, driver profile readiness layer.

## Why this feature, in the founder's own words

> "I still find myself jumping into practice first instead of registering for a race.
> Mostly because my time is fairly limited with kids and work that I need to get a
> little comfortable with a car/track pair before I run a race." (2026-07-13)

The briefing's job is to deliver that comfort in ~5 minutes instead of an hour of
practice. Demonstrated with real data during the spike: at Summit week 3, his M2
practice PB (82.18s) was **faster than the median best of his likely SoF ~1300–1500
split** (82.33s) — he was race-ready and didn't know it. That sentence is the product.

## The spike's spec-shaping facts

1. **Two briefing moments exist, cleanly separated by the roster boundary:**
   - **Pre-registration** ("should I register?") — no entrant names exist yet anywhere.
     Available: split/SoF band prediction from the week's history, field-size norms,
     population pace ladder, track/format facts, own-readiness from profile + tracks.db.
   - **At the grid** ("who am I racing?") — `reg_drivers_list` returns the full roster
     (names, iRating, SR, car) the moment the session launches; opponent cards cost
     2–3 API calls each.
2. **Split prediction must be a band, not a number** — split counts swing 6–22 per
   timeslot (median ~14.5 for M2 Cup). Honest claim: SoF band + typical field size +
   that band's real pace ladder.
3. **Race format is free** from the season schedule: time limit (M2 Cup = 12 min),
   standing start, fuel cap, weather flags. "This race costs you 12 minutes" is
   ammunition against the practice-first habit.
4. **The user's own pace side comes from local tracks.db** (watcher history), not the
   API (`member_bests` is empty without official races in the car).

## Decision menu (strawman recommendation first in each)

### D1 — v1 scope: which briefing moment(s)?
- **Strawman: pre-registration briefing only in v1**; design the data layer so the
  grid briefing bolts on as v1.5. Rationale: pre-reg attacks the founder's actual
  behavior (register more), needs zero live-session polling, and is fully cacheable.
  The grid briefing is the more theatrical moment ("you never grid up blind" literally)
  but adds a live-polling loop and a delivery-timing problem (user is in the car).
- Alt: both moments in v1 (bigger, riskier); grid-first (wrong order — you have to
  register before a grid exists).

### D2 — Delivery surface
- **Strawman: a new "Race Briefing" Streamlit page** — pick series (default: series
  the user actually races, from profile/history), see this week's briefing. Proactive
  delivery (watcher/cron notices the calendar and pre-builds) is a later layer on the
  same engine.
- Alt: extend the existing Scouting page (risks muddying two different jobs — track
  knowledge vs field intelligence); proactive-first (no pull surface to validate
  content against).

### D3 — Prediction presentation
- **Strawman:** SoF band + typical field size + real pace ladder (winner/median/P-last
  best laps from that band's recent subsessions) + a one-line readiness verdict that
  reuses the profile's practice-readiness layer ("Your Summit/M2 best is 82.18 —
  faster than this split's median. You're ready."). Bands over false precision.

### D4 — Deterministic vs AI
- **Strawman: mirror the debrief architecture exactly** — deterministic
  `BriefingData → render` core that works with no API key; optional AI narrative +
  chat on top (same synthesizer, same tone contract, profile injection already
  works). Proven pattern, no new risk.

### D5 — Strategy-plan depth in v1
- **Strawman: format facts only** (race length, standing start, fuel cap, weather
  flag) + the time-cost framing. Fuel-burn math deferred — real per-car burn data
  is derivable later from telemetry FuelLevel, which is already captured.

### D6 — Opponent content in pre-reg mode
- **Strawman: none in v1.** No names exist pre-registration; a "field archetype"
  (typical front/mid/back profile of this band) is derivable but speculative.
  Opponent cards belong to the grid briefing (v1.5), where they're real people.

### D7 — Relationship to the Scouting page
- **Strawman: separate pages now** (Scouting = know the track; Briefing = know the
  race), converge later into a single "Pre-Race" hub once both are validated.

## Open questions for the user (tonight)

1. Which series should v1 optimize for first? (M2 Cup was the spike's guinea pig.)
2. After tonight's races: did the debrief loop change how the race felt? Anything the
   briefing should promise that the debrief taught you?
3. Time-slot awareness: should the briefing know when you usually race (evenings,
   kids-asleep window) and predict THAT timeslot's split specifically? (The data
   supports per-timeslot prediction; it's a personalization decision.)
4. Is the 12-minute framing ("this race costs less time than a practice session")
   welcome nudging or annoying?
