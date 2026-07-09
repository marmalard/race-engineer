"""Tests for ManagedProcess — real detached processes, throwaway run dir."""

import sys
import time

import pytest

from core.live.process_control import ManagedProcess

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


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
