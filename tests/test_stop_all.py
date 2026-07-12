"""Tests for the pure PID-list parser in scripts/stop_all.py."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "stop_all",
    Path(__file__).resolve().parent.parent / "scripts" / "stop_all.py",
)
stop_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stop_all)


def test_parse_pids_extracts_integers():
    out = "1234\n5678\n"
    assert stop_all._parse_pids(out) == [1234, 5678]


def test_parse_pids_ignores_blank_and_nonnumeric_lines():
    out = "\n  9012 \nProcessId\n---\n3456\n"
    assert stop_all._parse_pids(out) == [9012, 3456]


def test_parse_pids_empty_output():
    assert stop_all._parse_pids("") == []


_launch_spec = importlib.util.spec_from_file_location(
    "launch",
    Path(__file__).resolve().parent.parent / "scripts" / "launch.py",
)
launch = importlib.util.module_from_spec(_launch_spec)
_launch_spec.loader.exec_module(launch)


def test_fragments_match_launchers_streamlit_command():
    """stop_all must recognize the exact command launch.py starts."""
    import subprocess as sp
    cmdline = sp.list2cmdline(launch.STREAMLIT_CMD)
    for frag in stop_all._CMDLINE_FRAGMENTS:
        assert frag in cmdline


def test_fragments_match_console_script_style():
    """The streamlit.exe console-script launch style must also match."""
    root = stop_all._ROOT
    cmdline = (
        f'"{root}\\.venv\\Scripts\\python.exe" '
        f'"{root}\\.venv\\Scripts\\streamlit.exe" run app/streamlit_app.py'
    )
    for frag in stop_all._CMDLINE_FRAGMENTS:
        assert frag in cmdline


def test_fragments_do_not_match_the_watcher():
    """The watcher's command line must never satisfy all fragments."""
    root = stop_all._ROOT
    cmdline = (
        f'"{root}\\.venv\\Scripts\\python.exe" scripts/watch_telemetry.py --watch'
    )
    assert not all(frag in cmdline for frag in stop_all._CMDLINE_FRAGMENTS)
