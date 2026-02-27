"""Lap-to-lap and benchmark comparison logic.

Compares two distance-normalized laps channel by channel. Calculates
deltas for braking point, minimum speed, throttle application, and
time gained/lost per corner.
"""

from dataclasses import dataclass

import numpy as np

from core.telemetry.normalizer import NormalizedLap
from core.telemetry.corner_detector import CornerSegment, LapSegmentation


@dataclass
class CornerDelta:
    """Comparison between two laps through a single corner."""

    corner: CornerSegment
    time_delta: float  # seconds (negative = comparison is faster)
    braking_point_delta: float  # meters (positive = comparison brakes later)
    apex_speed_delta: float  # m/s (positive = comparison is faster)
    exit_speed_delta: float  # m/s
    min_speed_delta: float  # m/s
    throttle_application_delta: float  # meters (positive = comparison gets on throttle later)
    entry_speed_delta: float  # m/s


@dataclass
class LapComparison:
    """Full comparison between two laps."""

    reference_lap: int  # Lap number of the reference (typically best) lap
    comparison_lap: int
    reference_time: float
    comparison_time: float
    total_time_delta: float
    corner_deltas: list[CornerDelta]
    cumulative_time_delta: np.ndarray  # Time delta at every distance point
    speed_delta: np.ndarray  # Speed difference at every distance point


@dataclass
class TheoreticalBest:
    """Theoretical best lap from best corners across all laps."""

    theoretical_time: float
    best_corners: dict[int, int]  # corner_number -> lap_number that was fastest
    actual_best_time: float
    gap_to_theoretical: float


@dataclass
class ConsistencyAnalysis:
    """Per-corner consistency across all laps in a session."""

    corner_number: int
    corner_name: str | None
    mean_time: float
    std_time: float
    best_time: float
    worst_time: float
    coefficient_of_variation: float  # std/mean
    is_consistency_issue: bool  # High variance
    is_technique_issue: bool  # Consistently slow vs theoretical


class LapComparator:
    """Compare laps and generate performance analysis."""

    def compare_laps(
        self,
        reference: NormalizedLap,
        comparison: NormalizedLap,
        segmentation: LapSegmentation,
    ) -> LapComparison:
        """Compare two laps corner by corner.

        The reference lap is typically the driver's best.
        The comparison lap is the one being analyzed.
        """
        # Ensure both laps are on the same distance grid
        min_len = min(len(reference.distance), len(comparison.distance))

        # Cumulative time delta at every distance point
        cum_delta = self._cumulative_time_delta(reference, comparison, min_len)

        # Speed delta at every distance point
        speed_delta = comparison.speed[:min_len] - reference.speed[:min_len]

        # Per-corner deltas
        corner_deltas: list[CornerDelta] = []
        for corner in segmentation.corners:
            delta = self._compute_corner_delta(
                reference, comparison, corner
            )
            if delta is not None:
                corner_deltas.append(delta)

        return LapComparison(
            reference_lap=reference.lap_number,
            comparison_lap=comparison.lap_number,
            reference_time=reference.lap_time,
            comparison_time=comparison.lap_time,
            total_time_delta=comparison.lap_time - reference.lap_time,
            corner_deltas=corner_deltas,
            cumulative_time_delta=cum_delta,
            speed_delta=speed_delta,
        )

    def theoretical_best(
        self,
        laps: list[NormalizedLap],
        segmentation: LapSegmentation,
    ) -> TheoreticalBest:
        """Calculate theoretical best by taking the fastest time
        through each corner across all laps.
        """
        if not laps or not segmentation.corners:
            best_time = min(l.lap_time for l in laps) if laps else 0.0
            return TheoreticalBest(
                theoretical_time=best_time,
                best_corners={},
                actual_best_time=best_time,
                gap_to_theoretical=0.0,
            )

        best_corners: dict[int, int] = {}
        total_theoretical = 0.0

        for corner in segmentation.corners:
            best_time_through = float("inf")
            best_lap_num = 0

            for lap in laps:
                ct = self._corner_time(lap, corner)
                if ct is not None and ct < best_time_through:
                    best_time_through = ct
                    best_lap_num = lap.lap_number

            if best_time_through < float("inf"):
                total_theoretical += best_time_through
                best_corners[corner.corner_number] = best_lap_num

        # Add straight time (approximate: total time minus corner time)
        # Use the best lap's straight time as baseline
        best_lap = min(laps, key=lambda l: l.lap_time)
        total_corner_time_best = sum(
            self._corner_time(best_lap, c) or 0.0
            for c in segmentation.corners
        )
        straight_time = best_lap.lap_time - total_corner_time_best
        theoretical_time = total_theoretical + straight_time

        actual_best = best_lap.lap_time

        return TheoreticalBest(
            theoretical_time=theoretical_time,
            best_corners=best_corners,
            actual_best_time=actual_best,
            gap_to_theoretical=actual_best - theoretical_time,
        )

    def consistency_analysis(
        self,
        laps: list[NormalizedLap],
        segmentation: LapSegmentation,
    ) -> list[ConsistencyAnalysis]:
        """Analyze per-corner consistency across all laps."""
        results: list[ConsistencyAnalysis] = []

        for corner in segmentation.corners:
            times: list[float] = []
            for lap in laps:
                ct = self._corner_time(lap, corner)
                if ct is not None and ct > 0:
                    times.append(ct)

            if len(times) < 2:
                continue

            times_arr = np.array(times)
            mean_t = float(np.mean(times_arr))
            std_t = float(np.std(times_arr))
            best_t = float(np.min(times_arr))
            worst_t = float(np.max(times_arr))
            cv = std_t / mean_t if mean_t > 0 else 0.0

            # Consistency issue: high variance (CV > 5%)
            is_consistency = cv > 0.05

            # Technique issue: consistently slow (mean is much worse than best)
            is_technique = (mean_t - best_t) > 0.5 and not is_consistency

            results.append(
                ConsistencyAnalysis(
                    corner_number=corner.corner_number,
                    corner_name=None,
                    mean_time=mean_t,
                    std_time=std_t,
                    best_time=best_t,
                    worst_time=worst_t,
                    coefficient_of_variation=cv,
                    is_consistency_issue=is_consistency,
                    is_technique_issue=is_technique,
                )
            )

        return results

    def _corner_time(
        self, lap: NormalizedLap, corner: CornerSegment
    ) -> float | None:
        """Calculate the time taken through a specific corner."""
        dist = lap.distance
        elapsed = lap.elapsed_time

        if len(dist) == 0:
            return None

        # Find indices closest to corner entry and exit
        entry_idx = int(np.searchsorted(dist, corner.distance_start))
        exit_idx = int(np.searchsorted(dist, corner.distance_end))

        # Clamp to valid range
        entry_idx = max(0, min(entry_idx, len(elapsed) - 1))
        exit_idx = max(0, min(exit_idx, len(elapsed) - 1))

        if exit_idx <= entry_idx:
            return None

        return float(elapsed[exit_idx] - elapsed[entry_idx])

    def _cumulative_time_delta(
        self,
        reference: NormalizedLap,
        comparison: NormalizedLap,
        length: int,
    ) -> np.ndarray:
        """Calculate the running time delta at every distance point.

        Positive = comparison is slower, negative = comparison is faster.
        """
        return comparison.elapsed_time[:length] - reference.elapsed_time[:length]

    def _compute_corner_delta(
        self,
        reference: NormalizedLap,
        comparison: NormalizedLap,
        corner: CornerSegment,
    ) -> CornerDelta | None:
        """Compute all deltas for a single corner between two laps."""
        ref_time = self._corner_time(reference, corner)
        comp_time = self._corner_time(comparison, corner)

        if ref_time is None or comp_time is None:
            return None

        # Find braking points in both laps for this corner
        ref_brake_dist = self._find_brake_onset(
            reference, corner.distance_start, corner.apex_distance
        )
        comp_brake_dist = self._find_brake_onset(
            comparison, corner.distance_start, corner.apex_distance
        )

        # Find throttle application in both laps
        ref_throttle_dist = self._find_throttle_onset(
            reference, corner.apex_distance, corner.distance_end
        )
        comp_throttle_dist = self._find_throttle_onset(
            comparison, corner.apex_distance, corner.distance_end
        )

        # Apex speeds
        apex_idx = int(np.searchsorted(reference.distance, corner.apex_distance))
        apex_idx = min(apex_idx, len(reference.speed) - 1, len(comparison.speed) - 1)

        # Entry speeds
        entry_idx = int(np.searchsorted(reference.distance, corner.distance_start))
        entry_idx = min(entry_idx, len(reference.speed) - 1, len(comparison.speed) - 1)

        # Exit speeds
        exit_idx = int(np.searchsorted(reference.distance, corner.distance_end))
        exit_idx = min(exit_idx, len(reference.speed) - 1, len(comparison.speed) - 1)

        # Min speed in corner range
        start_idx = int(np.searchsorted(reference.distance, corner.distance_start))
        end_idx = int(np.searchsorted(reference.distance, corner.distance_end))
        start_idx = max(0, min(start_idx, len(reference.speed) - 1))
        end_idx = max(start_idx + 1, min(end_idx, len(reference.speed)))

        ref_min = float(np.min(reference.speed[start_idx:end_idx]))
        comp_min = float(np.min(comparison.speed[start_idx:min(end_idx, len(comparison.speed))]))

        return CornerDelta(
            corner=corner,
            time_delta=comp_time - ref_time,
            braking_point_delta=comp_brake_dist - ref_brake_dist,
            apex_speed_delta=float(comparison.speed[apex_idx] - reference.speed[apex_idx]),
            exit_speed_delta=float(comparison.speed[exit_idx] - reference.speed[exit_idx]),
            min_speed_delta=comp_min - ref_min,
            throttle_application_delta=comp_throttle_dist - ref_throttle_dist,
            entry_speed_delta=float(comparison.speed[entry_idx] - reference.speed[entry_idx]),
        )

    def _find_brake_onset(
        self,
        lap: NormalizedLap,
        start_dist: float,
        apex_dist: float,
    ) -> float:
        """Find the distance where braking begins within a corner region."""
        start_idx = int(np.searchsorted(lap.distance, start_dist))
        apex_idx = int(np.searchsorted(lap.distance, apex_dist))
        start_idx = max(0, min(start_idx, len(lap.brake) - 1))
        apex_idx = max(start_idx, min(apex_idx, len(lap.brake) - 1))

        brake_segment = lap.brake[start_idx : apex_idx + 1]
        threshold = 0.05

        for i, val in enumerate(brake_segment):
            if val > threshold:
                return float(lap.distance[start_idx + i])

        return start_dist

    def _find_throttle_onset(
        self,
        lap: NormalizedLap,
        apex_dist: float,
        end_dist: float,
    ) -> float:
        """Find the distance where significant throttle begins after apex."""
        apex_idx = int(np.searchsorted(lap.distance, apex_dist))
        end_idx = int(np.searchsorted(lap.distance, end_dist))
        apex_idx = max(0, min(apex_idx, len(lap.throttle) - 1))
        end_idx = max(apex_idx, min(end_idx, len(lap.throttle) - 1))

        throttle_segment = lap.throttle[apex_idx : end_idx + 1]
        threshold = 0.5

        for i, val in enumerate(throttle_segment):
            if val > threshold:
                return float(lap.distance[apex_idx + i])

        return apex_dist
