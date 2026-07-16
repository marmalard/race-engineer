# Friend Installer (B2) — Client Packaging + Update Channel

**Date:** 2026-07-16
**Status:** Approved (founder, 2026-07-16)
**Predecessors:** Desktop launcher (`2026-07-12-desktop-launcher-design.md`), System-tray app B1 (`2026-07-15-consumer-ux-packaging-design.md` §B1)

---

## 1. Purpose & context

Package Race Engineer so a friend can go from "I have the installer" to "the app
is running and coaching me" without any manual Python setup. Today a new machine
needs: install uv → `uv sync` → hand-write `.env` → run `install_shortcut.py`.
This spec collapses that into a single `RaceEngineer-Setup.exe` plus an in-app
first-run wizard, and adds a safe self-update channel.

This is **sub-project #1** of the commercial-shape arc the founder described
(2026-07-16): a client that runs deterministic logic locally and will later lean
on a hosted server for AI and shared data.

**Deferred to later sub-projects (explicitly OUT of scope here):**
- **#2 AI-proxy server** — a hosted endpoint holding the Anthropic key so friends
  need no key of their own. In v1 the friend brings their own key.
- **#3 auth / licensing / community data** — per-user accounts, shared reference
  laps and track DB.

### Model shift this introduces

Today: the friend uses the founder's *hosted* Streamlit over Tailscale. After
this: the friend runs **their own client on their own rig, with their own iRacing
account and their own Anthropic key**. The Tailscale-shared host remains valid but
is no longer the only way a friend uses the product.

---

## 2. Locked decisions (founder, 2026-07-16)

1. **AI secrets in v1 — BYO key.** The friend enters their own Anthropic API key
   in the first-run wizard. The installer ships **no** Anthropic secret. The
   hosted proxy that removes this requirement is sub-project #2.
2. **Update transport — release-zip channel.** No git on the client. The app
   polls the GitHub Releases API, and updates by downloading the release zip for a
   newer tag, verifying its SHA-256, swapping code files, and re-running
   `uv sync`. Publishing an update = cutting a GitHub Release.
3. **iRacing OAuth app credential — ship the founder's.** The registered
   `pwlimited` `client_id`/`client_secret` is baked into the shipped code as a
   config default so full race-results + field-briefing features work in v1. This
   is one **app-level** secret (not a user credential — every user still enters
   their own iRacing login). It moves behind the proxy in v2, restoring a
   zero-secret client. This is a deliberate, time-boxed acceptance, recorded here.
4. **Distribution — Inno Setup + bundled uv, not a frozen binary.** (Carries the
   Atlas "uv-bootstrap installer, not frozen binaries" decision — PyInstaller with
   streamlit/scipy is not viable.)

---

## 3. Architecture

### 3.1 Install layout (per-user, no admin)

The installer targets `%LOCALAPPDATA%\RaceEngineer\` so it needs no elevation and
`data/` stays writable (a Program Files install would make the SQLite stores and
`data/run/` PID files read-only):

```
%LOCALAPPDATA%\RaceEngineer\
├── app\                # code snapshot — REPLACED on update
│   ├── app\  core\  scripts\
│   ├── pyproject.toml  uv.lock  .python-version
│   └── .venv\          # uv-managed — reconciled on update (uv sync)
├── data\               # SQLite dbs, run/, caches — PRESERVED across updates
├── .env                # friend's keys — PRESERVED across updates
└── uv.exe              # bundled uv (single static binary)
```

The installer bundles a **code snapshot** + `uv.exe` only — it does **not** bundle
the heavy wheels. A post-install `uv sync` fetches Python 3.14 and
numpy/scipy/pandas/streamlit into `app/.venv`. This keeps the installer small
(~30 MB, dominated by uv) and makes dependency provenance the pinned `uv.lock`.

### 3.2 Install-time flow (Inno Setup `[Run]` steps)

1. Unpack the code snapshot + `uv.exe` into the install dir.
2. `uv sync` (cwd = `app\`) — creates `.venv`, installs pinned deps, fetches
   Python 3.14 if absent. This is the slow step (progress shown by Inno).
3. Create the tray shortcut via the existing `install_shortcut.py`, retargeted at
   the installed `start-tray.bat` (see §6 for the path-portability change).
4. Launch the app once → first run lands on the Setup page (§4).

Uninstall removes `app\` and shortcuts; **prompts before removing `data\`/`.env`**
(a friend's race history and keys should not vanish silently).

### 3.3 Component boundaries

| Unit | Responsibility | Depends on | Tested |
|---|---|---|---|
| `core/update/` | PURE update logic: version compare, release lookup, SHA verify, selective swap | stdlib + httpx | Unit (heavy) |
| `core/config/env_setup.py` | `.env` read/detect-incomplete/write; baked iRacing app-cred default | stdlib | Unit |
| `app/pages/setup.py` | First-run wizard UI (display only) | `core/config` | Convention-untested |
| tray update orchestration | check on interval, menu item, stop→apply→sync→restart | `core/update`, `stop_all`, `launch` | Coupling only |
| `installer/race-engineer.iss` | Inno Setup script | — | Convention-untested |
| `scripts/build_release.py` | version bump, zip, SHA-256 print | stdlib | Unit (SHA + zip contents) |

---

## 4. First-run config (Setup page)

No separate GUI installer wizard — a **first-run Streamlit page**, because the app
already runs fine without keys (it degrades to empty/StubAPI everywhere).

- **Routing:** on app start, `core/config/env_setup.is_complete()` decides. If
  `.env` is missing or missing a required key, the app routes to the Setup page
  and suppresses the normal nav until setup completes.
- **Collected from the friend:** iRacing username, iRacing password, their own
  Anthropic API key.
- **NOT collected:** `IRACING_CLIENT_ID` / `IRACING_CLIENT_SECRET` — these are the
  baked-in founder app credential (§2.3), applied as defaults by
  `env_setup.write()` so the written `.env` is self-contained.
- **Validation (optional, per-field "Test" buttons):**
  - Anthropic key → a minimal `anthropic` client call; show ✓/✗.
  - iRacing login → an OAuth token fetch via the existing client; show ✓/✗.
  - Both are **non-blocking**: the friend can save unvalidated (offline install)
    and fix later; a failed test warns but does not prevent saving.
- **On save:** write `.env`, then `st.rerun()` into the normal Start page.
- **Re-editable:** a "Settings / keys" entry (Host group) re-opens the page so
  keys can be rotated without hand-editing `.env`.

### `.env` contract

`env_setup` owns the only knowledge of which keys are required:

```
REQUIRED = ("ANTHROPIC_API_KEY", "IRACING_USERNAME", "IRACING_PASSWORD")
DEFAULTS = {"IRACING_CLIENT_ID": "<baked>", "IRACING_CLIENT_SECRET": "<baked>"}
```

`is_complete()` = every `REQUIRED` key present and non-empty. Writing merges
`DEFAULTS` (unless already overridden in an existing `.env`) so a friend who later
registers their own OAuth app can override the default by editing `.env`.

---

## 5. Update channel

### 5.1 Pure updater core (`core/update/`)

Two entry points, no process control, no Streamlit — unit-testable in isolation:

**`check_for_update(current_version: str) -> UpdateInfo | None`**
- GETs the GitHub Releases API (`/repos/marmalard/race-engineer/releases/latest`).
- Parses the tag as semver; returns `None` if it is not strictly newer than
  `current_version`.
- Returns `UpdateInfo(tag, zip_url, sha256, notes)` where `sha256` is read from a
  published asset (a `SHA256SUMS` text asset or the release body — see §5.4).
- **Only release tags are ever considered — never a branch/`master` ref.** This is
  the safety anchor: unreviewed commits can't reach a client.
- Network/parse failure → `None` (fail-quiet; the app must never break because the
  update check failed). Logged.

**`apply_update(zip_bytes: bytes, expected_sha256: str, install_root: Path) -> None`**
1. Verify `sha256(zip_bytes) == expected_sha256`; raise `UpdateVerificationError`
   on mismatch **before writing anything**. (Tamper/corruption gate.)
2. Extract to a temp dir.
3. **Selective swap** into `install_root/app/`: replace `app/ core/ scripts/`,
   `pyproject.toml`, `uv.lock`, `.python-version`. **Never touch** `data/`,
   `.env`, `.venv/` (preserved; `.venv` is reconciled by the post-swap `uv sync`).
4. Return; the caller runs `uv sync` and restarts.

Current version source: the `[project] version` field already in `pyproject.toml`
(single source of truth, currently `0.1.0`), surfaced by a tiny
`core/update/version.py` reader (reused by the status strip and the Setup page
footer). `build_release.py` bumps this same field.

### 5.2 Orchestration (tray)

The tray already owns process lifecycle, so it owns the *when*:
- A daemon thread checks for updates on a slow interval (e.g. every 6 h) and at
  tray start; caches the result.
- If an update is available, the menu shows **"Update available (vX.Y.Z)"**.
- On the friend's click (consent-gated, never silent — file swap needs the app
  stopped anyway):
  1. `stop_all` (rig off),
  2. download zip → `apply_update` (verify + swap),
  3. `uv sync` (cwd = installed `app\`),
  4. relaunch via `launch`/tray start,
  5. report success/failure in the menu + log.
- Any failure leaves the previous install intact (swap only proceeds past a
  verified download; a `uv sync` failure is logged and the old `.venv` still
  works because deps are additive).

### 5.3 Trust model (v1)

The trust anchor is the **authenticated GitHub Release + the SHA-256 published in
it**, plus the tag-only rule. Full Authenticode code-signing of the installer
(paid cert; removes SmartScreen warnings) is acknowledged as a **future**
improvement, out of scope for v1 — a friend install tolerates the one-time
SmartScreen "more info → run anyway".

### 5.4 SHA-256 publication convention

The release SHA lives in a `SHA256SUMS` text asset attached to the release (one
line: `<sha256>  race-engineer-<tag>.zip`). `build_release.py` generates the zip
and this file together so they cannot drift. `check_for_update` reads the asset;
if absent, it returns `None` (an update without a checksum is not offered).

---

## 6. Path portability (small, required refactor)

The current launch/tray/shortcut scripts assume the repo lives at its dev path and
derive `_ROOT` from `__file__`. That already works from any install location
(they use `Path(__file__).resolve().parent.parent`), so **no hard-coded paths need
changing** — verified against `launch.py`, `tray_app.py`, `stop_all.py`,
`install_shortcut.py`. The only change: `install_shortcut.py` currently names the
target `start-race-engineer.bat`; the installed shortcut should target
`start-tray.bat` (the tray is the shipping entry point per B1). Add a
`--target` argument (default keeps current behavior) so the installer picks the
tray bat without breaking the dev shortcut.

This is the one place existing code is touched for the install goal; it is targeted
and coupling-tested, not a refactor.

---

## 7. Release process (how the founder pushes an update)

Documented as a checklist in `docs/RELEASING.md`:

1. `scripts/build_release.py --bump {patch|minor}` → bumps `pyproject.toml`
   version, writes `dist/race-engineer-<tag>.zip` + `dist/SHA256SUMS`, prints the
   SHA.
2. Build the installer: run the Inno Setup compiler on `installer/race-engineer.iss`
   (requires Inno Setup on the build machine only) → `dist/RaceEngineer-Setup.exe`.
3. `git tag vX.Y.Z && git push --tags`.
4. Create a GitHub Release for the tag; attach the zip, `SHA256SUMS`, and the
   `Setup.exe`.
5. Clients pick up the update within the check interval; the founder installs by
   re-running the new `Setup.exe` (idempotent — preserves `data/`/`.env`).

---

## 8. Phasing

The spec is one coherent effort but has a natural seam; the implementation plan
keeps it:

- **Phase 1a — shareable installer** (no auto-update): `env_setup` + Setup page +
  Inno Setup script + `build_release.py` + `install_shortcut --target` +
  `docs/RELEASING.md`. Outcome: a friend can install and run.
- **Phase 1b — updatable**: `core/update/` + tray orchestration + `SHA256SUMS`
  convention. Outcome: the founder can push an update the friend receives in-app.

---

## 9. Testing

Real logic is unit-tested; thin I/O follows the existing convention (untested).

- **`core/update/`** (the crux):
  - semver compare: newer/older/equal/malformed.
  - `apply_update`: SHA match applies; **SHA mismatch raises and writes nothing**;
    selective swap replaces code and **preserves `data/`, `.env`, `.venv`**
    (assert files present + unchanged after a swap into a temp install root);
    malformed zip handled.
  - `check_for_update`: newer tag → `UpdateInfo`; same/older → `None`; missing
    `SHA256SUMS` asset → `None`; network error → `None`. GitHub payload mocked;
    **no network in tests**.
- **`core/config/env_setup.py`**: `is_complete` on full/partial/missing `.env`;
  round-trip write→read; `DEFAULTS` merge applies the baked iRacing app-cred; an
  existing override is not clobbered.
- **`scripts/build_release.py`**: version bump math; zip contains the expected code
  paths and excludes `data/`/`.env`/`.venv`; `SHA256SUMS` line matches the zip.
- **Coupling**: `install_shortcut --target` produces the tray bat target; tray
  update orchestration references real `core/update` symbols (import-level, like
  `test_tray_app.py`/`test_toolbox_commands.py`).
- **Untested by convention**: the `.iss` script, tray/process I/O, browser open,
  Setup page rendering.

---

## 10. Success criteria

- A friend runs `RaceEngineer-Setup.exe` on a machine with no Python, enters three
  keys in the Setup page, and reaches a working Start page — no terminal, no manual
  `uv sync`.
- Uninstall preserves race history unless the friend opts to delete it.
- The founder cuts a GitHub Release and an installed client offers + applies the
  update, preserving `data/` and `.env`, with SHA-256 verification.
- Zero Anthropic secrets in the package; the single baked iRacing app credential is
  documented as a v1 acceptance slated for proxy removal in v2.
- All new `core/` logic unit-tested; full suite green.
