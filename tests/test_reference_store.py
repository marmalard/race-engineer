"""Tests for the reference lap store."""

from pathlib import Path

import numpy as np
import pytest

from core.benchmark.reference_store import ReferenceStore
from core.telemetry.normalizer import NormalizedLap


def _lap(lap_time: float = 100.0, n: int = 500) -> NormalizedLap:
    return NormalizedLap(
        lap_number=0,
        lap_time=lap_time,
        track_length=float(n),
        distance=np.arange(n, dtype=float),
        speed=np.full(n, 50.0),
        throttle=np.ones(n),
        brake=np.zeros(n),
        steering=np.zeros(n),
        gear=np.full(n, 4),
        rpm=np.full(n, 6000.0),
        lat=np.zeros(n),
        lon=np.zeros(n),
        elapsed_time=np.linspace(0, lap_time, n),
        is_valid=True,
    )


@pytest.fixture
def store(tmp_path: Path) -> ReferenceStore:
    return ReferenceStore(tmp_path / "refs.db")


def test_save_and_get_roundtrip(store):
    store.save("523", "BMW M2 CS Racing", _lap(), source="g61")
    ref = store.get("523", "BMW M2 CS Racing")
    assert ref is not None
    assert ref.source == "g61"
    np.testing.assert_allclose(ref.lap.speed, _lap().speed)
    assert ref.lap.lap_time == pytest.approx(100.0)


def test_get_missing_returns_none(store):
    assert store.get("999", "Nonexistent Car") is None


def test_g61_preferred_over_personal_best(store):
    store.save("523", "BMW M2 CS Racing", _lap(lap_time=99.0), source="personal_best")
    store.save("523", "BMW M2 CS Racing", _lap(lap_time=101.0), source="g61")
    ref = store.get("523", "BMW M2 CS Racing")
    assert ref.source == "g61"


def test_save_same_source_overwrites(store):
    store.save("523", "BMW M2 CS Racing", _lap(lap_time=100.0), source="g61")
    store.save("523", "BMW M2 CS Racing", _lap(lap_time=98.0), source="g61")
    ref = store.get("523", "BMW M2 CS Racing")
    assert ref.lap.lap_time == pytest.approx(98.0)
    assert len(store.list_all()) == 1


def test_list_all_metadata(store):
    store.save("523", "BMW M2 CS Racing", _lap(), source="g61", driver_name="A. Fast")
    entries = store.list_all()
    assert len(entries) == 1
    assert entries[0].track_id == "523"
    assert entries[0].car == "BMW M2 CS Racing"
    assert entries[0].driver_name == "A. Fast"
