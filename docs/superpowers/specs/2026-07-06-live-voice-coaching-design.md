# Live Voice Coaching — Design

**Date:** 2026-07-06
**Status:** Approved
**Context:** The between-lap terminal coach (live-coaching-spike) was validated in real driving at Spa (BMW M2 CS Racing, July 2026). Lap boundaries held across the session and nudge quality was good enough that the driver's times fell as lines and braking points improved. This design adds a voice layer so coaching reaches the driver without looking at a screen, in two phases: spoken between-lap nudges first, then approach-triggered in-corner prompts.

## Goals

- The driver hears coaching without taking eyes off the track.
- Phase 1: after each flying lap, a voice speaks the lap delta and the single top nudge.
- Phase 2: on the following lap, terse prompts fire before the corners where time was lost ("La Source — brake later"), targeting the ~2s the driver believes remains at Spa.
- Zero network on the critical path. Zero AI on the critical path. Voice failure degrades to the existing text surfaces (terminal + iPad feed), never crashes the loop.

## Non-Goals

- Crew Chief integration (stays a roadmap option for awareness/spotter calls, not technique nudges).
- Neural/cloud TTS (Windows SAPI now; the `Speaker` interface allows a later engine swap without pipeline changes).
- AI rewriting of nudge text (separate deferred track).
- Any change to the core analysis engine (`build_debrief`, `Normalizer`, nudge salience rules are reused unchanged).

## Decisions Made During Brainstorm

| Question | Decision |
|---|---|
| Voice timing | Both phases, shipped in order: between-lap voice first, then in-corner prompts |
| Audio path | PC-side speech, mixed with iRacing audio on the same output device |
| Voice engine | Windows built-in SAPI (via `pyttsx3`) — offline, free, instant |
| Architecture | In-process speaker thread + pure prompt scheduler (Approach A) |

Rejected: separate voice process polling `/feed` (2s poll latency disqualifies phase 2); Crew Chief as voice owner (external dependency, wrong lane for technique nudges).

## Architecture

Two new modules under `core/live/`, one new formatter in `core/live/nudges.py`, wiring in `scripts/live_coach.py`. Follows the established pattern: pure, tested state machines in `core/live/`; the script only drives pyirsdk.

```
scripts/live_coach.py (60Hz tick loop)
  ├── LapBoundaryTracker  (existing)
  ├── build_debrief       (existing, unchanged)
  ├── NudgeFeed / web     (existing, unchanged)
  ├── Speaker             (NEW — core/live/speaker.py)
  └── PromptScheduler     (NEW, phase 2 — core/live/prompt_scheduler.py)
```

### Phase 1 — Between-lap voice

**`core/live/speaker.py`**

- `Speaker` class: `say(text: str) -> None` enqueues text; a daemon worker thread dequeues and speaks via `pyttsx3` (Windows SAPI).
- **Queue-drop semantics:** the queue holds at most one pending utterance. If a new `say()` arrives while one is pending, the pending (stale) entry is replaced. The driver always hears the latest lap, never a backlog. An utterance already in progress is not interrupted.
- `NullSpeaker` with the same interface for tests and the `--mute` flag.
- The tick loop never blocks on speech: `say()` is O(1) enqueue only.

**`format_lap_speech()` in `core/live/nudges.py`**

- Sibling of `format_lap_block()`. Input: lap number, lap time, total delta, diagnoses, `is_baseline`.
- Output: one or two short sentences — delta first, then only the **top** nudge by salience. Example: "Up three tenths. Eau Rouge — carry more apex speed."
- Baseline lap: "Baseline set. Two eleven point four."
- Numbers rendered speech-friendly: deltas as tenths ("eight tenths off", "up two tenths"), lap times as "two eleven point four". No raw floats, no units the driver must parse.
- Display (`format_lap_block`) keeps the full multi-region block; voice gets the headline only.

**Wiring:** `emit()` in `live_coach.py` adds `speaker.say(format_lap_speech(...))`. `--mute` selects `NullSpeaker`.

### Phase 2 — In-corner prompts

**`core/live/prompt_scheduler.py`**

- `build_schedule(diagnoses, corners, track_length_m) -> list[ScheduledPrompt]` — runs once after each debriefed lap. Converts the top 2–3 loss regions into `(trigger_distance_m, text)` entries.
- **Trigger placement:** ~300 m before the region's brake-onset point (falling back to region start when no braking delta was found).
- **Safety clamp:** if a trigger distance falls within any known corner's span, move it earlier to the end of the preceding corner plus a margin; if no gap of at least ~100 m exists, drop the prompt. The coach never speaks inside a braking zone or mid-corner.
- **Cap:** max 3 prompts per lap.
- `feed(lap_dist_m: float) -> str | None` — called each tick; returns the prompt text when the car crosses a trigger point. Each entry fires at most once per lap; schedule re-arms at lap boundary. Handles the start/finish wrap (trigger near the line, car crossing).
- Prompt text is deterministic and ultra-terse, derived from the same salience rules as nudges: "La Source — brake later." / "Pouhon — carry more speed." Corner name when available, position fallback otherwise.
- No prompts while the lap is being gated out (pit, reset, invalid) — the scheduler is only fed when the tracker's buffer is live, mirroring existing gating.
- Ships behind `--corner-prompts` so phase 1's voice is validated in anger first.

**Wiring:** after each debrief in `live_coach.py`, rebuild the schedule from the fresh diagnoses; feed `LapDist` to the scheduler in the tick loop; route returned text to `speaker.say()`.

### Interaction between phases

In-corner prompts and the between-lap summary share the one-pending-slot queue. A between-lap summary that is still pending when a corner prompt fires gets replaced — the in-the-moment prompt wins, because it is only useful *now*.

## Error Handling

- Any `pyttsx3`/SAPI failure (init or runtime): log one warning, swap in `NullSpeaker`, continue. Voice is an enhancement layer; terminal + iPad feed remain the source of truth.
- Missing corner names: prompts use the position fallback already produced by `segment_annotator` (never invent turn numbers).
- Scheduler receives no valid diagnoses (e.g. baseline lap): empty schedule, silence.

## Testing

Mirrors `test_session_reader.py` / `test_nudges.py` style — pure functions, no SAPI, no pyirsdk.

- `test_speaker.py`: queue-drop semantics with a fake engine (latest-wins, in-progress not interrupted, never blocks), NullSpeaker no-ops, engine-failure fallback.
- `test_nudges.py` additions: golden-text tests for `format_lap_speech` — baseline, faster lap, slower lap, no-diagnoses, number rendering (tenths, lap-time speech form).
- `test_prompt_scheduler.py`: trigger placement at 300 m before brake onset; safety clamp moves/drops triggers inside corner spans; once-per-lap firing and lap-boundary re-arm; start/finish wrap; 3-prompt cap; empty-diagnoses silence.

## Dependencies

- `pyttsx3` (new, phase 1). Nothing else.

## Rollout

1. Phase 1 lands, driver validates spoken summaries over real sessions (audibility over engine noise, pacing, number readability).
2. Phase 2 lands behind `--corner-prompts`; driver validates trigger timing feels early enough to act on and never distracts mid-corner. Thresholds (300 m lead, 3-prompt cap) are constants expected to be tuned from real driving, like the 8 m / 2 m/s / 20 m nudge thresholds before them.
