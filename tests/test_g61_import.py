"""Tests for Garage 61 CSV import into NormalizedLap."""

from io import StringIO
from pathlib import Path

import numpy as np
import pytest

from core.benchmark.g61_import import G61ImportError, import_g61_csv
from core.telemetry.normalizer import NormalizedLap

FIXTURE = Path(__file__).parent / "fixtures" / "g61" / "reference.csv"

# Synthetic CSV in G61-like shape: 0.5m spacing, speed in km/h, pedals in %
def _synthetic_csv(n_rows: int = 4000, spacing: float = 0.5) -> StringIO:
    rows = ["Distance,Speed,Throttle,Brake,Gear,RPM,SteeringWheelAngle"]
    for i in range(n_rows):
        d = i * spacing
        speed_kmh = 200.0 - 100.0 * np.exp(-((d - 800) ** 2) / (2 * 60.0**2))
        brake = 80.0 if 700 <= d <= 780 else 0.0
        throttle = 0.0 if 700 <= d <= 850 else 100.0
        rows.append(f"{d},{speed_kmh},{throttle},{brake},4,6500,0.0")
    return StringIO("\n".join(rows))


def test_returns_normalized_lap_on_1m_grid():
    lap = import_g61_csv(_synthetic_csv(), track_length_m=2000.0)
    assert isinstance(lap, NormalizedLap)
    assert lap.distance[1] - lap.distance[0] == pytest.approx(1.0)
    assert lap.distance[-1] <= 2000.0


def test_speed_converted_to_ms():
    lap = import_g61_csv(_synthetic_csv(), track_length_m=2000.0)
    # 200 km/h = 55.6 m/s; if conversion is skipped values stay ~200
    assert lap.speed.max() == pytest.approx(200.0 / 3.6, abs=1.0)


def test_pedals_normalized_to_0_1():
    lap = import_g61_csv(_synthetic_csv(), track_length_m=2000.0)
    assert lap.brake.max() == pytest.approx(0.8, abs=0.05)
    assert lap.throttle.max() == pytest.approx(1.0, abs=0.05)


def test_elapsed_time_integrated_from_speed():
    lap = import_g61_csv(_synthetic_csv(), track_length_m=2000.0)
    assert np.all(np.diff(lap.elapsed_time) > 0)
    # Sanity: 2km at speeds between 100-200 km/h is ~40-70s
    assert 30.0 < lap.elapsed_time[-1] < 90.0
    assert lap.lap_time == pytest.approx(lap.elapsed_time[-1])


def test_unknown_columns_raise_with_found_headers():
    bad = StringIO("Foo,Bar\n1,2\n3,4")
    with pytest.raises(G61ImportError, match="Foo"):
        import_g61_csv(bad, track_length_m=2000.0)


@pytest.mark.skipif(not FIXTURE.exists(), reason="real G61 export not available")
def test_real_g61_export_imports():
    with open(FIXTURE) as f:
        lap = import_g61_csv(f, track_length_m=7004.0)  # Spa
    assert lap.is_valid
    assert 30.0 < lap.speed.max() < 100.0  # plausible m/s for a race car
    assert 100.0 < lap.lap_time < 200.0  # plausible Spa lap
