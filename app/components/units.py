"""Unit conversion utilities for the coaching UI.

All core analysis uses SI units (m/s, meters, seconds).
These functions convert for display only.
"""

import numpy as np
from numpy.typing import NDArray

# Conversion constants
MS_TO_KMH = 3.6
MS_TO_MPH = 2.23694
M_TO_FT = 3.28084


def speed_value(m_per_s: float | NDArray, imperial: bool) -> float | NDArray:
    """Convert m/s to km/h or mph."""
    return m_per_s * MS_TO_MPH if imperial else m_per_s * MS_TO_KMH


def speed_unit(imperial: bool) -> str:
    """Return the speed unit label."""
    return "mph" if imperial else "km/h"


def distance_value(meters: float | NDArray, imperial: bool) -> float | NDArray:
    """Convert meters to feet or pass through."""
    return meters * M_TO_FT if imperial else meters


def distance_unit(imperial: bool) -> str:
    """Return the distance unit label."""
    return "ft" if imperial else "m"


def fmt_speed(m_per_s: float, imperial: bool, signed: bool = True) -> str:
    """Format a speed value with unit."""
    val = speed_value(m_per_s, imperial)
    unit = speed_unit(imperial)
    if signed:
        return f"{val:+.1f} {unit}"
    return f"{val:.1f} {unit}"


def fmt_distance(meters: float, imperial: bool, signed: bool = False) -> str:
    """Format a distance value with unit."""
    val = distance_value(meters, imperial)
    unit = distance_unit(imperial)
    if signed:
        return f"{val:+.1f}{unit}"
    return f"{val:.0f}{unit}"
