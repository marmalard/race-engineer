"""Distance-based normalization of telemetry data.

Converts time-series telemetry (sampled at 60Hz) into distance-based
telemetry (sampled every N meters, default 1m). This creates a common
x-axis for comparing laps to each other and to external benchmarks.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d


@dataclass
class NormalizedLap:
    """A single lap with all channels resampled to uniform distance intervals."""

    lap_number: int
    lap_time: float
    track_length: float  # meters
    distance: np.ndarray  # uniform grid, 0 to track_length
    speed: np.ndarray  # m/s
    throttle: np.ndarray  # 0.0 to 1.0
    brake: np.ndarray  # 0.0 to 1.0
    steering: np.ndarray  # radians
    gear: np.ndarray  # integer
    rpm: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    elapsed_time: np.ndarray  # cumulative time from lap start at each distance point
    is_valid: bool


class Normalizer:
    """Normalize time-series telemetry to distance-based."""

    def __init__(self, distance_interval: float = 1.0):
        self.distance_interval = distance_interval

    def normalize_lap(
        self,
        lap_df: pd.DataFrame,
        lap_number: int,
        track_length_m: float,
    ) -> NormalizedLap:
        """Convert a single lap's time-series data to distance-based.

        Args:
            lap_df: DataFrame from IBTParser.get_laps() with columns including
                    LapDist, Speed, Throttle, Brake, etc.
            lap_number: The lap number for identification.
            track_length_m: Expected track length in meters.

        Returns:
            NormalizedLap with all channels at consistent distance intervals.
        """
        is_valid = self._validate_lap(lap_df, track_length_m)

        # Trim trailing stationary data (car stopped at end of session)
        lap_df = self._trim_stationary_tail(lap_df)

        # Get the raw distance values
        raw_dist = lap_df["LapDist"].values.astype(np.float64)

        # Handle duplicate distances (stationary or very slow)
        raw_dist, unique_mask = self._deduplicate_distances(raw_dist)

        # Create the uniform distance grid
        dist_max = min(raw_dist[-1], track_length_m)
        distance_grid = np.arange(0, dist_max, self.distance_interval)

        if len(distance_grid) == 0:
            return self._empty_lap(lap_number, track_length_m, is_valid=False)

        # Compute elapsed time from SessionTime
        elapsed_time_raw = self._compute_elapsed_time(lap_df, unique_mask)

        # Interpolate each channel onto the distance grid
        speed = self._interpolate_channel(
            raw_dist, lap_df["Speed"].values[unique_mask], distance_grid, kind="linear"
        )
        throttle = self._interpolate_channel(
            raw_dist, lap_df["Throttle"].values[unique_mask], distance_grid, kind="linear"
        )
        brake = self._interpolate_channel(
            raw_dist, lap_df["Brake"].values[unique_mask], distance_grid, kind="linear"
        )
        elapsed_time = self._interpolate_channel(
            raw_dist, elapsed_time_raw, distance_grid, kind="linear"
        )

        # Optional channels with fallbacks
        steering = self._interpolate_optional(
            lap_df, "SteeringWheelAngle", raw_dist, unique_mask, distance_grid, kind="linear"
        )
        rpm = self._interpolate_optional(
            lap_df, "RPM", raw_dist, unique_mask, distance_grid, kind="linear"
        )
        gear = self._interpolate_optional(
            lap_df, "Gear", raw_dist, unique_mask, distance_grid, kind="nearest"
        )
        lat = self._interpolate_optional(
            lap_df, "Lat", raw_dist, unique_mask, distance_grid, kind="linear"
        )
        lon = self._interpolate_optional(
            lap_df, "Lon", raw_dist, unique_mask, distance_grid, kind="linear"
        )

        # Clamp values to physical bounds
        throttle = np.clip(throttle, 0.0, 1.0)
        brake = np.clip(brake, 0.0, 1.0)
        speed = np.maximum(speed, 0.0)

        # Compute lap time from elapsed time
        lap_time = float(elapsed_time[-1]) if len(elapsed_time) > 0 else 0.0

        return NormalizedLap(
            lap_number=lap_number,
            lap_time=lap_time,
            track_length=track_length_m,
            distance=distance_grid,
            speed=speed,
            throttle=throttle,
            brake=brake,
            steering=steering,
            gear=gear,
            rpm=rpm,
            lat=lat,
            lon=lon,
            elapsed_time=elapsed_time,
            is_valid=is_valid,
        )

    def normalize_session(
        self,
        laps: list[pd.DataFrame],
        lap_numbers: list[int],
        track_length_m: float,
    ) -> list[NormalizedLap]:
        """Normalize all laps in a session.

        Args:
            laps: List of DataFrames from IBTParser.get_laps().
            lap_numbers: Corresponding lap numbers.
            track_length_m: Expected track length in meters.

        Returns:
            List of NormalizedLap objects (only valid laps included).
        """
        normalized: list[NormalizedLap] = []
        for lap_df, lap_num in zip(laps, lap_numbers):
            nlap = self.normalize_lap(lap_df, lap_num, track_length_m)
            if nlap.is_valid:
                normalized.append(nlap)
        return normalized

    def _validate_lap(self, lap_df: pd.DataFrame, track_length_m: float) -> bool:
        """Check if a lap is valid for normalization."""
        if "LapDist" not in lap_df.columns:
            return False

        dist = lap_df["LapDist"].values
        if len(dist) < 100:
            return False

        # Check distance coverage (at least 90% of track)
        dist_range = dist.max() - dist.min()
        if track_length_m > 0 and dist_range < track_length_m * 0.90:
            return False

        # Check for large distance jumps while the car is moving
        # (jumps while stationary are harmless — session resets, etc.)
        dist_diffs = np.diff(dist)
        if "Speed" in lap_df.columns:
            speed = lap_df["Speed"].values[:-1]
            moving = speed > 1.0  # m/s threshold
            if np.any((dist_diffs > 50) & moving):
                return False
            if np.any((dist_diffs < -100) & moving):
                return False
        else:
            if np.any(dist_diffs > 50):
                return False
            if np.any(dist_diffs < -100):
                return False

        return True

    def _trim_stationary_tail(self, lap_df: pd.DataFrame) -> pd.DataFrame:
        """Trim trailing samples where the car is stationary.

        At the end of a session, the car may sit still while iRacing
        records samples. These have zero speed and can cause distance jumps.
        """
        if "Speed" not in lap_df.columns:
            return lap_df

        speed = lap_df["Speed"].values
        # Find the last sample where the car is moving
        moving = np.where(speed > 0.5)[0]
        if len(moving) == 0:
            return lap_df

        last_moving = moving[-1]
        # Keep a small buffer after the last moving sample
        trim_idx = min(last_moving + 10, len(lap_df))
        return lap_df.iloc[:trim_idx].copy()

    def _deduplicate_distances(
        self, distances: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Remove duplicate distance values, keeping the last occurrence.

        Returns the deduplicated distances and a boolean mask for the original array.
        """
        # Find indices where distance actually changes
        diffs = np.diff(distances, prepend=-1)
        mask = diffs > 0

        # Always keep the first sample
        mask[0] = True

        return distances[mask], mask

    def _compute_elapsed_time(
        self, lap_df: pd.DataFrame, mask: np.ndarray
    ) -> np.ndarray:
        """Compute cumulative elapsed time from the start of the lap."""
        if "SessionTime" in lap_df.columns:
            session_time = lap_df["SessionTime"].values[mask]
            return session_time - session_time[0]
        elif "LapCurrentLapTime" in lap_df.columns:
            return lap_df["LapCurrentLapTime"].values[mask]
        else:
            # Fallback: assume 60Hz sample rate
            return np.arange(np.sum(mask)) / 60.0

    def _interpolate_channel(
        self,
        x_raw: np.ndarray,
        y_raw: np.ndarray,
        x_grid: np.ndarray,
        kind: str = "linear",
    ) -> np.ndarray:
        """Interpolate a channel from raw distance samples to the uniform grid."""
        if len(x_raw) < 2 or len(y_raw) < 2:
            return np.zeros_like(x_grid)

        y_raw = y_raw.astype(np.float64)

        interp_func = interp1d(
            x_raw,
            y_raw,
            kind=kind,
            bounds_error=False,
            fill_value=(y_raw[0], y_raw[-1]),
        )
        return interp_func(x_grid)

    def _interpolate_optional(
        self,
        lap_df: pd.DataFrame,
        column: str,
        raw_dist: np.ndarray,
        mask: np.ndarray,
        distance_grid: np.ndarray,
        kind: str = "linear",
    ) -> np.ndarray:
        """Interpolate an optional channel, returning zeros if missing."""
        if column not in lap_df.columns:
            return np.zeros_like(distance_grid)
        return self._interpolate_channel(
            raw_dist, lap_df[column].values[mask], distance_grid, kind=kind
        )

    def _empty_lap(
        self, lap_number: int, track_length: float, is_valid: bool = False
    ) -> NormalizedLap:
        """Return an empty NormalizedLap for edge cases."""
        empty = np.array([], dtype=np.float64)
        return NormalizedLap(
            lap_number=lap_number,
            lap_time=0.0,
            track_length=track_length,
            distance=empty,
            speed=empty,
            throttle=empty,
            brake=empty,
            steering=empty,
            gear=empty,
            rpm=empty,
            lat=empty,
            lon=empty,
            elapsed_time=empty,
            is_valid=is_valid,
        )
