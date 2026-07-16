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
- **Restart-critical changes need a note.** After an update applies, the
  RUNNING tray restarts the rig with its OLD in-memory code — new
  `scripts/` land on disk but don't execute until the tray is quit and
  reopened. If a release changes `STREAMLIT_CMD`, ManagedProcess PID-file
  names, `_start_rig`/`stop_all` semantics, or the `run_update_flow`
  contract, say so in the release notes (users should Quit + reopen the
  tray) — and never change PID names and the restart path in the same
  release without thinking through the old-tray-restarts-new-rig seam.
