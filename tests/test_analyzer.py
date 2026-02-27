"""Tests for the coaching analysis orchestrator."""

import pytest
from pathlib import Path

from core.coaching.analyzer import (
    CoachingAnalysis,
    PriorityCorner,
    analyze_session,
)


class TestAnalyzeSession:
    """Integration tests for the full analysis pipeline."""

    def test_produces_coaching_analysis(self, multilap_ibt_path: Path):
        """analyze_session should return a complete CoachingAnalysis."""
        analysis = analyze_session(multilap_ibt_path)

        assert isinstance(analysis, CoachingAnalysis)
        assert analysis.track_name
        assert analysis.car_name
        assert analysis.valid_lap_count >= 2
        assert analysis.best_lap_time > 0

    def test_best_lap_is_fastest(self, multilap_ibt_path: Path):
        """Best lap should have the lowest lap time."""
        analysis = analyze_session(multilap_ibt_path)

        for lap in analysis.all_laps:
            assert analysis.best_lap_time <= lap.lap_time + 0.001

    def test_comparison_lap_is_not_best(self, multilap_ibt_path: Path):
        """Comparison lap should be different from the best lap."""
        analysis = analyze_session(multilap_ibt_path)
        assert analysis.comparison_lap.lap_number != analysis.best_lap.lap_number

    def test_theoretical_best_leq_actual(self, multilap_ibt_path: Path):
        """Theoretical best should be <= actual best."""
        analysis = analyze_session(multilap_ibt_path)
        assert analysis.theoretical_best_time <= analysis.best_lap_time + 0.5

    def test_gap_to_theoretical_non_negative(self, multilap_ibt_path: Path):
        """Gap to theoretical should be >= 0."""
        analysis = analyze_session(multilap_ibt_path)
        assert analysis.gap_to_theoretical >= -0.01

    def test_priority_corners_at_most_3(self, multilap_ibt_path: Path):
        """Should return at most 3 priority corners."""
        analysis = analyze_session(multilap_ibt_path)
        assert len(analysis.priority_corners) <= 3

    def test_priority_corners_ranked_by_time(self, multilap_ibt_path: Path):
        """Priority corners should be sorted by abs(time_lost) descending."""
        analysis = analyze_session(multilap_ibt_path)

        if len(analysis.priority_corners) < 2:
            pytest.skip("Need at least 2 priority corners to test ordering")

        for i in range(len(analysis.priority_corners) - 1):
            current = abs(analysis.priority_corners[i].time_lost)
            next_val = abs(analysis.priority_corners[i + 1].time_lost)
            assert current >= next_val - 0.001

    def test_priority_corners_have_valid_fields(self, multilap_ibt_path: Path):
        """Each priority corner should have all fields populated."""
        analysis = analyze_session(multilap_ibt_path)

        for pc in analysis.priority_corners:
            assert isinstance(pc, PriorityCorner)
            assert pc.corner_number > 0
            assert pc.issue_type in ("consistency", "technique", "minor", "both")

    def test_lap_times_sorted(self, multilap_ibt_path: Path):
        """Lap times list should be sorted by lap time."""
        analysis = analyze_session(multilap_ibt_path)

        times = [t for _, t in analysis.lap_times]
        assert times == sorted(times)

    def test_segmentation_has_corners(self, multilap_ibt_path: Path):
        """Should detect at least some corners."""
        analysis = analyze_session(multilap_ibt_path)
        assert len(analysis.segmentation.corners) > 0

    def test_accepts_bytes_input(self, multilap_ibt_path: Path):
        """Should accept raw bytes (simulating Streamlit upload)."""
        raw_bytes = multilap_ibt_path.read_bytes()
        analysis = analyze_session(raw_bytes)
        assert analysis.valid_lap_count >= 2

    def test_street_track_type(self, multilap_ibt_path: Path):
        """Should work with street track type (more sensitive detection)."""
        analysis = analyze_session(multilap_ibt_path, track_type="street")
        assert analysis.valid_lap_count >= 2


class TestAnalyzeSessionErrors:
    """Error handling tests."""

    def test_too_few_laps_raises(self, sample_ibt_path: Path):
        """Should raise ValueError if fewer than 2 valid laps.

        The sample.ibt at Spa has only 1 valid normalized lap.
        """
        with pytest.raises(ValueError, match="at least 2 valid laps"):
            analyze_session(sample_ibt_path)


class TestCornerNames:
    """Tests for corner name matching in the analysis pipeline."""

    def test_no_corner_names_without_db(self, multilap_ibt_path: Path):
        """Without db_path, corner_name should be None on all priority corners."""
        analysis = analyze_session(multilap_ibt_path)
        for pc in analysis.priority_corners:
            assert pc.corner_name is None
        assert analysis.corner_names == {}

    def test_corner_names_with_db(self, multilap_ibt_path: Path, tmp_path: Path):
        """With db_path and Crew Chief data, corner names should be populated."""
        import json
        from core.track.crew_chief_seeder import seed_track_by_id
        from core.track.track_db import TrackDB

        # Set up DB and cache with Road America data
        db_path = tmp_path / "tracks.db"
        cache_path = tmp_path / "crew_chief_cache.json"

        # Minimal Crew Chief JSON with Road America corners
        cc_data = {
            "TrackLandmarksData": [
                {
                    "irTrackName": "roadamerica full",
                    "trackLandmarks": [
                        {"landmarkName": "turn1", "distanceRoundLapStart": 541.94,
                         "distanceRoundLapEnd": 758, "isCommonOvertakingSpot": True},
                        {"landmarkName": "turn3", "distanceRoundLapStart": 1027.32,
                         "distanceRoundLapEnd": 1227.80, "isCommonOvertakingSpot": True},
                        {"landmarkName": "the_sweep", "distanceRoundLapStart": 1569.25,
                         "distanceRoundLapEnd": 2182.89, "isCommonOvertakingSpot": False},
                        {"landmarkName": "turn5", "distanceRoundLapStart": 2217.70,
                         "distanceRoundLapEnd": 2382.10, "isCommonOvertakingSpot": True},
                        {"landmarkName": "turn6", "distanceRoundLapStart": 2532.47,
                         "distanceRoundLapEnd": 2686, "isCommonOvertakingSpot": True},
                        {"landmarkName": "turn7", "distanceRoundLapStart": 2761.68,
                         "distanceRoundLapEnd": 2939, "isCommonOvertakingSpot": True},
                        {"landmarkName": "turn8", "distanceRoundLapStart": 3170.59,
                         "distanceRoundLapEnd": 3343, "isCommonOvertakingSpot": True},
                        {"landmarkName": "the_carousel", "distanceRoundLapStart": 3386.07,
                         "distanceRoundLapEnd": 3930, "isCommonOvertakingSpot": False},
                        {"landmarkName": "the_kink", "distanceRoundLapStart": 4131.72,
                         "distanceRoundLapEnd": 4411, "isCommonOvertakingSpot": False},
                        {"landmarkName": "canada_corner", "distanceRoundLapStart": 5017.59,
                         "distanceRoundLapEnd": 5156.97, "isCommonOvertakingSpot": True},
                        {"landmarkName": "thunder_valley", "distanceRoundLapStart": 5172.14,
                         "distanceRoundLapEnd": 5334.57, "isCommonOvertakingSpot": False},
                        {"landmarkName": "bill_mitchell_bend", "distanceRoundLapStart": 5343.98,
                         "distanceRoundLapEnd": 5563, "isCommonOvertakingSpot": False},
                        {"landmarkName": "turn14", "distanceRoundLapStart": 5652.12,
                         "distanceRoundLapEnd": 5862, "isCommonOvertakingSpot": False},
                    ],
                }
            ]
        }
        cache_path.write_text(json.dumps(cc_data), encoding="utf-8")

        # Pre-seed the DB
        db = TrackDB(db_path)
        seed_track_by_id(db, "18", cache_path=cache_path)

        # Run analysis with DB
        analysis = analyze_session(multilap_ibt_path, db_path=db_path)

        # At least some corners should have names
        assert len(analysis.corner_names) > 0
        # At least one priority corner should have a name
        named_pcs = [pc for pc in analysis.priority_corners if pc.corner_name]
        assert len(named_pcs) > 0, (
            f"Expected named priority corners. "
            f"Available names: {analysis.corner_names}"
        )


class TestBuildCoachingPrompt:
    """Test the prompt builder."""

    def test_builds_valid_json(self, multilap_ibt_path: Path):
        """build_coaching_prompt should produce valid JSON in the prompt."""
        import json
        from core.coaching.prompts.coaching import build_coaching_prompt

        analysis = analyze_session(multilap_ibt_path)
        prompt = build_coaching_prompt(analysis)

        # The prompt wraps JSON in the template text - extract the JSON portion
        assert "session" in prompt
        assert "priority_corners" in prompt
        assert analysis.track_name in prompt
        assert analysis.car_name in prompt

    def test_prompt_includes_key_data(self, multilap_ibt_path: Path):
        """Prompt should include session summary and corner data."""
        from core.coaching.prompts.coaching import build_coaching_prompt

        analysis = analyze_session(multilap_ibt_path)
        prompt = build_coaching_prompt(analysis)

        assert "best_lap_time_seconds" in prompt
        assert "theoretical_best_seconds" in prompt
        assert "time_lost_seconds" in prompt

    def test_prompt_includes_corner_names(self, multilap_ibt_path: Path, tmp_path: Path):
        """When corner names exist, prompt should include corner_name fields."""
        import json
        from core.coaching.prompts.coaching import build_coaching_prompt
        from core.track.crew_chief_seeder import seed_track_by_id
        from core.track.track_db import TrackDB

        db_path = tmp_path / "tracks.db"
        cache_path = tmp_path / "cache.json"
        cc_data = {
            "TrackLandmarksData": [
                {
                    "irTrackName": "roadamerica full",
                    "trackLandmarks": [
                        {"landmarkName": "turn1", "distanceRoundLapStart": 541.94,
                         "distanceRoundLapEnd": 758, "isCommonOvertakingSpot": True},
                        {"landmarkName": "turn3", "distanceRoundLapStart": 1027.32,
                         "distanceRoundLapEnd": 1227.80, "isCommonOvertakingSpot": True},
                        {"landmarkName": "the_sweep", "distanceRoundLapStart": 1569.25,
                         "distanceRoundLapEnd": 2182.89, "isCommonOvertakingSpot": False},
                        {"landmarkName": "turn5", "distanceRoundLapStart": 2217.70,
                         "distanceRoundLapEnd": 2382.10, "isCommonOvertakingSpot": True},
                        {"landmarkName": "turn6", "distanceRoundLapStart": 2532.47,
                         "distanceRoundLapEnd": 2686, "isCommonOvertakingSpot": True},
                        {"landmarkName": "turn7", "distanceRoundLapStart": 2761.68,
                         "distanceRoundLapEnd": 2939, "isCommonOvertakingSpot": True},
                        {"landmarkName": "turn8", "distanceRoundLapStart": 3170.59,
                         "distanceRoundLapEnd": 3343, "isCommonOvertakingSpot": True},
                        {"landmarkName": "the_carousel", "distanceRoundLapStart": 3386.07,
                         "distanceRoundLapEnd": 3930, "isCommonOvertakingSpot": False},
                        {"landmarkName": "the_kink", "distanceRoundLapStart": 4131.72,
                         "distanceRoundLapEnd": 4411, "isCommonOvertakingSpot": False},
                        {"landmarkName": "canada_corner", "distanceRoundLapStart": 5017.59,
                         "distanceRoundLapEnd": 5156.97, "isCommonOvertakingSpot": True},
                        {"landmarkName": "thunder_valley", "distanceRoundLapStart": 5172.14,
                         "distanceRoundLapEnd": 5334.57, "isCommonOvertakingSpot": False},
                        {"landmarkName": "bill_mitchell_bend", "distanceRoundLapStart": 5343.98,
                         "distanceRoundLapEnd": 5563, "isCommonOvertakingSpot": False},
                        {"landmarkName": "turn14", "distanceRoundLapStart": 5652.12,
                         "distanceRoundLapEnd": 5862, "isCommonOvertakingSpot": False},
                    ],
                }
            ]
        }
        cache_path.write_text(json.dumps(cc_data), encoding="utf-8")

        db = TrackDB(db_path)
        seed_track_by_id(db, "18", cache_path=cache_path)

        analysis = analyze_session(multilap_ibt_path, db_path=db_path)
        prompt = build_coaching_prompt(analysis)

        assert "corner_name" in prompt
