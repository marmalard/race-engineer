"""Tray app (B1): pure builders + the standing coupling rule — every
tray-spawned command must parse against the CLI it launches."""

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live_coach = _load_script("live_coach")

from scripts import launch  # noqa: E402
from scripts import tray_app  # noqa: E402


class TestSpawnCommandCoupling:
    def test_coach_command_parses_against_live_coach_cli(self):
        cmd = tray_app.coach_process().command
        args = live_coach.build_parser().parse_args(cmd[2:])
        # Bare spawn == CLI bare run: voice on, corner prompts ON.
        assert args.mute is False
        assert args.corner_prompts is True

    def test_watcher_command_is_the_launchers(self):
        assert tray_app.watcher_process().command == launch._watcher().command

    def test_app_command_is_the_launchers_streamlit_cmd(self):
        assert tray_app.app_process().command == launch.STREAMLIT_CMD

    def test_managed_names_match_the_rigs(self):
        # PID-file names must match Toolbox/launcher/stop_all or the
        # running/stopped state desyncs across surfaces.
        assert tray_app.coach_process().name == "live-coach"
        assert tray_app.watcher_process().name == "telemetry-watcher"
        assert tray_app.app_process().name == "streamlit-app"


class TestIcon:
    def test_icon_image_is_checkered_and_sized(self):
        img = tray_app.make_icon_image(64)
        assert img.size == (64, 64)
        # Opposite corners of a checkerboard differ.
        assert img.getpixel((1, 1)) != img.getpixel((1, 62))


class TestMenuSpec:
    def test_menu_labels_exact(self):
        labels = [item.label for item in tray_app.menu_spec()]
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

    def test_every_item_has_an_action_except_status(self):
        # Status has no action (display-only); Quit's action is bound in
        # main() to get the icon reference -- it is intentionally None here.
        no_action_labels = {"Status", "Quit (stops everything)"}
        for item in tray_app.menu_spec():
            if item.label in no_action_labels:
                assert item.action is None
            else:
                assert callable(item.action)


class TestStatusText:
    def test_status_text_composes_injected_parts(self):
        text = tray_app.status_text(
            app_up=True, watcher_up=True, watcher_when="2m ago",
            coach_up=False,
        )
        assert text == (
            "App: running \xb7 Watcher: running (2m ago) \xb7 Coach: stopped"
        )

    def test_status_text_all_down(self):
        text = tray_app.status_text(
            app_up=False, watcher_up=False, watcher_when=None, coach_up=False,
        )
        assert text == "App: stopped \xb7 Watcher: stopped \xb7 Coach: stopped"


class _FakeProc:
    """Stand-in for ManagedProcess — tests must NEVER touch the live rig."""

    def __init__(self, running: bool):
        self.running = running
        self.started = 0
        self.stopped = 0

    def is_running(self) -> bool:
        return self.running

    def start(self) -> int:
        self.started += 1
        self.running = True
        return 1

    def stop(self) -> bool:
        self.stopped += 1
        self.running = False
        return True


class TestWatchdog:
    def test_revives_dead_watcher_when_intended(self, tmp_path):
        proc = _FakeProc(running=False)
        log = tmp_path / "telemetry-watcher.log"
        assert tray_app.watchdog_tick(True, proc, log, "2026-07-15T22:00:00")
        assert proc.started == 1
        assert "[tray watchdog]" in log.read_text(encoding="utf-8")

    def test_leaves_running_watcher_alone(self, tmp_path):
        proc = _FakeProc(running=True)
        assert not tray_app.watchdog_tick(
            True, proc, tmp_path / "w.log", "t"
        )
        assert proc.started == 0

    def test_respects_deliberate_stop(self, tmp_path):
        # Stop watcher / Stop everything clear the intent flag — the
        # watchdog must never resurrect a deliberately stopped watcher.
        proc = _FakeProc(running=False)
        assert not tray_app.watchdog_tick(
            False, proc, tmp_path / "w.log", "t"
        )
        assert proc.started == 0

    def test_log_write_failure_does_not_block_revival(self, tmp_path):
        proc = _FakeProc(running=False)
        bad_log = tmp_path / "no-such-dir" / "w.log"
        assert tray_app.watchdog_tick(True, proc, bad_log, "t")
        assert proc.started == 1


class TestIntentWiring:
    def _action(self, label: str):
        return next(
            i for i in tray_app.menu_spec() if i.label == label
        ).action

    def test_start_watcher_sets_intent(self, monkeypatch):
        fake = _FakeProc(running=False)
        monkeypatch.setattr(tray_app, "watcher_process", lambda: fake)
        tray_app._watcher_intended.clear()
        self._action("Start watcher")()
        assert tray_app._watcher_intended.is_set()
        assert fake.started == 1

    def test_stop_watcher_clears_intent(self, monkeypatch):
        fake = _FakeProc(running=True)
        monkeypatch.setattr(tray_app, "watcher_process", lambda: fake)
        tray_app._watcher_intended.set()
        self._action("Stop watcher")()
        assert not tray_app._watcher_intended.is_set()
        assert fake.stopped == 1

    def test_stop_everything_clears_intent(self, monkeypatch):
        monkeypatch.setattr(tray_app, "_stop_everything", lambda: None)
        tray_app._watcher_intended.set()
        self._action("Stop everything")()
        assert not tray_app._watcher_intended.is_set()

    def test_start_rig_sets_intent(self, monkeypatch):
        fake_watcher = _FakeProc(running=False)
        monkeypatch.setattr(tray_app, "watcher_process", lambda: fake_watcher)
        monkeypatch.setattr(tray_app, "is_port_listening", lambda port: True)
        tray_app._watcher_intended.clear()
        tray_app._start_rig()
        assert tray_app._watcher_intended.is_set()
        assert fake_watcher.started == 1


class TestOpenRevivesTheRig:
    def test_open_app_starts_rig_then_waits_then_opens(self, monkeypatch):
        # Founder acceptance 2026-07-15: Stop everything left no way back —
        # Open must revive a dead rig before pointing a browser at it.
        calls = []
        monkeypatch.setattr(
            tray_app, "_start_rig", lambda: calls.append("start")
        )
        monkeypatch.setattr(
            tray_app, "wait_for_port",
            lambda port, timeout_s: calls.append(("wait", port)) or True,
        )
        monkeypatch.setattr(
            tray_app.webbrowser, "open", lambda url: calls.append(("open", url))
        )
        tray_app.open_app()
        assert calls == [
            "start", ("wait", tray_app.PORT), ("open", tray_app.URL),
        ]


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
