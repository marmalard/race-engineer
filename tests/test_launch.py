"""Tests for the pure port helpers in scripts/launch.py."""

import importlib.util
import socket
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "launch",
    Path(__file__).resolve().parent.parent / "scripts" / "launch.py",
)
launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launch)


def _free_port() -> int:
    """A port number nothing is listening on (bound then released)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_is_port_listening_true_for_open_socket():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert launch.is_port_listening(port) is True
    finally:
        srv.close()


def test_is_port_listening_false_for_closed_port():
    assert launch.is_port_listening(_free_port()) is False


def test_wait_for_port_returns_true_immediately_when_open():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert launch.wait_for_port(port, timeout_s=1.0, interval_s=0.05) is True
    finally:
        srv.close()


def test_wait_for_port_times_out_for_closed_port():
    start = time.monotonic()
    ok = launch.wait_for_port(_free_port(), timeout_s=0.2, interval_s=0.05)
    elapsed = time.monotonic() - start
    assert ok is False
    assert elapsed < 1.0  # honored the short timeout, did not hang
