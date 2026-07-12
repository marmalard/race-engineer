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
