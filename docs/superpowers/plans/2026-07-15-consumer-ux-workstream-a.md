# Consumer UX Workstream A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the consumer surface of the 2026-07-15 consumer-UX spec (workstream A, sequencing steps 1–3): glossary + error taxonomy components, `st.navigation` app shell, state-aware Start page, sample debrief, Guide restructure, Toolbox radio transcript, and the A6 ride-alongs.

**Architecture:** Pure display components in `app/components/` carry all new logic (glossary, errors, host detection, sample loading) so they are unit-testable; pages stay display-only per CLAUDE.md. Nav becomes data (`app/navigation.py` `NAV_SPEC`) built into `st.Page` objects — coupling-tested like the Toolbox spawn commands. One small core change: `ingest_race` gains an optional `on_phase` progress callback (no logic change).

**Tech Stack:** Python 3.14, Streamlit ≥1.54 (`st.navigation`, `st.Page`, `st.segmented_control`, `st.status` all available), pytest.

**Spec:** `docs/superpowers/specs/2026-07-15-consumer-ux-packaging-design.md` (workstream A; A7 corner mini-map is phase 2 — NOT in this plan; workstream B tray/installer NOT in this plan).

---

## CRITICAL execution constraints

1. **The production app may be running from the main checkout while the founder races.** ALL work happens in a git worktree (Task 0). NEVER check out a branch in `C:\Users\antho\Documents\Coding\personal-race-engineer` itself — Streamlit hot-reloads edited files into the live app.
2. **Edit tool only** for file edits. NEVER PowerShell `Get-Content`/`Set-Content` on repo text files (PS 5.1 mangles UTF-8 — happened twice).
3. **No double quotes inside git commit messages** (PS 5.1 here-string quoting bug — the commit silently fails). Single quotes are fine. Check `git log -1` after any commit.
4. **Merging is NOT part of this plan.** After the final task, stop and use superpowers:finishing-a-development-branch. After any future merge the founder must restart the app (running Streamlit serves new page code against old cached modules) and kill stray `launch.py` processes first.
5. Tests run with the MAIN repo's venv from the WORKTREE directory:
   `powershell: Set-Location <worktree>; C:\Users\antho\Documents\Coding\personal-race-engineer\.venv\Scripts\python.exe -m pytest -q`
   (the worktree has no `.venv`; deps are identical). All pytest commands below assume this pattern.
6. Start-page copy and all new product-voice strings are DRAFTS — flag them for founder review at handoff (spec open item: product voice is his). Do not block on it.

---

### Task 0: Worktree + branch setup

**Files:** none (git only)

- [ ] **Step 1: Create the worktree**

```powershell
Set-Location C:\Users\antho\Documents\Coding\personal-race-engineer
git worktree add ..\race-engineer-ux-a -b consumer-ux-a
Set-Location ..\race-engineer-ux-a
```

Expected: `Preparing worktree (new branch 'consumer-ux-a')`. All subsequent tasks run in `C:\Users\antho\Documents\Coding\race-engineer-ux-a`.

- [ ] **Step 2: Verify the test suite is green at baseline**

Run: `C:\Users\antho\Documents\Coding\personal-race-engineer\.venv\Scripts\python.exe -m pytest -q`
Expected: 703 passed (skips vary with local fixtures — the worktree lacks gitignored fixtures, so the skip count will be HIGHER than the main checkout; that is expected and fine). Record the pass/skip counts; every later task must not reduce the pass count.

---

### Task 1: Glossary component (A2)

**Files:**
- Create: `app/components/glossary.py`
- Test: `tests/test_glossary.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_glossary.py`:

```python
"""Glossary component (A2) — two-tier vocabulary, single source of truth."""

import pytest

from app.components.glossary import TERMS, glossary_markdown, help_text


class TestTerms:
    def test_every_term_has_nonempty_help(self):
        for name, term in TERMS.items():
            assert term.help.strip(), name

    def test_tiers_are_only_1_or_2(self):
        assert set(t.tier for t in TERMS.values()) <= {1, 2}

    def test_spec_terms_present(self):
        # The A2 spec list, verbatim.
        for name in [
            "IBT", "iRating", "SR", "SoF", "split", "reference lap",
            "pace-deserved position", "clean lap", "representative lap",
            "Garage 61", "practice PB", "implied iRating", "prep ledger",
        ]:
            assert name in TERMS, name

    def test_platform_terms_are_tier_1(self):
        # Tier 1 = iRacing's own vocabulary (design-language rule 2).
        for name in ["iRating", "SR", "SoF", "split"]:
            assert TERMS[name].tier == 1, name


class TestHelpText:
    def test_returns_the_term_help(self):
        assert help_text("SoF") == TERMS["SoF"].help

    def test_unknown_term_raises(self):
        # A typo in a page should fail a test, not ship an empty tooltip.
        with pytest.raises(KeyError):
            help_text("not-a-term")


class TestGlossaryMarkdown:
    def test_every_term_renders(self):
        md = glossary_markdown()
        for name, term in TERMS.items():
            assert f"**{name}**" in md, name
            assert term.help in md, name

    def test_two_tier_headings(self):
        md = glossary_markdown()
        assert "**iRacing's words**" in md
        assert "**Our words**" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `...python.exe -m pytest tests/test_glossary.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.components.glossary'`

- [ ] **Step 3: Implement the component**

Create `app/components/glossary.py`:

```python
"""Two-tier glossary (consumer-UX design-language rule 2).

Tier 1 = iRacing's own vocabulary: used plainly in copy, tooltip only
(spelling out the sim's own words reads as patronizing to members).
Tier 2 = OUR coinages + telemetry domain: plain-language first use per
screen PLUS tooltip — nobody knows what we mean by these until told.

Single source of truth: pages pass help=help_text("SoF") at a term's
first widget/metric per page; the Guide renders the whole dict via
glossary_markdown() (exact-string tested).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    tier: int  # 1 = platform vocabulary, 2 = product/analysis vocabulary
    help: str


TERMS: dict[str, Term] = {
    # --- Tier 1: iRacing's own vocabulary --------------------------------
    "iRating": Term(1, (
        "iRacing's skill rating — it moves after every official race "
        "based on who you finished ahead of and behind."
    )),
    "SR": Term(1, (
        "Safety Rating — iRacing's incident-based licence metric. "
        "Clean races raise it, contact and off-tracks lower it."
    )),
    "SoF": Term(1, (
        "Strength of Field — the average iRating of the drivers in your "
        "split. Higher SoF = tougher race and bigger rating swings."
    )),
    "split": Term(1, (
        "When enough drivers register, iRacing divides them into splits "
        "by iRating — you only race the drivers in your split."
    )),
    # --- Tier 2: our coinages + telemetry domain --------------------------
    "IBT": Term(2, (
        "iRacing's telemetry file (.ibt). Press Alt+L in the car to "
        "record; files land in Documents\\iRacing\\telemetry."
    )),
    "reference lap": Term(2, (
        "The lap you're compared against — your fastest clean lap for "
        "the combo, or a Garage 61 import when one exists."
    )),
    "clean lap": Term(2, (
        "A racing lap with no incident, no pit visit, and not under "
        "caution — the laps that count when we talk about pace."
    )),
    "representative lap": Term(2, (
        "A clean lap within 110% of your best for the combo — so "
        "out-laps and crawl laps don't pollute your numbers."
    )),
    "pace-deserved position": Term(2, (
        "Where your clean-lap pace alone should have finished you. The "
        "gap between that and your actual finish is what the debrief "
        "digs into."
    )),
    "implied iRating": Term(2, (
        "The iRating whose typical pace matches your lap time at this "
        "track — your speed translated onto the ladder."
    )),
    "practice PB": Term(2, (
        "Your fastest clean, complete practice lap for a combo — "
        "promoted automatically by the telemetry watcher."
    )),
    "prep ledger": Term(2, (
        "What you've actually done at this week's combo: sessions, "
        "clean laps, and how your session best is trending."
    )),
    "Garage 61": Term(2, (
        "A community telemetry service many sim racers run — its lap "
        "exports can serve as reference laps here."
    )),
}


def help_text(name: str) -> str:
    """Tooltip text for a term.

    Raises KeyError on unknown names — a typo in a page should fail a
    test, not ship an empty tooltip.
    """
    return TERMS[name].help


def glossary_markdown() -> str:
    """The Guide's glossary section, generated from TERMS."""
    tier1 = [n for n, t in TERMS.items() if t.tier == 1]
    tier2 = [n for n, t in TERMS.items() if t.tier == 2]
    lines = ["**iRacing's words** (the sim's own vocabulary):", ""]
    lines += [f"- **{n}** — {TERMS[n].help}" for n in tier1]
    lines += ["", "**Our words** (what Race Engineer means by them):", ""]
    lines += [f"- **{n}** — {TERMS[n].help}" for n in tier2]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `...python.exe -m pytest tests/test_glossary.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add app/components/glossary.py tests/test_glossary.py
git commit -m 'feat(ux): two-tier glossary component (A2)'
git log -1 --oneline
```

---

### Task 2: Error taxonomy component (A5a)

**Files:**
- Create: `app/components/errors.py`
- Test: `tests/test_errors_component.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_errors_component.py`:

```python
"""Error taxonomy (A5) — consumer sentences for known failure classes.

Exact-string tests (nudges precedent): the copy IS the product.
"""

import struct

from app.components.errors import (
    API_DOWN,
    GENERIC,
    NO_AI_KEY,
    NOT_A_RACE,
    NOT_TELEMETRY,
    explain,
)
from core.race.ingest import RaceIngestError


class TestConstants:
    def test_not_telemetry_exact(self):
        assert NOT_TELEMETRY == (
            "This file doesn't look like an iRacing telemetry (.ibt) "
            "file. Telemetry lands in Documents\\iRacing\\telemetry "
            "after a session with recording on (Alt+L in the car)."
        )

    def test_not_a_race_exact(self):
        assert NOT_A_RACE == (
            "This is a practice or qualifying session — the Debrief "
            "page wants an official race. The Lap Coaching page handles "
            "practice telemetry."
        )

    def test_no_ai_key_exact(self):
        assert NO_AI_KEY == (
            "The AI debrief isn't configured on this host — the race "
            "story above is complete without it."
        )

    def test_api_down_exact(self):
        assert API_DOWN == (
            "iRacing's data service didn't answer for this race — "
            "showing what your telemetry alone supports. Re-open this "
            "race later to fill in official results."
        )

    def test_generic_exact(self):
        assert GENERIC == (
            "Something went wrong analyzing this file. The technical "
            "details are below if the host wants to dig in."
        )


class TestExplain:
    def test_non_race_ingest_error_maps_to_not_a_race(self):
        # Message shape from core/race/ingest.py::load_race_ibt
        exc = RaceIngestError(
            "This IBT is not an official race session "
            "(EventType='Practice', SubSessionID=0)."
        )
        assert explain(exc) == NOT_A_RACE

    def test_other_ingest_errors_pass_through(self):
        exc = RaceIngestError("No race simsession in results payload")
        assert explain(exc) == "No race simsession in results payload"

    def test_parse_failures_map_to_not_telemetry(self):
        for exc in [
            ValueError("File too small for header: 12 bytes"),
            TypeError("Expected Path or bytes, got int"),
            struct.error("unpack_from requires a buffer"),
            EOFError(),
        ]:
            assert explain(exc) == NOT_TELEMETRY, type(exc).__name__

    def test_unknown_exceptions_map_to_generic(self):
        assert explain(RuntimeError("boom")) == GENERIC
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `...python.exe -m pytest tests/test_errors_component.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `app/components/errors.py`:

```python
"""Consumer-facing failure sentences (A5 error taxonomy).

One place turns known failure classes into a plain sentence a guest can
act on; unknown failures get GENERIC and the page shows the traceback in
a collapsed host expander. Message constants are exact-string tested
(nudges precedent) — edit copy here, not in pages.

Note: upload-too-large is enforced client-side by Streamlit itself
(.streamlit/config.toml maxUploadSize 400) — it never reaches Python,
so it has no constant here.
"""

from __future__ import annotations

import struct

from core.race.ingest import RaceIngestError

NOT_TELEMETRY = (
    "This file doesn't look like an iRacing telemetry (.ibt) file. "
    "Telemetry lands in Documents\\iRacing\\telemetry after a session "
    "with recording on (Alt+L in the car)."
)
NOT_A_RACE = (
    "This is a practice or qualifying session — the Debrief page wants "
    "an official race. The Lap Coaching page handles practice telemetry."
)
NO_AI_KEY = (
    "The AI debrief isn't configured on this host — the race story "
    "above is complete without it."
)
API_DOWN = (
    "iRacing's data service didn't answer for this race — showing what "
    "your telemetry alone supports. Re-open this race later to fill in "
    "official results."
)
GENERIC = (
    "Something went wrong analyzing this file. The technical details "
    "are below if the host wants to dig in."
)

# Failure classes the IBT parse layer raises on corrupt/wrong files
# (core/telemetry/ibt_parser.py raises ValueError/TypeError; struct and
# EOF errors surface from truncated binaries).
_PARSE_ERRORS = (ValueError, TypeError, struct.error, EOFError)


def explain(exc: Exception) -> str:
    """Map a failure to its consumer sentence; GENERIC when unknown."""
    if isinstance(exc, RaceIngestError):
        if "not an official race" in str(exc):
            return NOT_A_RACE
        return str(exc)  # ingest messages are already user-facing
    if isinstance(exc, _PARSE_ERRORS):
        return NOT_TELEMETRY
    return GENERIC
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `...python.exe -m pytest tests/test_errors_component.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add app/components/errors.py tests/test_errors_component.py
git commit -m 'feat(ux): error taxonomy component with consumer sentences (A5)'
git log -1 --oneline
```

---

### Task 3: Host helpers component (A6 foundation)

**Files:**
- Create: `app/components/host.py`
- Test: `tests/test_host_component.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_host_component.py`:

```python
"""Host helpers — TELEMETRY_DIR env override, watcher freshness reads."""

from pathlib import Path

from app.components.host import (
    relative_time,
    telemetry_dir,
    watcher_last_activity,
)


class TestTelemetryDir:
    def test_env_var_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TELEMETRY_DIR", str(tmp_path))
        assert telemetry_dir() == tmp_path

    def test_default_is_documents_iracing_telemetry(self, monkeypatch):
        monkeypatch.delenv("TELEMETRY_DIR", raising=False)
        expected = Path.home() / "Documents" / "iRacing" / "telemetry"
        assert telemetry_dir() == expected


class TestWatcherLastActivity:
    def test_none_when_no_log(self, tmp_path):
        assert watcher_last_activity(run_dir=tmp_path) is None

    def test_mtime_when_log_exists(self, tmp_path):
        log = tmp_path / "telemetry-watcher.log"
        log.write_text("scan ok", encoding="utf-8")
        assert watcher_last_activity(run_dir=tmp_path) == log.stat().st_mtime


class TestRelativeTime:
    def test_buckets_exact(self):
        now = 1_000_000.0
        assert relative_time(now - 5, now) == "just now"
        assert relative_time(now - 240, now) == "4m ago"
        assert relative_time(now - 7200, now) == "2h ago"
        assert relative_time(now - 3 * 86400, now) == "3d ago"

    def test_future_timestamps_clamp_to_just_now(self):
        assert relative_time(2_000_000.0, 1_000_000.0) == "just now"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `...python.exe -m pytest tests/test_host_component.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `app/components/host.py`:

```python
"""Host-vs-guest helpers and watcher freshness reads.

The app serves two audiences from one process: the founder's host
machine (telemetry folder, background processes) and guests over
tailscale. Everything host-only keys off telemetry_dir() existing —
previously a hardcoded founder path in two pages (spec A6).
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUN_DIR = _REPO_ROOT / "data" / "run"
_DEFAULT_TELEMETRY = Path.home() / "Documents" / "iRacing" / "telemetry"


def telemetry_dir() -> Path:
    """The iRacing telemetry folder (TELEMETRY_DIR env var overrides)."""
    override = os.environ.get("TELEMETRY_DIR")
    return Path(override) if override else _DEFAULT_TELEMETRY


def is_host() -> bool:
    """True when this process runs on the machine with the sim."""
    return telemetry_dir().exists()


def watcher_running() -> bool:
    """True when the telemetry watcher's managed process is alive."""
    from core.live.process_control import ManagedProcess

    # Command is irrelevant for a status read — liveness comes from the
    # PID file in run_dir (same name the Toolbox/launcher use).
    return ManagedProcess(
        "telemetry-watcher", ["status-only"], run_dir=_RUN_DIR
    ).is_running()


def watcher_last_activity(run_dir: Path | None = None) -> float | None:
    """mtime of the watcher log (last output); None when it never ran."""
    log = (run_dir or _RUN_DIR) / "telemetry-watcher.log"
    try:
        return log.stat().st_mtime
    except OSError:
        return None


def relative_time(then_s: float, now_s: float) -> str:
    """'just now' / '4m ago' / '2h ago' / '3d ago'."""
    delta = max(0, int(now_s - then_s))
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `...python.exe -m pytest tests/test_host_component.py -q`
Expected: all pass. (`watcher_running` is process I/O — untested by repo convention, like ManagedProcess spawn.)

- [ ] **Step 5: Commit**

```powershell
git add app/components/host.py tests/test_host_component.py
git commit -m 'feat(ux): host helpers - TELEMETRY_DIR env var + watcher freshness (A6)'
git log -1 --oneline
```

---

### Task 4: Radio-transcript formatter (A6b)

**Files:**
- Modify: `core/live/feed.py` (append to end of file)
- Test: `tests/test_feed.py` (append new test class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feed.py` (do not touch existing tests; add imports as needed at the top — `from core.live.feed import format_transcript_line` plus existing imports):

```python
class TestFormatTranscriptLine:
    """Exact-string per event type (nudges precedent).

    Events without a 't' timestamp render '--:--:--' — used here so the
    expected strings are timezone-independent.
    """

    def test_connect_with_reference(self):
        line = format_transcript_line({
            "event": "connect", "track": "Okayama", "car": "MX-5",
            "reference": {"source": "g61", "lap_time": 98.412,
                          "driver": "R. Mott"},
        })
        assert line == (
            "--:--:--  \U0001f399 On air — Okayama · MX-5 · "
            "reference 1:38.412 loaded"
        )

    def test_connect_without_reference(self):
        line = format_transcript_line({
            "event": "connect", "track": "Okayama", "car": "MX-5",
            "reference": None,
        })
        assert line == (
            "--:--:--  \U0001f399 On air — Okayama · MX-5 · "
            "no reference — lap one sets the baseline"
        )

    def test_lap(self):
        line = format_transcript_line({
            "event": "lap", "lap": 5, "lap_time": 143.501,
            "delta": 2.5, "improved": False, "dirty": False,
        })
        assert line == "--:--:--  \U0001f3c1 Lap 5 — 2:23.501 (+2.5s)"

    def test_lap_dirty_gets_asterisk_clause(self):
        line = format_transcript_line({
            "event": "lap", "lap": 6, "lap_time": 142.900,
            "delta": 1.9, "dirty": True,
        })
        assert line == (
            "--:--:--  \U0001f3c1 Lap 6 — 2:22.900 (+1.9s) "
            "— track limits, won't count"
        )

    def test_baseline(self):
        line = format_transcript_line({
            "event": "baseline", "lap": 1, "lap_time": 145.2,
        })
        assert line == "--:--:--  \U0001f3c1 Lap 1 — 2:25.200, baseline set"

    def test_prompt(self):
        line = format_transcript_line({
            "event": "prompt", "text": "Coming up — carry it flat",
        })
        assert line == "--:--:--  \U0001f399 Coming up — carry it flat"

    def test_discard(self):
        line = format_transcript_line({
            "event": "discard", "reason": "reset",
            "speech": "Reset — scratch that lap.",
        })
        assert line == "--:--:--  ↩ Reset — scratch that lap."

    def test_invalid(self):
        line = format_transcript_line({
            "event": "invalid", "lap": 3,
            "speech": "That lap won't count — data's incomplete.",
        })
        assert line == (
            "--:--:--  ⚠ That lap won't count — data's incomplete."
        )

    def test_dirty_baseline_skipped(self):
        line = format_transcript_line({
            "event": "dirty_baseline_skipped",
            "speech": "That lap had track limits — I won't use it as the baseline. Give me a clean one.",
        })
        assert line == (
            "--:--:--  ⚠ That lap had track limits — I won't use it as "
            "the baseline. Give me a clean one."
        )

    def test_schedule_is_machinery_and_hidden(self):
        assert format_transcript_line({"event": "schedule"}) == ""

    def test_unknown_event_falls_back_to_name(self):
        assert format_transcript_line({"event": "mystery"}) == (
            "--:--:--  · mystery"
        )

    def test_timestamp_renders_as_local_clock(self):
        import re

        line = format_transcript_line({
            "event": "prompt", "text": "x",
            "t": "2026-07-15T18:30:00+00:00",
        })
        assert re.match(r"^\d{2}:\d{2}:\d{2}  ", line)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `...python.exe -m pytest tests/test_feed.py -q`
Expected: new tests FAIL (`ImportError: cannot import name 'format_transcript_line'`); existing feed tests still pass once import is fixed to only-new-name failing — if collection errors, temporarily confirm via `-k TestFormatTranscriptLine`.

- [ ] **Step 3: Implement the formatter**

Append to `core/live/feed.py` (also add `from datetime import datetime` to the imports at the top):

```python
# --- Radio-transcript formatter (consumer-UX A6b) -------------------------
# One line per session-log event (core/live/session_log.py JSONL). Pure
# formatter — reused by the Toolbox activity feed and, later, the tray
# status view and the iPad feed. Empty string = machinery, don't show.

_ICON_RADIO = "\U0001f399"
_ICON_LAP = "\U0001f3c1"


def _fmt_clock(iso: str | None) -> str:
    """UTC ISO timestamp -> local HH:MM:SS ('--:--:--' when absent)."""
    if not iso:
        return "--:--:--"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return "--:--:--"


def _fmt_lap_time(seconds: float) -> str:
    """Seconds -> m:ss.mmm (kept local: core/live must not import
    core/briefing for a 2-line format)."""
    m = int(seconds // 60)
    return f"{m}:{seconds - 60 * m:06.3f}"


def format_transcript_line(event: dict) -> str:
    """One radio-transcript line for a live-session JSONL event."""
    clock = _fmt_clock(event.get("t"))
    kind = event.get("event", "")
    if kind == "connect":
        ref = event.get("reference")
        tail = (
            f"reference {_fmt_lap_time(ref['lap_time'])} loaded"
            if ref
            else "no reference — lap one sets the baseline"
        )
        return (
            f"{clock}  {_ICON_RADIO} On air — {event.get('track', '?')} · "
            f"{event.get('car', '?')} · {tail}"
        )
    if kind == "lap":
        delta = event.get("delta")
        delta_txt = f" ({delta:+.1f}s)" if delta is not None else ""
        dirty_txt = " — track limits, won't count" if event.get("dirty") else ""
        return (
            f"{clock}  {_ICON_LAP} Lap {event.get('lap', '?')} — "
            f"{_fmt_lap_time(event['lap_time'])}{delta_txt}{dirty_txt}"
        )
    if kind == "baseline":
        return (
            f"{clock}  {_ICON_LAP} Lap {event.get('lap', '?')} — "
            f"{_fmt_lap_time(event['lap_time'])}, baseline set"
        )
    if kind == "prompt":
        return f"{clock}  {_ICON_RADIO} {event.get('text', '')}"
    if kind == "discard":
        return f"{clock}  ↩ {event.get('speech', 'Lap discarded.')}"
    if kind in ("invalid", "dirty_baseline_skipped"):
        return f"{clock}  ⚠ {event.get('speech', '')}"
    if kind == "schedule":
        return ""  # prompt-schedule dump — machinery, not radio
    return f"{clock}  · {kind}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `...python.exe -m pytest tests/test_feed.py -q`
Expected: all pass (old + new).

- [ ] **Step 5: Commit**

```powershell
git add core/live/feed.py tests/test_feed.py
git commit -m 'feat(live): radio-transcript formatter for session-log events (A6b)'
git log -1 --oneline
```

---

### Task 5: Sample debrief assets + loader (A3)

**Files:**
- Create: `app/assets/sample_narrative.json`
- Create: `app/assets/sample_debrief.md`
- Create: `app/components/sample.py`
- Test: `tests/test_sample_debrief.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sample_debrief.py`:

```python
"""Sample debrief (A3) — frozen synthetic narrative, round-trip pinned.

If RaceNarrative's model evolves, this test breaks loudly instead of
the Start page's sample button breaking silently.
"""

from app.components.sample import (
    load_sample_debrief_text,
    load_sample_narrative,
)
from core.race.models import RaceNarrative


class TestSampleNarrative:
    def test_loads_and_round_trips(self):
        narrative = load_sample_narrative()
        rebuilt = RaceNarrative.from_dict(narrative.to_dict())
        assert rebuilt == narrative

    def test_is_clearly_synthetic(self):
        n = load_sample_narrative()
        # Sentinel ids: can never collide with a real captured race.
        assert n.header.subsession_id == 0
        assert n.header.cust_id == 0

    def test_has_the_shapes_the_page_renders(self):
        n = load_sample_narrative()
        assert len(n.position_timeline) >= 10
        assert n.lap1 is not None
        assert len(n.gaps) == 2
        assert len(n.incidents) == 1
        assert n.pace is not None
        # Pace honesty (2026-07-15): both views present in the sample.
        assert n.pace.pace_rank is not None
        assert n.pace.all_lap_rank is not None
        assert n.attribution is not None
        assert n.attribution.summary_lines

    def test_narrative_markdown_renders(self):
        from core.race.render import render_narrative_markdown

        md = render_narrative_markdown(load_sample_narrative())
        assert len(md) > 200


class TestSampleDebriefText:
    def test_loads_nonempty_markdown(self):
        text = load_sample_debrief_text()
        assert len(text) > 300
        assert "Sam" in text  # addresses the fictional driver
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `...python.exe -m pytest tests/test_sample_debrief.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the frozen sample narrative JSON**

Create `app/assets/sample_narrative.json` (hand-authored per the spec's open item; fictional drivers, plausible MX-5-at-Okayama times ~1:38s):

```json
{
  "header": {
    "subsession_id": 0,
    "cust_id": 0,
    "driver_name": "Sam Vega",
    "track_id": 166,
    "track_name": "Okayama International Circuit",
    "track_config": "Full Course",
    "car_name": "Mazda MX-5 Cup",
    "series_name": "Production Car Challenge (sample race)",
    "session_date": "2026-07-04 19:00:00",
    "sof": 1350,
    "field_size": 11,
    "start_position": 8,
    "finish_position": 5,
    "incidents": 5,
    "irating_old": 1289,
    "irating_new": 1322
  },
  "position_timeline": [
    {"lap": 1, "position": 7},
    {"lap": 2, "position": 7},
    {"lap": 3, "position": 6},
    {"lap": 4, "position": 8},
    {"lap": 5, "position": 8},
    {"lap": 6, "position": 7},
    {"lap": 7, "position": 7},
    {"lap": 8, "position": 6},
    {"lap": 9, "position": 6},
    {"lap": 10, "position": 6},
    {"lap": 11, "position": 5},
    {"lap": 12, "position": 5}
  ],
  "lap1": {
    "grid_position": 8,
    "position_after_lap1": 7,
    "position_after_lap2": 7,
    "place_changes": [
      {
        "lap": 1,
        "lap_dist_pct": 0.12,
        "corner_name": "Turn 1",
        "from_position": 8,
        "to_position": 7
      }
    ]
  },
  "gaps": [
    {
      "cust_id": 901,
      "display_name": "Riley Mott",
      "finish_position": 4,
      "gaps": [
        {"lap": 1, "gap_s": 4.1},
        {"lap": 2, "gap_s": 3.8},
        {"lap": 3, "gap_s": 3.5},
        {"lap": 4, "gap_s": 10.9},
        {"lap": 5, "gap_s": 10.2},
        {"lap": 6, "gap_s": 9.0},
        {"lap": 7, "gap_s": 7.6},
        {"lap": 8, "gap_s": 6.1},
        {"lap": 9, "gap_s": 4.7},
        {"lap": 10, "gap_s": 3.2},
        {"lap": 11, "gap_s": 1.9},
        {"lap": 12, "gap_s": 0.8}
      ]
    },
    {
      "cust_id": 902,
      "display_name": "Dana Kwan",
      "finish_position": 6,
      "gaps": [
        {"lap": 1, "gap_s": 1.5},
        {"lap": 2, "gap_s": 1.2},
        {"lap": 3, "gap_s": 0.9},
        {"lap": 4, "gap_s": -6.5},
        {"lap": 5, "gap_s": -5.9},
        {"lap": 6, "gap_s": -4.4},
        {"lap": 7, "gap_s": -3.0},
        {"lap": 8, "gap_s": 1.1},
        {"lap": 9, "gap_s": 0.4},
        {"lap": 10, "gap_s": -0.6},
        {"lap": 11, "gap_s": -1.4},
        {"lap": 12, "gap_s": -2.2}
      ]
    }
  ],
  "incidents": [
    {
      "lap": 4,
      "lap_dist_pct": 0.55,
      "corner_name": "Hairpin",
      "delta_incidents": 2,
      "position_before": 6,
      "position_after": 8,
      "time_lost_estimate_s": 7.4
    }
  ],
  "stints": [
    {
      "start_lap": 1,
      "end_lap": 12,
      "median_clean_pace": 98.412,
      "trend_s": -0.3
    }
  ],
  "cautions": [],
  "pace": {
    "median_clean_lap": 98.412,
    "best_lap": 97.821,
    "consistency_stdev": 0.41,
    "clean_lap_count": 9,
    "pace_rank": 4,
    "ranked_drivers": 9,
    "unranked_drivers": 2,
    "median_all_lap": 98.93,
    "all_lap_rank": 5,
    "all_lap_ranked_drivers": 11
  },
  "attribution": {
    "irating_old": 1289,
    "irating_new": 1322,
    "irating_delta": 33,
    "pace_deserved_position": 4,
    "actual_position": 5,
    "incident_time_lost_s": 7.4,
    "lap1_net_positions": 1,
    "summary_lines": [
      "Your clean pace ranked P4 of 9 ranked drivers (9 clean laps).",
      "The Hairpin contact on lap 4 cost about 7.4s and two places - you spent five laps winning them back.",
      "Net: finished one place behind where your pace deserved."
    ]
  },
  "key_rivals": [901, 902]
}
```

- [ ] **Step 4: Create the canned example debrief text**

Create `app/assets/sample_debrief.md` (engineer voice; the page labels it as an example — DRAFT for founder voice review):

```markdown
Good race to bank, Sam. P8 to P5 with the fourth-best clean pace in an
eleven-car field — the finishing position undersold the speed, and
that's the whole story of this one.

The headline is lap 4 at the Hairpin. Contact cost you about seven and
a half seconds and two places, and you spent the next five laps buying
those places back one by one. Your pace says P4 was on the table:
Riley Mott finished eight tenths up the road after you'd closed ten
seconds on them since lap 4. Without the contact, that's your position.

Two things worth keeping from this race. First, the recovery drive was
genuinely quick — your stint trend was negative, meaning you got faster
as the race went on while the field held steady. Second, the start:
you took a place into Turn 1 and held it, which is exactly the low-risk
opening lap that keeps races like this alive.

The one thing to work on is the move that led to the contact. You were
P6 with pace in hand — the overtake didn't need to happen at the
Hairpin on lap 4. With nine clean laps of P4 pace, patience there turns
this P5 into a P4, maybe better.

Net on the day: +33 iRating. The speed is ahead of the results — keep
racing and the results catch up.
```

- [ ] **Step 5: Create the loader component**

Create `app/components/sample.py`:

```python
"""Sample debrief assets (A3) — see the product before uploading.

The narrative is synthetic (fictional drivers, hand-authored times,
sentinel subsession/cust ids of 0) and frozen in app/assets/; a
round-trip test pins RaceNarrative.from_dict against it so model
evolution can't silently break the sample button.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.race.models import RaceNarrative

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
SAMPLE_NARRATIVE_PATH = _ASSETS / "sample_narrative.json"
SAMPLE_DEBRIEF_PATH = _ASSETS / "sample_debrief.md"


def load_sample_narrative() -> RaceNarrative:
    """The frozen synthetic race, as a full RaceNarrative."""
    data = json.loads(SAMPLE_NARRATIVE_PATH.read_text(encoding="utf-8"))
    return RaceNarrative.from_dict(data)


def load_sample_debrief_text() -> str:
    """The canned example AI debrief (static markdown, no API call)."""
    return SAMPLE_DEBRIEF_PATH.read_text(encoding="utf-8")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `...python.exe -m pytest tests/test_sample_debrief.py -q`
Expected: all pass. If `rebuilt == narrative` fails, the JSON has a field-name typo vs the dataclasses in `core/race/models.py` — fix the JSON, never the models.

- [ ] **Step 7: Commit**

```powershell
git add app/assets/sample_narrative.json app/assets/sample_debrief.md app/components/sample.py tests/test_sample_debrief.py
git commit -m 'feat(ux): frozen sample debrief narrative + loader (A3)'
git log -1 --oneline
```

---

### Task 6: `ingest_race` progress callback (A5b core support)

**Files:**
- Modify: `core/race/ingest.py` (signature of `ingest_race`, ~line 222)
- Test: `tests/test_race_ingest.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_race_ingest.py`:

```python
class TestOnPhaseCallback:
    def test_parsing_phase_fires_before_parse(self):
        import pytest

        from core.race.ingest import ingest_race

        labels = []
        with pytest.raises(Exception):
            ingest_race(b"not an ibt file", None, on_phase=labels.append)
        assert labels == ["Parsing telemetry..."]

    def test_callback_failure_never_breaks_ingest(self):
        import pytest

        from core.race.ingest import ingest_race

        def boom(_label):
            raise RuntimeError("progress display died")

        # The parse error should surface, NOT the callback's RuntimeError.
        with pytest.raises(Exception) as excinfo:
            ingest_race(b"not an ibt file", None, on_phase=boom)
        assert not isinstance(excinfo.value, RuntimeError)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `...python.exe -m pytest tests/test_race_ingest.py -q -k OnPhase`
Expected: FAIL — `TypeError: ingest_race() got an unexpected keyword argument 'on_phase'`.

- [ ] **Step 3: Implement the callback**

In `core/race/ingest.py`, change the `ingest_race` signature and add the phase hook (the existing body is unchanged except the two `_phase(...)` insertions):

```python
def ingest_race(
    source: Path | bytes,
    api,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    ibt_path_for_record: str = "",
    on_phase: Callable[[str], None] | None = None,
) -> RaceData:
    """Full ingestion: IBT + YAML + API (cached) -> RaceData.

    api is a LiveIRacingAPI/StubIRacingAPI or None. API failures degrade
    to a partial RaceData (results/lap_chart/driver_laps empty) with a
    warning — the page renders what the telemetry alone supports.
    on_phase (optional) receives coarse progress labels for st.status;
    a failing callback is swallowed — progress display never breaks
    ingestion.
    """

    def _phase(label: str) -> None:
        if on_phase is not None:
            try:
                on_phase(label)
            except Exception:  # noqa: BLE001 — display-only hook
                pass

    _phase("Parsing telemetry...")
    ibt, meta = load_race_ibt(source)
```

Then inside the existing `if api is not None:` block, add `_phase("Fetching official results...")` as its first line (immediately before the `try:` that wraps `_cached_fetch` of results.json).

`Callable` is already imported in this module (used by `_cached_fetch`) — verify, don't re-import.

- [ ] **Step 4: Run the full race-ingest suite**

Run: `...python.exe -m pytest tests/test_race_ingest.py -q`
Expected: all pass (pre-existing tests unaffected — the parameter is optional).

- [ ] **Step 5: Commit**

```powershell
git add core/race/ingest.py tests/test_race_ingest.py
git commit -m 'feat(race): optional on_phase progress callback in ingest_race (A5)'
git log -1 --oneline
```

---

### Task 7: Navigation registry + app shell (A0)

**Files:**
- Create: `app/navigation.py`
- Create: `app/pages/start.py` (STUB ONLY in this task — full page in Task 8; the nav registry needs the module to exist)
- Modify: `app/streamlit_app.py` (full rewrite, it's 74 lines)
- Modify: `app/components/theme.py` (CSS: un-hide + style the st.navigation nav)
- Test: `tests/test_navigation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_navigation.py`:

```python
"""Nav registry coupling tests (A0).

NAV_SPEC is the single source of truth for the shell. These tests pin:
(a) the grouping the spec mandates, (b) URL-path uniqueness (pages are
linkable), (c) that every module/function actually exists — a renamed
render function must fail HERE, not at app startup (the 2026-07-14
Toolbox flag-drift lesson applied to navigation).
"""

import importlib

from app.navigation import NAV_SPEC


class TestNavSpec:
    def test_groups_exact(self):
        assert [g for g, _ in NAV_SPEC] == ["Race", "Practice", "Help", "Host"]

    def test_race_group_pages_exact(self):
        race = dict(NAV_SPEC)["Race"]
        assert [p.title for p in race] == [
            "Start", "Race Debrief", "Race Briefing", "Driver Profile",
        ]

    def test_practice_group_pages_exact(self):
        practice = dict(NAV_SPEC)["Practice"]
        assert [p.title for p in practice] == ["Lap Coaching", "Scouting Report"]

    def test_url_paths_unique(self):
        paths = [p.url_path for _, specs in NAV_SPEC for p in specs]
        assert len(paths) == len(set(paths))

    def test_exactly_one_default_and_it_is_start(self):
        defaults = [
            p for _, specs in NAV_SPEC for p in specs if p.default
        ]
        assert len(defaults) == 1
        assert defaults[0].title == "Start"

    def test_every_render_function_exists(self):
        for _, specs in NAV_SPEC:
            for spec in specs:
                module = importlib.import_module(spec.module)
                func = getattr(module, spec.func)
                assert callable(func), f"{spec.module}.{spec.func}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `...python.exe -m pytest tests/test_navigation.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the Start page stub**

Create `app/pages/start.py` (Task 8 replaces the body; the stub keeps the nav test green in the meantime):

```python
"""Start page — the state-aware landing surface (built in Task 8)."""

from __future__ import annotations

import streamlit as st


def render_start_page() -> None:
    st.header("Start")
```

- [ ] **Step 4: Create the navigation registry**

Create `app/navigation.py`:

```python
"""Single source of truth for the app's pages and nav structure (A0).

NAV_SPEC is pure data (coupling-tested in tests/test_navigation.py);
build_pages() turns it into st.Page objects for st.navigation, and
page_for() gives pages a target for st.switch_page / st.page_link
without importing streamlit_app (no circular imports).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    title: str
    icon: str
    url_path: str
    module: str
    func: str
    default: bool = False


NAV_SPEC: list[tuple[str, list[PageSpec]]] = [
    (
        "Race",
        [
            PageSpec("Start", "\U0001f3c1", "start",
                     "app.pages.start", "render_start_page", default=True),
            PageSpec("Race Debrief", "\U0001f399", "debrief",
                     "app.pages.race_debrief", "render_race_debrief_page"),
            PageSpec("Race Briefing", "\U0001f4cb", "briefing",
                     "app.pages.briefing", "render_briefing_page"),
            PageSpec("Driver Profile", "\U0001f464", "profile",
                     "app.pages.driver_profile", "render_driver_profile_page"),
        ],
    ),
    (
        "Practice",
        [
            PageSpec("Lap Coaching", "⏱️", "coaching",
                     "app.pages.coaching", "render_coaching_page"),
            PageSpec("Scouting Report", "\U0001f52d", "scouting",
                     "app.pages.scouting", "render_scouting_page"),
        ],
    ),
    (
        "Help",
        [
            PageSpec("Guide", "\U0001f4d6", "guide",
                     "app.pages.guide", "render_guide_page"),
        ],
    ),
    (
        "Host",
        [
            PageSpec("Toolbox", "\U0001f39b", "toolbox",
                     "app.pages.toolbox", "render_toolbox_page"),
        ],
    ),
]


def _page(spec: PageSpec):
    import streamlit as st

    render = getattr(importlib.import_module(spec.module), spec.func)
    return st.Page(
        render,
        title=spec.title,
        icon=spec.icon,
        url_path=spec.url_path,
        default=spec.default,
    )


def build_pages() -> dict[str, list]:
    """NAV_SPEC -> {section: [st.Page, ...]} for st.navigation."""
    return {
        section: [_page(spec) for spec in specs]
        for section, specs in NAV_SPEC
    }


def page_for(url_path: str):
    """A st.Page for st.switch_page / st.page_link, by url path."""
    for _, specs in NAV_SPEC:
        for spec in specs:
            if spec.url_path == url_path:
                return _page(spec)
    raise KeyError(url_path)
```

- [ ] **Step 5: Run the nav tests**

Run: `...python.exe -m pytest tests/test_navigation.py -q`
Expected: all pass.

- [ ] **Step 6: Rewrite the entry point**

Replace the FULL contents of `app/streamlit_app.py` with:

```python
"""Race Engineer — Main Streamlit entry point (st.navigation shell)."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so absolute imports work.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

st.set_page_config(
    page_title="Race Engineer",
    page_icon="\U0001f3c1",
    layout="wide",
)

from app.components.theme import apply_theme, brand_sidebar  # noqa: E402
from app.navigation import build_pages  # noqa: E402

apply_theme()

# st.navigation renders its own grouped nav at the top of the sidebar;
# the brand block and units toggle follow below it.
pg = st.navigation(build_pages(), position="sidebar")

brand_sidebar()
st.sidebar.segmented_control(
    "Units", ["Metric", "Imperial"], key="unit_system", default="Metric"
)

pg.run()
```

(`unit_system` values stay "Metric"/"Imperial" — `app/pages/coaching.py:32` reads `st.session_state.get("unit_system", "Metric") == "Imperial"`, so a deselected segmented control (None) safely means metric.)

- [ ] **Step 7: Un-hide and style the st.navigation nav in the theme**

In `app/components/theme.py`, replace this block:

```css
/* Streamlit auto-builds a multipage nav from app/pages/*.py; those
   entries bypass our dispatch (no theme, no wiring) — hide it. Routing
   happens only through the radio below the brand block. */
[data-testid="stSidebarNav"] {{ display: none; }}
```

with:

```css
/* st.navigation renders the grouped nav here (A0 shell). It IS the
   router now — style it, don't hide it. (Before A0 this selector was
   display:none to suppress Streamlit's auto-discovered pages/ nav;
   st.navigation disables that auto-discovery entirely.) */
[data-testid="stSidebarNav"] a span {{
    font-family: {FONT_BODY};
    letter-spacing: 0.02em;
}}
[data-testid="stSidebarNav"] header,
[data-testid="stNavSectionHeader"] {{
    font-family: {FONT_DISPLAY};
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: 0.68rem;
    color: {TEXT_MUTED};
}}
```

(These selectors are additive — if a Streamlit version renames a testid, the nav still renders, just less styled. The load-bearing change is REMOVING `display: none`.)

- [ ] **Step 8: Smoke-run the shell from the worktree on a spare port**

The production app may hold 8501 — ALWAYS use 8502 from the worktree:

```powershell
C:\Users\antho\Documents\Coding\personal-race-engineer\.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py --server.port 8502 --server.headless true
```

Verify (browser or `Invoke-WebRequest http://localhost:8502` returning 200 + a manual look if possible): grouped sidebar nav (Race/Practice/Help/Host), Start is the default page, per-page URLs work (`http://localhost:8502/debrief` loads Race Debrief), units segmented control renders. Then stop the server (Ctrl+C / kill the process). If `st.switch_page`/nav misbehaves here, fix before proceeding — Task 8 depends on this shell.

- [ ] **Step 9: Run the full suite**

Run: `...python.exe -m pytest -q`
Expected: pass count ≥ baseline + new tests.

- [ ] **Step 10: Commit**

```powershell
git add app/navigation.py app/pages/start.py app/streamlit_app.py app/components/theme.py tests/test_navigation.py
git commit -m 'feat(ux): st.navigation app shell - grouped nav, page URLs, segmented units (A0)'
git log -1 --oneline
```

---

### Task 8: Start page (A1)

**Files:**
- Modify: `app/pages/start.py` (replace the Task 7 stub entirely)
- Test: `tests/test_start_page.py`

- [ ] **Step 1: Write the failing tests (pure helpers only — rendering is display-only by repo convention)**

Create `tests/test_start_page.py`:

```python
"""Start page pure helpers (A1). Rendering is display-only (untested
by repo convention); the state-aware pick logic is pure and tested."""

from core.race.race_store import StoredRaceMeta

from app.pages.start import pick_undebriefed


def _meta(subsession_id: int, track: str = "Okayama") -> StoredRaceMeta:
    return StoredRaceMeta(
        subsession_id=subsession_id, cust_id=1, driver_name="X",
        track_name=track, car="MX-5", series_name="S",
        session_date="2026-07-14 19:00:00", sof=1300,
        start_position=8, finish_position=5, incidents=2,
        irating_delta=12, created_at="2026-07-14 21:00:00",
    )


class TestPickUndebriefed:
    def test_empty_list_returns_none(self):
        assert pick_undebriefed([], lambda s, c: False) is None

    def test_first_meta_without_debrief_wins(self):
        # list_races is newest-first (created_at DESC) — position 0 is
        # the latest capture.
        metas = [_meta(3), _meta(2), _meta(1)]
        picked = pick_undebriefed(metas, lambda s, c: s == 3)
        assert picked is not None and picked.subsession_id == 2

    def test_all_debriefed_returns_none(self):
        metas = [_meta(2), _meta(1)]
        assert pick_undebriefed(metas, lambda s, c: True) is None

    def test_store_errors_do_not_propagate(self):
        def boom(_s, _c):
            raise RuntimeError("db locked")

        assert pick_undebriefed([_meta(1)], boom) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `...python.exe -m pytest tests/test_start_page.py -q`
Expected: FAIL — `ImportError: cannot import name 'pick_undebriefed'`.

- [ ] **Step 3: Implement the full Start page**

Replace the FULL contents of `app/pages/start.py` with:

```python
"""Start page — the state-aware landing surface (A1).

North-star down-payment: before showing entry paths, check state and
lead with the one thing that matters now — an undebriefed captured
race beats everything. Display-only: state checks are thin reads over
RaceStore and the watcher's run files; all copy is founder-reviewable
draft (product voice).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import streamlit as st

from app.components.host import (
    is_host,
    relative_time,
    telemetry_dir,
    watcher_last_activity,
    watcher_running,
)
from app.components.sample import load_sample_narrative
from app.components.theme import section_header
from app.navigation import page_for
from core.race.race_store import RaceStore, StoredRaceMeta

_REPO_ROOT = Path(__file__).resolve().parents[2]

# DRAFT copy — founder reviews wording before merge (spec open item).
INTRO = (
    "Your personal race engineer for iRacing. **Never start a race "
    "blind** — the briefing reads the field before you load in. "
    "**Never race alone** — the debrief and the voice coach sit on "
    "your pit wall. Every race you run makes them smarter."
)


def pick_undebriefed(
    metas: list[StoredRaceMeta], has_debrief
) -> StoredRaceMeta | None:
    """Newest captured race with no AI debrief yet, else None.

    has_debrief: callable(subsession_id, cust_id) -> bool. Pure logic
    with injected store access — unit-tested without a database. Any
    store error means no lead card, never a broken landing page.
    """
    try:
        for meta in metas:  # list_races is newest-first (created_at DESC)
            if not has_debrief(meta.subsession_id, meta.cust_id):
                return meta
    except Exception:  # noqa: BLE001 — landing page must always render
        return None
    return None


@st.cache_data(show_spinner=False)
def _app_version() -> str:
    """git short SHA of the running checkout; 'unknown' off-git."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=_REPO_ROOT, timeout=3,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — cosmetic only
        return "unknown"


def _open_stored_race(meta: StoredRaceMeta) -> None:
    store = RaceStore()
    st.session_state["race_narrative"] = store.get_race(
        meta.subsession_id, meta.cust_id
    )
    st.session_state["sample_mode"] = False


def render_start_page() -> None:
    st.header("Start")
    st.markdown(INTRO)

    # --- State-aware lead: the one thing that matters now ---------------
    store = RaceStore()
    try:
        lead = pick_undebriefed(
            store.list_races(),
            lambda s, c: store.get_debrief(s, c) is not None,
        )
    except Exception:  # noqa: BLE001 — empty state is a valid state
        lead = None

    if lead is not None:
        with st.container(border=True):
            st.markdown(
                f"**Your race at {lead.track_name} on "
                f"{lead.session_date[:10]} is ready to debrief** — "
                f"P{lead.finish_position}, {lead.irating_delta:+d} iR."
            )
            if st.button("Open the debrief", type="primary"):
                _open_stored_race(lead)
                st.switch_page(page_for("debrief"))

    # --- Entry paths (fallback for empty state + the guest path) --------
    section_header("Where to next")
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("**I just raced — debrief it**")
            st.caption(
                "Upload your race's telemetry file and the engineer "
                "reconstructs what actually happened."
            )
            st.page_link(page_for("debrief"), label="Go to Race Debrief")
    with col2:
        with st.container(border=True):
            st.markdown("**I'm about to race — brief me**")
            st.caption(
                "Field strength, pace targets, and where your rating "
                "says you'll run this week."
            )
            st.page_link(page_for("briefing"), label="Go to Race Briefing")

    with st.expander("Where is my telemetry (.ibt) file?"):
        st.markdown(
            "iRacing records telemetry when you press **Alt+L** in the "
            "car (the Garage 61 agent records automatically). Files "
            f"land in `{telemetry_dir()}` — after a race, the newest "
            ".ibt from your race session is the one to upload."
        )

    if st.button("See a sample debrief"):
        st.session_state["race_narrative"] = load_sample_narrative()
        st.session_state["sample_mode"] = True
        st.switch_page(page_for("debrief"))

    # --- Status strip ----------------------------------------------------
    parts = [
        f"v {_app_version()}",
        "host mode" if is_host() else "guest mode",
    ]
    if is_host():
        if watcher_running():
            last = watcher_last_activity()
            when = (
                relative_time(last, time.time()) if last else "just started"
            )
            parts.append(f"telemetry watcher: running, last activity {when}")
        else:
            parts.append("telemetry watcher: stopped")
    st.caption(" · ".join(parts))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `...python.exe -m pytest tests/test_start_page.py tests/test_navigation.py -q`
Expected: all pass (nav test now exercises the real render function import).

- [ ] **Step 5: Smoke-run and verify the two switch paths**

Same 8502 smoke command as Task 7 Step 8. Verify: Start renders intro + entry paths + expander + sample button + status caption; clicking "See a sample debrief" switches to the Debrief page (the sample narrative renders after Task 9 wires sample mode — at this point just confirm the page SWITCHES without exceptions). Stop the server.

- [ ] **Step 6: Commit**

```powershell
git add app/pages/start.py tests/test_start_page.py
git commit -m 'feat(ux): state-aware Start landing page (A1)'
git log -1 --oneline
```

---

### Task 9: Race Debrief page wiring (A5b phases, A5a errors, A2 tooltips, A3 sample mode, A6 host dir)

**Files:**
- Modify: `app/pages/race_debrief.py`

All edits below use the Edit tool against the current file (read it first). No new tests — every behavior change routes through components already tested in Tasks 1–6; the page stays display-only.

- [ ] **Step 1: Update imports and the telemetry-dir constant**

Add imports (after the existing `from app.components.theme import (...)` block):

```python
from app.components.errors import API_DOWN, NO_AI_KEY, explain
from app.components.glossary import help_text
from app.components.host import telemetry_dir
from app.components.sample import load_sample_debrief_text
```

Add `import traceback` to the stdlib imports. Delete the module constant `TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")` and replace its two uses (`TELEMETRY_DIR.exists()` and `_scan_race_ibts(str(TELEMETRY_DIR))`) with `telemetry_dir().exists()` and `_scan_race_ibts(str(telemetry_dir()))`. The import of `RaceIngestError` from `core.race.ingest` becomes unused — remove it from that import list (keep `ingest_race`).

- [ ] **Step 2: Thread on_phase through `_analyze`**

Change the signature and body:

```python
def _analyze(
    source, ibt_path: str, store: RaceStore, on_phase=None
) -> RaceNarrative:
    """Ingest -> narrative -> persist. Returns the narrative."""
    api = _make_api()
    try:
        data = ingest_race(source, api, on_phase=on_phase)
    finally:
        if api is not None:
            api.close()
    if on_phase is not None:
        on_phase("Reconstructing the race...")
    corners = _load_corners(
        data.track_id, data.track_directory, data.track_length_m, data.track_name
    )
    narrative = build_narrative(data, corners)
    store.save_race(narrative, ibt_file_path=ibt_path)
    return narrative
```

- [ ] **Step 3: Replace the analyze click handler (spinner -> st.status phases, error taxonomy)**

Replace the current `if source is not None and st.button("Analyze race", ...)` block with:

```python
        if source is not None and st.button("Analyze race", type="primary"):
            try:
                with st.status("Analyzing the race...", expanded=False) as status:
                    narrative = _analyze(
                        source, ibt_path, store,
                        on_phase=lambda label: status.update(label=label),
                    )
                    status.update(
                        label="Race reconstructed.", state="complete"
                    )
                st.session_state["race_narrative"] = narrative
                st.session_state["sample_mode"] = False
            except Exception as exc:
                logger.exception("_analyze failed")
                st.error(explain(exc))
                with st.expander("Technical details (for the host)"):
                    st.code(traceback.format_exc(), language=None)
```

- [ ] **Step 4: Sample-debrief empty state in the stored tab + sample_mode reset on open**

In `tab_stored`, replace `st.caption("No debriefed races yet.")` with:

```python
        if not stored:
            st.caption("No debriefed races yet.")
            if st.button("No race yet? See what a debrief looks like"):
                from app.components.sample import load_sample_narrative

                st.session_state["race_narrative"] = load_sample_narrative()
                st.session_state["sample_mode"] = True
                st.rerun()
```

And in the stored-race open button body, add `st.session_state["sample_mode"] = False` after setting `race_narrative`.

- [ ] **Step 5: Glossary tooltips at first occurrence (A2)**

- File uploader: `st.file_uploader("Race IBT file", type=["ibt"], help=help_text("IBT"))`
- iRating metric: `cols[1].metric("iRating", h.irating_new, f"{h.irating_new - h.irating_old:+d}", help=help_text("iRating"))` (leave the `"—"` fallback branch as `cols[1].metric("iRating", "—", help=help_text("iRating"))`)
- SoF metric: `cols[2].metric("SoF", h.sof, help=help_text("SoF"))`

- [ ] **Step 6: Error-taxonomy constants replace inline strings**

- The partial-data `st.warning(...)` ("Some race data was unavailable — ...") becomes `st.warning(API_DOWN)`.
- The no-key `st.info(...)` ("AI debrief unavailable — ANTHROPIC_API_KEY is not configured. ...") becomes `st.info(NO_AI_KEY)`.

- [ ] **Step 7: Sample mode renders the canned example instead of live AI**

At the bottom of `render_race_debrief_page`, replace the final `_render_debrief_and_chat(narrative, store)` call with:

```python
    if st.session_state.get("sample_mode"):
        section_header("\U0001f399 Engineer's debrief — example")
        st.info(
            "This is a sample race with fictional drivers — it shows "
            "what a debrief looks like before you upload your own. "
            "The engineer's text below is a canned example, not live AI."
        )
        with st.container(border=True):
            st.markdown(load_sample_debrief_text())
    else:
        _render_debrief_and_chat(narrative, store)
```

(Sample mode never touches RaceStore: the loader doesn't save, and this branch skips generate/chat/export — sentinel ids 0/0 can't be persisted by any path.)

- [ ] **Step 8: Smoke + full suite**

8502 smoke: upload nothing, open "Past debriefs" (empty in the worktree) → sample button renders the full sample debrief page with example section; a garbage `.ibt` (make one: `Set-Content -Path C:\tmp\fake.ibt -Value 'garbage'`) uploads and errors with the NOT_TELEMETRY sentence + collapsed details expander. Stop the server. Then:

Run: `...python.exe -m pytest -q`
Expected: pass count ≥ prior task.

- [ ] **Step 9: Commit**

```powershell
git add app/pages/race_debrief.py
git commit -m 'feat(ux): debrief page - status phases, error taxonomy, glossary tooltips, sample mode (A5/A2/A3)'
git log -1 --oneline
```

---

### Task 10: Toolbox radio transcript + host dir (A6b, A6)

**Files:**
- Modify: `app/pages/toolbox.py`

- [ ] **Step 1: Swap the hardcoded telemetry path**

In `app/pages/toolbox.py`: add `from app.components.host import telemetry_dir` to imports, delete `TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")`, and change the gate to `if not telemetry_dir().exists():`.

- [ ] **Step 2: Replace the raw-JSONL activity feed with the transcript**

Add `from core.live.feed import format_transcript_line` to imports. Replace the whole `events = _latest_session_events()` block (from `events = ...` through the `st.text(json.dumps(e)[:160])` line) with:

```python
    events = _latest_session_events(12)
    if events:
        st.caption("Latest session activity (newest last):")
        for e in events:
            line = format_transcript_line(e)
            if line:
                st.text(line)
        with st.expander("Raw events (host debugging)"):
            st.code(
                "\n".join(json.dumps(e) for e in events), language="json"
            )
```

Also change `_latest_session_events(n: int = 8)` default to `n: int = 12` (transcript lines are cheaper to scan than raw JSON). The `json` import stays (used in `_latest_session_events` and the raw expander).

- [ ] **Step 3: Verify the Toolbox coupling tests still pass**

Run: `...python.exe -m pytest tests/test_toolbox_commands.py tests/test_feed.py -q`
Expected: all pass (spawn commands untouched).

- [ ] **Step 4: Commit**

```powershell
git add app/pages/toolbox.py
git commit -m 'feat(ux): toolbox radio-transcript activity feed + TELEMETRY_DIR env (A6b/A6)'
git log -1 --oneline
```

---

### Task 11: Guide restructure (A4)

**Files:**
- Modify: `app/pages/guide.py` (render function + one constant tweak)

- [ ] **Step 1: Restructure the render function**

Add `from app.components.glossary import glossary_markdown` to imports. Replace `render_guide_page` with:

```python
def render_guide_page() -> None:
    st.header("Guide")
    st.markdown(
        "Everything you need to get your first debrief — hosting and "
        "command-line reference lives at the bottom, collapsed."
    )

    # --- Getting started (guest-facing) ----------------------------------
    section_header("Get your first debrief")
    st.markdown(_ONBOARDING)

    section_header("How to read your debrief")
    st.markdown(_HONEST_NOTES)

    section_header("Glossary")
    st.markdown(glossary_markdown())

    # --- Host reference (founder-facing, collapsed) -----------------------
    section_header("Host reference")
    with st.expander("For the host — running services, data, command line"):
        st.markdown(_RUNNING)
        st.markdown("**The rest of the app**")
        st.markdown(_FOUNDER_PAGES)
        st.markdown("**Where your data lives**")
        st.markdown(_FOUNDER_DATA)
        st.markdown("**Command line & hosting**")
        st.markdown(_FOUNDER_TOOLS)
```

(All markdown constants `_ONBOARDING`, `_HONEST_NOTES`, `_RUNNING`, `_FOUNDER_PAGES`, `_FOUNDER_DATA`, `_FOUNDER_TOOLS` stay exactly as they are.)

- [ ] **Step 2: Verify glossary renders in the Guide (coupling already tested)**

`tests/test_glossary.py::TestGlossaryMarkdown` pins every term into `glossary_markdown()`; the Guide renders that exact string — import-only convention covers the rest. Run: `...python.exe -m pytest tests/test_glossary.py -q` — pass.

- [ ] **Step 3: Commit**

```powershell
git add app/pages/guide.py
git commit -m 'feat(ux): guide restructure - guest-first, host reference collapsed, glossary section (A4)'
git log -1 --oneline
```

---

### Task 12: A6 ride-alongs (host-only AI metadata, profile freshness, page subtitles)

**Files:**
- Modify: `app/pages/coaching.py` (two spots)
- Modify: `app/pages/driver_profile.py` (freshness caption + subtitle)

- [ ] **Step 1: AI Metadata expander becomes host-only**

In `app/pages/coaching.py`: add `from app.components.host import is_host` to imports, then wrap the metadata expander (currently `with st.expander("AI Metadata"):` at ~line 230):

```python
            if is_host():
                with st.expander("AI Metadata"):
                    st.markdown(
                        f"- **Model**: {report.model_used}\n"
                        f"- **Input tokens**: {report.input_tokens:,}\n"
                        f"- **Output tokens**: {report.output_tokens:,}"
                    )
```

- [ ] **Step 2: Coaching page one-sentence job line**

Directly under `st.header("Lap Coaching")` (line ~37), add (or replace an existing subtitle markdown if one exists — read the file first):

```python
    st.markdown(
        "Upload practice telemetry — the engineer compares your laps to "
        "your best reference and shows where the time is."
    )
```

- [ ] **Step 3: Driver Profile freshness line + subtitle**

In `app/pages/driver_profile.py`: add imports

```python
import time

from app.components.host import (
    is_host,
    relative_time,
    watcher_last_activity,
    watcher_running,
)
```

Then directly under `st.title("Driver Profile")` add:

```python
    st.markdown(
        "What your races say about how you race — and which combos are "
        "race-ready."
    )
    if is_host():
        last = watcher_last_activity()
        if watcher_running():
            when = relative_time(last, time.time()) if last else "just started"
            st.caption(
                f"History updates automatically — telemetry watcher "
                f"running, last activity {when}."
            )
        elif last is not None:
            st.caption(
                f"History updates automatically — telemetry watcher last "
                f"active {relative_time(last, time.time())}. Start it from "
                f"the Toolbox to keep this fresh."
            )
        else:
            st.caption(
                "The telemetry watcher hasn't run yet — start it from "
                "the Toolbox and this page fills itself in."
            )
```

- [ ] **Step 4: Full suite**

Run: `...python.exe -m pytest -q`
Expected: pass count ≥ prior task, zero failures.

- [ ] **Step 5: Commit**

```powershell
git add app/pages/coaching.py app/pages/driver_profile.py
git commit -m 'feat(ux): A6 ride-alongs - host-only AI metadata, watcher freshness, page job lines'
git log -1 --oneline
```

---

### Task 13: Final verification + docs + handoff

**Files:**
- Modify: `CLAUDE.md` (status section)

- [ ] **Step 1: Full suite, recorded**

Run: `...python.exe -m pytest -q`
Expected output recorded verbatim (superpowers:verification-before-completion — no success claims without this output).

- [ ] **Step 2: Full manual smoke on 8502**

Start the app from the worktree (same command as Task 7 Step 8). Walk: Start (default, intro, entry paths, sample button, status strip) → sample debrief renders end-to-end with example section → nav groups + URLs (`/debrief`, `/briefing`, `/profile`, `/guide`, `/coaching`, `/scouting`, `/toolbox`) → Guide shows glossary + collapsed host expander → garbage-IBT upload shows the consumer error + details expander. Note anything broken; fix before proceeding. Stop the server.

- [ ] **Step 3: Update CLAUDE.md**

Add to the Current Status section of `CLAUDE.md` (after the Phase 4 block), using the Edit tool:

```markdown
**Consumer UX Workstream A** (complete, branch consumer-ux-a — spec docs/superpowers/specs/2026-07-15-consumer-ux-packaging-design.md, plan docs/superpowers/plans/2026-07-15-consumer-ux-workstream-a.md)
- [x] A2 glossary component (two-tier TERMS dict, help_text tooltips, Guide section generated from the same dict)
- [x] A5 error taxonomy (app/components/errors.py explain() + exact-string constants) + st.status phases through ingest_race(on_phase=...)
- [x] A0 st.navigation shell — app/navigation.py NAV_SPEC (coupling-tested), grouped nav Race/Practice/Help/Host, per-page URLs, segmented units control; theme un-hides stSidebarNav (it IS the router now)
- [x] A1 state-aware Start page (default landing): undebriefed-race lead card, two entry paths, IBT explainer, sample button, status strip (version/host-guest/watcher)
- [x] A3 frozen sample debrief (app/assets/sample_narrative.json sentinel ids 0/0 + canned sample_debrief.md; round-trip pinned; sample_mode never persists)
- [x] A4 Guide restructure (guest-first, host reference collapsed) + A6 ride-alongs (TELEMETRY_DIR env var via app/components/host.py, host-only AI metadata, watcher freshness lines) + A6b Toolbox radio-transcript feed (core/live/feed.py format_transcript_line, exact-string tested)
- [ ] Founder copy review: Start-page INTRO, sample_debrief.md, error sentences (all DRAFT product voice)
- [ ] A7 corner mini-map (phase 2, after top-5) + workstream B (tray + installer) — not started
```

- [ ] **Step 4: Commit + report**

```powershell
git add CLAUDE.md
git commit -m 'docs: consumer UX workstream A status'
git log --oneline master..HEAD
```

Then STOP and use superpowers:finishing-a-development-branch. Handoff notes for the founder MUST include: (1) copy strings are drafts for his review (Start INTRO, sample debrief text, error sentences); (2) after merging, kill stray launch.py processes and restart the app — running Streamlit serves new page code against old cached modules; (3) the brand block now sits BELOW the st.navigation nav (st.navigation always renders at the sidebar top; moving the wordmark above it needs st.logo or CSS — flagged as a design trade-off for his call).

---

## Self-review notes (done at plan time)

- **Spec coverage:** A0→Task 7, A1→Task 8, A2→Tasks 1/9/11, A3→Tasks 5/8/9, A4→Task 11, A5→Tasks 2/6/9, A6→Tasks 3/10/12, A6b→Tasks 4/10. Not covered by design: A7 (phase 2 per spec), workstream B (separate plan), briefing phase-wording alignment (already phased with adequate wording — no-op), upload-too-large sentence (enforced client-side by Streamlit config, documented in errors.py docstring).
- **Type consistency:** `help_text`/`glossary_markdown`/`TERMS` (T1↔T9/T11); `explain`/`NO_AI_KEY`/`API_DOWN` (T2↔T9); `telemetry_dir`/`is_host`/`watcher_running`/`watcher_last_activity`/`relative_time` (T3↔T8/T10/T12); `format_transcript_line` (T4↔T10); `load_sample_narrative`/`load_sample_debrief_text` (T5↔T8/T9); `on_phase` kwarg (T6↔T9); `page_for`/`build_pages`/`NAV_SPEC` (T7↔T8).
- **Known risks:** (1) `st.switch_page(page_for(...))` builds a fresh equivalent `st.Page` — expected to resolve to the same page; if Streamlit rejects it, fall back to `st.page_link` for the sample/lead buttons and note it. (2) Nav CSS testids may vary by Streamlit version — additive only, nav renders regardless. (3) The worktree has no gitignored fixtures — skip counts differ from the main checkout; compare pass counts, not skip counts.
