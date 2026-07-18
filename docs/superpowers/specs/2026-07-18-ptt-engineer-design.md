# PTT Live Engineer + Natural Voice — Design

**Date:** 2026-07-18
**Status:** Approved (brainstorm 2026-07-18; resumed after disconnect, decisions recovered from session fce5e943)
**Strategy anchor:** Phase 5 of `docs/race-engineer-v2-strategy.md` — "Live Engineer with push-to-talk", the third market surface. "You never race alone."

## 1. What this is

One spec, three stages. Each stage ships alone and is useful alone:

- **Stage A — the voice.** Swap the live coach's SAPI voice for a local neural TTS (Kokoro-82M). The existing coach speaks in the new voice the day this lands; voice quality is validated months before PTT exists.
- **Stage B — race awareness.** A rolling race-state summarizer over the live CarIdx arrays, plus four sparse engineer-initiated calls (threat behind, attack ahead, closing laps, where-you're-losing-the-guy-ahead).
- **Stage C — push-to-talk.** Wheel button → mic capture → local STT → hybrid answer engine (deterministic fast path + Claude grounded in race state) → priority voice reply. Target latency: ≤2s fast path, ≤4s Claude path.

## 2. Decisions locked (brainstorm)

1. **Scope:** one spec, three stages (A voice, B summarizer + calls, C PTT). Not separate specs.
2. **PTT input:** Simagic wheel button read directly as a DirectInput/HID joystick button (pygame-class dependency). No remapping software in the loop.
3. **Answer engine:** hybrid. Deterministic intent matcher answers the common quantitative calls (gaps, position, laps left, pace delta) instantly from race state — the no-API-on-critical-path house pattern. Everything else goes to Claude (Haiku-class) grounded in the race-state JSON. Network down → fast path still works; open questions get a spoken "Can't reach the pit wall — stand by."
4. **V1 engineer-initiated call set:** threat behind, attack ahead, closing-laps callout, and where-you're-losing-the-guy-ahead (founder addition). Fuel/pit-window call is a fast-follow, NOT v1.
5. **Race voice mix:** engineer calls join the existing gated cues (persistent-fault cues + exit verdicts stay). ONE voice, one Speaker; a PTT answer always wins the next slot; a strict global rate limit (RadioBudget) applies across ALL sources. The named failure mode to avoid is Trophi-style overload — an engineer who mostly shuts up is a feature.

## 3. Architecture

**Option A — extend the live coach process** (chosen over a separate engineer daemon and over cloud realtime speech-to-speech):

- The engineer lives inside `scripts/live_coach.py`'s existing 60Hz loop. That loop already reads shared memory, owns the one Speaker, tracks session transitions, and carries the race gate.
- New package `core/engineer/` supplies the pieces. Everything in it is pure (no pyirsdk, no I/O) in the `LapBoundaryTracker` mold — `live_coach.py` remains the only driver.
- The per-tick cost of the summarizer is a cheap CarIdx array read. STT and Claude calls run on worker threads; the tick thread never blocks.
- Rejected: **B, separate daemon** — needs a second Speaker (two voices) or IPC to share one, plus a second tray-managed process; the one-voice decision kills it. **C, cloud realtime voice API** — network on the critical path, per-race-hour cost, a second AI vendor (Anthropic ships no realtime voice API); contradicts the house pattern.

New modules:

```
core/engineer/
├── race_state.py     # PURE: per-tick CarIdx samples → rolling race state + snapshot()
├── calls.py          # PURE: the four engineer-initiated calls over state histories
├── radio_budget.py   # PURE: global rate limiter across all spoken sources
├── intents.py        # PURE: transcript → deterministic fast-path answer, or None
├── ptt_input.py      # pygame joystick read (thin; polled by the tick loop)
└── stt.py            # faster-whisper wrapper (worker-thread use only)
core/coaching/prompts/engineer.py   # radio tone contract for the Claude path
core/live/speaker.py                # extended: priority slot (see 4)
```

## 4. Stage A — the voice

**Engine.** `Speaker`'s engine is already `Callable[[str], None]`, so this is a new engine factory, not a rewrite. **Kokoro-82M** (Apache 2.0, natural, faster-than-realtime on CPU — deliberate: iRacing owns the GPU), synthesized to a buffer and played via `sounddevice`. **Piper** is the fallback if Kokoro's torch dependency fights Python 3.14 — same callable seam either way, decided at plan time by a compat check. Voice selection is a module constant. **SAPI remains the degrade path**: any load failure at startup falls back to the current pyttsx3 engine; `NullSpeaker` behavior is unchanged.

**Priority slot.** One small, tested change to `Speaker`: a second pending slot. `say_priority(text)` (PTT answers) always beats `say(text)` (cues, verdicts, engineer calls) for the next utterance. In-progress speech is still never interrupted. The one-slot latest-wins rule holds *within each tier*.

**RadioBudget.** A global rate limiter across ALL engineer-originated speech (minimum spacing between utterances, per-episode once-only semantics). Cues/verdicts keep their existing gates on top — the budget is a floor under everything, not a replacement for the race gate. PTT answers are exempt from spacing (the driver asked; answering is never overload) but still logged against the budget for tuning.

## 5. Stage B — race-state summarizer + engineer calls

### 5.1 RaceState (`core/engineer/race_state.py`)

Pure state machine fed one sample dict per tick (the `LapBoundaryTracker` pattern). Holds:

- **Roster** from the session YAML at connect: driver name, iRating, car class per CarIdx — calls say "Hamilton behind you," never "car 14".
- **Per-car live state** from CarIdx arrays (`CarIdxPosition`, `CarIdxClassPosition`, `CarIdxLap`, `CarIdxLapDistPct`, `CarIdxOnPitRoad`, `CarIdxTrackSurface`): position, lap, track position, pit status. Lap-time history per car derived from `CarIdxLap` transitions against SessionTime.
- **Gap histories** to the cars directly ahead and behind in running order (`CarIdxF2Time` / `CarIdxEstTime`), recorded once per lap boundary. Closing-rate trends come from lap-boundary history, never from noisy per-tick deltas.
- **Session context:** laps or time remaining (`SessionLapsRemain` / `SessionTimeRemain`), session type via the existing `current_session_type` (race_gate) — the SessionInfo-per-session lesson, not `WeekendInfo.EventType`.
- **`snapshot()`** → compact dict: the race-state JSON. One representation, two consumers (fast-path answers and the Claude grounding payload).

Per-tick work is an array copy + boundary detection; all trend math runs on lap boundaries.

**Not available live (accepted):** other cars' pedals, tires, fuel. Opponent behavior is inferred from position deltas and lap-time trends — which is what real engineers do.

### 5.2 The four calls (`core/engineer/calls.py`)

Pure functions over RaceState histories; every call passes through the RadioBudget; all thresholds are module constants tuned from session JSONL.

1. **Threat behind.** Gap behind under `THREAT_GAP_S` (~1.5s) and shrinking across `TREND_LAPS` (N) consecutive laps → "P8 is closing, three tenths a lap. Keep your head down." Episode semantics: fires once, re-arms only when the gap resets (pass, pit, or the gap reopens past a hysteresis margin).
2. **Attack ahead.** Mirror image: gap ahead shrinking consistently → "You're pulling P5 in, half a second a lap."
3. **Closing laps.** One call at `CLOSING_LAPS_N` to go (or the time-remaining equivalent) with position and gap behind — "Five to go, P6, gap behind 2.1." Fires exactly once per race.
4. **Where you're losing the guy ahead.** Samples the gap to the target car each time the player crosses a corner boundary (corner spans already loaded at connect via `_load_corners` in live_coach). Accumulates per-corner gap deltas over consecutive laps; when one corner dominates the loss, one call: "You're losing him in the Chase — everywhere else you match him." Self-gates on data quality: needs the target in measurement range and stable corner spans for 2+ consecutive laps, otherwise stays silent. Fires at most once per target car per race.

### 5.3 Voice-mix integration

Engineer calls emit through the same one-slot `say()` path as cues and verdicts. The shipped race gate is untouched — persistent-fault cues and exit verdicts keep their `--race-cues` behavior. The RadioBudget sits under everything.

## 6. Stage C — the PTT pipeline

Button → mic → STT → answer → voice. Everything heavy runs off the tick thread.

- **Button** (`core/engineer/ptt_input.py`): pygame reads the Simagic wheel button as a HID joystick button, polled in the 60Hz loop. Press starts mic capture; release stops it and hands the buffer to a worker thread. A press also cancels any *pending* non-priority utterance — the engineer shuts up when the driver keys the radio. Button index is a config constant surfaced at startup ("PTT on joystick 0 button 5").
- **Capture:** `sounddevice` input stream while held, 10s hard cap.
- **STT** (`core/engineer/stt.py`): **faster-whisper** (CTranslate2 — no torch, so no Python 3.14 fight; base/small model; well under a second for a radio question on CPU). Fallback if it won't install: whisper.cpp bindings — same seam, decided by the same plan-time compat check as Kokoro/Piper.
- **Fast path** (`core/engineer/intents.py`): deterministic patterns over the transcript — gap ahead/behind, position, laps left, pace delta, who's behind/ahead of me — answered instantly from `snapshot()`. Pure; exact-string tested like nudges.
- **Claude path:** unmatched transcripts go to a Haiku-class call with the race-state JSON under a terse radio tone contract (`core/coaching/prompts/engineer.py` — engineer, not essayist: one or two sentences, numbers rounded, no scolding, consistent with the debrief tone contract's honesty rules). 4s timeout, or no API key → spoken "Can't reach the pit wall — stand by." The fast path works with zero network, zero key.
- **Out:** answers via `say_priority()` — a PTT reply always beats a queued cue or call.
- **Latency budget:** release → speech start: ≤2s fast path, ≤4s Claude path.

## 7. Wiring, observability, config

- **Flags:** `--no-engineer` (engineer + PTT on by default in Race sessions only, matching the race-gate posture; practice/quali sessions run the coach exactly as today). Existing flags (`--mute`, `--no-corner-prompts`, `--race-cues`) untouched.
- **Toolbox:** gets the new flag through the existing coupling-test pattern — any UI that builds this CLI command gets a test against `live_coach.build_parser()` (the 2026-07-14 rule).
- **Feed:** engineer calls, PTT transcripts, and answers `emit()` to the terminal + iPad web feed like every other utterance.
- **JSONL:** every call, transcript, answer, and suppressed-by-budget event logs to the session JSONL with a state snapshot attached — that is the tuning corpus for thresholds.
- **Dependencies added:** kokoro (or piper-tts), sounddevice, faster-whisper (or whisper.cpp bindings), pygame. All local; compat with Python 3.14 verified at plan time; every one degrades (voice → SAPI, STT missing → PTT disabled with a visible startup line, pygame missing → PTT disabled, coach unaffected).

## 8. Testing

- **RaceState:** fed synthetic tick dicts (session_reader precedent) — lap-boundary detection, gap-history recording, roster mapping, snapshot shape.
- **Calls:** unit tests over synthetic gap histories — fire/no-fire thresholds, episode re-arm, once-per-race semantics, corner-loss attribution on constructed per-corner deltas.
- **RadioBudget:** spacing + once-per-episode property tests; PTT exemption.
- **Speaker priority:** extended fake-engine tests — priority beats pending, in-progress never interrupted, latest-wins within tier.
- **Intents:** exact-string tests (nudges precedent) — transcript in, answer line out.
- **No hardware or network in the suite:** fake mic buffers, fake STT, fake API client, fake engines throughout (speaker's fake-engine precedent). Kokoro/whisper model loads are import-guarded so the suite runs without the models present.

## 9. Deferred / fast-follows

- Fuel/pit-window call (needs fuel-burn estimation) — first fast-follow after v1.
- Two-tier model routing (escalation to a larger model for strategy reasoning) — v1 is Haiku-class only.
- Barge-in (interrupting in-progress speech for PTT answers) — v1 keeps the never-interrupt rule.
- Crew Chief coexistence decision — per strategy, decided post-Surface-2; nothing here precludes it.
- Wake-word or open-mic — PTT only, by design (radio discipline).

## 10. Success criteria

- Stage A: the founder hears the neural voice on the next practice drive; failure on any machine degrades to SAPI, silently logged.
- Stage B: in the next official race, the engineer makes its sparse calls correctly (no overload, no wrong-direction gap claims) — validated against the session JSONL.
- Stage C: a mid-race "what's the gap" answers in ≤2s; an open strategy question gets a grounded Claude answer in ≤4s; network loss never mutes the fast path.
- The leading metric stays the strategy's: official-race volume goes up because starting a race no longer feels blind or alone.
