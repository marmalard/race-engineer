# Live Between-Lap Coaching — De-Risk Spike Design

**Date:** 2026-06-12
**Status:** Approved by user, pending implementation planning
**Scope:** Spike only (the live loop + nudges to a terminal). The iPad HUD web service is the named follow-on (Plan 2), designed after this spike proves the foundations.

## Why (strategic reframe)

The question that prompted this: is Streamlit the right surface, or is a live between-lap coach more impactful? Conclusion — **a live between-lap coach is the high-impact surface; Streamlit polish is not.** Evidence:

- The upload-an-IBT ritual already killed the habit once (the original redesign's friction finding).
- Yesterday's real session showed content matters more than polish: the legacy corner-detection path ranked a 0.24s issue #1 while missing a ~2s Eau Rouge/Raidillon/Kemmel loss. No visual design fixes that.
- The analysis core is now lap-shaped and source-agnostic — `build_debrief(driver_lap, reference_lap, corners)` does not care whether a `NormalizedLap` came from an IBT file, a Garage 61 CSV, or a live buffer. The hard, trust-critical work (loss-region attribution, validated yesterday on real data) is done.

So the live coach is mostly **plumbing around a tested engine**, and the tightest feedback loop the user will actually act on: read "carry it flat through Eau Rouge" on the Kemmel straight, try it the same lap.

Two delivery surfaces were considered and deferred in favor of a between-lap **chat feed**: spoken TTS nudges (shares the entire hard part with the feed — voice is a later delivery layer, and on a web surface it becomes nearly free via the browser's Web Speech API) and an in-sim transparent overlay (a separate rendering problem). The chat feed is the proving ground for both.

## What this spike proves (the two real unknowns)

1. **pyirsdk lap-boundary detection survives reality** — pits, resets, tows, incidents, out-laps, in-laps. The buffer must start and end on the right samples and never emit nudges for a garbage lap.
2. **Deterministic nudges read naturally on real laps** — turning `RegionDiagnosis` metrics into terse imperative lines ("brake 15m later", "carry it flat, you lifted") that are correct and actionable, not noise.

Both are answerable in a few driving sessions with terminal output, before any HUD is built. Building a pretty HUD on an unproven loop is the risk this sequencing avoids.

## Architecture (spike)

A single Python process on the gaming PC, run from the terminal:

```
pyirsdk attach to shared memory
  └─ loop at sim tick rate:
       buffer Speed/Throttle/Brake/Steering/Lat/Lon/Gear/RPM/LapDist/
              LapDistPct/SessionTime/Lap/OnPitRoad/PlayerTrackSurface
       on lap-completion transition:
         if lap is valid (not out/in/pit/off-track-corrupted):
            normalize buffered samples → NormalizedLap
            if faster than session-best (or first valid lap):
               update session-best
            debrief THIS lap vs session-best (existing build_debrief)
            top 1–2 loss regions → deterministic nudges
            print nudges to terminal
       on pit/reset/tow: discard the in-progress buffer cleanly
```

Reuses unchanged: `Normalizer`, `build_debrief`, `find_loss_regions`, `annotate_region`, `TrackDB` corner lookup (track ID comes from the live session YAML, same as the IBT path). New code is the live ingestion loop and the nudge template layer.

## Components / files

```
core/live/
├── session_reader.py    # pyirsdk attach, tick loop, lap-boundary detection, buffering
├── lap_buffer.py        # accumulate live samples → DataFrame in the shape Normalizer expects
└── nudges.py            # RegionDiagnosis → terse imperative nudge strings
scripts/
└── live_coach.py        # terminal entry point: wires reader → debrief → nudges → print
tests/
├── test_lap_buffer.py
├── test_nudges.py
└── test_session_reader.py   # lap-boundary logic tested against synthetic tick streams
```

`session_reader.py` is split from `lap_buffer.py` so the boundary-detection state machine (the risky part) is testable in isolation against synthetic tick sequences without a live sim or pyirsdk. The buffer just accumulates and emits a DataFrame matching what `IBTParser.get_laps()` produces, so `Normalizer.normalize_lap` consumes it unchanged.

## Lap-boundary detection (the risk)

State machine over the per-tick stream, keyed on the `Lap` channel transition and guarded by pit/surface flags:

- **Lap increments** → the just-completed lap's buffer is a candidate.
- **Validity gates** (reuse existing pipeline conventions): reject if `OnPitRoad` was true during the lap, if `PlayerTrackSurface` indicates off-track for a sustained span, or if the normalized lap fails the existing 90%-coverage / distance-jump checks. The existing 10%-pace disrupted-lap filter applies once a session-best exists.
- **First valid lap** sets the baseline; no nudge beyond "baseline set."
- **Reset/tow/pit-exit** discards the in-progress buffer (detected via `Lap` going backward, `OnPitRoad`, or a large `LapDist` discontinuity).

This logic lives in `session_reader.py` and is unit-tested against hand-built synthetic tick streams covering: clean lap, out-lap→flying-lap, in-lap→pit, off-track lap, reset mid-lap, tow.

## Nudge templates (the product heart)

Deterministic, no AI, no API key (the user's key is mid-rotation; the critical path must not depend on it). `nudges.py` maps a `RegionDiagnosis` to at most one short line using its existing fields:

- `braking_delta_m` strongly negative → "brake later into {corner}" (you brake early)
- `braking_delta_m` strongly positive → "brake earlier into {corner}"
- `min_speed_delta_ms` strongly negative at a high-speed/flat corner → "carry it flat through {corner}, you lifted"
- `min_speed_delta_ms` strongly negative at a slow corner → "less brake, carry more apex speed in {corner}"
- `throttle_delta_m` strongly positive → "back to power earlier out of {corner}"

Each nudge carries the justifying number for display ("−14 km/h"). Thresholds tuned during the spike so only meaningful deltas speak. Output format per completed lap:

```
Lap 6  (2:23.4, +1.2s)
  Eau Rouge — carry it flat, you lifted  (−14 km/h)
  Les Combes — brake 15m later
```

An optional AI rewrite layer is explicitly out of scope for the spike (deferred to the HUD plan, never on the critical path).

## Deferred to Plan 2 (the HUD)

- NiceGUI web service binding `0.0.0.0` (reachable on LAN at `http://<pc-lan-ip>:PORT` as the default path, and on the tailnet IP for free — LAN is primary, no Tailscale dependency).
- Glanceable dark HUD, websocket push, chat-bubble feed, live mini loss-map.
- Voice via the iPad browser's Web Speech API (a HUD checkbox; the server just sends text).
- Multi-screen sync (iPad + second monitor + phone, same URL).

## Deferred indefinitely / out of scope

- In-sim transparent overlay (separate rendering problem).
- Server-side TTS (ElevenLabs/OpenAI) — the browser path makes it unnecessary.
- Streamlit IA cleanup (lead with loss map, retire misleading legacy corner-detection sections) — a separate cheap half-day, not part of this build.

## Testing

- `test_lap_buffer.py`: synthetic tick stream → DataFrame shape matches `IBTParser.get_laps()` output; `Normalizer.normalize_lap` accepts it and produces a valid `NormalizedLap`.
- `test_session_reader.py`: the boundary state machine against the synthetic scenarios listed above (clean, out-lap, in-lap, off-track, reset, tow) — asserts the right laps are emitted and garbage laps are suppressed.
- `test_nudges.py`: each `RegionDiagnosis` shape → expected nudge string and number; below-threshold deltas produce no nudge.
- Live validation: the user drives real sessions with `scripts/live_coach.py` printing to a terminal, and reports (a) whether lap boundaries are detected correctly across pits/resets, and (b) whether the nudges read naturally. This is the spike's real acceptance test.

## Success criteria

The spike succeeds when, across several real driving sessions:

1. Every completed flying lap emits a debrief; no out-laps, in-laps, pit laps, or reset-corrupted laps emit phantom nudges.
2. The nudges are correct (match what the user felt in the car) and terse enough to read between laps.
3. The user wants to keep it running — the signal that the HUD is worth building.

If lap-boundary detection proves unreliable or the nudges read as noise, that is a cheap, early finding — fix the loop/templates before any HUD work, exactly as intended.
