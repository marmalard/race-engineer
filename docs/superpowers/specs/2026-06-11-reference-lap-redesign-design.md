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
- **Corners are labels, not foundations.** Loss regions are annotated with names from the track DB. Crew Chief landmarks (already imported for 30 tracks) are the primary segmentation — their distance ranges define named segments directly. The heuristic corner detector is demoted to a fallback annotator for unmapped tracks. A small manual edit path lets the user correct a name/extent once, persistently.
- **Numbering policy:** turn numbers are shown only where landmark data actually provides them. The system never invents numbering (sequential detected-corner IDs presented as turn numbers is what destroyed trust before).
- **Diagnosis stays deterministic.** Within a loss region: braking onset delta, minimum speed delta, throttle-on delta vs the reference — existing comparator logic anchored to real segments. AI synthesis narrates only numbers that exist; the prompt cites them and the UI displays them so every claim is auditable.

## Resolution and alignment (the G61 problem)

- G61 CSVs and IBT files have different sample rates and distance references. Both go through the same normalizer to the same 1 m grid; comparison code is source-agnostic.
- **Offset correction:** after resampling, cross-correlate the speed traces and shift the reference by the best-fit offset to reconcile disagreement between G61's distance zero and iRacing's start/finish line. Deterministic and unit-testable.

## Track map — making "turn 12" mean something

GPS lat/lon is already extracted by the IBT parser. From any lap the track outline is drawn (Plotly):

- **Debrief:** track map with loss regions colored by time lost — spatial answer before prose. Hover/click for detail.
- **Briefing:** each corner card includes a mini-map with the corner highlighted, plus a verbal anchor chain: name + turn number (when real) + position ("~4.4 km in") + what-comes-before ("after the back-section esses"). On day one at an unfamiliar track the map and anchors carry the reference; as the track is learned, names take over.

## Briefing format ("Prep this combo")

Per-corner cards built from the reference lap's telemetry — braking point, gear, minimum speed, throttle-on point — i.e., data-derived, car-specific guidance no generic track guide can match. Layered on top:

- Claude web-search synthesis of community track guides (existing scouting pipeline): curbs, bumps, common mistakes, what the track punishes.
- Pace context from the iRacing Data API (existing): competitive window, target ladder.

## Ingestion — the watcher

- v1: scan `C:\Users\antho\Documents\iRacing\telemetry\` for new IBT files on app launch (true background daemon deferred).
- For each new file: read car/track from session YAML → find matching reference lap → run debrief → store result.
- Streamlit becomes the **viewer** (session history, debriefs, briefings). The upload form remains only as a manual fallback.
- Live between-lap coaching via pyirsdk is explicitly deferred to a later phase, after the prep/debrief loop proves itself in weekly use.

## Deleted / demoted / kept

| Disposition | What |
|---|---|
| Deleted as foundation | Corner detection driving analysis (replaced by loss regions) |
| Demoted | Corner detector → fallback annotator; upload form → manual fallback |
| Kept | IBT parser, normalizer, comparator internals, track DB, Crew Chief seeder, scouting web-synthesis, pace context, unit toggle |

This is a re-plumbing, not a rewrite.

## Validation gate (trust contract)

Before building features on the new analysis: take real laps (Spa, Road America) plus G61 exports of the same sessions, and reconcile this tool's deltas against what G61 displays. Fix until they match. This check becomes a **permanent fixture-based test**, not a one-off.

## Staging

1. **Trust rebuild** — reference lap store, delta-trace loss regions, G61 import + alignment, validation gate, landmark-based annotation, track map.
2. **Briefing** — corner cards from reference lap + existing scouting synthesis + pace context.
3. **Watcher** — folder scan on launch, auto-debrief, Streamlit as viewer.
4. **(Later)** Live between-lap coaching via pyirsdk.

## Out of scope

- Garage 61 API automation (API too limited).
- Real-time mid-corner coaching, setup optimization, social features (per PRD "What This Is Not").
- Phase 3 longitudinal features (driver profile, cross-session "did you fix it") — designed-for but not part of this redesign.
