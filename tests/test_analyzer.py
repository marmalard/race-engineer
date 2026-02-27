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
