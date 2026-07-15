# Consumer-Grade UX + Friend Packaging — Design

**Date:** 2026-07-15
**Status:** Spec for post-Fable execution (plan to be written from this; a cheaper model executes). Written inside the Fable window per the v3 addendum §9 allocation.
**Inputs:** `docs/reviews/2026-07-13-pullup-review.md` (UX audit: "the missing 20% is the consumer layer", ranked top-5), `docs/race-engineer-v3-confidence-arc.md` §7 (friend package = rig installer: voice coach + watcher + tray). Founder framing: "something my friend could run with minimal guidance from me."
**Success test:** friend #1 goes from URL (or installer) to their first debrief without messaging the founder.

Two workstreams, one spec. A ships before B; B reuses A's copy.

---

## Workstream A — the consumer surface (hosted app)

### A1. Landing / Start page (pull-up #1 — biggest friction)

New first page in nav: **"Start"** (replaces Race Debrief as the default landing).

- Three sentences on what Race Engineer is, in product voice: never start blind, never race alone, every race makes you smarter.
- **Two entry paths, visually distinct:** "I just raced — debrief it" (→ Race Debrief page, with the IBT-location explainer inline) and "I'm about to race — brief me" (→ Race Briefing page).
- **Sample debrief button** (A3) — see the product before uploading anything.
- Status strip: watcher last-scan time when running locally ("telemetry watcher: last scan 2m ago"), app version (git short SHA), host mode vs guest mode.
- The "where is my IBT file" explainer lives HERE (with the default `Documents\iRacing\telemetry` path shown), not buried in Guide.

### A2. Glossary as a component (pull-up #2)

- `app/components/glossary.py`: a single `TERMS: dict[str, str]` (IBT, iRating, SR, SoF, split, reference lap, pace-deserved position, clean lap, representative lap, Garage 61, practice PB, implied iRating, prep ledger) + `help_text(term)` accessor.
- Every page passes `help=glossary.help_text("SoF")` at the FIRST widget/metric where a term appears (Streamlit native tooltips — no custom UI).
- A rendered glossary section at the bottom of Guide, generated from the same dict (single source of truth; exact-string test pins that every TERMS key renders there).

### A3. Sample debrief (pull-up #3)

- A **synthetic `RaceNarrative` JSON with fictional driver names**, committed to the repo (`app/assets/sample_narrative.json`) — no real-driver privacy question, works with zero API/key/upload.
- Built once by a dev script from a real narrative shape (field renamed, times lightly fuzzed), then frozen; a round-trip test pins `RaceNarrative.from_dict(sample)` so model evolution can't silently break it.
- Surfaced in two places: the Start page button, and the Race Debrief page empty state ("no race yet? see what a debrief looks like").
- Renders the deterministic markdown only (no AI call) + one canned AI-debrief example as static text, labeled as an example.

### A4. Guide restructure (pull-up #4)

- Split into two documents-in-one-page: **"Getting started" (guest-facing, top)** — upload flow, what the pages do, glossary; **"Host reference" (founder-facing, bottom, collapsed expander)** — DB layout, CLI paths, tailscale, Toolbox. Nothing founder-ops-related visible uncollapsed.
- Nav order becomes: Start, Race Debrief, Race Briefing, Driver Profile, Guide, Scouting, Lap Coaching, Toolbox.
- Toolbox stays host-only as-is (existing gating), label unchanged.

### A5. Error taxonomy + progress phases (pull-up #5)

- `app/components/errors.py`: `explain(exc) -> str` mapping known failure classes to consumer sentences — corrupt/unreadable IBT ("this file doesn't look like an iRacing telemetry file"), non-race IBT on the debrief page ("this is a practice session — the Debrief page wants a race; Lap Coaching handles practice"), missing `ANTHROPIC_API_KEY` ("AI debrief isn't configured on this host — the deterministic debrief below is complete"), Data API down ("iRacing's data service isn't answering; telemetry-only debrief shown"), upload too large. Unknown exceptions get the generic line + a collapsed traceback expander (host debugging without scaring guests).
- Long operations get **phased status** (`st.status` with staged updates), replacing bare spinners: debrief = parsing telemetry → fetching official results → reconstructing the race → (optional) engineer's debrief; briefing already has phases — align its wording.
- Exact-string tests for every mapped message (nudges precedent).

### A6. Small fixes riding along (from the pull-up's additional findings)

- Hardcoded founder telemetry path → `TELEMETRY_DIR` env var, default `~/Documents/iRacing/telemetry`; the folder picker no longer silently gated.
- "AI Metadata" expander (model/tokens) becomes host-only (hidden unless host mode).
- Driver Profile page gets the watcher-freshness line ("history updated: last scan X ago / how to run a scan").
- Nav labels keep emoji but the page headers state the page's job in one plain sentence (already true on Briefing; audit the rest).

**A-testing:** all copy pinned by exact-string tests; `errors.explain` unit-tested per exception class; sample-narrative round-trip test; no business logic added to pages (components carry the logic).

---

## Workstream B — the friend package (rig installer + tray)

Target user: a sim-racing friend with iRacing installed, comfortable double-clicking an installer, NOT comfortable with git/venvs. Delivers the live voice coach + watcher locally; debriefs stay on the founder's hosted app (v3 §7: no auth, no per-user server data, no phone-home in v1).

### B1. The tray app (the package's face)

- `scripts/tray_app.py` using **pystray** (new dep): persistent tray icon with menu — Start/Stop Voice Coach, Start/Stop Watcher, Open Race Engineer (browser to the hosted URL or localhost), Status (watcher last scan, coach running/stopped), Quit.
- Composes `ManagedProcess` + existing launch/stop logic **unchanged** (v3 §7 commitment). No console windows: processes spawn detached exactly as the Toolbox does today.
- **Coupling tests pin every tray-spawned command against the target CLI's parser** (the 2026-07-14 Toolbox flag-drift lesson, now a standing rule).
- Coach remains OFF by default at tray start — starting it is a deliberate click (the founder's locked decision extends to friends).
- Absorbs the launcher's job on the founder rig too (tray replaces desktop .bat as the recommended start; .bats remain).

### B2. The installer

- **Not frozen binaries** (pyirsdk shared memory, SAPI voice, and numpy/scipy make PyInstaller fragile and huge). Instead a **scripted bootstrap**: `install-race-engineer.bat` → `scripts/setup_rig.py`:
  1. Checks/installs `uv` (official installer, user scope),
  2. Clones/updates the repo to `%LOCALAPPDATA%\RaceEngineer`,
  3. `uv sync`,
  4. Writes a minimal `.env` interactively (iRacing creds optional — coach + watcher work without them; without creds races are captured PARTIAL and refilled on the hosted app, documented behavior),
  5. Creates Start-menu/desktop shortcuts to the tray app (existing `install_shortcut.py` pattern),
  6. Launches the tray + opens a "you're set up" page (the Guide's getting-started anchor).
- One-page friend instructions in the Guide: install → drive practice (watcher builds your references silently) → toggle the coach when you want a voice → upload race IBTs to the hosted app for debriefs.
- Update story v1: tray menu "Check for updates" = `git pull` + `uv sync` + restart (honest and simple; auto-update deferred).

### B3. Explicitly out of scope (v1)

Auth/multi-user server data; telemetry phone-home/history sync (arc for friends waits for it — v3 §7); coach voice/persona changes; oval plausibility ceiling; Mac/Linux (pyirsdk+SAPI are Windows-bound).

**B-testing:** tray↔CLI coupling tests; `setup_rig.py` pure helpers (env writing, path resolution) unit-tested; process/browser/installer I/O manual by convention. Manual acceptance: a fresh Windows user account goes installer → tray → coach speaks a radio check, without touching a terminal.

---

## Sequencing (post-Fable execution order)

1. A5 errors/phases + A2 glossary (pure components, immediate payoff on every page)
2. A1 Start page + A3 sample debrief
3. A4 Guide restructure + A6 ride-alongs
4. Friend funnel opens here: `tailscale funnel` + URL to friend #1 (hosted-only experience)
5. B1 tray → B2 installer → friend #1 upgrades to the rig package
6. Measure: does friend #1 reach a debrief unaided; does the founder's official-race volume move (the metric)

## Open items (decide at plan time, not blockers)

- Start-page copy: draft in the plan, founder reviews wording before merge (product voice is his).
- Sample narrative source: fuzz the Oulton race vs hand-author; either satisfies A3.
- Tray icon asset (any checkered-flag glyph; placeholder fine).
- Whether `install-race-engineer.bat` also offers the G61 reference import (probably v1.1).
