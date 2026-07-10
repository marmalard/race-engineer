"""Tests for ManagedProcess — real detached processes, throwaway run dir."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.live.process_control import ManagedProcess

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CREATE_NO_WINDOW = 0x08000000  # checker gets its own (hidden) console


@pytest.fixture
def proc(tmp_path):
    p = ManagedProcess("test-sleeper", SLEEPER, run_dir=tmp_path)
    yield p
    p.stop()  # never leak a sleeper past the test


def test_starts_and_reports_running(proc):
    pid = proc.start()
    assert pid > 0
    assert proc.is_running()
    assert proc.pid() == pid


def test_start_is_idempotent_while_running(proc):
    first = proc.start()
    second = proc.start()  # already running -> same pid, no second spawn
    assert second == first


def test_stop_terminates_and_clears_pidfile(proc, tmp_path):
    proc.start()
    assert proc.stop() is True
    # Termination is async on Windows; poll briefly.
    for _ in range(50):
        if not proc.is_running():
            break
        time.sleep(0.1)
    assert not proc.is_running()
    assert not (tmp_path / "test-sleeper.pid").exists()


def test_stop_when_not_running_returns_false(proc):
    assert proc.stop() is False


@pytest.mark.skipif(os.name != "nt", reason="Windows console-affinity bug")
def test_is_running_visible_from_another_console(proc, tmp_path):
    """A live process must report running from a checker in a DIFFERENT console.

    This is the Toolbox reality: Streamlit (its own console) checks a watcher
    spawned from a terminal. os.kill(pid, 0) on Windows is
    GenerateConsoleCtrlEvent(CTRL_C_EVENT), which only reaches process groups
    on the CALLER'S console — from any other console it raises WinError 87
    and a live process reads as stopped.
    """
    proc.start()
    assert proc.is_running()  # sanity: visible from the parent

    checker = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from pathlib import Path;"
        "from core.live.process_control import ManagedProcess;"
        "p = ManagedProcess('test-sleeper', [], run_dir=Path(sys.argv[2]));"
        "print(p.is_running())"
    )
    out = subprocess.run(
        [sys.executable, "-c", checker, str(_REPO_ROOT), str(tmp_path)],
        capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW,
    )
    assert out.stdout.strip() == "True", (
        f"stdout={out.stdout!r} stderr={out.stderr[-300:]!r}"
    )


def test_stale_pidfile_treated_as_not_running(tmp_path):
    p = ManagedProcess("test-sleeper", SLEEPER, run_dir=tmp_path)
    (tmp_path / "test-sleeper.pid").write_text("999999999")
    assert not p.is_running()
    pid = p.start()  # stale file must not block a fresh start
    assert pid > 0
    assert p.is_running()
    p.stop()


def test_log_file_captures_output(tmp_path):
    p = ManagedProcess(
        "test-echo",
        [sys.executable, "-c", "print('hello from child')"],
        run_dir=tmp_path,
    )
    p.start()
    log = tmp_path / "test-echo.log"
    for _ in range(50):
        if log.exists() and "hello from child" in log.read_text(encoding="utf-8", errors="replace"):
            break
        time.sleep(0.1)
    assert "hello from child" in log.read_text(encoding="utf-8", errors="replace")
