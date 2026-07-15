# Race Engineer — v3 Addendum: The Confidence Arc & the AI-Native Business

**Date:** July 15, 2026
**Status:** Strategic addendum. Extends `docs/race-engineer-v2-strategy.md` the way v2 extended the PRD — nothing in v2 is replaced. The thesis (coach the race, not the lap; sell confidence, not pace), the three surfaces, and the Surface 1→2→3 build order all still hold. This document adds the layer v2 left implicit: **the behavioral progression that turns an anxious practicer into a confident racer, and the operating model that runs the business with humans involved by exception.**
**Origin:** Founder brainstorm 2026-07-15, inside the Fable window (frontier-model access ends 2026-07-19). This doc is the map; companion specs (briefing v1, UX/packaging, progression + persistence) are written against it.

---

## 1. The diagnosis: why the founder doesn't race (verified against user #1)

The pull-up review (2026-07-13) measured the founder's practice:race ratio at 64:8 — the exact anxiety pattern the product exists to fix. Asked directly what stops the register click on a night with time and a practiced combo, the founder ranked the causes:

1. **(a) Informational gap — primary.** "I genuinely didn't know whether I was ready." Proven concretely: at Summit week 3 his M2 practice PB (82.18s) beat the median best of his likely split, and he had no idea. He was race-ready and practiced anyway.
2. **(c) Planning friction — primary.** Races run on schedules; practice starts instantly. For a driver whose window is "after the kids are asleep," finding a slot that fits AND being ready at that moment is the hard part. The default (practice) wins because it requires no planning.
3. **(b) Loss aversion — situational.** Mostly relevant near promotion thresholds: close to an SR boundary, a bad race means digging out. Not the everyday blocker, but real when it fires.

Design consequence: the product's centerpiece is **a readiness verdict plus a race plan** — not a reframe, not a pep talk. Accuracy first, warmth second; the confidence comes from being *shown* you're ready, at a *specific time that fits your life*, with the SR math *pre-checked*.

## 2. The confidence arc (the spine everything hangs on)

The v2 surfaces are moments. The arc is the progression that connects them:

> **Practice with purpose** (skill diagnosis → prescriptions) → **see progress** (progression view) → **know you're ready** (readiness verdict) → **plan the race** (week plan: slot + SR check) → **race supported** (grid briefing now, live engineer later) → **debrief reframes, win or lose** → around again, one notch more confident.

Every surface, page, and notification should know where the user is on this arc and pull them one step forward. The leading metric is unchanged (does official-race volume go up?) — the arc is the mechanism that moves it.

## 3. The week plan (the unifying artifact)

One recurring deliverable that operationalizes the arc for a time-limited driver:

> "You're ready to race the M2 at Summit — your practice best beats this split's median. Tuesday 9:15pm fits your window; the race costs 12 minutes and your SR survives a bad night. Thursday, spend 20 minutes in the Porsche at Spa — it'll force the trail-brake modulation I keep seeing you lose time on."

Components, each traceable to a diagnosed cause:
- **Readiness verdict** (fixes 1a) — reuses the profile readiness layer + population pace ladder. Bands, not false precision.
- **Slot planning** (fixes 1c) — series calendar + the user's actual racing window (per-timeslot split prediction is feasible per the Phase 4 spike). Reduce the decision to yes/no on a concrete slot.
- **SR/iR threshold awareness** (fixes 1b) — "even a bad night keeps you above the line" or, near a boundary, "this is the low-stakes week to bank SR."
- **Prescriptive practice** (§4) — the practice half of the week, made purposeful.

**Delivery model (decided): scheduled push, architected toward conversational.** v1 = the engineer prepares the week plan on a schedule (iRacing week flips Tuesday; plan lands Sunday/Monday) and it is *waiting* — app inbox first, email/Discord as the channel decision matures. The end state is a conversational engineer that adjusts mid-week ("you're ready a day early — good slot tonight"). Pull-only was rejected: the 64:8 pattern shows the default wins, so the product must own the default. Radio discipline applies to notifications exactly as it does to the live engineer: an engineer who mostly shuts up is a feature.

## 4. Prescriptive practice and the transfer principle

Founder realization (2026-07-14, Spa): returning to the F4 after racing the M2, 911, and other demanding cars, the F4 felt "sticky and easy" — top-5 practice pace where he'd previously struggled.

**The transfer principle: hard cars are the teachers.** A car with an obvious, unforgiving bite point makes a technique *legible* — you cannot fake Eau Rouge in the Porsche without finding the throttle discipline, and once found, that skill transfers down and unlocks the "easier" cars most drivers run below potential. This is contrarian: naive coaching sends a struggling driver toward easier equipment. The engineer prescribes the combo that makes the weak skill **unavoidable**, then names the transfer explicitly so the driver knows why they're there.

Mechanics:
- **Diagnosis:** cross-session technique patterns ("brake-release losses at most slow corners, across three combos"). Dependency: **loss-region persistence** — the debrief pipeline already produces per-region diagnoses (trail guard, exit speed, braking deltas) and currently discards them. Persisting them was a deferred roadmap item; it is now load-bearing for both prescriptions and progression (§5), and is promoted accordingly.
- **Prescription mapping** (skill → combo that teaches it): LLM-judgment over racing knowledge, seeded with curated lived examples (Porsche/Eau Rouge = throttle discipline & trail-brake bite; M2 = weight management; F4 = the transfer beneficiary that reveals gains). The mapping is a curated knowledge layer, not a data-mining problem — start with a hand-written seed table, let the corpus grow it.
- **Tone:** positive, capability-framed. "This combo will make trail braking click" — never "you're bad at trail braking."

## 5. Progression: the Strava layer

Visible progress is both the retention mechanism (the strategy-doc blind spot the pull-up review flagged) and confidence made tangible — the driver doesn't have to believe they're improving; they can see it.

Content, cheapest first:
- **Per-combo pace trend** — session-best over time (readiness layer computes this today).
- **PB timeline** — reference-store history across combos.
- **iRating / SR over time** — Data API chart endpoint (already in the plumbing branch).
- **Race-volume streak** — the strategy's leading metric, shown to the user as their own stat. The product's success metric and the user's pride metric are the same number; instrument it once, serve both.
- **Technique trends** — "trail-brake losses shrinking across combos" (needs loss-region persistence, §4). Segment-times-going-down, Strava-style.

## 6. Data-leverage map (are we getting everything we can?)

Three tiers, from official to inferred:

| Tier | Source | What it gives | Status |
|---|---|---|---|
| 1 | iRacing Data API | **WHO is fast** — results, per-lap times, rosters, iR/SR charts, schedules, population pace ladders. No corner-level data exists in this API, period. | Strong. Six endpoint families built + reviewed on `phase4-api-plumbing`. |
| 2 | Garage 61 dev API | **WHY they're fast** — community-shared telemetry laps. A fetched top lap is a `NormalizedLap` via the existing G61 importer; `build_debrief` against it yields per-turn loss regions unchanged. "Where the fast guys gain on you, turn by turn" is the existing engine with a different reference. | Verified to exist (2026-07-10), parked. Slotted as **v1.5 enrichment** for debrief/briefing; also a prescription signal (the combo where your losses diverge most from the fast cohort). |
| 3 | Live CarIdx inference | **What the fast guy in YOUR practice session is doing** — `CarIdxLapDistPct` at 60Hz for every car; position-over-time differentiates into a speed trace. Per-corner minimum speeds and approximate braking points of the session leader, reconstructed live, from data already flowing into the rig. No incumbent does this. | Unexploited. Inference-grade (no pedals), ranked behind tier 2. Capability recorded; no v1 commitment. |

## 7. The friend package (distribution unit)

Decision context: the highest-value surface for friend #1 is the **live voice lap coach**, which is inherently rig-local (shared memory, SAPI, sub-second loop) — but also deliberately server-free (no API key on the critical path). Therefore:

**Friend package v1 = a local installer: live voice coach + telemetry watcher + tray UI.** The coach works out of the box (radio check covers the no-reference case; lap 1 sets a baseline) and gets better every session as the watcher builds PB references silently. The hosted web app remains the debrief surface (upload-first). No auth, no per-user server data, no phone-home in v1 — history sync to the hosted brain arrives later, when the arc needs their data.

The **system-tray app already on the roadmap is promoted**: from founder rig-ergonomics to the face of the friend package. Same composition (ManagedProcess + launch/stop scripts), new job: the thing a friend double-clicks.

This is also the embryo of the AI-native architecture: a sensor on the rig, an engineer in the cloud, meeting in the driver's data.

## 8. The AI-native operating model (humans by exception)

The 2026-07-09 parked brainstorm, now taken up. Two halves:

**The engineer as agent.** Not an app with AI features — an engineer who works for you between sessions. The watcher is the embryo (it already ingests, analyzes, and promotes without being asked). The progression: auto-capture (done) → scheduled week plan (v1, §3) → conversational engineer that notices and reaches out (target). Every user gets a per-user agent loop: ingest their races, write their debriefs, prep their briefings, adjust their plan — button presses optional.

**Ops as agents.** The business side runs the same way:
- **Onboarding agent** — walks a new driver from install to first debrief; the Guide page becomes its script.
- **Support triage agent** — first responder on errors and questions; escalates exceptions to the founder.
- **Distribution agent** — debriefs are inherently shareable; an agent that renders share-safe race stories (with driver consent) for Discord/community posting turns every good race into marketing.
- **Founder role:** exceptions, community presence, product judgment. The corpus of accumulated driver profiles and technique histories is the defensible layer no incumbent can copy quickly.

Not designed here: pricing, multi-user auth, re-platforming. Those remain gated on validation (v2 §6 unchanged; Streamlit ceiling revisit at Phase 6).

## 9. Sequencing: the Fable window and after

Frontier access ends 2026-07-19. Allocation principle: **build the most design-intensive thing; spec everything else well enough for cheaper-model execution.**

In-window (07-15 → 07-19):
1. Merge `phase4-api-plumbing` (shelf-ready, six endpoint families, reviewed).
2. This addendum (the map).
3. **Briefing v1 — spec AND build.** Kept as the in-window build, reframed as the first slice of the week plan: readiness verdict + split/SoF band + format facts, D1–D7 decided under the week-plan umbrella.
4. **UX/packaging spec** — pull-up top-5 (landing/onboarding, glossary, sample debrief, Guide restructure, errors/progress) + the friend installer/tray. Spec only.
5. **Progression + loss-region persistence spec** — schema design for persisted diagnoses, technique tendencies, progression page, prescription seed table. Spec only.

Post-Fable execution order: UX/packaging pass → friend #1 funnel (installer + hosted URL + Guide) → progression build → week-plan push delivery → G61 tier-2 enrichment. The founder validation burst (race, chat with debriefs, racecraft unlock at race #3) runs through all of it, unchanged.

## 10. What this is not (guard rails, extending v2 §8)

- **Not a nag.** The week plan is one push per week plus genuinely exceptional notices. Notification discipline = radio discipline.
- **Not gamification theater.** Progression shows real, measured improvement (pace trends, technique deltas, race volume). No badges for logging in.
- **Not real-time technique coaching for the market** (unchanged from v2) — prescriptions direct *practice attention*, they don't coach mid-corner.
- **Not a data firehose.** Tier-2/3 competitor insight feeds the same opinionated 2–3-things voice; it never becomes a telemetry-comparison dashboard. That's Garage 61's product.
- **Not premature platform.** The friend package deliberately ships without auth or server-side user data. Multi-user architecture waits for validation signal, as v2 decided.
