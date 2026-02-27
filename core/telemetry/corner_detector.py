"""Automated corner detection from telemetry.

Segments a normalized lap into corners and straights using speed trace
heuristics. The algorithm:

1. Smooth the speed trace (Savitzky-Golay filter)
2. Find local minima (corner apexes) using scipy.signal.find_peaks
3. Walk backward from each apex to find braking initiation
4. Walk forward from each apex to find full throttle application (exit)
5. Merge close corners (chicanes, esses)
6. Filter false positives
7. Number corners sequentially
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
from scipy.signal import savgol_filter, find_peaks

from core.telemetry.normalizer import NormalizedLap


class SegmentType(Enum):
    CORNER = "corner"
    STRAIGHT = "straight"


@dataclass
class CornerSegment:
    """A detected corner within a lap."""

    segment_type: SegmentType
    corner_number: int
    distance_start: float  # meters from start/finish
    distance_end: float
    apex_distance: float  # distance of minimum speed
    apex_speed: float  # minimum speed in the corner (m/s)
    entry_speed: float  # speed at braking point
    exit_speed: float  # speed at throttle application
    braking_distance: float  # distance of braking initiation
    throttle_application_distance: float  # distance of throttle pickup


@dataclass
class LapSegmentation:
    """Complete segmentation of a lap into corners and straights."""

    corners: list[CornerSegment]
    track_length: float
    car: str
    track: str


@dataclass
class DetectionParams:
    """Tunable parameters for corner detection.

    Different track types need different sensitivity.
    """

    speed_smoothing_window: int = 25  # Savitzky-Golay window (must be odd)
    speed_smoothing_order: int = 3  # Polynomial order
    min_corner_speed_drop: float = 5.0  # m/s prominence to count as corner
    min_corner_distance: int = 50  # min meters between corner apexes
    brake_threshold: float = 0.05  # Brake pressure onset threshold
    throttle_threshold: float = 0.9  # Throttle application threshold
    merge_distance: int = 30  # Merge corners closer than this (meters)


class CornerDetector:
    """Detect corners in normalized telemetry using speed trace heuristics."""

    def __init__(self, params: DetectionParams | None = None):
        self.params = params or DetectionParams()

    def detect(self, lap: NormalizedLap) -> LapSegmentation:
        """Run full corner detection pipeline on a normalized lap."""
        if len(lap.speed) < self.params.speed_smoothing_window:
            return LapSegmentation(
                corners=[], track_length=lap.track_length, car="", track=""
            )

        # 1. Smooth the speed trace
        smoothed = self._smooth_speed(lap.speed)

        # 2. Find apex points (local minima in speed)
        apex_indices = self._find_apexes(smoothed)

        if len(apex_indices) == 0:
            return LapSegmentation(
                corners=[], track_length=lap.track_length, car="", track=""
            )

        # 3. For each apex, find braking point and corner exit
        corners: list[CornerSegment] = []
        for i, apex_idx in enumerate(apex_indices):
            braking_idx = self._find_braking_point(
                lap.brake, smoothed, apex_idx
            )
            exit_idx = self._find_corner_exit(
                lap.throttle, smoothed, apex_idx
            )

            corner = CornerSegment(
                segment_type=SegmentType.CORNER,
                corner_number=i + 1,  # Will be renumbered after merge
                distance_start=float(lap.distance[braking_idx]),
                distance_end=float(lap.distance[exit_idx]),
                apex_distance=float(lap.distance[apex_idx]),
                apex_speed=float(smoothed[apex_idx]),
                entry_speed=float(smoothed[braking_idx]),
                exit_speed=float(smoothed[exit_idx]),
                braking_distance=float(lap.distance[braking_idx]),
                throttle_application_distance=float(lap.distance[exit_idx]),
            )
            corners.append(corner)

        # 4. Merge chicanes
        corners = self._merge_close_corners(corners)

        # 5. Filter false positives
        corners = self._filter_false_positives(corners)

        # 6. Renumber sequentially
        for i, c in enumerate(corners):
            c.corner_number = i + 1

        return LapSegmentation(
            corners=corners,
            track_length=lap.track_length,
            car="",
            track="",
        )

    def _smooth_speed(self, speed: np.ndarray) -> np.ndarray:
        """Apply Savitzky-Golay filter to smooth the speed trace."""
        window = self.params.speed_smoothing_window
        # Window must be odd
        if window % 2 == 0:
            window += 1
        # Window must be <= data length
        if window > len(speed):
            window = len(speed) if len(speed) % 2 == 1 else len(speed) - 1
        if window < 3:
            return speed.copy()

        return savgol_filter(
            speed,
            window_length=window,
            polyorder=min(self.params.speed_smoothing_order, window - 1),
        )

    def _find_apexes(self, smoothed_speed: np.ndarray) -> np.ndarray:
        """Find local minima in the speed trace (corner apex points).

        Uses find_peaks on the inverted speed trace.
        """
        inverted = -smoothed_speed
        peaks, _ = find_peaks(
            inverted,
            distance=self.params.min_corner_distance,
            prominence=self.params.min_corner_speed_drop,
        )
        return peaks

    def _find_braking_point(
        self,
        brake: np.ndarray,
        speed: np.ndarray,
        apex_idx: int,
    ) -> int:
        """Walk backward from apex to find braking initiation.

        Looks for where brake pressure first exceeds the threshold,
        or where significant deceleration begins.
        """
        threshold = self.params.brake_threshold

        # Walk backward from apex
        for i in range(apex_idx, 0, -1):
            # Check brake pressure onset
            if brake[i] > threshold and (i == 0 or brake[i - 1] <= threshold):
                return i

            # Check if speed is increasing as we go backward (= we passed the braking zone)
            if i < apex_idx - 10 and speed[i] > speed[apex_idx] * 1.15:
                # We're well above apex speed — the braking zone started somewhere ahead
                # Find the local maximum between here and the apex
                segment = speed[i : apex_idx + 1]
                local_max = i + np.argmax(segment)
                return int(local_max)

        return 0

    def _find_corner_exit(
        self,
        throttle: np.ndarray,
        speed: np.ndarray,
        apex_idx: int,
    ) -> int:
        """Walk forward from apex to find full throttle application.

        Looks for where throttle exceeds threshold AND speed is increasing.
        """
        threshold = self.params.throttle_threshold
        max_idx = len(throttle) - 1

        for i in range(apex_idx, max_idx):
            if throttle[i] >= threshold and speed[i] > speed[max(0, i - 1)]:
                return i

        # If no full throttle found, look for where speed recovers
        # to significantly above apex speed
        apex_speed = speed[apex_idx]
        for i in range(apex_idx, max_idx):
            if speed[i] > apex_speed * 1.3:
                return i

        return max_idx

    def _merge_close_corners(
        self, corners: list[CornerSegment]
    ) -> list[CornerSegment]:
        """Merge corners that are very close together (chicanes, esses).

        If exit of corner N is within merge_distance of entry of corner N+1,
        combine them into one segment.
        """
        if len(corners) <= 1:
            return corners

        merged: list[CornerSegment] = [corners[0]]

        for next_corner in corners[1:]:
            prev = merged[-1]
            gap = next_corner.distance_start - prev.distance_end

            if gap < self.params.merge_distance:
                # Merge: keep the wider segment bounds, use the slower apex
                if next_corner.apex_speed < prev.apex_speed:
                    apex_dist = next_corner.apex_distance
                    apex_speed = next_corner.apex_speed
                else:
                    apex_dist = prev.apex_distance
                    apex_speed = prev.apex_speed

                merged[-1] = CornerSegment(
                    segment_type=SegmentType.CORNER,
                    corner_number=prev.corner_number,
                    distance_start=prev.distance_start,
                    distance_end=next_corner.distance_end,
                    apex_distance=apex_dist,
                    apex_speed=apex_speed,
                    entry_speed=prev.entry_speed,
                    exit_speed=next_corner.exit_speed,
                    braking_distance=prev.braking_distance,
                    throttle_application_distance=next_corner.throttle_application_distance,
                )
            else:
                merged.append(next_corner)

        return merged

    def _filter_false_positives(
        self, corners: list[CornerSegment]
    ) -> list[CornerSegment]:
        """Remove minor speed variations that aren't real corners.

        A real corner should have a meaningful speed drop from entry to apex.
        """
        return [
            c
            for c in corners
            if (c.entry_speed - c.apex_speed) >= self.params.min_corner_speed_drop
        ]

    @classmethod
    def for_track_type(cls, track_type: str) -> "CornerDetector":
        """Factory that returns a detector with params tuned for the track type.

        Args:
            track_type: 'road', 'street', or 'oval'
        """
        presets: dict[str, DetectionParams] = {
            "road": DetectionParams(
                min_corner_speed_drop=3.0,
                min_corner_distance=50,
            ),
            "street": DetectionParams(
                min_corner_speed_drop=3.0,
                min_corner_distance=30,
                merge_distance=20,
            ),
            "oval": DetectionParams(
                min_corner_speed_drop=2.0,
                min_corner_distance=200,
            ),
        }
        return cls(presets.get(track_type, DetectionParams()))
