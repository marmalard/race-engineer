# Live Voice Coaching — Design

**Date:** 2026-07-06 (amended same day after coverage review)
**Status:** Approved
**Context:** The between-lap terminal coach (live-coaching-spike) was validated in real driving at Spa (BMW M2 CS Racing, July 2026). Lap boundaries held across the session and nudge quality was good enough that the driver's times fell as lines and braking points improved. This design adds a voice layer so coaching reaches the driver without looking at a screen, in two phases: spoken between-lap nudges first, then approach-triggered in-corner prompts. Amendments extend the diagnosis engine (trail braking, exit speed) and wire stored reference laps into the live path, because self-referential coaching alone cannot teach a technique the driver has never used — the coaching ceiling is the driver's own best lap.

## Goals

- The driver hears coaching without taking eyes off the track.
- Phase 1: after each flying lap, a voice speaks the lap delta and the single top nudge, plus a confirmation when a previously flagged corner comes good.
- Phase 2: on the following lap, terse prompts fire before the corners where time was lost ("La Source — brake a car length later"), targeting the ~2 s the driver believes remains at Spa.
- Coach against a stored fast reference lap (Garage 61 import) from lap 1 when one exists, so trail-braking and exit-speed coaching is grounded in a lap that actually demonstrates the technique.
- Zero network on the critical path. Zero AI on the critical path. Voice failure degrades to the existing text surfaces (terminal + iPad feed), never crashes the loop.

## Non-Goals

- **Line analysis.** GPS lateral-offset comparison against the reference lap is deferred to its own future spec — it is computable from captured channels but noisy, self-referential, and hard to reduce to one honest instruction. Today a line error surfaces indirectly as an apex-speed or exit-speed nudge (symptomatically true, causally incomplete).
- **Per-corner technique notes** (AI/scouting-generated prose in `corners.notes`, cited by voice). Stage 2 scope — pairs with the corner-cards briefing work.
- Crew Chief integration (stays a roadmap option for awareness/spotter calls, not technique nudges).
- Neural/cloud TTS (Windows SAPI now; the `Speaker` interface allows a later engine swap without pipeline changes).
- AI rewriting of nudge text (separate deferred track).
- Personal-best auto-promotion into the ReferenceStore (Stage 3 watcher scope).

## Decisions Made During Brainstorm

| Question | Decision |
|---|---|
| Voice timing | Both phases, shipped in order: between-lap voice first, then in-corner prompts |
| Audio path | PC-side speech, mixed with iRacing audio on the same output device |
| Voice engine | Windows built-in SAPI (via `pyttsx3`) — offline, free, instant |
| Architecture | In-process speaker thread + pure prompt scheduler (Approach A) |
| Coverage gaps | Add trail-braking (brake release) and exit-speed metrics now; defer line analysis |
| Reference lap | Wire ReferenceStore into the live coach; fall back to session best |

Rejected: separate voice process polling `/feed` (2 s poll latency disqualifies phase 2); Crew Chief as voice owner (external dependency, wrong lane for technique nudges).

## Architecture

```
scripts/live_coach.py (60Hz tick loop)
  ├── LapBoundaryTracker  (existing)
  ├── ReferenceStore      (existing — NEW wiring: reference lookup at connect)
  ├── build_debrief       (existing — AMENDED: 2 new diagnosis metrics)
  ├── NudgeFeed / web     (existing, unchanged)
  ├── Speaker             (NEW — core/live/speaker.py)
  └── PromptScheduler     (NEW, phase 2 — core/live/prompt_scheduler.py)
```

### Diagnosis engine amendments (`core/coaching/debrief.py`)

`RegionDiagnosis` gains two fields, computed with the same onset-arithmetic pattern as the existing three:

- `brake_release_delta_m: float | None` — distance delta between driver and reference brake-release points (last sample above `BRAKE_THRESHOLD` before the apex). Sign convention matches `braking_delta_m`: **negative = driver releases earlier** (gives up the brakes sooner, i.e. less trail braking).
- `exit_speed_delta_ms: float` — speed delta at the region end. **Negative = driver slower onto the following straight** (the loss compounds down the whole straight).

**Trail-braking guard:** the release delta is only meaningful where the reference actually trail-brakes. It is computed as `None` unless the reference lap carries brake to within a threshold distance of its own apex in that region. Corners the reference takes with straight-line braking (or no braking) never produce a trail nudge — this is how "not every corner needs trail braking" is enforced by data rather than heuristics.

Both fields also flow into the Streamlit debrief cards (display-only change in `coaching.py`).

### Nudge salience ladder (`core/live/nudges.py`)

Extended from three rungs to five; one nudge per region as before:

1. Apex-speed deficit (a lift / over-slow) — existing
2. Braking-point error — existing
3. Brake-release error (trail braking) — NEW: "carry the brakes deeper" / "release the brakes more slowly"
4. Exit-speed deficit — NEW: "prioritize the exit, you're slow onto the straight"
5. Late full-throttle pickup — existing

New thresholds (tunable constants, like the existing 8 m / 2 m/s / 20 m): release delta ≥ 10 m, exit-speed deficit ≥ 2 m/s.

### Phase 1 — Between-lap voice

**`core/live/speaker.py`**

- `Speaker` class: `say(text: str) -> None` enqueues text; a daemon worker thread dequeues and speaks via `pyttsx3` (Windows SAPI).
- **Queue-drop semantics:** the queue holds at most one pending utterance. If a new `say()` arrives while one is pending, the pending (stale) entry is replaced. The driver always hears the latest thing, never a backlog. An utterance already in progress is not interrupted.
- `NullSpeaker` with the same interface for tests and the `--mute` flag.
- The tick loop never blocks on speech: `say()` is O(1) enqueue only.

**`format_lap_speech()` in `core/live/nudges.py`**

- Sibling of `format_lap_block()`. Output: one or two short sentences — delta first, then only the **top** nudge by salience, then at most one confirmation.
- **Speech phrasing rules:**
  - Braking and release distances in **car lengths** (~4.5 m, rounded to the nearest half): "brake a car length later", "carry the brakes two lengths deeper" — never raw meters in speech.
  - Speed deltas in **km/h**, rounded: "you had eight more through Pouhon on the reference."
  - Lap deltas as tenths: "up three tenths", "eight tenths off."
  - Between-lap lines are explicitly **self-referential** ("the reference braked later there", "your best lap carried more speed"); in-corner prompts (phase 2) are pure imperatives.
- **Confirmation nudges:** when a region flagged on the previous lap (matched by label) produces no nudge this lap and the lap improved, append "Pouhon — that's it, keep that." At most one confirmation per lap. Deterministic: requires only the previous lap's flagged labels, held in the loop.
- Baseline lap (no stored reference): "Baseline set. Two eleven point four."
- Display (`format_lap_block`) keeps the full multi-region block; voice gets the headline.

**Wiring:** `emit()` in `live_coach.py` adds `speaker.say(format_lap_speech(...))`. `--mute` selects `NullSpeaker`.

### Reference lap wiring (`scripts/live_coach.py`)

- At connect, read the car name from the live session YAML (`DriverInfo`), using the **same field the offline IBT pipeline stores into ReferenceStore** — the lookup is an exact string match on `(track_id, car)`, so the extraction must be shared/consistent, not re-derived.
- `ReferenceStore.get(track_id, car)` returns the stored lap (G61 preferred over personal_best by the store's existing ordering). When found: it becomes the comparison lap from the **first** valid flying lap — no baseline lap needed, coaching starts immediately. Announce it: "Reference loaded: Garage 61 lap, two nine point eight."
- When no stored reference exists: behavior unchanged — first valid lap becomes session best, coaching starts on lap 2.
- The stored reference is **not** replaced by a faster session lap mid-session (the reference is the target, not a leaderboard); session-best replacement logic applies only in fallback mode.

### Phase 2 — In-corner prompts

**`core/live/prompt_scheduler.py`**

- `build_schedule(diagnoses, corners, track_length_m) -> list[ScheduledPrompt]` — runs once after each debriefed lap. Converts the top 2–3 loss regions into `(trigger_distance_m, text)` entries.
- **Trigger placement:** ~300 m before the region's brake-onset point (falling back to region start when no braking delta was found).
- **Safety clamp:** if a trigger distance falls within any known corner's span, move it earlier to the end of the preceding corner plus a margin; if no gap of at least ~100 m exists, drop the prompt. The coach never speaks inside a braking zone or mid-corner.
- **Cap:** max 3 prompts per lap.
- `feed(lap_dist_m: float) -> str | None` — called each tick; returns the prompt text when the car crosses a trigger point. Each entry fires at most once per lap; schedule re-arms at lap boundary. Handles the start/finish wrap.
- Prompt text: corner name (position fallback otherwise) + one imperative ≤ 5 words from the salience ladder, phrased per the speech rules: "La Source — brake a car length later." / "Rivage — carry the brakes deeper."
- No prompts while the lap is being gated out (pit, reset, invalid) — the scheduler is only fed when the tracker's buffer is live.
- Ships behind `--corner-prompts` so phase 1's voice is validated in anger first.

**Wiring:** after each debrief, rebuild the schedule from the fresh diagnoses; feed `LapDist` to the scheduler in the tick loop; route returned text to `speaker.say()`.

### Interaction between phases

In-corner prompts and the between-lap summary share the one-pending-slot queue. A between-lap summary still pending when a corner prompt fires gets replaced — the in-the-moment prompt wins, because it is only useful *now*.

## Error Handling

- Any `pyttsx3`/SAPI failure (init or runtime): log one warning, swap in `NullSpeaker`, continue. Voice is an enhancement layer; terminal + iPad feed remain the source of truth.
- ReferenceStore lookup failure (missing DB, car-string mismatch): log which key was tried, fall back to session-best mode. A mismatch must be visible, not silent, or the driver won't know why trail coaching is absent.
- Missing corner names: prompts use the position fallback already produced by `segment_annotator` (never invent turn numbers).
- Scheduler receives no valid diagnoses: empty schedule, silence.

## Testing

Mirrors `test_session_reader.py` / `test_nudges.py` style — pure functions, no SAPI, no pyirsdk.

- `test_debrief.py` additions: brake-release delta arithmetic and sign convention; trail guard (reference that doesn't trail → `None`); exit-speed delta at region end.
- `test_nudges.py` additions: five-rung salience ordering; golden-text tests for `format_lap_speech` — baseline, reference-loaded, faster/slower lap, car-length rounding, km/h rounding, confirmation nudge appears once and only when the label was flagged previously and the lap improved.
- `test_speaker.py`: queue-drop semantics with a fake engine (latest-wins, in-progress not interrupted, never blocks), NullSpeaker no-ops, engine-failure fallback.
- `test_prompt_scheduler.py`: trigger placement; safety clamp moves/drops triggers inside corner spans; once-per-lap firing and lap-boundary re-arm; start/finish wrap; 3-prompt cap; empty-diagnoses silence.
- `test_live_coach_helpers.py` additions: reference lookup key construction (car-string consistency with the offline pipeline); fallback to session-best mode.

## Dependencies

- `pyttsx3` (new, phase 1). Nothing else.

## Rollout

0. **Close the G61 validation gate first:** export one real Spa / BMW M2 CS Racing lap CSV from Garage 61, verify `CHANNEL_ALIASES` against the real headers, import into ReferenceStore. This is both the long-pending trust-contract item and the prerequisite for meaningful trail/exit coaching at Spa.
1. Phase 1 lands (diagnosis amendments + voice + reference wiring); driver validates spoken summaries over real sessions — audibility over engine noise, pacing, car-length phrasing, and whether trail nudges fire only at genuine trail corners.
2. Phase 2 lands behind `--corner-prompts`; driver validates trigger timing feels early enough to act on and never distracts mid-corner. Thresholds (300 m lead, 100 m clamp margin, 3-prompt cap, 10 m release, 2 m/s exit) are constants expected to be tuned from real driving, like the 8 m / 2 m/s / 20 m nudge thresholds before them.
