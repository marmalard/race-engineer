# Exit Verdict Cues — closing the corner feedback loop

**Date:** 2026-07-16
**Status:** Approved (founder, this session)
**Origin:** Third race field note (VIR, 2026-07-16): "it's hard to know if
I'm nailing the advice after the turn — maybe it'd be good if it said that
was better, or you're still a bit late/early."

## Problem

The approach cue asks for something ("Coming up — brake a couple car
lengths later"), but the driver gets no answer until the end-of-lap
summary — and the existing "healed" confirmation line fires minutes of
corners later, disconnected from the attempt. The loop is open exactly
where learning happens: at the corner exit, while the attempt is fresh.

## What ships

After an approach cue speaks for a corner, the coach evaluates the
driver's execution of THAT corner live and speaks a one-clause verdict
1–2 seconds after the exit:

- **"That's it."** — the coached fault is now under its threshold.
- **"Better — still a touch late."** — magnitude shrank meaningfully
  (under ~half of last lap's) but not fixed. Direction word matches the
  fault.
- **"Too far — back it off."** — sign flipped past threshold
  (overcorrection; asked for later, driver went past the reference).
- **"Still late on the brakes."** (or the fault's equivalent) —
  unchanged.

Quantity-free by design (same philosophy as the approach cue: the driver
is at speed and cannot act on numbers). One verdict per prompted corner,
once per lap, max 3/lap by construction (verdicts exist only for
scheduled prompts).

Plus a race-session gate (below) with a `--race-cues` toggle.

## Decisions locked this session

1. **Scope: only prompted corners.** A verdict is armed iff that corner's
   approach cue was actually scheduled. A cue dropped for having no safe
   speaking gap arms no verdict. Tight call-and-response, max 3/lap.
2. **Voice: terse, quantity-free.** Buckets, not magnitudes.
3. **Overcorrection is called out** ("Too far — back it off") — the
   convergence loop closes in both directions; without it the driver
   only learns via a flipped cue next lap, which reads as whiplash.
4. **Race sessions: persistence gate + toggle.** Default `persistent`:
   in a Race session, a corner is cued (and thus verdict-armed) only
   when its primary fault has persisted ≥ 2 consecutive laps — one
   scrappy corner while dicing stays silent; a repeatable deficit gets
   flagged. `--race-cues full|persistent|off` overrides. Practice /
   qualifying behavior unchanged (every lap, immediate).
   "Consistently below the FIELD" (opponent corner pace) is not
   measurable live today — it lands with Phase 5 opponent data.

## Architecture

New pure module `core/live/exit_verdict.py` — no pyirsdk, no I/O,
mirroring PromptScheduler's shape. Core analysis engine untouched
(reused-engine principle).

### ArmedVerdict (dataclass)

One per scheduled prompt: corner label; span (start/end m); ordered
coached fault list (the ≤ 2 faults the cue spoke, from the salience
ladder); reference metrics the diagnosis already carries
(`reference_brake_onset_m`, `reference_min_speed_ms`); last lap's fault
magnitudes (`braking_delta_m`, `min_speed_delta_ms`,
`throttle_delta_m`, `exit_speed_delta_ms`, `brake_release_delta_m`).

### Plan builder

`build_schedule` grows into a plan builder returning
`(prompts, armed_verdicts)` from the same diagnoses — one construction
site so scope rule 1 holds structurally. Existing callers/tests updated
(live_coach + test_prompt_scheduler).

### VerdictWatcher

Fed each tick with `(lap_dist_m, speed_ms, brake, throttle)` — all
already in `READ_CHANNELS`. Per armed corner it passively observes:

- **Brake onset**: first tick with brake above the on-threshold within
  `[span_start − 200 m, span_end]` — the offline `_diagnose_region`
  search window, exactly.
- **Min speed** inside the span.
- **Throttle-on**: first sustained throttle after the observed min-speed
  point, up to `span_end + 100 m` (offline window again).

At `span_end + VERDICT_POINT_M` (100 m — the end of the throttle
window; ~1–2 s past exit at speed) it buckets the PRIMARY coached fault
and returns the verdict line. Wrap-safe crossing via the `_crossed`
logic; `rearm()` at lap boundaries; `reset_position()` on pit/tow
exactly like the scheduler.

### Bucketing (primary coached fault)

Signed live delta vs reference, same sign conventions as the debrief
(negative braking delta = earlier; positive throttle delta = later):

Rows are evaluated top-down; the first match wins. Overcorrection is
checked BEFORE "better" — a sign-flipped delta that is numerically
smaller than last lap's must not produce "still a touch late" with the
wrong direction word.

| Condition (in order) | Verdict |
|---|---|
| abs(delta) < fault threshold | That's it. |
| sign flipped vs last lap AND abs(delta) ≥ threshold | Too far — back it off. |
| abs(delta) < IMPROVED_FRACTION (0.5) × abs(last lap's) | Better — still a touch {direction}. |
| otherwise | Still {direction} {fault phrase}. |

Thresholds imported from `nudges.py` (`BRAKING_THRESHOLD_M`,
`MIN_SPEED_THRESHOLD_MS`, …) — never duplicated. All phrasings
exact-string tested. If the primary fault is fixed and a second coached
fault is not, the verdict still evaluates ONLY the primary — one clause,
no essay; the second fault re-cues next lap if it persists.

### FaultStreakTracker (race gate)

Pure: fed each completed lap's diagnoses, tracks consecutive-lap streak
per (corner label, primary fault kind). Race mode `persistent` filters
the plan builder's input to streak ≥ `RACE_STREAK_MIN` (2).

**Session-type detection**: `SessionInfo Sessions[SessionNum]
.SessionType == "Race"` — NOT `WeekendInfo.EventType`, which reads
"Race" for practice/quali sessions on a race server (the pre-race-chunk
lesson, 2026-07-15). `SessionNum` is read per tick (cheap scalar);
session type refreshes when it changes mid-weekend.

### live_coach wiring

- Watcher `feed()` sits beside the scheduler's in the tick loop, gated
  by the same `corner_prompts` flag.
- Verdict line → `speaker.say` + `emit` (terminal + iPad feed) + a
  `verdict` session-log event carrying observed metrics (brake onset,
  min speed, throttle-on, computed delta, bucket) for field tuning from
  `data/live_sessions`.
- `--race-cues {full,persistent,off}` added to `build_parser`
  (default `persistent`). Toolbox spawn-command coupling tests updated
  (the 2026-07-14 flag-drift lesson).

## Failure modes

- List-valued churn ticks: the existing whole-tick skip protects the
  watcher (it is fed after the churn guard).
- `LapDist` None (tow/out-of-world) or `OnPitRoad`: `reset_position()`,
  same as the scheduler.
- Any exception inside watcher feed or plan building is caught in the
  loop, logged to the session log, and never kills the coach
  (2026-07-12 daemon lesson).
- Speaker collision (verdict + next corner's cue near-simultaneous):
  handled by the existing one-slot latest-wins queue; verdict lines are
  ~1 s. Tune from field logs if dense sections prove chatty; no special
  guard in v1.
- No armed verdicts (no reference yet, clean lap, race gate filtering
  everything): watcher is empty and silent — zero-cost pass-through.

## Anti-drift lock

The live metric extraction re-implements three small offline
definitions. Two locks:

1. Thresholds and search-window constants imported from their existing
   homes, never copied.
2. A coupling test replays a real normalized lap through the watcher
   tick-by-tick and asserts the observed brake onset matches
   `_diagnose_region`'s within grid tolerance (1 m grid, ±2 samples).

## Testing

- Watcher state machine on synthetic tick streams: fixed / better /
  unchanged / overcorrected; start-finish wrap; pit-resume position
  reset; once-per-lap; rearm.
- Exact-string phrasing tests (like nudges).
- Live-vs-offline brake-onset coupling test (real fixture lap).
- FaultStreakTracker: streak build, reset on clean lap, per-fault keys.
- Session-type gate: Race vs Practice vs Lone Qualify; SessionNum
  transition mid-weekend.
- Parser: `--race-cues` choices + default; Toolbox coupling tests.

## Out of scope (deliberate)

- Opponent-relative corner pace ("below the field") — Phase 5.
- Verdicts for un-prompted corners.
- AI phrasing / neural TTS — separate tracks (voice naturalness).
- Quieting ALL technique coaching in races — revisit with the Phase 5
  racecraft engineer.

## Field validation (after ship)

Drive a practice session and confirm: verdict timing lands after exit
but before the next braking zone; buckets match felt reality; race
persistence gate stays quiet in traffic. Tune `VERDICT_POINT_M`,
`IMPROVED_FRACTION`, `RACE_STREAK_MIN` from session logs.
