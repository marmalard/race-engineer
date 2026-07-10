# Live Voice Coach UX — Round 2

**Date:** 2026-07-09
**Status:** Design — approved in brainstorm, pending spec review
**Origin:** First real driving validation of the between-lap voice coach (Bathurst / Porsche 992 Cup, 2026-07-09). Content was helpful; three UX gaps surfaced.

## Context

The live voice coach (`scripts/live_coach.py` + `core/live/`) speaks a between-lap
summary after each flying lap and can fire approach prompts before flagged corners.
Three field-test findings drive this round:

1. **No audio confirmation on connect when there's no reference.** The connect line
   only speaks when a stored reference lap exists; with no reference the coach prints
   silently — exactly the case where you'd most want to confirm the audio path works
   before leaving the pits.
2. **Silence is ambiguous when a lap is thrown away.** `LapBoundaryTracker.feed()`
   returns `CompletedLap | None`, and `None` hides four cases (buffering, pit,
   reset/tow, too-short). A completed-but-normalizer-rejected lap is silent too. You
   finish what feels like a real lap, expect a nudge, and hear nothing.
3. **Named corners are spatially confusing.** The between-lap summary references
   corners by name ("Hell Corner") while you're on a straight — the name has no
   spatial anchor in the moment. The fix is to cue the coaching *as you approach the
   corner*, where the cue can say "here" and drop the name entirely.

All decision logic stays in tested `core/` modules; `live_coach.py` only wires speech.
No AI, no API key on the path.

## Goals

- Always confirm the audio path on connect (with or without a reference).
- Never leave a discarded lap ambiguous — a brief spoken acknowledgment whenever a lap
  that could have produced coaching is thrown away.
- Deliver the corner coaching as an approach cue that references "here", combines the
  top faults for that corner, and gives a coarse, actionable magnitude.

## Non-Goals (explicitly deferred)

- **Track-limits asterisk** (its own spec): keep a clean-telemetry lap that has a minor
  track-limits infraction, coach it normally, but flag the *time* as not counting
  (detect via `PlayerCarMyIncidentCount` delta + `PlayerTrackSurface` OffTrack +
  `LapDist`→corner). This ALSO closes the watcher's "no cleanliness gate on promoted
  PBs" item. **Hard line for this spec:** the discard acknowledgment (Feature B) fires
  only on *normalizer-invalid corruption* (spin / tow / incomplete coverage) — never on
  a clean lap with a track-limits infraction. Those two must not be conflated.
- Braking-marker anchoring ("brake at the 100 board") — needs per-track marker data we
  don't have yet.
- Cold-track startup rundown / track-temp warnings — separate backlog item.

---

## Feature A — Startup radio check

New pure helper in `core/live/nudges.py`:

```python
def format_radio_check(reference: ReferenceLapMeta | None) -> str: ...
```

- With reference:
  `"Radio check, reading you. Reference lap 2 07.7, loaded. Coaching from lap one."`
- Without reference:
  `"Radio check, reading you. No reference for this combo — I'll set a baseline from your first lap."`

Reuses `_speech_lap_time` for the lap time. In `live_coach.py`, this **replaces** the
current reference-only spoken line (the `speaker.say("Reference lap loaded, …")` block)
and **adds** the no-reference spoken branch, so a spoken line fires in **both** cases.
The existing printed / `emit` lines are unchanged.

## Feature B — Discard acknowledgment (broken data only)

Widen the tracker's per-tick return so it can say *why* a lap vanished, instead of
duplicating pit/reset logic in the wiring.

In `core/live/session_reader.py`:

```python
class DiscardReason(str, Enum):
    RESET = "reset"   # backward Lap jump: reset / tow
    PIT   = "pit"     # a pit-touched lap that closed

@dataclass
class TickResult:
    completed: CompletedLap | None = None
    discarded: DiscardReason | None = None
```

`feed()` returns `TickResult` (was `CompletedLap | None`). Rules:

- **RESET** — flagged on a backward Lap jump **only if** the discarded buffer held a
  real attempt (`len(buffer) >= min_lap_samples`). Garage / pit-box resets with tiny
  buffers stay silent (no nagging).
- **PIT** — flagged once when a pit-touched lap closes.
- **too-short** fragments — **not** announced (they usually follow a reset that already
  spoke; avoids double-speak).

New helper in `core/live/nudges.py`:

```python
def format_discard_speech(reason: DiscardReason) -> str: ...
```

- `RESET` → `"Reset — scratch that lap."`
- `PIT`   → `"In the pits — that lap won't count."`

**Normalizer-invalid case** (off-track excursion causing a distance jump, incomplete
coverage — the biggest source of confusing silence today) is handled in
`live_coach.py`. It already branches on `if nlap.is_valid:` — add an `else` that speaks
`"That lap won't count — data's incomplete."` This stays in the wiring because
`is_valid` is only known after `normalize_lap`, outside the tracker.

Each discard is a single-tick transition, so it speaks once. The speaker is already
latest-wins / non-interrupting.

## Feature D — Approach-corner cue

The `PromptScheduler` already fires an approach prompt ~`LEAD_M` (300 m) before the
reference brake onset for a flagged corner, with a corner-span safety clamp. The timing
infrastructure is done. This feature (1) enriches the prompt *text* and (2) turns the
system on by default.

**Enrichment.** Today `build_schedule` uses `nudge.prompt` — a single terse,
name-prefixed phrase ("Hell Corner — brake later"). Replace it with a combined cue built
from the *same* diagnosis's multiple deltas.

New pure helper in `core/live/nudges.py`:

```python
def approach_cue_from_diagnosis(diag: RegionDiagnosis) -> str | None: ...
```

- Considers the corner's salient faults (braking point, apex/lift, trail release, exit
  speed, late throttle — same thresholds as `nudge_from_diagnosis`), builds a short
  phrase for each, and joins the **top 1–2** by salience into one line.
- **Drops the corner name.** Leads with "Coming up —" (spoken on approach, not at the
  apex).
- **Coarse car-length magnitude**, bucketed — *"a bit later"* / *"a couple car lengths
  later"* / *"much later"* — never a fake-exact meter figure. Car-lengths are
  visualizable and match the unit the between-lap summary already uses.
- Returns `None` if nothing crosses threshold (no prompt scheduled for that corner).

Example: `"Coming up — brake a couple car lengths later, get to throttle earlier on exit."`

`build_schedule` calls `approach_cue_from_diagnosis(diag)` for the prompt text; when it
returns `None`, that corner is skipped (same as today's `nudge is None` skip). The
anchor, `_place_trigger` clamp, `MAX_PROMPTS`, and firing logic are unchanged.

**Default on.** In `live_coach.py`, approach cues become the default. Replace the
`--corner-prompts` opt-in flag with `--no-corner-prompts` to disable. All the guarded
blocks (`if args.corner_prompts:` → the inverse) run by default.

**Magnitude wording is a tuning knob.** The bucket boundaries and phrases live in named
constants in `nudges.py` (like the existing salience thresholds), so they can be tuned
from `data/live_sessions/*.jsonl` after a few laps.

**Known watch item (unchanged):** the corner-span clamp drops the Bruxelles prompt at
Spa's chicane-dense Rivage/Bruxelles stretch. Expected behavior; keep watching whether
it loses the most valuable prompt.

---

## Files touched

| File | Change |
|------|--------|
| `core/live/nudges.py` | + `format_radio_check`, `format_discard_speech`, `approach_cue_from_diagnosis`, magnitude-bucket constants |
| `core/live/session_reader.py` | `feed()` → `TickResult`; `DiscardReason` enum; RESET/PIT flagging |
| `core/live/prompt_scheduler.py` | `build_schedule` uses `approach_cue_from_diagnosis` for prompt text |
| `scripts/live_coach.py` | radio check always speaks; `TickResult` handling + discard speech; normalizer-invalid `else` speaks; `--no-corner-prompts` (default on) |

## Testing

- **`test_nudges.py`** — `format_radio_check` (both branches), `format_discard_speech`
  (both reasons), `approach_cue_from_diagnosis` (single-fault, combined two-fault, coarse
  magnitude buckets, below-threshold → `None`, no corner name in output).
- **`test_session_reader.py`** — update existing assertions to `TickResult`; add:
  full-buffer backward jump → `discarded == RESET`; short-buffer backward jump → no
  discard; pit-touched close → `discarded == PIT`; clean completion → `completed` set,
  `discarded is None`; too-short → neither.
- **`test_prompt_scheduler.py`** — `build_schedule` emits combined cue text; still
  respects clamp / `MAX_PROMPTS`; `None` cue skips the corner.
- **`test_live_coach_helpers.py`** — normalizer-invalid → discard-speech mapping if a
  helper is extracted.

## Rollout

Restart the live coach after merge. Validate in one session: audio confirmed on connect
(drive a combo with no reference to hear the no-ref line), a deliberate spin / off / pit
to hear each discard line, and approach cues landing before the flagged corners with
intelligible combined phrasing. Tune magnitude buckets from the session log.
