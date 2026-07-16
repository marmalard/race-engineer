# Friend Installer (B2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A friend runs `RaceEngineer-Setup.exe` on a machine with no Python, enters three keys on a first-run Setup page, and gets a working Race Engineer — plus a SHA-256-verified release-zip self-update channel driven from the tray.

**Architecture:** Inno Setup per-user installer to `%LOCALAPPDATA%\RaceEngineer` bundling a code snapshot + `uv.exe` (post-install `uv sync` fetches Python 3.14 and deps). First-run routing in `streamlit_app.py` shows only a Setup page until `core/config/env_setup.is_complete()`. Updates: `core/update/` (pure — GitHub Releases lookup, semver compare, SHA-256 verify, selective swap) orchestrated by the tray (stop rig → download → verify+swap → `uv sync` → restart).

**Tech Stack:** Python 3.14, stdlib (`tomllib`, `zipfile`, `hashlib`), httpx, Streamlit, Inno Setup 6 (build machine only), uv.

**Spec:** `docs/superpowers/specs/2026-07-16-friend-installer-design.md` (approved 2026-07-16).

**Execution note:** Implement in a **git worktree** — the production app hot-reloads the main checkout (standing rule since 2026-07-15). Branch name: `friend-installer-b2`.

---

## Two deliberate spec amendments (read first)

**1. Flat install layout (spec §3.1 showed a nested `app\` snapshot dir).** Every existing module derives `data/`, `.env`, `data/run/` paths from `_ROOT` (the directory containing `app/ core/ scripts/`). The spec's nested layout would put `data\` and `.env` at the *parent* of that root — the installed app would write `app\data` while updates/uninstall protect `..\data`. That contradicts spec §6 ("no hard-coded paths need changing"). Resolution: **`%LOCALAPPDATA%\RaceEngineer` IS the code root** — it contains `app/ core/ scripts/ pyproject.toml uv.lock .python-version uv.exe` plus the preserved `data/`, `.env`, `.venv`. The update's selective swap replaces only the six `RELEASE_ENTRIES`; everything else is untouched by construction. Every spec invariant (preserve `data/`+`.env`+`.venv`, replace code, uninstall prompt) holds, and zero existing paths change. Installed-layout detection = `uv.exe` present at the code root (never true in a dev checkout).

**2. Baked iRacing app credential is injected at build time, never committed (spec §2.3).** The repo is **PUBLIC** on GitHub — committing `IRACING_CLIENT_SECRET` to source would publish it to the internet, far beyond the spec's "shipped code" acceptance. Resolution: `core/config/_baked.py` is **gitignored**; `scripts/build_release.py` regenerates it from the founder's `.env` before zipping, and the Inno installer sources files from the founder's checkout where it exists on disk. Release artifacts carry the credential (the documented v1 acceptance); git history never does. `env_setup.py` imports it with an `ImportError` fallback to empty defaults, so a public-checkout clone still works (the Setup page then says no app credential is baked). **Note for the founder:** release assets on a public repo are world-downloadable, so the credential is still extractable by strangers who find the release — same risk class the spec accepted, worth re-checking at v2 proxy time.

---

## File map

| File | Action | Phase |
|---|---|---|
| `core/update/__init__.py` | Create (empty) | 1a |
| `core/update/version.py` | Create — `get_version`, `bump_version` | 1a |
| `core/update/manifest.py` | Create — `RELEASE_ENTRIES`, `is_installed_layout` | 1a |
| `core/config/__init__.py` | Create (empty) | 1a |
| `core/config/env_setup.py` | Create — `.env` contract | 1a |
| `core/benchmark/iracing_api.py` | Modify — add `verify_login()` | 1a |
| `app/pages/setup.py` | Create — Setup page | 1a |
| `app/navigation.py` | Modify — Setup page in Host group | 1a |
| `app/streamlit_app.py` | Modify — first-run routing | 1a |
| `app/pages/start.py` | Modify — version in status strip | 1a |
| `scripts/install_shortcut.py` | Modify — `--target tray` | 1a |
| `scripts/build_release.py` | Create — bump + zip + SHA256SUMS + baked-cred refresh | 1a |
| `installer/race-engineer.iss` | Create — Inno Setup script | 1a |
| `installer/.gitignore` | Create — ignore `uv.exe` | 1a |
| `docs/RELEASING.md` | Create — release checklist | 1a |
| `.gitignore` | Modify — `_baked.py`, `dist/` | 1a |
| `core/update/releases.py` | Create — `check_for_update`, `download_zip` | 1b |
| `core/update/apply.py` | Create — `apply_update` | 1b |
| `scripts/tray_app.py` | Modify — update check thread + menu + flow | 1b |
| `tests/test_update_version.py` | Create | 1a |
| `tests/test_env_setup.py` | Create | 1a |
| `tests/test_iracing_api.py` | Modify | 1a |
| `tests/test_install_shortcut.py` | Create | 1a |
| `tests/test_build_release.py` | Create | 1a |
| `tests/test_update_releases.py` | Create | 1b |
| `tests/test_update_apply.py` | Create | 1b |
| `tests/test_tray_app.py` | Modify | 1b |

Convention-untested (thin I/O): `app/pages/setup.py` rendering, `streamlit_app.py` routing, the `.iss` script, tray process I/O.

---

# Phase 1a — shareable installer

### Task 1: `core/update` package — version reader + release manifest

**Files:**
- Create: `core/update/__init__.py`
- Create: `core/update/version.py`
- Create: `core/update/manifest.py`
- Test: `tests/test_update_version.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Version source of truth + release manifest (B2).

get_version reads the real pyproject (single version source, spec 5.1);
bump math and layout detection are pure.
"""

from pathlib import Path

import pytest

from core.update.manifest import RELEASE_ENTRIES, is_installed_layout
from core.update.version import bump_version, get_version

_ROOT = Path(__file__).resolve().parent.parent


class TestGetVersion:
    def test_reads_the_real_pyproject(self):
        # Whatever the current version is, it parses as x.y.z.
        version = get_version()
        assert bump_version(version, "patch")  # round-trips through the parser

    def test_reads_an_explicit_pyproject(self, tmp_path):
        py = tmp_path / "pyproject.toml"
        py.write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
        assert get_version(py) == "1.2.3"


class TestBumpVersion:
    def test_patch(self):
        assert bump_version("0.1.0", "patch") == "0.1.1"

    def test_minor_resets_patch(self):
        assert bump_version("0.1.7", "minor") == "0.2.0"

    def test_malformed_version_raises(self):
        with pytest.raises(ValueError):
            bump_version("0.1", "patch")

    def test_unknown_part_raises(self):
        with pytest.raises(ValueError):
            bump_version("0.1.0", "major-ish")


class TestManifest:
    def test_release_entries_exact(self):
        # The swap/zip whitelist — data/, .env, .venv are preserved by
        # NOT being here. Changing this list changes what an update
        # replaces on a friend's machine.
        assert RELEASE_ENTRIES == (
            "app", "core", "scripts",
            "pyproject.toml", "uv.lock", ".python-version",
        )

    def test_release_entries_exist_in_this_checkout(self):
        for entry in RELEASE_ENTRIES:
            assert (_ROOT / entry).exists(), entry

    def test_dev_checkout_is_not_installed_layout(self):
        assert not is_installed_layout(_ROOT)

    def test_uv_exe_marks_installed_layout(self, tmp_path):
        (tmp_path / "uv.exe").write_bytes(b"")
        assert is_installed_layout(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_update_version.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.update'`

- [ ] **Step 3: Write the implementation**

`core/update/__init__.py` — empty file.

`core/update/version.py`:

```python
"""App version source of truth for the update channel (B2, spec 5.1).

The [project] version in pyproject.toml is the single source; the
status strip, Setup page footer, update check, and build_release all
read it from here.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parent.parent.parent


def get_version(pyproject: Path | None = None) -> str:
    """The [project] version from pyproject.toml."""
    path = pyproject if pyproject is not None else _CODE_ROOT / "pyproject.toml"
    with open(path, "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def bump_version(version: str, part: str) -> str:
    """'0.1.0' + patch -> '0.1.1'; minor resets patch. Raises on malformed."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise ValueError(f"not an x.y.z version: {version!r}")
    major, minor, patch = (int(g) for g in match.groups())
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump part: {part!r}")
```

`core/update/manifest.py`:

```python
"""What a release contains and how an install is recognized (B2).

RELEASE_ENTRIES is the whitelist shared by build_release (what goes in
the zip) and apply_update (what a swap replaces) — data/, .env and
.venv are preserved across updates by NOT appearing here.
"""

from __future__ import annotations

from pathlib import Path

RELEASE_ENTRIES: tuple[str, ...] = (
    "app", "core", "scripts",
    "pyproject.toml", "uv.lock", ".python-version",
)


def is_installed_layout(code_root: Path) -> bool:
    """True when running from an installed tree (bundled uv.exe beside
    the code). Never true in a dev checkout — the tray uses this to keep
    the update channel off dev rigs (git manages those)."""
    return (Path(code_root) / "uv.exe").is_file()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_update_version.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add core/update tests/test_update_version.py
git commit -m "feat(update): version reader + release manifest (B2 task 1)"
```

---

### Task 2: `core/config/env_setup.py` — the `.env` contract

**Files:**
- Create: `core/config/__init__.py`
- Create: `core/config/env_setup.py`
- Modify: `.gitignore` (add `core/config/_baked.py` and `dist/`)
- Test: `tests/test_env_setup.py`

- [ ] **Step 1: Write the failing tests**

```python
"""env_setup owns the only knowledge of which .env keys are required
(spec 4). Values are double-quoted with escaping so passwords containing
spaces/#/quotes survive the python-dotenv parse."""

from core.config import env_setup
from core.config.env_setup import (
    REQUIRED,
    is_complete,
    read_env,
    write_env,
)


class TestRequiredContract:
    def test_required_keys_exact(self):
        assert REQUIRED == (
            "ANTHROPIC_API_KEY", "IRACING_USERNAME", "IRACING_PASSWORD",
        )


class TestIsComplete:
    def test_missing_file_is_incomplete(self, tmp_path):
        assert not is_complete(tmp_path / "no-such.env")

    def test_partial_file_is_incomplete(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "ANTHROPIC_API_KEY=sk-x\nIRACING_USERNAME=me\nIRACING_PASSWORD=\n",
            encoding="utf-8",
        )
        assert not is_complete(env)

    def test_full_file_is_complete(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "ANTHROPIC_API_KEY=sk-x\nIRACING_USERNAME=me\n"
            "IRACING_PASSWORD=pw\n",
            encoding="utf-8",
        )
        assert is_complete(env)


class TestReadEnv:
    def test_skips_comments_and_blanks(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "# iRacing OAuth\n\nIRACING_USERNAME=me\n", encoding="utf-8"
        )
        assert read_env(env) == {"IRACING_USERNAME": "me"}

    def test_missing_file_reads_empty(self, tmp_path):
        assert read_env(tmp_path / "nope.env") == {}


class TestWriteEnv:
    def test_round_trip_nasty_password(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        nasty = 'pa ss#w"ord\\n'  # space, hash, quote, literal backslash-n
        write_env({"IRACING_PASSWORD": nasty}, env, defaults={})
        assert read_env(env)["IRACING_PASSWORD"] == nasty

    def test_defaults_fill_missing_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        write_env(
            {"ANTHROPIC_API_KEY": "sk-x"},
            env,
            defaults={"IRACING_CLIENT_ID": "founder-id"},
        )
        assert read_env(env)["IRACING_CLIENT_ID"] == "founder-id"

    def test_existing_override_is_not_clobbered(self, tmp_path, monkeypatch):
        # A friend who registers their own OAuth app keeps it (spec 4).
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        env.write_text("IRACING_CLIENT_ID=their-own\n", encoding="utf-8")
        write_env(
            {"ANTHROPIC_API_KEY": "sk-x"},
            env,
            defaults={"IRACING_CLIENT_ID": "founder-id"},
        )
        assert read_env(env)["IRACING_CLIENT_ID"] == "their-own"

    def test_empty_default_is_not_written(self, tmp_path, monkeypatch):
        # Public checkout without _baked.py: don't write blank cred keys.
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        write_env(
            {"ANTHROPIC_API_KEY": "sk-x"}, env,
            defaults={"IRACING_CLIENT_ID": ""},
        )
        assert "IRACING_CLIENT_ID" not in read_env(env)

    def test_write_updates_process_env(self, tmp_path, monkeypatch):
        # The running app must pick up saved keys without a restart
        # (Setup page saves then st.rerun()s — no fresh load_dotenv).
        fake_environ: dict = {}
        monkeypatch.setattr(env_setup.os, "environ", fake_environ)
        write_env({"ANTHROPIC_API_KEY": "sk-x"}, tmp_path / ".env", defaults={})
        assert fake_environ["ANTHROPIC_API_KEY"] == "sk-x"

    def test_preserves_unrelated_existing_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        env.write_text("SOME_OTHER=keepme\n", encoding="utf-8")
        write_env({"ANTHROPIC_API_KEY": "sk-x"}, env, defaults={})
        assert read_env(env)["SOME_OTHER"] == "keepme"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_env_setup.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.config'`

- [ ] **Step 3: Write the implementation**

`core/config/__init__.py` — empty file.

`core/config/env_setup.py`:

```python
""".env contract for first-run setup (B2, spec 4).

The ONLY module that knows which keys are required and which the app
bakes as defaults. The baked iRacing app credential lives in the
gitignored core/config/_baked.py (generated by scripts/build_release.py
from the founder .env — the PUBLIC repo never carries it; release
artifacts do, per the spec 2.3 v1 acceptance).

Values are written double-quoted with backslash escaping so passwords
containing spaces, '#', or quotes survive the python-dotenv parse the
app does at startup.
"""

from __future__ import annotations

import os
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED: tuple[str, ...] = (
    "ANTHROPIC_API_KEY", "IRACING_USERNAME", "IRACING_PASSWORD",
)

try:  # generated at build time; absent in a public checkout
    from core.config._baked import BAKED_DEFAULTS
except ImportError:
    BAKED_DEFAULTS: dict[str, str] = {}

DEFAULTS: dict[str, str] = {
    "IRACING_CLIENT_ID": "",
    "IRACING_CLIENT_SECRET": "",
    **BAKED_DEFAULTS,
}


def env_file() -> Path:
    """The app's .env — beside app/ core/ scripts/ in both the dev
    checkout and the installed layout (flat root, plan amendment 1)."""
    return _CODE_ROOT / ".env"


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1]
        out: list[str] = []
        i = 0
        while i < len(inner):
            if inner[i] == "\\" and i + 1 < len(inner):
                out.append(inner[i + 1])
                i += 2
            else:
                out.append(inner[i])
                i += 1
        return "".join(out)
    return value


def read_env(path: Path | None = None) -> dict[str, str]:
    """KEY=VALUE pairs from a .env file; {} when the file is absent."""
    path = path if path is not None else env_file()
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = _unquote(val.strip())
    return values


def is_complete(path: Path | None = None) -> bool:
    """Every REQUIRED key present and non-empty (spec 4)."""
    values = read_env(path)
    return all(values.get(key) for key in REQUIRED)


def write_env(
    values: dict[str, str],
    path: Path | None = None,
    defaults: dict[str, str] | None = None,
) -> Path:
    """Merge new values over the existing file, fill missing keys from
    defaults (never clobbering an existing override), write, and update
    os.environ so the running app sees the keys immediately."""
    path = path if path is not None else env_file()
    defaults = DEFAULTS if defaults is None else defaults
    merged = read_env(path)
    merged.update({k: v.strip() for k, v in values.items()})
    for key, default in defaults.items():
        if default and not merged.get(key):
            merged[key] = default
    lines = [f"{key}={_quote(val)}" for key, val in merged.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ.update(merged)
    return path
```

Append to the repo root `.gitignore` (Edit tool, never PowerShell):

```
# B2 installer: build-time-injected app credential + release artifacts
core/config/_baked.py
dist/
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_env_setup.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add core/config tests/test_env_setup.py .gitignore
git commit -m "feat(config): env_setup .env contract with build-time baked credential (B2 task 2)"
```

---

### Task 3: `LiveIRacingAPI.verify_login()`

**Files:**
- Modify: `core/benchmark/iracing_api.py` (after `_ensure_token`, ~line 416)
- Test: `tests/test_iracing_api.py` (append a class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_iracing_api.py`:

```python
class TestVerifyLogin:
    def test_verify_login_authenticates_and_returns_true(self, monkeypatch):
        from core.benchmark.iracing_api import LiveIRacingAPI

        api = LiveIRacingAPI("cid", "csecret", "user@example.com", "pw")
        calls = []
        monkeypatch.setattr(
            api, "_authenticate", lambda: calls.append("auth")
        )
        assert api.verify_login() is True
        assert calls == ["auth"]

    def test_verify_login_propagates_auth_failure(self, monkeypatch):
        from core.benchmark.iracing_api import LiveIRacingAPI

        api = LiveIRacingAPI("cid", "csecret", "user@example.com", "pw")

        def boom():
            raise RuntimeError("401")

        monkeypatch.setattr(api, "_authenticate", boom)
        try:
            api.verify_login()
            assert False, "should have raised"
        except RuntimeError:
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_iracing_api.py::TestVerifyLogin -q`
Expected: FAIL — `AttributeError: ... has no attribute 'verify_login'`

- [ ] **Step 3: Write the implementation**

In `core/benchmark/iracing_api.py`, after `_ensure_token` (before the `# --- Data API calls ---` divider):

```python
    def verify_login(self) -> bool:
        """Perform a full authentication and return True on success.

        Setup-page credential check (B2): raises the underlying httpx
        error on bad credentials so the page can show it.
        """
        self._authenticate()
        return True
```

- [ ] **Step 4: Run the module's tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_iracing_api.py -q`
Expected: all pass (existing tests plus 2 new)

- [ ] **Step 5: Commit**

```bash
git add core/benchmark/iracing_api.py tests/test_iracing_api.py
git commit -m "feat(api): verify_login for the Setup page credential test (B2 task 3)"
```

---

### Task 4: Setup page, first-run routing, version surfacing

**Files:**
- Create: `app/pages/setup.py`
- Modify: `app/navigation.py` (Host group)
- Modify: `app/streamlit_app.py` (routing)
- Modify: `app/pages/start.py` (status strip version)
- Test: `tests/test_navigation.py` (Host group pin)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_navigation.py` inside `TestNavSpec`:

```python
    def test_host_group_pages_exact(self):
        # Settings & Keys is the re-editable Setup page (B2 spec 4) —
        # it must stay reachable after first run so keys can rotate
        # without hand-editing .env.
        host = dict(NAV_SPEC)["Host"]
        assert [p.title for p in host] == ["Toolbox", "Settings & Keys"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_navigation.py -q`
Expected: FAIL — `test_host_group_pages_exact` (list is `["Toolbox"]`)

- [ ] **Step 3: Add the nav entry**

In `app/navigation.py`, change the Host group to:

```python
    (
        "Host",
        [
            PageSpec("Toolbox", "\U0001f39b", "toolbox",
                     "app.pages.toolbox", "render_toolbox_page"),
            PageSpec("Settings & Keys", "\U0001f511", "setup",
                     "app.pages.setup", "render_setup_page"),
        ],
    ),
```

- [ ] **Step 4: Create the Setup page**

`app/pages/setup.py`:

```python
"""First-run Setup page + key rotation (B2, spec 4). Display only —
the .env contract lives in core/config/env_setup.

Both Test buttons are thin I/O over real services and are non-blocking:
a failed test warns, saving is always allowed (offline install).
Convention-untested (Streamlit rendering + network I/O).
"""

from __future__ import annotations

import streamlit as st

from core.config.env_setup import (
    DEFAULTS,
    is_complete,
    read_env,
    write_env,
)
from core.update.version import get_version

_FIRST_RUN_INTRO = (
    "Welcome — three keys and you're racing. Your **iRacing login** lets "
    "the engineer pull official results and field data; your **Anthropic "
    "API key** powers the AI debriefs (get one at console.anthropic.com). "
    "Everything is stored only on this machine, in a local `.env` file."
)

_EDIT_INTRO = (
    "Update your saved keys here. Changes take effect immediately — no "
    "restart needed."
)


def _test_anthropic_key(key: str) -> str | None:
    """None on success, error text on failure. A models.list() call —
    cheap, no tokens consumed."""
    try:
        import anthropic

        anthropic.Anthropic(api_key=key).models.list()
        return None
    except Exception as exc:  # noqa: BLE001 — shown to the user, never raised
        return str(exc)


def _test_iracing_login(username: str, password: str) -> str | None:
    """None on success, error text on failure (OAuth token fetch)."""
    client_id = DEFAULTS.get("IRACING_CLIENT_ID", "")
    client_secret = DEFAULTS.get("IRACING_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return (
            "This build has no iRacing app credential baked in — "
            "set IRACING_CLIENT_ID / IRACING_CLIENT_SECRET in .env."
        )
    try:
        from core.benchmark.iracing_api import LiveIRacingAPI

        with LiveIRacingAPI(client_id, client_secret, username, password) as api:
            api.verify_login()
        return None
    except Exception as exc:  # noqa: BLE001 — shown to the user, never raised
        return str(exc)


def render_setup_page() -> None:
    first_run = not is_complete()
    st.header("Setup" if first_run else "Settings & Keys")
    st.markdown(_FIRST_RUN_INTRO if first_run else _EDIT_INTRO)

    existing = read_env()
    username = st.text_input(
        "iRacing username (email)",
        value=existing.get("IRACING_USERNAME", ""),
    )
    password = st.text_input(
        "iRacing password",
        value=existing.get("IRACING_PASSWORD", ""),
        type="password",
    )
    if st.button("Test iRacing login"):
        if not (username and password):
            st.warning("Enter your iRacing username and password first.")
        else:
            err = _test_iracing_login(username, password)
            if err is None:
                st.success("iRacing login works.")
            else:
                st.warning(f"iRacing login failed — you can still save. {err}")

    anthropic_key = st.text_input(
        "Anthropic API key",
        value=existing.get("ANTHROPIC_API_KEY", ""),
        type="password",
    )
    if st.button("Test Anthropic key"):
        if not anthropic_key:
            st.warning("Enter your Anthropic API key first.")
        else:
            err = _test_anthropic_key(anthropic_key)
            if err is None:
                st.success("Anthropic key works.")
            else:
                st.warning(f"Key test failed — you can still save. {err}")

    st.divider()
    if st.button("Save and start", type="primary"):
        write_env({
            "IRACING_USERNAME": username,
            "IRACING_PASSWORD": password,
            "ANTHROPIC_API_KEY": anthropic_key,
        })
        st.success("Saved.")
        st.rerun()  # first run: routing now sees a complete .env

    st.caption(f"Race Engineer v{get_version()}")
```

- [ ] **Step 5: Wire the first-run routing**

In `app/streamlit_app.py`, replace the block from `from app.components.prefs import ...` down to `pg.run()` with:

```python
from app.components.prefs import load_unit_system, save_unit_system  # noqa: E402
from app.components.theme import apply_theme, brand_sidebar  # noqa: E402
from app.navigation import build_pages, page_for  # noqa: E402
from core.config.env_setup import is_complete  # noqa: E402

apply_theme()

# First run (B2 spec 4): until the required keys exist, the Setup page
# is the only page — no nav, no units control.
if not is_complete():
    pg = st.navigation([page_for("setup")], position="sidebar")
    brand_sidebar()
    pg.run()
else:
    # st.navigation renders its own grouped nav at the top of the sidebar;
    # the brand block and units toggle follow below it.
    pg = st.navigation(build_pages(), position="sidebar")

    brand_sidebar()

    # Units survive reloads: seed a fresh session from the host pref file,
    # save on change (deselecting reads as Metric everywhere).
    if "unit_system" not in st.session_state:
        st.session_state["unit_system"] = load_unit_system()

    def _save_units() -> None:
        save_unit_system(st.session_state.get("unit_system") or "Metric")

    st.sidebar.segmented_control(
        "Units", ["Metric", "Imperial"], key="unit_system",
        on_change=_save_units,
    )

    pg.run()
```

- [ ] **Step 6: Surface the app version in the Start status strip**

In `app/pages/start.py`: add the import near the other imports:

```python
from core.update.version import get_version
```

Then in `render_start_page`, replace the status-strip `parts` assignment:

```python
    # --- Status strip ----------------------------------------------------
    sha = _app_version()
    version = f"v{get_version()}" + (f" ({sha})" if sha != "unknown" else "")
    parts = [
        version,
        "host mode" if is_host() else "guest mode",
    ]
```

(The old first element was `f"v {_app_version()}"` — installed friends have no git, so the semantic version leads and the git SHA becomes a dev-only suffix.)

- [ ] **Step 7: Run the nav + start tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_navigation.py tests/test_start_page.py -q`
Expected: all pass (`test_every_render_function_exists` now also imports `app.pages.setup`).

- [ ] **Step 8: Smoke the routing by hand (worktree, port 8502)**

Run: `.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py --server.port 8502 --server.headless true`
Expected: with the dev `.env` present → normal app, "Settings & Keys" under Host. Temporarily rename `.env` → only the Setup page renders; restore `.env`. Stop the server.

- [ ] **Step 9: Commit**

```bash
git add app/pages/setup.py app/navigation.py app/streamlit_app.py app/pages/start.py tests/test_navigation.py
git commit -m "feat(setup): first-run Setup page, key rotation entry, version in status strip (B2 task 4)"
```

---

### Task 5: `install_shortcut.py --target tray`

**Files:**
- Modify: `scripts/install_shortcut.py`
- Test: `tests/test_install_shortcut.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
"""Shortcut spec coupling (B2 spec 6): the installer points the desktop
shortcut at the tray; the dev default stays the console launcher. Pure
spec builder tested; the PowerShell COM call is thin I/O (untested)."""

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


install_shortcut = _load_script("install_shortcut")


class TestShortcutSpec:
    def test_default_is_the_console_launcher(self):
        spec = install_shortcut.shortcut_spec()
        assert spec.target_path.lower().endswith("cmd.exe")
        assert "start-race-engineer.bat" in spec.arguments

    def test_tray_targets_pythonw_directly(self):
        # pythonw (not cmd /c bat): no console flash, still pinnable.
        spec = install_shortcut.shortcut_spec("tray")
        assert spec.target_path.endswith("pythonw.exe")
        assert "tray_app.py" in spec.arguments

    def test_tray_paths_exist_in_this_checkout(self):
        spec = install_shortcut.shortcut_spec("tray")
        assert Path(spec.target_path).is_file()  # venv pythonw
        assert (_ROOT / "scripts" / "tray_app.py").is_file()

    def test_unknown_target_raises(self):
        with pytest.raises(ValueError):
            install_shortcut.shortcut_spec("frozen-binary")

    def test_cli_accepts_target(self):
        args = install_shortcut.build_parser().parse_args(["--target", "tray"])
        assert args.target == "tray"

    def test_cli_default_target(self):
        args = install_shortcut.build_parser().parse_args([])
        assert args.target == "launcher"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_install_shortcut.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'shortcut_spec'`

- [ ] **Step 3: Rewrite `scripts/install_shortcut.py`**

```python
"""Create the Desktop shortcut for Race Engineer.

Run once:  .venv\\Scripts\\python.exe scripts\\install_shortcut.py [--target tray]

Targets (B2 spec 6):
  launcher (default) — cmd.exe /c start-race-engineer.bat, the dev rig's
      console launcher. cmd.exe as target keeps 'Pin to taskbar' offered.
  tray — pythonw.exe scripts/tray_app.py directly: no console flash, an
      exe target (pinnable). Used by the installer.

Uses the Windows Script Host COM object via PowerShell (no pywin32 dep)
and resolves the Desktop through the shell special folder so
OneDrive-redirected Desktops still work.
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BAT = _ROOT / "scripts" / "start-race-engineer.bat"
_SHORTCUT_NAME = "Race Engineer.lnk"
_CMD = r"C:\Windows\System32\cmd.exe"


@dataclass(frozen=True)
class ShortcutSpec:
    target_path: str
    arguments: str
    description: str


def shortcut_spec(target: str = "launcher") -> ShortcutSpec:
    """Pure shortcut definition per target (coupling-tested)."""
    if target == "launcher":
        return ShortcutSpec(
            target_path=_CMD,
            arguments=f'/c ""{_BAT}""',
            description="Start Race Engineer (Streamlit + watcher)",
        )
    if target == "tray":
        pythonw = _ROOT / ".venv" / "Scripts" / "pythonw.exe"
        tray = _ROOT / "scripts" / "tray_app.py"
        return ShortcutSpec(
            target_path=str(pythonw),
            arguments=f'"{tray}"',
            description="Start Race Engineer (system tray)",
        )
    raise ValueError(f"unknown shortcut target: {target!r}")


def create_shortcut(target: str = "launcher") -> str:
    """Create (or overwrite) the Desktop .lnk; returns its path."""
    spec = shortcut_spec(target)
    ps = (
        "$desktop = [Environment]::GetFolderPath('Desktop'); "
        f"$lnk = Join-Path $desktop '{_SHORTCUT_NAME}'; "
        "$ws = New-Object -ComObject WScript.Shell; "
        "$s = $ws.CreateShortcut($lnk); "
        f"$s.TargetPath = '{spec.target_path}'; "
        f"$s.Arguments = '{spec.arguments}'; "
        f"$s.WorkingDirectory = '{_ROOT}'; "
        f"$s.Description = '{spec.description}'; "
        "$s.Save(); "
        "Write-Output $lnk"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create the Desktop shortcut.")
    parser.add_argument(
        "--target", choices=("launcher", "tray"), default="launcher",
        help="what the shortcut starts (default: the console launcher)",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    path = create_shortcut(args.target)
    print(f"Created shortcut: {path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_install_shortcut.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/install_shortcut.py tests/test_install_shortcut.py
git commit -m "feat(shortcut): --target tray points the desktop shortcut at pythonw (B2 task 5)"
```

---

### Task 6: `scripts/build_release.py`

**Files:**
- Create: `scripts/build_release.py`
- Test: `tests/test_build_release.py`

- [ ] **Step 1: Write the failing tests**

```python
"""build_release: bump math delegated to core.update.version (tested
there); here we pin pyproject rewriting, zip contents (RELEASE_ENTRIES
in, data//.env/.venv/__pycache__ out), the SHA256SUMS line, and the
baked-credential generator."""

import hashlib
import importlib.util
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_release = _load_script("build_release")


def _fake_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    for entry in ("app", "core", "scripts"):
        (root / entry).mkdir(parents=True)
        (root / entry / "keep.py").write_text("# code\n", encoding="utf-8")
    (root / "core" / "__pycache__").mkdir()
    (root / "core" / "__pycache__" / "keep.cpython-314.pyc").write_bytes(b"x")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "uv.lock").write_text("lock\n", encoding="utf-8")
    (root / ".python-version").write_text("3.14\n", encoding="utf-8")
    # Things that must NEVER ship:
    (root / "data").mkdir()
    (root / "data" / "races.db").write_bytes(b"secret history")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-real\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "big.dll").write_bytes(b"x" * 10)
    return root


class TestWritePyprojectVersion:
    def test_rewrites_only_the_version_line(self, tmp_path):
        py = tmp_path / "pyproject.toml"
        py.write_text(
            '[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        build_release.write_pyproject_version(py, "0.2.0")
        text = py.read_text(encoding="utf-8")
        assert 'version = "0.2.0"' in text
        assert 'name = "x"' in text

    def test_missing_version_line_raises(self, tmp_path):
        py = tmp_path / "pyproject.toml"
        py.write_text('[project]\nname = "x"\n', encoding="utf-8")
        with pytest.raises(ValueError):
            build_release.write_pyproject_version(py, "0.2.0")


class TestBuildZip:
    def test_zip_contains_code_and_excludes_private_files(self, tmp_path):
        root = _fake_checkout(tmp_path)
        out = tmp_path / "dist" / "race-engineer-v0.1.0.zip"
        build_release.build_zip(root, out)
        names = zipfile.ZipFile(out).namelist()
        assert "app/keep.py" in names
        assert "core/keep.py" in names
        assert "scripts/keep.py" in names
        assert "pyproject.toml" in names
        assert "uv.lock" in names
        assert ".python-version" in names
        for name in names:
            assert not name.startswith("data/")
            assert not name.startswith(".venv/")
            assert ".env" not in name
            assert "__pycache__" not in name
            assert not name.endswith(".pyc")

    def test_returned_sha_matches_the_file(self, tmp_path):
        root = _fake_checkout(tmp_path)
        out = tmp_path / "dist" / "z.zip"
        sha = build_release.build_zip(root, out)
        assert sha == hashlib.sha256(out.read_bytes()).hexdigest()


class TestSha256SumsLine:
    def test_two_space_gnu_format(self):
        line = build_release.sha256sums_line("ab" * 32, "race-engineer-v0.2.0.zip")
        assert line == f"{'ab' * 32}  race-engineer-v0.2.0.zip\n"


class TestRefreshBakedCredentials:
    def test_writes_importable_module_from_env(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "IRACING_CLIENT_ID=1226848-pwlimited\n"
            "IRACING_CLIENT_SECRET=sekrit\n",
            encoding="utf-8",
        )
        out = tmp_path / "_baked.py"
        assert build_release.refresh_baked_credentials(env, out) is True
        ns: dict = {}
        exec(out.read_text(encoding="utf-8"), ns)
        assert ns["BAKED_DEFAULTS"] == {
            "IRACING_CLIENT_ID": "1226848-pwlimited",
            "IRACING_CLIENT_SECRET": "sekrit",
        }

    def test_missing_credential_writes_nothing(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=sk-x\n", encoding="utf-8")
        out = tmp_path / "_baked.py"
        assert build_release.refresh_baked_credentials(env, out) is False
        assert not out.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_release.py -q`
Expected: FAIL — `FileNotFoundError` loading `scripts/build_release.py`

- [ ] **Step 3: Write `scripts/build_release.py`**

```python
"""Cut a Race Engineer release artifact set (B2, spec 7).

Usage:
    .venv\\Scripts\\python.exe scripts\\build_release.py [--bump patch|minor]

Steps: optional version bump in pyproject.toml -> refresh the gitignored
core/config/_baked.py from the founder .env (the public repo never
carries the iRacing app credential; release artifacts do, spec 2.3) ->
write dist/race-engineer-v<ver>.zip (RELEASE_ENTRIES only) +
dist/SHA256SUMS -> print the tag, paths, and SHA.

The zip is FLAT (entries at the zip root) — apply_update and the
installer both rely on that layout.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.update.manifest import RELEASE_ENTRIES  # noqa: E402
from core.update.version import bump_version, get_version  # noqa: E402

_EXCLUDED_DIR_NAMES = {"__pycache__", ".venv"}
_BAKED_PATH = _ROOT / "core" / "config" / "_baked.py"


def write_pyproject_version(pyproject: Path, new_version: str) -> None:
    """Rewrite the [project] version line in place (format-preserving)."""
    text = pyproject.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'^version = "[^"]+"', f'version = "{new_version}"',
        text, count=1, flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(f"version line not found in {pyproject}")
    pyproject.write_text(updated, encoding="utf-8")


def refresh_baked_credentials(env_path: Path, out_path: Path) -> bool:
    """Generate core/config/_baked.py from the founder .env.

    Returns False (writing nothing) when the credential is absent — the
    release then ships without a baked iRacing app cred and the Setup
    page says so.
    """
    from dotenv import dotenv_values

    values = dotenv_values(env_path)
    client_id = values.get("IRACING_CLIENT_ID") or ""
    client_secret = values.get("IRACING_CLIENT_SECRET") or ""
    if not client_id or not client_secret:
        return False
    out_path.write_text(
        '"""GENERATED by scripts/build_release.py - do not commit."""\n'
        "BAKED_DEFAULTS = {\n"
        f"    'IRACING_CLIENT_ID': {client_id!r},\n"
        f"    'IRACING_CLIENT_SECRET': {client_secret!r},\n"
        "}\n",
        encoding="utf-8",
    )
    return True


def _include(rel: Path) -> bool:
    if set(rel.parts) & _EXCLUDED_DIR_NAMES:
        return False
    return rel.suffix != ".pyc"


def build_zip(
    code_root: Path, out_zip: Path,
    entries: tuple[str, ...] = RELEASE_ENTRIES,
) -> str:
    """Write the flat release zip; returns its sha256 hex digest."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            src = code_root / entry
            if src.is_file():
                zf.write(src, entry)
                continue
            for path in sorted(src.rglob("*")):
                rel = path.relative_to(code_root)
                if path.is_file() and _include(rel):
                    zf.write(path, rel.as_posix())
    return hashlib.sha256(out_zip.read_bytes()).hexdigest()


def sha256sums_line(sha: str, zip_name: str) -> str:
    """GNU coreutils two-space format — what check_for_update parses."""
    return f"{sha}  {zip_name}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cut a release artifact set.")
    parser.add_argument("--bump", choices=("patch", "minor"))
    args = parser.parse_args(argv)

    if args.bump:
        new = bump_version(get_version(), args.bump)
        write_pyproject_version(_ROOT / "pyproject.toml", new)
        print(f"Bumped version -> {new}")

    version = get_version()
    if refresh_baked_credentials(_ROOT / ".env", _BAKED_PATH):
        print(f"Refreshed {_BAKED_PATH.name} from .env")
    else:
        print(
            "WARNING: no IRACING_CLIENT_ID/SECRET in .env - "
            "release ships WITHOUT a baked iRacing app credential."
        )

    zip_name = f"race-engineer-v{version}.zip"
    dist = _ROOT / "dist"
    sha = build_zip(_ROOT, dist / zip_name)
    (dist / "SHA256SUMS").write_text(
        sha256sums_line(sha, zip_name), encoding="utf-8"
    )

    print(f"Tag:        v{version}")
    print(f"Zip:        {dist / zip_name}")
    print(f"SHA256SUMS: {dist / 'SHA256SUMS'}")
    print(f"SHA-256:    {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_release.py -q`
Expected: 7 passed

- [ ] **Step 5: Real-tree smoke (writes only to `dist/`, which is gitignored)**

Run: `.venv/Scripts/python.exe scripts/build_release.py`
Expected: `Refreshed _baked.py from .env` (founder checkout has the cred), a `dist/race-engineer-v0.1.0.zip` several MB, SHA printed. Verify: `git status` shows NO new tracked files (`_baked.py` and `dist/` ignored).

- [ ] **Step 6: Commit**

```bash
git add scripts/build_release.py tests/test_build_release.py
git commit -m "feat(release): build_release.py - bump, flat zip, SHA256SUMS, baked-cred refresh (B2 task 6)"
```

---

### Task 7: Inno Setup script + RELEASING.md

**Files:**
- Create: `installer/race-engineer.iss`
- Create: `installer/.gitignore`
- Create: `docs/RELEASING.md`

These are convention-untested (build-machine artifacts). Verify by compiling once on the founder machine (RELEASING.md step) — not part of the test suite.

- [ ] **Step 1: Create `installer/race-engineer.iss`**

```iss
; Race Engineer per-user installer (B2 spec 3.1-3.2).
; Compile:  ISCC.exe installer\race-engineer.iss /DAppVersion=<version>
; Prereqs:  scripts/build_release.py has run (fresh core/config/_baked.py),
;           and uv.exe sits at installer\uv.exe (see docs/RELEASING.md).
; Layout: {localappdata}\RaceEngineer IS the code root (flat) - app/,
; core/, scripts/, pyproject.toml, uv.lock, .python-version, uv.exe,
; plus the preserved data/, .env and .venv the app creates.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B2E31A6F-8A44-4C58-9A02-6E1F4CE3D761}}
AppName=Race Engineer
AppVersion={#AppVersion}
AppPublisher=Race Engineer
DefaultDirName={localappdata}\RaceEngineer
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RaceEngineer-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\core\*"; DestDir: "{app}\core"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.python-version"; DestDir: "{app}"; Flags: ignoreversion
Source: "uv.exe"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "{app}\uv.exe"; Parameters: "sync"; WorkingDir: "{app}"; StatusMsg: "Installing Python and dependencies (a few minutes on first install)..."; Flags: runhidden
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\scripts\install_shortcut.py"" --target tray"; WorkingDir: "{app}"; StatusMsg: "Creating the desktop shortcut..."; Flags: runhidden
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\scripts\tray_app.py"""; WorkingDir: "{app}"; Description: "Start Race Engineer now"; Flags: postinstall nowait
Filename: "http://localhost:8501/"; Description: "Open Race Engineer in the browser (first run lands on Setup)"; Flags: postinstall shellexec nowait skipifsilent

[UninstallRun]
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\scripts\stop_all.py"""; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "StopRig"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { The venv is a machine artifact - always removed. }
    DelTree(ExpandConstant('{app}\.venv'), True, True, True);
    { Race history and keys survive unless the user opts out (spec 3.2). }
    if DirExists(ExpandConstant('{app}\data')) or
       FileExists(ExpandConstant('{app}\.env')) then
    begin
      if MsgBox('Also delete your race history and saved keys ' +
                '(data folder and .env)?',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(ExpandConstant('{app}\data'), True, True, True);
        DeleteFile(ExpandConstant('{app}\.env'));
        RemoveDir(ExpandConstant('{app}'));
      end;
    end;
  end;
end;
```

- [ ] **Step 2: Create `installer/.gitignore`**

```
uv.exe
```

- [ ] **Step 3: Create `docs/RELEASING.md`**

```markdown
# Releasing Race Engineer (B2)

How the founder cuts a release that installed clients pick up (spec §7).

## One-time build-machine setup

1. Install Inno Setup 6: https://jrsoftware.org/isinfo.php (adds `ISCC.exe`,
   typically `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`).
2. Drop a current `uv.exe` at `installer\uv.exe` (gitignored): download
   `uv-x86_64-pc-windows-msvc.zip` from
   https://github.com/astral-sh/uv/releases/latest and extract `uv.exe`.

## Per release

1. **Build the artifacts** (bumps the version, refreshes the gitignored
   baked credential from `.env`, writes the zip + SHA256SUMS):

       .venv\Scripts\python.exe scripts\build_release.py --bump patch

   Use `--bump minor` for feature releases; omit `--bump` to rebuild the
   current version. Note the printed tag (e.g. `v0.1.1`) and SHA.

2. **Compile the installer** (version must match step 1's tag, no `v`):

       "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\race-engineer.iss /DAppVersion=0.1.1

   Output: `dist\RaceEngineer-Setup.exe`.

3. **Commit the version bump, tag, push:**

       git add pyproject.toml
       git commit -m "release: v0.1.1"
       git tag v0.1.1
       git push && git push --tags

4. **Create the GitHub Release** for the tag with all three assets:

       gh release create v0.1.1 dist\race-engineer-v0.1.1.zip dist\SHA256SUMS dist\RaceEngineer-Setup.exe --title v0.1.1 --notes "What changed"

   The zip + SHA256SUMS assets are what installed clients verify and
   apply (spec §5); the Setup.exe is for new installs.

5. Installed clients see "Update available (v0.1.1)" in the tray within
   the 6-hour check window (or immediately via "Check for updates").

## Rules

- **Tag-only channel:** clients only ever apply published release tags —
  never master. Don't publish a release from an unreviewed branch.
- The zip must ship with a matching `SHA256SUMS` asset or clients will
  not offer the update at all.
- The baked iRacing app credential rides in `core/config/_baked.py`
  inside the zip/installer (v1 acceptance, spec §2.3). It is gitignored —
  never commit it. The repo is public.
- SmartScreen will warn on the unsigned Setup.exe ("More info → Run
  anyway") — known v1 limitation (spec §5.3); Authenticode signing is a
  future improvement.
```

- [ ] **Step 4: Commit**

```bash
git add installer/race-engineer.iss installer/.gitignore docs/RELEASING.md
git commit -m "feat(installer): Inno Setup script + release checklist (B2 task 7)"
```

---

**Phase 1a checkpoint:** run the full suite — `.venv/Scripts/python.exe -m pytest -q` — everything green. Outcome so far: a friend can install (once the founder compiles the Setup.exe) and self-configure; no self-update yet.

---

# Phase 1b — updatable

### Task 8: `core/update/releases.py` — release lookup

**Files:**
- Create: `core/update/releases.py`
- Test: `tests/test_update_releases.py`

- [ ] **Step 1: Write the failing tests**

```python
"""check_for_update: GitHub payloads mocked, NO network (spec 9). The
fail-quiet contract matters most — the app must never break because the
update check did."""

import pytest

from core.update.releases import (
    UpdateInfo,
    check_for_update,
    download_zip,
    parse_tag,
)


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", content=b""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.content = content

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _release_payload(tag="v0.2.0", *, with_zip=True, with_sums=True, body="notes"):
    assets = []
    if with_zip:
        assets.append({
            "name": f"race-engineer-{tag}.zip",
            "browser_download_url": f"https://gh/{tag}.zip",
        })
    if with_sums:
        assets.append({
            "name": "SHA256SUMS",
            "browser_download_url": "https://gh/SHA256SUMS",
        })
    return {"tag_name": tag, "body": body, "assets": assets}


def _fake_get(release_json, sums_text="", *, release_status=200, sums_status=200):
    def get(url):
        if "SHA256SUMS" in url:
            return _FakeResp(sums_status, text=sums_text)
        return _FakeResp(release_status, json_data=release_json)
    return get


_SHA = "a" * 64


class TestParseTag:
    def test_parses_v_prefixed(self):
        assert parse_tag("v1.2.3") == (1, 2, 3)

    def test_parses_bare(self):
        assert parse_tag("1.2.3") == (1, 2, 3)

    def test_malformed_is_none(self):
        assert parse_tag("release-candidate") is None

    def test_numeric_compare_not_lexical(self):
        assert parse_tag("v0.10.0") > parse_tag("v0.9.9")


class TestCheckForUpdate:
    def test_newer_tag_returns_update_info(self):
        get = _fake_get(
            _release_payload("v0.2.0"),
            f"{_SHA}  race-engineer-v0.2.0.zip\n",
        )
        info = check_for_update("0.1.0", get=get)
        assert info == UpdateInfo(
            tag="v0.2.0", zip_url="https://gh/v0.2.0.zip",
            sha256=_SHA, notes="notes",
        )

    def test_same_version_returns_none(self):
        get = _fake_get(_release_payload("v0.1.0"), f"{_SHA}  x.zip\n")
        assert check_for_update("0.1.0", get=get) is None

    def test_older_release_returns_none(self):
        get = _fake_get(_release_payload("v0.0.9"), f"{_SHA}  x.zip\n")
        assert check_for_update("0.1.0", get=get) is None

    def test_missing_sums_asset_returns_none(self):
        # An update without a checksum is not offered (spec 5.4).
        get = _fake_get(_release_payload("v0.2.0", with_sums=False))
        assert check_for_update("0.1.0", get=get) is None

    def test_missing_zip_asset_returns_none(self):
        get = _fake_get(_release_payload("v0.2.0", with_zip=False))
        assert check_for_update("0.1.0", get=get) is None

    def test_sums_without_our_zip_line_returns_none(self):
        get = _fake_get(
            _release_payload("v0.2.0"), f"{_SHA}  something-else.zip\n"
        )
        assert check_for_update("0.1.0", get=get) is None

    def test_http_error_returns_none(self):
        get = _fake_get(_release_payload("v0.2.0"), release_status=503)
        assert check_for_update("0.1.0", get=get) is None

    def test_network_exception_returns_none(self):
        def get(url):
            raise OSError("no network")
        assert check_for_update("0.1.0", get=get) is None

    def test_malformed_tag_returns_none(self):
        get = _fake_get(_release_payload("nightly"), f"{_SHA}  x.zip\n")
        assert check_for_update("0.1.0", get=get) is None


class TestDownloadZip:
    def test_returns_bytes_on_200(self):
        def get(url):
            return _FakeResp(200, content=b"zipbytes")
        assert download_zip("https://gh/x.zip", get=get) == b"zipbytes"

    def test_raises_on_http_error(self):
        def get(url):
            return _FakeResp(404)
        with pytest.raises(RuntimeError):
            download_zip("https://gh/x.zip", get=get)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_update_releases.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.update.releases'`

- [ ] **Step 3: Write `core/update/releases.py`**

```python
"""GitHub Releases lookup for the update channel (B2, spec 5.1/5.4).

PURE update logic: no process control, no Streamlit. Only release TAGS
are ever considered — never a branch ref; unreviewed commits cannot
reach a client. check_for_update is fail-quiet (None on any failure,
logged) because the app must never break over a failed update check.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

RELEASES_LATEST_URL = (
    "https://api.github.com/repos/marmalard/race-engineer/releases/latest"
)


@dataclass(frozen=True)
class UpdateInfo:
    tag: str
    zip_url: str
    sha256: str
    notes: str


def parse_tag(tag: str) -> tuple[int, int, int] | None:
    """'v1.2.3' or '1.2.3' -> (1, 2, 3); None when malformed."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    if match is None:
        return None
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def _default_get(url: str):
    import httpx

    return httpx.get(url, follow_redirects=True, timeout=30.0)


def _sha_for(sums_text: str, zip_name: str) -> str | None:
    """The 64-hex digest on the SHA256SUMS line naming zip_name."""
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == zip_name:
            if re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                return parts[0].lower()
    return None


def check_for_update(
    current_version: str, *, get: Callable | None = None
) -> UpdateInfo | None:
    """The latest release, when strictly newer than current_version and
    carrying both the zip asset and its SHA256SUMS. None otherwise."""
    get = get or _default_get
    try:
        resp = get(RELEASES_LATEST_URL)
        if resp.status_code != 200:
            return None
        release = resp.json()
        tag = release.get("tag_name", "")
        latest, current = parse_tag(tag), parse_tag(current_version)
        if latest is None or current is None or latest <= current:
            return None
        assets = {a.get("name"): a for a in release.get("assets", [])}
        zip_name = f"race-engineer-{tag}.zip"
        zip_asset = assets.get(zip_name)
        sums_asset = assets.get("SHA256SUMS")
        if zip_asset is None or sums_asset is None:
            return None  # no checksum, no offer (spec 5.4)
        sums_resp = get(sums_asset["browser_download_url"])
        if sums_resp.status_code != 200:
            return None
        sha = _sha_for(sums_resp.text, zip_name)
        if sha is None:
            return None
        return UpdateInfo(
            tag=tag,
            zip_url=zip_asset["browser_download_url"],
            sha256=sha,
            notes=release.get("body") or "",
        )
    except Exception:  # noqa: BLE001 — fail-quiet by contract
        logger.warning("update check failed", exc_info=True)
        return None


def download_zip(url: str, *, get: Callable | None = None) -> bytes:
    """The release zip bytes; raises on any HTTP failure (the caller's
    update flow reports it — downloading is already user-consented)."""
    get = get or _default_get
    resp = get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"download failed: HTTP {resp.status_code} for {url}")
    return resp.content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_update_releases.py -q`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add core/update/releases.py tests/test_update_releases.py
git commit -m "feat(update): tag-only GitHub release lookup with SHA256SUMS gate (B2 task 8)"
```

---

### Task 9: `core/update/apply.py` — verify + selective swap

**Files:**
- Create: `core/update/apply.py`
- Test: `tests/test_update_apply.py`

- [ ] **Step 1: Write the failing tests**

```python
"""apply_update (the crux, spec 9): SHA mismatch writes NOTHING;
selective swap replaces code and preserves data/, .env, .venv."""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from core.update.apply import (
    UpdateApplyError,
    UpdateVerificationError,
    apply_update,
)


def _make_zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _good_zip() -> bytes:
    return _make_zip({
        "app/pages/new.py": "new app code",
        "core/update/new.py": "new core code",
        "scripts/new.py": "new script",
        "pyproject.toml": '[project]\nversion = "0.2.0"\n',
        "uv.lock": "new lock",
        ".python-version": "3.14",
    })


def _install_root(tmp_path: Path) -> Path:
    root = tmp_path / "RaceEngineer"
    for entry in ("app", "core", "scripts"):
        (root / entry).mkdir(parents=True)
        (root / entry / "old.py").write_text("old", encoding="utf-8")
    (root / "pyproject.toml").write_text("old", encoding="utf-8")
    (root / "uv.lock").write_text("old", encoding="utf-8")
    (root / ".python-version").write_text("old", encoding="utf-8")
    # The preserved trio:
    (root / "data").mkdir()
    (root / "data" / "races.db").write_bytes(b"race history")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-friend\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "python.exe").write_bytes(b"venv bits")
    (root / "uv.exe").write_bytes(b"uv bits")
    return root


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


class TestVerification:
    def test_sha_mismatch_raises_and_writes_nothing(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        with pytest.raises(UpdateVerificationError):
            apply_update(blob, "0" * 64, root)
        # NOTHING changed — old code intact.
        assert (root / "app" / "old.py").read_text(encoding="utf-8") == "old"
        assert (root / "pyproject.toml").read_text(encoding="utf-8") == "old"

    def test_sha_comparison_is_case_insensitive(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        apply_update(blob, _sha(blob).upper(), root)
        assert (root / "app" / "pages" / "new.py").exists()


class TestSelectiveSwap:
    def test_swap_replaces_code_entries(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        apply_update(blob, _sha(blob), root)
        assert not (root / "app" / "old.py").exists()
        assert (root / "app" / "pages" / "new.py").read_text(
            encoding="utf-8"
        ) == "new app code"
        assert (root / "uv.lock").read_text(encoding="utf-8") == "new lock"

    def test_swap_preserves_data_env_venv_and_uv(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        apply_update(blob, _sha(blob), root)
        assert (root / "data" / "races.db").read_bytes() == b"race history"
        assert (root / ".env").read_text(encoding="utf-8") == (
            "ANTHROPIC_API_KEY=sk-friend\n"
        )
        assert (root / ".venv" / "python.exe").read_bytes() == b"venv bits"
        assert (root / "uv.exe").read_bytes() == b"uv bits"


class TestMalformedInput:
    def test_not_a_zip_raises_apply_error_and_writes_nothing(self, tmp_path):
        root = _install_root(tmp_path)
        blob = b"definitely not a zip"
        with pytest.raises(UpdateApplyError):
            apply_update(blob, _sha(blob), root)
        assert (root / "app" / "old.py").exists()

    def test_zip_missing_entries_raises_and_writes_nothing(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _make_zip({"app/pages/new.py": "only the app dir"})
        with pytest.raises(UpdateApplyError):
            apply_update(blob, _sha(blob), root)
        assert (root / "core" / "old.py").exists()

    def test_zip_slip_member_raises(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _make_zip({"../evil.py": "escape"})
        with pytest.raises(UpdateApplyError):
            apply_update(blob, _sha(blob), root)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_update_apply.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.update.apply'`

- [ ] **Step 3: Write `core/update/apply.py`**

```python
"""Verify-then-swap update application (B2, spec 5.1).

Order of operations is the safety story: sha256 gate BEFORE any write,
full extraction + layout validation in a temp dir, and only then the
selective swap of RELEASE_ENTRIES into the install root. data/, .env,
.venv and uv.exe are preserved by never being swap targets.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from core.update.manifest import RELEASE_ENTRIES


class UpdateVerificationError(Exception):
    """The downloaded zip does not match the published SHA-256."""


class UpdateApplyError(Exception):
    """The zip is malformed or its layout is not a release zip."""


def apply_update(
    zip_bytes: bytes, expected_sha256: str, install_root: Path
) -> None:
    """Verify zip_bytes against expected_sha256, then selectively swap
    RELEASE_ENTRIES into install_root. Raises before writing anything on
    verification or layout failure."""
    digest = hashlib.sha256(zip_bytes).hexdigest()
    if digest != expected_sha256.strip().lower():
        raise UpdateVerificationError(
            f"sha256 mismatch: got {digest}, expected {expected_sha256}"
        )

    install_root = Path(install_root)
    with tempfile.TemporaryDirectory(prefix="race-engineer-update-") as td:
        staged = Path(td)
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for name in zf.namelist():
                    part = Path(name)
                    if part.is_absolute() or ".." in part.parts:
                        raise UpdateApplyError(f"unsafe zip member: {name}")
                zf.extractall(staged)
        except zipfile.BadZipFile as exc:
            raise UpdateApplyError(f"malformed zip: {exc}") from exc

        missing = [e for e in RELEASE_ENTRIES if not (staged / e).exists()]
        if missing:
            raise UpdateApplyError(f"zip missing expected entries: {missing}")

        # Validate-then-swap: nothing above touched install_root.
        for entry in RELEASE_ENTRIES:
            dest = install_root / entry
            if dest.is_dir():
                shutil.rmtree(dest)
            elif dest.exists():
                dest.unlink()
            shutil.move(str(staged / entry), str(dest))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_update_apply.py -q`
Expected: 7 passed

- [ ] **Step 5: End-to-end sanity — the real zip applies to a fake install**

Run this one-off in the worktree, from the repo root (Bash tool — builds a real zip with build_release, applies it to a temp install root):

```bash
.venv/Scripts/python.exe - <<'EOF'
import sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
from core.update.apply import apply_update
from scripts.build_release import build_zip

root = Path(".")
with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "r.zip"
    sha = build_zip(root, out)
    install = Path(td) / "install"
    (install / "data").mkdir(parents=True)
    (install / "data" / "keep.txt").write_text("x")
    (install / ".env").write_text("KEY=v")
    apply_update(out.read_bytes(), sha, install)
    assert (install / "pyproject.toml").exists()
    assert (install / "data" / "keep.txt").read_text() == "x"
    assert (install / ".env").read_text() == "KEY=v"
    print("real-zip round trip OK")
EOF
```

Expected: `real-zip round trip OK` (this proves build_release's flat layout and apply_update's expectations agree — the coupling the two test files each assume).

- [ ] **Step 6: Commit**

```bash
git add core/update/apply.py tests/test_update_apply.py
git commit -m "feat(update): sha-gated selective-swap apply_update (B2 task 9)"
```

---

### Task 10: Tray update orchestration

**Files:**
- Modify: `scripts/tray_app.py`
- Test: `tests/test_tray_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tray_app.py`:

```python
class TestUpdateLabel:
    def test_no_update_reads_check(self):
        assert tray_app.update_label(None) == "Check for updates"

    def test_available_update_names_the_tag(self):
        from core.update.releases import UpdateInfo

        info = UpdateInfo("v0.2.0", "https://gh/z.zip", "a" * 64, "")
        assert tray_app.update_label(info) == (
            "Update available (v0.2.0) - install"
        )


class TestCheckNow:
    def test_dev_checkout_never_calls_the_network(self, monkeypatch):
        # No uv.exe beside the code -> git manages updates, not the tray.
        def boom(*a, **k):
            raise AssertionError("check_for_update must not be called in dev")

        monkeypatch.setattr(tray_app, "check_for_update", boom)
        assert tray_app._check_now() is None


class TestRunUpdateFlow:
    def _info(self):
        from core.update.releases import UpdateInfo

        return UpdateInfo("v0.2.0", "https://gh/z.zip", "a" * 64, "")

    def test_success_runs_stop_download_apply_sync_restart(self):
        calls = []
        ok = tray_app.run_update_flow(
            self._info(),
            stop_rig=lambda: calls.append("stop"),
            download=lambda url: calls.append(("download", url)) or b"zip",
            apply=lambda blob, sha: calls.append(("apply", blob, sha)),
            sync=lambda: calls.append("sync"),
            restart=lambda: calls.append("restart"),
            log=lambda msg: None,
        )
        assert ok is True
        assert calls == [
            "stop",
            ("download", "https://gh/z.zip"),
            ("apply", b"zip", "a" * 64),
            "sync",
            "restart",
        ]

    def test_download_failure_restarts_old_code_and_returns_false(self):
        calls = []

        def bad_download(url):
            raise RuntimeError("404")

        ok = tray_app.run_update_flow(
            self._info(),
            stop_rig=lambda: calls.append("stop"),
            download=bad_download,
            apply=lambda blob, sha: calls.append("apply"),
            sync=lambda: calls.append("sync"),
            restart=lambda: calls.append("restart"),
            log=lambda msg: calls.append(("log", msg)),
        )
        assert ok is False
        assert "apply" not in calls and "sync" not in calls
        assert calls[-1] == "restart"  # rig comes back up on the old code

    def test_verification_failure_never_syncs(self):
        from core.update.apply import UpdateVerificationError

        calls = []

        def bad_apply(blob, sha):
            raise UpdateVerificationError("mismatch")

        ok = tray_app.run_update_flow(
            self._info(),
            stop_rig=lambda: calls.append("stop"),
            download=lambda url: b"zip",
            apply=bad_apply,
            sync=lambda: calls.append("sync"),
            restart=lambda: calls.append("restart"),
            log=lambda msg: None,
        )
        assert ok is False
        assert "sync" not in calls
        assert "restart" in calls

    def test_sync_failure_still_restarts_and_reports_success(self):
        # Deps are additive - the old .venv still works (spec 5.2).
        calls = []

        def bad_sync():
            raise RuntimeError("uv exploded")

        ok = tray_app.run_update_flow(
            self._info(),
            stop_rig=lambda: None,
            download=lambda url: b"zip",
            apply=lambda blob, sha: None,
            sync=bad_sync,
            restart=lambda: calls.append("restart"),
            log=lambda msg: calls.append(("log", msg)),
        )
        assert ok is True
        assert "restart" in calls
```

Also update the EXISTING `TestMenuSpec.test_menu_labels_exact` list in place — insert `"Check for updates"` between `"Status"` and `"Start voice coach"` so the 9-item list reads:

```python
        assert labels == [
            "Open Race Engineer",
            "Status",
            "Check for updates",
            "Start voice coach",
            "Stop voice coach",
            "Start watcher",
            "Stop watcher",
            "Stop everything",
            "Quit (stops everything)",
        ]
```

Do NOT add a second label test. `TestMenuSpec.test_every_item_has_an_action_except_status` needs no change — "Check for updates" gets a real action.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tray_app.py -q`
Expected: FAIL — `AttributeError: ... 'update_label'` plus the label-list mismatch

- [ ] **Step 3: Implement in `scripts/tray_app.py`**

Add imports after the existing `from scripts.launch import ...` block:

```python
from core.update.apply import apply_update  # noqa: E402
from core.update.manifest import is_installed_layout  # noqa: E402
from core.update.releases import (  # noqa: E402
    UpdateInfo,
    check_for_update,
    download_zip,
)
from core.update.version import get_version  # noqa: E402
```

Add after the watchdog section (before `MenuItemSpec`):

```python
# --- update channel (B2 spec 5.2) ------------------------------------------
# The tray owns the WHEN: a slow background check caches the result; the
# apply is consent-gated (a menu click) because the file swap needs the
# rig stopped anyway. Dev checkouts (no bundled uv.exe) never check —
# git manages those.

UPDATE_CHECK_INTERVAL_S = 6 * 3600.0

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_available_update: UpdateInfo | None = None


def update_label(info: UpdateInfo | None) -> str:
    """Menu text for the update item (pure, exact-string tested)."""
    if info is not None:
        return f"Update available ({info.tag}) - install"
    return "Check for updates"


def _update_label_live(_item=None) -> str:
    return update_label(_available_update)


def _update_log(message: str) -> None:
    try:
        log_dir = _ROOT / "data" / "run"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().isoformat(timespec="seconds")
        with open(log_dir / "update.log", "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except OSError:
        pass  # logging must never block an update


def _check_now() -> UpdateInfo | None:
    if not is_installed_layout(_ROOT):
        return None
    return check_for_update(get_version())


def _uv_sync() -> None:
    import subprocess

    result = subprocess.run(
        [str(_ROOT / "uv.exe"), "sync"],
        cwd=str(_ROOT), capture_output=True,
        creationflags=_CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"uv sync exited {result.returncode}: {result.stderr[-500:]}"
        )


def run_update_flow(
    info: UpdateInfo,
    *,
    stop_rig: Callable[[], None],
    download: Callable[[str], bytes],
    apply: Callable[[bytes, str], None],
    sync: Callable[[], None],
    restart: Callable[[], None],
    log: Callable[[str], None],
) -> bool:
    """stop -> download -> verify+swap -> sync -> restart (spec 5.2).

    Injected side effects (watchdog_tick precedent). Any failure before
    the swap leaves the previous install intact; the rig is restarted on
    whatever code is present either way. Returns True when the new code
    is in place.
    """
    try:
        stop_rig()
        blob = download(info.zip_url)
        apply(blob, info.sha256)
        log(f"update {info.tag}: verified and swapped")
    except Exception as exc:  # noqa: BLE001 — reported, old code restored
        log(f"update {info.tag} FAILED: {exc}")
        restart()
        return False
    try:
        sync()
    except Exception as exc:  # noqa: BLE001 — old .venv still works
        log(f"update {info.tag}: uv sync failed ({exc}); "
            "old dependencies still in place")
    restart()
    log(
        f"update {info.tag}: done - rig restarted "
        "(quit and reopen the tray to update it too)"
    )
    return True


def _do_update() -> None:
    """Menu action: check when nothing is cached, apply when it is."""
    global _available_update
    if _available_update is None:
        _available_update = _check_now()
        return
    ok = run_update_flow(
        _available_update,
        stop_rig=_stop_rig,
        download=download_zip,
        apply=lambda blob, sha: apply_update(blob, sha, _ROOT),
        sync=_uv_sync,
        restart=_start_rig,
        log=_update_log,
    )
    if ok:
        _available_update = None


def _update_check_loop() -> None:
    global _available_update
    while True:
        try:
            if _available_update is None:
                _available_update = _check_now()
        except Exception:  # noqa: BLE001 — the checker never dies
            pass
        time.sleep(UPDATE_CHECK_INTERVAL_S)
```

Update `menu_spec()` — insert after the Status item:

```python
        MenuItemSpec("Check for updates", _guard(_do_update)),
```

In `main()`, bind the dynamic label (mirror the Status pattern) — the loop becomes:

```python
    for spec in menu_spec():
        if spec.label == "Status":
            items.append(pystray.MenuItem(_live_status, None, enabled=False))
        elif spec.label == "Check for updates":
            items.append(pystray.MenuItem(_update_label_live, spec.action))
        elif spec.action is None:  # Quit: stop the rig, then the tray
            def _quit(icon, _item) -> None:
                _guard(_stop_rig)()
                icon.stop()

            items.append(pystray.MenuItem(spec.label, _quit))
        else:
            items.append(pystray.MenuItem(spec.label, spec.action))
```

And start the check thread next to the watchdog (non-smoke path):

```python
    _start_rig()
    threading.Thread(target=_watchdog_loop, daemon=True).start()
    threading.Thread(target=_update_check_loop, daemon=True).start()
    icon.run()
```

- [ ] **Step 4: Run the tray tests + smoke**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tray_app.py -q`
Expected: all pass (old + new).

Run: `.venv/Scripts/python.exe scripts/tray_app.py --smoke`
Expected: exit 0 (icon + menu build; no processes touched).

- [ ] **Step 5: Commit**

```bash
git add scripts/tray_app.py tests/test_tray_app.py
git commit -m "feat(tray): consent-gated update check + apply flow (B2 task 10)"
```

---

### Task 11: Full suite, docs, finish

**Files:**
- Modify: `CLAUDE.md` (status section)

- [ ] **Step 1: Full test suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all green (~800 existing + ~50 new). Fix anything red before proceeding.

- [ ] **Step 2: Update `CLAUDE.md`**

Add a status section after "System-Tray App (B1)" summarizing what shipped (mirror the style of existing sections): new modules (`core/update/`, `core/config/env_setup.py`, `app/pages/setup.py`, `installer/`, `scripts/build_release.py`, `docs/RELEASING.md`), the two spec amendments (flat install layout; build-time-injected `_baked.py` because the repo is public), the `--target tray` shortcut change, and the open on-machine acceptance items (compile Setup.exe, install on a clean machine or VM, cut release v0.1.1 and watch a client update).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: B2 friend installer status (CLAUDE.md)"
```

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch. Post-merge reminders (standing rules): restart the production app (new `core.config`/`core.update` names = hybrid-module ImportError risk), kill stray `launch.py` processes first.

---

## Founder acceptance (not agent-executable — after merge)

1. Install Inno Setup 6 + drop `installer/uv.exe` (RELEASING.md one-time setup).
2. `build_release.py` → ISCC → install `RaceEngineer-Setup.exe` on a clean machine/VM (or a temp user account): three keys in Setup page → working Start page. SmartScreen "run anyway" expected.
3. Cut `v0.1.1`, publish the release, click "Update available" on the installed client: verify `data/` + `.env` survive and the app comes back on the new version.
4. Uninstall: confirm the data prompt appears and declining preserves `data/`+`.env`.
