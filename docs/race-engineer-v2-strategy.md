# Race Engineer — v2 Strategy & Direction Handoff

**Date:** July 6, 2026
**Status:** Strategic update to `docs/prd.md`. Do not replace the PRD — this document extends it. The existing core philosophy (opinionated over comprehensive, coaching over data, AI as synthesis layer, data foundation first) all still holds.
**Repo:** `C:/Users/antho/Documents/Coding/personal-race-engineer` (github.com/marmalard/race-engineer)
**Current state:** Phases 1 & 2 complete (telemetry pipeline, scouting report, coaching synthesis, unit toggle, pace context). Phase 3 (intelligence layer) was next. This doc revises what Phase 3+ should be.

---

## 1. The strategic shift

The original PRD frames Race Engineer as a **lap coaching** product: analyze telemetry, find where you're leaving time, tell you what to fix. That problem is now well-served by funded incumbents, and it is the wrong hill to fight on.

**New thesis: coach the race, not the lap.** Every existing product is fundamentally a hotlapping tool. Nobody has built the thing this product is literally named after. A real race engineer doesn't teach you to drive — they win you races with the pace you already have.

### The emotional core (this is the actual product)

The founding user insight, verbatim: *"this might get me to race more instead of being nervous and just ending up doing practices so I don't tank my safety and iRating by not being confident."*

The target user is not "driver who wants to be 0.3s faster." It is **"driver who practices more than they race because racing feels risky."** This is a huge, unserved population on iRacing. iRating/SR anxiety is a well-known community phenomenon — people grind practice, avoid officials, and race below their volume potential because racing without preparation or support feels like gambling their rating.

Every incumbent sells *pace*. Race Engineer sells *confidence*. The product promise: **you never start a race blind, you never race alone, and every race makes you smarter — win or lose.** Design decisions should be evaluated against this promise, not against lap time delta.

### Positioning implications

- Race Engineer is a **complement** to Trophi/Garage 61/VRS, not a substitute. Best early adopters may be paying Trophi subscribers who plateaued on pace. Avoid rip-and-replace framing.
- Tagline territory: incumbents = "get faster." Race Engineer = "finish better" / "race with an engineer in your corner."
- Do not compete on: real-time driving-technique voice coaching (Trophi Mansell's fortress), reference-lap benchmarking (Garage 61/VRS commodity), free spotter/plumbing (Crew Chief).

---

## 2. Competitive landscape (verified July 2026)

| Product | What it does | What it doesn't do |
|---|---|---|
| **Trophi.ai (Mansell)** | Real-time in-ear voice coaching on driving technique; post-session Coach Report (corner-by-corner, mistakes ranked by time cost); expert lap video w/ synced telemetry; top tier bundles human Driver61 coaching + pro setups. iRacing, ACC, F1, LMU. Funded, real coaching pedigree. | Anything race-level: no racecraft, no strategy, no opponent awareness, no race debrief. Coaches you as if you're alone on track. |
| **Garage 61** | Lap/telemetry comparison, team telemetry, reference laps. | No coaching intelligence, no race context. A viewer, not an engineer. |
| **VRS** | Datapacks, telemetry comparison, human coaching marketplace. | Same — lap-centric. |
| **Crew Chief** | Free, beloved, rule-based spotter + engineer: fuel calc, gaps, pit info, **voice-command Q&A** ("how's my fuel"). | Canned responses to threshold triggers. Cannot reason. Can report the gap is 1.2s; cannot tell you *what to do about it*. |

**Key insight:** Crew Chief already validated the interaction model (drivers talking to an engineer mid-race via voice). The entire differentiation is replacing a rule-based brain with a reasoning one. "Crew Chief with an LLM brain that actually understands the race" is a fair one-line description of the live product.

**Why incumbents left this open:** they optimized the tractable, measurable problem (lap delta vs. reference) because telemetry math could solve it. Race intelligence requires reasoning over messy multi-car, multi-lap context — intractable until LLMs, and their architectures aren't built around it. This is a capability-shift moat, much better than price.

---

## 3. Data feasibility (verified — this all works)

Three iRacing data surfaces, all legitimate/supported:

### Live telemetry (irsdk shared memory, 60Hz)
Player car: full inputs, speed, fuel, tires, incidents — already integrated (Phases 1–2 parse IBT).
**Critical for racecraft — the CarIdx arrays cover every car in the session, live:**
- `CarIdxLapDistPct`, `CarIdxLap` — everyone's track position
- `CarIdxPosition`, `CarIdxClassPosition` — race order
- `CarIdxF2Time`, `CarIdxEstTime` — gaps/relative timing
- `CarIdxOnPitRoad`, `CarIdxTrackSurface` — pit status, off-tracks
- Session YAML: full driver roster **with iRating and SR per driver**, car classes, session metadata

**Not available live:** other cars' pedal inputs, tire state, fuel. Opponent behavior must be inferred from position deltas and lap-time trends (which is what real engineers do anyway). Opponent incidents/contact inferred, not read directly.

### iRacing Data API (REST, historical)
Race results, qualifying times, series schedules/standings, driver profiles, iRating history, `result_search_series` (already on the roadmap for population pace benchmarking). This powers **field scouting**: before the race, know that P4 is a 4.2k who always sends T1 and P6 is a split-jumping rookie with a high incident rate.

### IBT files (post-session, 60Hz)
Already the backbone of Phases 1–2. For race sessions, IBT + the results API + session YAML are enough to reconstruct race narrative: position changes, gap evolution, incident timing, stint pace, restart performance.

**Conclusion: racecraft coaching is fully feasible with exposed data.** No scraping, no ToS gray zones for the core product.

---

## 4. Product architecture: three surfaces, one brain

The engineer has three moments of contact with the driver. Build them in this order — it's backwards from the sexiness ranking, and that's intentional.

### Surface 1: Post-Race Debrief (build first)
*"What actually happened, and what should I take from it?"*

- Ingest a race (IBT + results API + session YAML). Reconstruct the race narrative.
- Debrief covers: where positions were gained/lost and why; lap-1/restart decision quality; incident analysis (avoidable? positioning error vs. bad luck?); pace vs. position outcomes (did you finish where your pace deserved?); **iRating attribution — did you lose rating to pace or to incidents/decisions?** (this stat directly serves the confidence thesis); overtake/defense patterns; traffic management.
- Output: written debrief in the existing coaching voice + **conversational follow-up** — the driver can interrogate it ("walk me through the lap 9 incident," "should I have pitted with the leaders?"). This is where LLM-native beats every incumbent's static report.
- **Anti-anxiety design requirement:** the debrief must reframe bad races as intelligence gained. Tone: engineer, not judge. Never scold. A wrecked race should produce the most *useful* debrief, not the most painful one.
- No latency constraints, no overlay, no game hooks. Builds the race-state model everything else needs. Testable in weeks.

### Surface 2: Pre-Race Briefing (build second)
*"What am I walking into?"*

- Extends the existing Scouting Report (Phase 2) from track scouting to **field + strategy scouting**:
  - Field analysis from Data API: expected SoF, likely split, where the driver will probably qualify, notable opponents (aggression/incident patterns, pace profile from history)
  - Strategy plan: fuel/tire/pit-window for the actual race length; weather if applicable
  - Threats & opportunities: "you'll be one of the faster cars in this split — clean lap 1 and you gain 3 spots for free"
  - Personal history layer (existing driver-profile roadmap item plugs in here)
- This is the single most differentiated feature vs. all incumbents, and it attacks pre-race anxiety directly: **you never grid up blind.**
- Zero real-time pressure. Mostly Data API + existing synthesis pipeline.

### Surface 3: Live Engineer with push-to-talk (build third)
*"Talk to me."*

- Two interaction modes, mirroring real radio discipline:
  - **Engineer-initiated, sparse and event-driven only:** pace-delta trends, pit window opening, strategy divergence, threat approaching on different strategy. An engineer who mostly shuts up is a feature. (Known failure mode: Trophi users report cognitive overload from over-talking. Do not repeat it.)
  - **Driver-initiated PTT (the magic):** wheel button → question → grounded answer. "Should I pit with the leaders or run long?" "Where am I losing to the car ahead?" Crew Chief proved drivers want to ask; LLMs mean the answer can be real.
- **Engineering constraints:**
  - Target ≤1–2s response latency → realtime voice APIs, not request/response TTS chains
  - Maintain a rolling **race-state summary** (positions, gaps, trends, fuel, strategy state) continuously pre-computed, so the model answers from a compact briefing doc, not raw 60Hz telemetry
  - Two-tier model routing: small/fast model for routine calls, escalation for strategy reasoning
  - Model API cost per race-hour must be measured early — it sets the pricing floor
- Existing roadmap items (Crew Chief integration or TTS output, between-lap coaching) fold into this surface. Consider whether to integrate with Crew Chief or replace it — integration is friendlier for adoption; decide after Surfaces 1–2 ship.

### The shared brain
All three surfaces run on the same race-state model + driver profile. Phase 3's planned intelligence layer (driver profile accumulation, session history, cross-session coaching) is still correct — it just now also accumulates **racecraft tendencies** (lap-1 behavior, restart performance, defense under pressure, incident patterns), not just corner technique. Schema design should anticipate this now.

---

## 5. Revised roadmap

Preserve existing next_actions where still relevant; re-sequence around the race-intelligence thesis.

**Phase 3 (revised): Race Debrief + Intelligence foundation**
- Race session ingestion: IBT (race sessions) + Data API results + session YAML → race narrative reconstruction (position timeline, gap evolution, incident timeline, stint pace)
- Debrief generation in existing synthesis voice + conversational follow-up loop
- iRating attribution analysis (pace vs. incidents/decisions)
- Driver profile v1: technique tendencies (existing plan) + racecraft tendencies (new)
- Carry-over: corner detection v2 (Road America 7/14 problem), population pace via `result_search_series` — both feed the debrief's pace-context layer

**Phase 4 (revised): Pre-Race Briefing / Field Scouting**
- Field scouting from Data API (roster analysis, SoF/split prediction, opponent profiles)
- Strategy plan generation (fuel/tire/pit windows)
- Series calendar awareness (existing roadmap item) → proactive briefings for upcoming races

**Phase 5: Live Engineer**
- Rolling race-state summarizer service (consumes irsdk live, emits compact state)
- PTT input + realtime voice output; latency budget ≤2s
- Sparse event-driven engineer calls with strict rate limiting
- Crew Chief coexistence decision

**Phase 6 (commercial hardening, only after validation):** multi-user, auth, billing, packaging. Note: current stack (Python/Streamlit/SQLite, local) is right for v1 validation speed. Do not prematurely re-platform; re-platform only if strangers paying is proven.

---

## 6. Validation & commercial track (context for build priorities)

- **Goal:** side income at "boat money" scale — roughly $500–800/mo, i.e., 50–80 subscribers at ~$10/mo. Niche-viable; does not require venture-scale outcomes.
- **90-day test:** ship debrief (Surface 1) to one iRacing community (Discord/official forums) as a beta → convert to paid → signal = ~20 paying strangers by month 6.
- **Leading indicator to instrument from day one: does the user's official-race volume go up after adopting the tool?** Races-per-week delta is the confidence thesis, measured. If beta users race more, the product works even before revenue proves it.
- **Distribution:** community-native — post real debriefs of real races (starting with the founder's). The debrief is inherently shareable content; if the insights are good, people post them.
- **Pricing posture:** priced above free (Crew Chief) is justified by reasoning + live voice costs; positioned alongside, not against, Trophi ("get faster" vs. "finish better"). Undercutting is not the strategy.
- **Structural:** LLC before first dollar (Illinois). Sim racing is maximally distant from healthcare consulting — deliberate — but review the Chartis partnership agreement's outside-activities clause before monetizing.

**Founder dogfooding note:** the founder is the target user (practices > races due to iR/SR anxiety, intermediate iRating bracket, Simagic Alpha Evo rig with ample wheel buttons for PTT). Also planned: hands-on eval of Trophi (Mansell) and Crew Chief simultaneously — every moment of overload from Mansell and every unanswerable mid-race question is v1 spec input. Capture that friction list in `docs/` when it happens.

---

## 7. Open questions (park, don't block)

1. Live incident/contact detection for other cars is inference-only — how good is good enough for debrief incident analysis? (Replay files may help; investigate later.)
2. Crew Chief: integrate (output through it) vs. coexist vs. replace? Decide post-Surface-2.
3. Realtime voice stack selection (latency, cost per race-hour, interruptibility) — prototype in Phase 5, not before.
4. Data API rate limits and auth model for a multi-user future (per-user OAuth vs. user-supplied credentials).
5. Expansion sims (ACC, LMU) — architecture should keep iRacing-specific ingestion behind an interface, but do not build abstraction prematurely.

---

## 8. What this is not (updated)

Everything in the PRD's list still applies, plus:
- **Not a real-time driving-technique coach.** Mid-corner "brake later" voice coaching is Trophi's territory and a cognitive-overload trap. The live engineer talks strategy and situation, between corners, sparsely.
- **Not a spotter replacement (yet).** Crew Chief does proximity calls fine. Don't rebuild plumbing before the brain is proven.
- **Not neutral.** The engineer has opinions, a consistent voice, and the driver's back. Especially after bad races.
