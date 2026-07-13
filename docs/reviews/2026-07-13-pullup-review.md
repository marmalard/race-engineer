# Pull-Up Review — Application, Roadmap, and Next Priority

**Date:** 2026-07-13 (review conducted 07-12/13)
**Method:** three parallel audits — UX/product audit of the app surface, strategy-doc
drift review, and a database reality check of what's actually used.

## The headline finding

Build track is far ahead of the validation track. Usage data (read-only DB queries):

| Surface | Evidence |
|---|---|
| Lap coaching + watcher (founder tool) | 64 practice sessions, 444 laps, 31 PB references — heavily used |
| Live voice coach | 5 session logs; 3 at Summit on 2026-07-12 — round-2 validation underway |
| **Race debrief (the market product)** | **2 races captured, 1 AI debrief ever generated, 0 chat messages ever** |

The founder's own practice:race ratio is **64:8 — the exact anxiety pattern the
product exists to fix**. The strategy's leading metric ("does official-race volume go
up?") has not yet moved for user #1. Root cause per the founder: limited time → needs
comfort with a combo before risking a race → practices instead. This is the Phase 4
briefing's job (see brainstorm prep doc).

## Strategy review verdict (docs vs reality)

- Thesis ("coach the race, not the lap"; sell confidence, not pace) is intact and
  uncontested by incumbents. Surface 1→2→3 sequencing honored; founder/market track
  balance over the last week was healthy.
- **Phase 4 (pre-race briefing) is the right next build** per the strategy's own logic
  ("the single most differentiated feature vs all incumbents").
- **Validation debt is the real gap:** AI debrief tone check, voice round-2 tuning,
  asterisk drive-test, launcher smoke test, G61 gate fixtures, friend funnel — all
  queued, none done at review time. The strategy says instrument race-volume from day
  one; measurement can't start until the founder + a friend are actually racing.
- Strategy-doc blind spots (nowhere addressed): retention/habit loop, sharing
  scaffolding (debriefs are "inherently shareable" but export-only), stranger
  onboarding, mobile story (consciously parked — now recorded), pricing (correctly
  blocked on Phase 5 voice costs).

## UX audit verdict (consumer-grade gap)

"The product is ~80% of the way to launch. The analysis and features are solid. The
missing 20% is the consumer layer." Full findings preserved below in summary; the
ranked top-5:

1. **Real landing/onboarding page** — new users land on "upload a race IBT" with zero
   context (biggest friction moment; no explanation of what an IBT is or where it lives).
2. **Glossary/inline tooltips** — IBT, SoF, iRating, pace-deserved position, Garage 61,
   reference lap: all unexplained everywhere they appear.
3. **Sample debrief** — show what the product does before asking for a 25–205 MB
   upload; celebrate the first successful analysis.
4. **Guide restructured as consumer onboarding** — currently a founder manual (exposes
   DB layout, CLI paths, tailscale) buried at nav position 3.
5. **Error messages + progress phases** — "couldn't analyze this file" currently covers
   everything from corrupt file to missing ANTHROPIC_API_KEY; long analyses show a
   bare spinner (should be phased status: parsing → fetching results → building).

Additional notable findings: hardcoded founder telemetry path silently gates the folder
picker; "AI Metadata" expander exposes model/token internals; Toolbox jargon
("pit-wall tools") unexplained; emoji-only nav labels; no mobile/iPad responsiveness
(Streamlit ceiling — file upload on iPad is a platform limitation); watcher dependency
is invisible on the Driver Profile page (add "last scan: X ago / scan now").

Streamlit-ceiling items (platform, not polish): iPad file picking, true mobile reflow,
background jobs, live log streaming. Revisit at the Phase 6 VPS/packaging decision.

## Decided sequencing (2026-07-13, under the Fable deadline of 2026-07-19)

Frontier-model access ends 07-19; allocate it to work where model quality matters most.

1. **Founder validation burst (user, this week):** 3–5 official races; debrief + CHAT
   with every one; validates Surface 1 tone, asterisk, voice round 2, launcher; unlocks
   racecraft tendencies (needs 3 races).
2. **Phase 4 pre-race briefing (Fable window):** feasibility spike DONE 07-13 (all six
   data questions feasible — see spike findings doc); API plumbing building 07-13;
   brainstorm → spec → build v1 next.
3. **Consumer-grade pass (post-Fable):** execute the UX top-5 from a written plan —
   copy/flow work a cheaper model executes well. Plan to be written before 07-19.
4. **Friend funnel:** immediately after the consumer pass, not after more features.

## Fun / personality (parked with a shape)

Personality is cheap on the text path (prompt-level persona for debrief/chat: name,
history, dry humor, opinions — a tone-contract evolution) and expensive on the voice
path (per-personality TTS rides the future neural-TTS swap). Sequencing: text persona
can join the consumer-grade era; voice persona waits for the TTS upgrade. A memorable
engineer who knows your history doubles as the missing retention/habit mechanism.
