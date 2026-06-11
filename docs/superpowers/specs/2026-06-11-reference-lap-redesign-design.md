# Reference Lap Redesign — Design Spec

**Date:** 2026-06-11
**Status:** Approved by user, pending implementation planning

## Why (diagnosis)

Phases 1–2 are built and tested, but the tool isn't used. The user's diagnosis:

- **Trust broken:** heuristic corner detection finds ~7 of 14 corners, sequential numbering doesn't match real turn numbers, and downstream numbers (deltas, time lost) inherited the doubt. No external ground truth — comparing the driver to themselves can't show whether their best is itself slow.
- **Friction too high:** the upload-an-IBT Streamlit flow never became a habit. iRacing already writes IBT files to disk automatically; the upload step is friction the data source doesn't require.
- The self-referential coaching *concept* was not the problem ("told me nothing new" was explicitly rejected as a failure mode).

Two architectural bets are reversed by this design:

1. Heuristic corner detection as the foundation → replaced by reference-lap delta analysis; corners become annotation.
2. Upload-based UI as the surface → replaced by automatic ingestion from the telemetry folder; Streamlit becomes a viewer.

## Product shape — two moments, one spine

The tool serves exactly two moments:

- **"Prep this combo"** (deliberate, ~once per race week): user selects car + track, optionally imports a Garage 61 CSV of a reference lap. Output: a briefing built from the reference lap's actual data plus Claude web-synthesis of community track guides plus iRacing API pace context.
- **"Debrief my session"** (automatic, every session): new IBT files are picked up from the iRacing telemetry folder, analyzed against the combo's reference lap, and the debrief is presented without any upload step.

The spine connecting them is the **reference lap per car/track combo**, stored once, used by both. The briefing describes what the reference lap does; the debrief shows where the driver diverges from it. Same numbers, same corner names, both directions — this symmetry is what rebuilds trust.

## Reference lap store

- One reference lap per car/track combo, stored in SQLite alongside the existing track DB.
- **Sources, in priority order:**
  1. Garage 61 CSV export, imported manually during combo prep. The right reference is a clean lap **1–2 seconds faster than the driver**, not an alien lap — G61 lets the user choose the pace. (The G61 API was investigated and is too limited to automate this; manual CSV once per combo is acceptable friction.)
  2. The driver's own best lap from any prior session at the combo (automatic fallback).
- Reference laps are normalized through the same pipeline as IBT laps and stored in normalized form.

## Analysis rebuild — delta trace first, corners as annotation

- **Primary primitive: the time-delta trace.** Driver lap and reference lap are resampled to the same 1 m distance grid (existing normalizer). Cumulative time delta is computed; **loss regions** are contiguous spans where the delta grows. Time lost per region is arithmetic on the trace — correct regardless of corner detection.
- **Corners are labels, not foundations.** Loss regions are annotated with names from the track DB, seeded from two open sources: **lovely-track-data** (CC BY-NC-SA; 185 iRacing track configs with named corner ranges as track-position fractions; track IDs align with IBT session YAML naming) and **Crew Chief landmarks** (already imported, 30 tracks, distance ranges in meters). Where both exist, prefer whichever has been manually verified; the heuristic corner detector is demoted to a fallback annotator for tracks in neither source. A small manual edit path lets the user correct a name/extent once, persistently.
- **Numbering policy:** turn numbers are shown only where landmark data actually provides them. The system never invents numbering (sequential detected-corner IDs presented as turn numbers is what destroyed trust before).
- **Diagnosis stays deterministic.** Within a loss region: braking onset delta, minimum speed delta, throttle-on delta vs the reference — existing comparator logic anchored to real segments. AI synthesis narrates only numbers that exist; the prompt cites them and the UI displays them so every claim is auditable.

## Resolution and alignment (the G61 problem)

- G61 CSVs and IBT files have different sample rates and distance references. Both go through the same normalizer to the same 1 m grid; comparison code is source-agnostic.
- **Offset correction:** after resampling, cross-correlate the speed traces and shift the reference by the best-fit offset to reconcile disagreement between G61's distance zero and iRacing's start/finish line. Deterministic and unit-testable.

## Track map — making "turn 12" mean something

Two complementary map sources:

- **Official iRacing track maps** via the Data API `track/assets` endpoint: layered SVGs (`active`, `start-finish`, and a dedicated `turns` layer with official turn numbers), fetched once per track and cached locally. This is the briefing map — professionally drawn, official numbering, every track iRacing sells. The endpoint also returns official track-description HTML (`detail_copy`), which is injected into the scouting prompt as grounding text.
- **GPS-derived outline** from lap telemetry (lat/lon already parsed): used on the debrief to color loss regions by time lost — spatial answer before prose. (Projecting telemetry onto the official SVG requires per-track offset calibration; the GPS outline avoids that for v1.)

Briefing corner cards include the mini-map with the corner highlighted, plus a verbal anchor chain: name + official turn number (from the `turns` layer / track data) + position ("~4.4 km in") + what-comes-before ("after the back-section esses"). On day one at an unfamiliar track the map and anchors carry the reference; as the track is learned, names take over.

## Briefing format ("Prep this combo")

Per-corner cards built from the reference lap's telemetry — braking point, gear, minimum speed, throttle-on point — i.e., data-derived, car-specific guidance no generic track guide can match. Layered on top:

- Claude web-search synthesis of community track guides (existing scouting pipeline): curbs, bumps, common mistakes, what the track punishes.
- Pace context from the iRacing Data API (existing): competitive window, target ladder.

## Ingestion — the watcher

- The watcher is a **separate process** (`watcher.py`), not in-UI code: it watches/scans `C:\Users\antho\Documents\iRacing\telemetry\` for new IBT files, runs the analysis core, and writes results to SQLite. This makes it UI-framework-independent, immune to UI reruns, and the natural home for live telemetry later. v1 may start as scan-on-launch invoked by the same entry point.
- For each new file: read car/track from session YAML → find matching reference lap → run debrief → store result.
- The UI becomes a read-only **viewer** polling SQLite (session history, debriefs, briefings). The upload form remains only as a manual fallback.
- Live between-lap coaching via pyirsdk is explicitly deferred to a later phase, after the prep/debrief loop proves itself in weekly use.

## Tech choices — OSS-first, nothing sacred

Principle (user-stated): no loyalty to past tech or surfaces; borrow from existing open-source work and open data wherever it's better. Decisions from the 2026-06-11 ecosystem survey:

- **Keep our IBT parser** (numpy-strided, faster than alternatives, tested on real files) — but add **pyirsdk** (MIT, actively maintained) as a cross-validation oracle in tests (assert our channels match `irsdk.IBT.get_all()` on fixtures) and as the live-telemetry bridge for the later phase.
- **Replace `core/benchmark/iracing_api.py` with the `iracingdataapi` package** (MIT, maintained, v1.4.4 Mar 2026): covers everything ours does plus `result_search_series` (population pace by iRating bracket), rate-limit tracking, and maintained auth.
- **UI: stay on Streamlit for now.** With the watcher as a separate process, Streamlit + `st.fragment(run_every=…)` polling covers between-lap cadence. **NiceGUI is the named successor**, migrated to only when a concrete trigger fires: wanting watcher+UI in one process, push notifications, sub-second live updates, or Streamlit state-juggling eating real time. FastAPI+React, Tauri/Electron, and TUI options were evaluated and rejected for a single-user local tool.
- **Adopt lovely-track-data + iRacing `track/assets`** as open data sources (see Analysis and Track map sections).
- **Repos to read, not port:** POWERRRRRRRR/simracing-ai-coach (MIT — LLM provider abstraction, reference-lap file format), SeriousOldMan/Simulator-Controller (NC license — coaching delivery design only), tariknz/irdashies (sector-delta UI conventions, live-attach architecture), Crew Chief source (between-lap "record → compare → speak" loop).
- **Confirmed dead ends:** no open repository of fast-lap telemetry exists (G61 manual CSV is the community standard); VRS datapacks are paywalled/proprietary; OSM raceway geometry is unlabeled and worse than our GPS traces.

## Deleted / demoted / kept

| Disposition | What |
|---|---|
| Deleted as foundation | Corner detection driving analysis (replaced by loss regions) |
| Demoted | Corner detector → fallback annotator; upload form → manual fallback |
| Replaced | Hand-rolled `iracing_api.py` → `iracingdataapi` package |
| Kept | IBT parser (+ pyirsdk validation oracle), normalizer, comparator internals, track DB, Crew Chief seeder (joined by lovely-track-data), scouting web-synthesis, pace context, unit toggle, Streamlit (as viewer) |

This is a re-plumbing, not a rewrite.

## Validation gate (trust contract)

Before building features on the new analysis: take real laps (Spa, Road America) plus G61 exports of the same sessions, and reconcile this tool's deltas against what G61 displays. Fix until they match. This check becomes a **permanent fixture-based test**, not a one-off.

## Staging

1. **Trust rebuild** — reference lap store, delta-trace loss regions, G61 import + alignment, validation gate, segment annotation (lovely-track-data + Crew Chief), pyirsdk parser cross-validation, track maps (official SVG + GPS outline).
2. **Briefing** — corner cards from reference lap + existing scouting synthesis (grounded with official track `detail_copy`) + pace context via `iracingdataapi`.
3. **Watcher** — separate `watcher.py` process, auto-debrief to SQLite, Streamlit as polling viewer.
4. **(Later)** Live between-lap coaching via pyirsdk.

## Out of scope

- Garage 61 API automation (API too limited).
- Real-time mid-corner coaching, setup optimization, social features (per PRD "What This Is Not").
- Phase 3 longitudinal features (driver profile, cross-session "did you fix it") — designed-for but not part of this redesign.
- UI framework migration (NiceGUI) — deferred until a named trigger fires.
- VRS datapacks, OSM track geometry, TUMFTM racing lines — evaluated, rejected or deferred.
