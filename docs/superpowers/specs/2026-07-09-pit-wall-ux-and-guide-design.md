# Pit Wall UX Pass + In-App Guide — Design

**Date:** 2026-07-09
**Status:** Approved (theme direction and layout chosen via visual companion; scope confirmed)
**Context:** Surface 1 shipped 2026-07-06 and is being handed to the first friend tester. The app looks default-Streamlit; the user guide exists nowhere. Two additions: a "Pit Wall" visual identity across the app shell, and an in-app Guide page for friend onboarding + founder reference.

## Decisions (confirmed 2026-07-09)

| Question | Decision |
|---|---|
| Guide home | In-app Guide page (one URL to send a friend) |
| UX scope | Whole app shell (theme, sidebar, nav) + Race Debrief layout polish; Scouting/Coaching inherit theme only |
| Design direction | **Pit Wall** — dark carbon `#0e1116`, panels `#161b24`, telemetry-green accent `#00d17a`, monospace numerals (Consolas stack, no external font fetch) |
| Race Debrief layout | **Story Stack** — same vertical order as today, properly dressed; chat stays at the bottom |

## Goals

- The app reads as a racing engineering tool, not a default Streamlit demo.
- A friend can onboard themselves from the Guide page: record telemetry → find the IBT → upload → debrief → chat → export.
- Display-only change: zero edits to `core/` analysis logic; the one small `core` exception is a `render_narrative_markdown` header-suppression flag (below). Full suite stays green.

## Non-Goals

- No layout rewrite of Scouting Report or Lap Coaching (theme inherits).
- No logo assets (text wordmark only), no auth, no mobile-specific work beyond what the stack layout gives for free.

## Design

### 1. Theme (`app/components/theme.py` + `.streamlit/config.toml`)

- `config.toml` gains a `[theme]` block: `base="dark"`, `primaryColor="#00d17a"`, `backgroundColor="#0e1116"`, `secondaryBackgroundColor="#161b24"`, `textColor="#e6e9ee"`.
- `theme.py` exports:
  - Color constants (`ACCENT`, `PANEL`, `BORDER`, `TEXT_MUTED`, `RIVAL_BLUE`, …) — single source for CSS and charts.
  - `apply_theme()` — injects one shared CSS block via `st.markdown`: metric cards (panel background, border, radius; monospace values; small-caps labels), small-caps section headers with green rule (`.re-section`), sidebar styling, buttons/chat polish. Prefer custom classes; keep `data-testid` selectors to the few stable ones (metrics) since they're version-sensitive.
  - `chart_layout(**overrides) -> dict` — pure dict for Plotly `update_layout`: transparent paper, `#10151d` plot bg, muted grid, consistent margins/height. Testable without Streamlit.
  - `section_header(title)` — renders a `.re-section` label.
  - `brand_sidebar()` — "RACE ENGINEER" wordmark + tagline "Never start blind. Never race alone."
- `streamlit_app.py`: call `apply_theme()` once after `set_page_config`; sidebar brand block; nav becomes 🏁 Race Debrief · 📖 Guide · 🔭 Scouting Report · ⏱ Lap Coaching (label→page mapping so emoji changes can't break dispatch).

### 2. Race Debrief polish (`app/pages/race_debrief.py`)

- Header strip (track · config · car · series · date · SoF) as a styled div; the four `st.metric`s pick up card styling from the theme CSS.
- Charts use `chart_layout()`; player trace `ACCENT`, rivals in muted blues.
- Narrative sections introduced by `section_header(...)`; the deterministic markdown renders **without its own H1/header block** — new keyword `render_narrative_markdown(narrative, include_header=True)` in `core/race/render.py` (default keeps export/tests unchanged; the page passes `False` because the strip + metrics already show that data). One new test.
- AI debrief inside `st.container(border=True)` under a "🎙 ENGINEER'S DEBRIEF" section label; chat below unchanged.

### 3. Guide page (`app/pages/guide.py`)

- Display-only; markdown constants + `render_guide_page()`. Nav position #2.
- **Get your first debrief** (friend onboarding): 1) record telemetry — press **Alt+L** once the session loads (Garage 61 agent users: it auto-records); must be an official race; 2) find the `.ibt` in `Documents\iRacing\telemetry` (newest file after the race); 3) upload → Analyze; 4) read the debrief, ask follow-ups in chat, export markdown.
- **How to read your debrief** honest-notes box: the engineer only knows this race's data and says so when asked beyond it; what pace-deserved position means; why time-lost numbers are labeled estimates.
- **Founder reference**: what each page does; where data lives (`races.db`, `race_cache/`, `tracks.db`, `reference_laps.db`); CLI tools (`scripts/live_coach.py`, `scripts/record_race_fixture.py`); Tailscale serve/funnel commands.

## Implementation plan (inline, 3 commits)

1. `feat: pit wall theme — config, theme component, branded shell` (config.toml, theme.py, streamlit_app.py)
2. `feat: race debrief page polish — pit wall dress on the story stack` (race_debrief.py, render.py flag + test)
3. `feat: in-app guide page — friend onboarding + founder reference` (guide.py, nav already wired in commit 1)

Verification per commit: full suite green (429 + any new render test), page import checks; final manual look via the running app (Streamlit hot-reloads pages; theme config change needs an app restart, which I control — the app currently runs as a background task).

## Watch items

- Streamlit `data-testid` selectors can drift across versions — CSS kept minimal and custom-class-first so breakage degrades to "unstyled", never broken function.
- Guide screenshots deliberately omitted (they'd stale fast); revisit after friend #1's onboarding feedback.
