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
    # Register before exec so dataclasses can resolve cls.__module__ (Python 3.14+).
    import sys
    sys.modules.setdefault(name, module)
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
