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
