"""Corner registry — match detected corners to named corners in the database."""

from core.telemetry.corner_detector import CornerSegment
from core.track.models import Corner
from core.track.track_db import TrackDB


class CornerRegistry:
    """Match detected corners to named corners in the database.

    Uses distance-based matching with a tolerance window.
    """

    def __init__(self, track_db: TrackDB, tolerance_meters: float = 50.0):
        self.track_db = track_db
        self.tolerance = tolerance_meters

    def match_corners(
        self,
        track_id: str,
        detected_corners: list[CornerSegment],
    ) -> list[tuple[CornerSegment, Corner | None]]:
        """Match detected corners to database corners by distance overlap.

        Returns pairs of (detected_corner, database_corner_or_None).
        """
        db_corners = self.track_db.get_corners(track_id)

        results: list[tuple[CornerSegment, Corner | None]] = []
        for detected in detected_corners:
            best_match: Corner | None = None
            best_overlap = 0.0

            for db_corner in db_corners:
                overlap = self._compute_overlap(
                    detected.distance_start,
                    detected.distance_end,
                    db_corner.distance_start_meters,
                    db_corner.distance_end_meters,
                )
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_match = db_corner

            # Also try matching by apex distance proximity
            if best_match is None:
                for db_corner in db_corners:
                    midpoint = (
                        db_corner.distance_start_meters
                        + db_corner.distance_end_meters
                    ) / 2
                    if abs(detected.apex_distance - midpoint) < self.tolerance:
                        best_match = db_corner
                        break

            results.append((detected, best_match))

        return results

    def _compute_overlap(
        self,
        start_a: float,
        end_a: float,
        start_b: float,
        end_b: float,
    ) -> float:
        """Compute the overlap distance between two segments."""
        overlap_start = max(start_a, start_b)
        overlap_end = min(end_a, end_b)
        return max(0.0, overlap_end - overlap_start)
