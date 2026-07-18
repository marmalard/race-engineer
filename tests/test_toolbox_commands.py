"""Coupling tests: the Toolbox's spawn commands must parse against the
actual CLIs they launch.

Why this exists: round 2 (2026-07-10) renamed the coach's --corner-prompts
flag to --no-corner-prompts, the Toolbox kept passing the old flag, and on
2026-07-14 the coach died at startup with an argparse usage error the moment
the user actually used the Toolbox button. Nothing could catch that drift —
these tests do.
"""

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


live_coach = _load_script("live_coach")

# toolbox imports streamlit; that's fine headless, we only call the pure
# command builders.
from app.pages.toolbox import _coach, _watcher  # noqa: E402


@pytest.mark.parametrize("mute", [False, True])
@pytest.mark.parametrize("prompts", [False, True])
def test_toolbox_coach_command_parses_against_live_coach_cli(mute, prompts):
    cmd = _coach(mute=mute, corner_prompts=prompts).command
    flags = cmd[2:]  # [python, script, *flags]
    args = live_coach.build_parser().parse_args(flags)  # must not SystemExit
    assert args.mute is mute
    assert args.corner_prompts is prompts


def test_toolbox_watcher_command_uses_documented_flag():
    # watch_telemetry's parser is built inline; asserting the exact flag
    # list keeps the Toolbox honest without refactoring that CLI.
    cmd = _watcher().command
    assert cmd[2:] == ["--watch"]


def test_toolbox_coach_defaults_match_cli_defaults():
    """The Toolbox's no-argument spawn must mean the same thing as running
    the CLI bare: voice on, corner prompts ON (round-2 default)."""
    cmd = _coach().command
    flags = cmd[2:]
    args = live_coach.build_parser().parse_args(flags)
    assert args.mute is False
    assert args.corner_prompts is True


@pytest.mark.parametrize("engineer", [False, True])
def test_toolbox_engineer_flag_parses_against_live_coach_cli(engineer):
    cmd = _coach(engineer=engineer).command
    args = live_coach.build_parser().parse_args(cmd[2:])
    assert args.engineer is engineer


def test_engineer_defaults_on_in_both_cli_and_toolbox():
    assert live_coach.build_parser().parse_args([]).engineer is True
    cmd = _coach().command
    assert live_coach.build_parser().parse_args(cmd[2:]).engineer is True
