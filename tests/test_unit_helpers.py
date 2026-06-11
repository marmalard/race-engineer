"""Tests for unit conversion helpers."""

import numpy as np
import pytest

from app.components.units import (
    M_TO_FT,
    MS_TO_KMH,
    MS_TO_MPH,
    distance_unit,
    distance_value,
    fmt_distance,
    fmt_speed,
    speed_unit,
    speed_value,
)


class TestSpeedValue:
    def test_metric(self) -> None:
        assert speed_value(10.0, imperial=False) == pytest.approx(36.0)

    def test_imperial(self) -> None:
        assert speed_value(10.0, imperial=True) == pytest.approx(10.0 * MS_TO_MPH)

    def test_array_metric(self) -> None:
        arr = np.array([10.0, 20.0, 30.0])
        result = speed_value(arr, imperial=False)
        np.testing.assert_allclose(result, arr * MS_TO_KMH)

    def test_array_imperial(self) -> None:
        arr = np.array([10.0, 20.0, 30.0])
        result = speed_value(arr, imperial=True)
        np.testing.assert_allclose(result, arr * MS_TO_MPH)


class TestDistanceValue:
    def test_metric_passthrough(self) -> None:
        assert distance_value(100.0, imperial=False) == 100.0

    def test_imperial(self) -> None:
        assert distance_value(100.0, imperial=True) == pytest.approx(100.0 * M_TO_FT)

    def test_array_imperial(self) -> None:
        arr = np.array([100.0, 200.0])
        result = distance_value(arr, imperial=True)
        np.testing.assert_allclose(result, arr * M_TO_FT)


class TestFmtSpeed:
    def test_metric_positive(self) -> None:
        result = fmt_speed(1.0, imperial=False)
        assert result == "+3.6 km/h"

    def test_imperial_positive(self) -> None:
        result = fmt_speed(1.0, imperial=True)
        assert "mph" in result
        assert result.startswith("+")

    def test_metric_negative(self) -> None:
        result = fmt_speed(-1.0, imperial=False)
        assert result == "-3.6 km/h"

    def test_unsigned(self) -> None:
        result = fmt_speed(1.0, imperial=False, signed=False)
        assert result == "3.6 km/h"


class TestFmtDistance:
    def test_metric(self) -> None:
        assert fmt_distance(1234.0, imperial=False) == "1234m"

    def test_imperial(self) -> None:
        result = fmt_distance(100.0, imperial=True)
        assert "ft" in result
        assert result == "328ft"

    def test_signed_metric(self) -> None:
        result = fmt_distance(5.0, imperial=False, signed=True)
        assert result == "+5.0m"

    def test_signed_imperial(self) -> None:
        result = fmt_distance(-3.0, imperial=True, signed=True)
        assert "ft" in result
        assert result.startswith("-")


class TestUnitLabels:
    def test_speed_unit_metric(self) -> None:
        assert speed_unit(imperial=False) == "km/h"

    def test_speed_unit_imperial(self) -> None:
        assert speed_unit(imperial=True) == "mph"

    def test_distance_unit_metric(self) -> None:
        assert distance_unit(imperial=False) == "m"

    def test_distance_unit_imperial(self) -> None:
        assert distance_unit(imperial=True) == "ft"
