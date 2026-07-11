"""Exact-string tests for verdicts and the prompt block (like nudges)."""

import json

from core.profile.models import (
    ComboReadiness,
    DriverProfile,
    IncidentTendency,
    PaceVsResultTendency,
    RacecraftTendencies,
    StartsTendency,
    TrajectoryTendency,
)
from core.profile.render import (
    profile_markdown,
    profile_prompt_block,
    verdict_incidents,
    verdict_pace_vs_result,
    verdict_readiness,
    verdict_starts,
    verdict_trajectory,
)


def test_verdict_starts_losing():
    t = StartsTendency(mean_lap1_net=-1.4, mean_lap2_net=0.2,
                       races_lost_ground=5, sample=6, enough_data=True)
    assert verdict_starts(t) == (
        "You lose ground at the start — avg -1.4 places on lap 1 "
        "across 6 races (lost ground in 5 of 6)."
    )


def test_verdict_starts_gaining_and_neutral():
    g = StartsTendency(mean_lap1_net=1.2, mean_lap2_net=0.0,
                       races_lost_ground=1, sample=4, enough_data=True)
    assert verdict_starts(g) == (
        "You gain ground at the start — avg +1.2 places on lap 1 "
        "across 4 races (lost ground in 1 of 4)."
    )
    n = StartsTendency(mean_lap1_net=0.1, mean_lap2_net=0.0,
                       races_lost_ground=2, sample=4, enough_data=True)
    assert verdict_starts(n).startswith("Starts are roughly neutral")


def test_verdict_pace_vs_result_leaving_positions():
    t = PaceVsResultTendency(mean_positions_left=2.0,
                             mean_incident_time_lost_s=8.5,
                             mean_actual_position=6.0,
                             mean_deserved_position=4.0,
                             sample=5, enough_data=True)
    assert verdict_pace_vs_result(t) == (
        "Your pace deserves ~P4 but you finish ~P6 — the gap is incidents "
        "and decisions, not speed (avg 8.5s/race lost to incidents)."
    )


def test_verdict_pace_vs_result_earning_and_even():
    e = PaceVsResultTendency(mean_positions_left=-1.0,
                             mean_actual_position=4.0,
                             mean_deserved_position=5.0,
                             sample=4, enough_data=True)
    assert verdict_pace_vs_result(e) == (
        "You finish ~P4 on ~P5 pace — strong racecraft is earning "
        "you positions."
    )
    v = PaceVsResultTendency(mean_positions_left=0.2,
                             mean_actual_position=5.0,
                             mean_deserved_position=5.0,
                             sample=4, enough_data=True)
    assert verdict_pace_vs_result(v) == (
        "You finish about where your pace deserves (~P5)."
    )


def test_verdict_incidents_with_recurring():
    t = IncidentTendency(mean_incident_points=3.2, lap1_share=0.4,
                         recurring_corners=[("Old Hall", 3), ("Lodge", 2)],
                         sample=5, enough_data=True)
    assert verdict_incidents(t) == (
        "3.2 incident points/race, 40% of incidents on lap 1. "
        "Repeat trouble: Old Hall (3x), Lodge (2x)."
    )


def test_verdict_incidents_no_events():
    t = IncidentTendency(mean_incident_points=0.5, lap1_share=None,
                         sample=3, enough_data=True)
    assert verdict_incidents(t) == "0.5 incident points/race."


def test_verdict_trajectory_gains_but_fades():
    t = TrajectoryTendency(mean_race_net=1.8, mean_stint_fade_s=0.3,
                           sample=4, enough_data=True)
    assert verdict_trajectory(t) == (
        "You gain +1.8 places over a race on average, but fade late "
        "(+0.3s second-half pace)."
    )


def test_verdict_trajectory_flat_no_fade():
    t = TrajectoryTendency(mean_race_net=0.1, mean_stint_fade_s=0.05,
                           sample=4, enough_data=True)
    assert verdict_trajectory(t) == "You finish about where you start."


def test_verdict_trajectory_losing_reads_naturally():
    """No double negative: 'You lose 1.8 places', not 'You lose -1.8'."""
    t = TrajectoryTendency(mean_race_net=-1.8, mean_stint_fade_s=None,
                           sample=4, enough_data=True)
    assert verdict_trajectory(t) == (
        "You lose 1.8 places over a race on average."
    )


def test_verdict_readiness():
    c = ComboReadiness(track_id="525", track_name="Spa", car="M2",
                       sessions=14, valid_laps=89, last_driven="2026-07-08",
                       best_lap=159.2, pb_trend_s=1.2, consistency_s=0.4,
                       enough_data=True)
    assert verdict_readiness(c) == (
        "Spa / M2: 14 sessions, 89 clean laps. Session best down 1.2s over the run; "
        "recent laps within ±0.4s."
    )


def test_verdict_readiness_minimal():
    c = ComboReadiness(track_id="1", track_name="Okayama", car="MX-5",
                       sessions=2, valid_laps=12, last_driven="2026-07-01",
                       best_lap=100.0, pb_trend_s=None, consistency_s=None,
                       enough_data=True)
    assert verdict_readiness(c) == "Okayama / MX-5: 2 sessions, 12 clean laps."


def _full_profile() -> DriverProfile:
    return DriverProfile(
        cust_id=100, driver_name="D", races_captured=6, combos_tracked=2,
        racecraft=RacecraftTendencies(
            starts=StartsTendency(mean_lap1_net=-1.4, mean_lap2_net=0.2,
                                  races_lost_ground=5, sample=6,
                                  enough_data=True),
            pace_vs_result=PaceVsResultTendency(
                mean_positions_left=2.0, mean_incident_time_lost_s=8.5,
                mean_actual_position=6.0, mean_deserved_position=4.0,
                sample=5, enough_data=True),
            incidents=IncidentTendency(mean_incident_points=3.2,
                                       lap1_share=0.4,
                                       recurring_corners=[("Old Hall", 3)],
                                       sample=6, enough_data=True),
            trajectory=TrajectoryTendency(sample=2, enough_data=False),
        ),
        readiness=[
            ComboReadiness(track_id="525", track_name="Spa", car="M2",
                           sessions=14, valid_laps=89,
                           last_driven="2026-07-08", best_lap=159.2,
                           pb_trend_s=1.2, consistency_s=0.4,
                           enough_data=True),
            ComboReadiness(track_id="219", track_name="Bathurst", car="992",
                           sessions=1, valid_laps=4, enough_data=False),
        ],
    )


def test_prompt_block_includes_only_enough_data():
    block = profile_prompt_block(_full_profile())
    assert block.startswith("--- DRIVER PROFILE")
    assert block.rstrip().endswith("--- END DRIVER PROFILE ---")
    payload = json.loads(
        block.split("---\n", 1)[1].rsplit("\n---", 1)[0]
    )
    assert set(payload["tendencies"]) == {"starts", "pace_vs_result", "incidents"}
    assert "trajectory" not in payload["tendencies"]     # below threshold
    assert len(payload["readiness"]) == 1                # Bathurst excluded
    assert payload["races"] == 6


def test_prompt_block_empty_when_nothing_crosses_threshold():
    assert profile_prompt_block(DriverProfile(races_captured=1)) == ""


def test_prompt_block_respects_char_cap():
    p = _full_profile()
    p.readiness = [
        ComboReadiness(track_id=str(i), track_name="T" * 40, car="C" * 40,
                       sessions=5, valid_laps=50, last_driven="2026-07-08",
                       best_lap=100.0, pb_trend_s=0.5, consistency_s=0.3,
                       enough_data=True)
        for i in range(50)
    ]
    block = profile_prompt_block(p)
    assert len(block) <= 2000
    assert block.rstrip().endswith("--- END DRIVER PROFILE ---")


def test_profile_markdown_mixes_ready_and_collecting():
    md = profile_markdown(_full_profile())
    assert "**6** races captured" in md
    assert "Pace vs result" in md
    assert "collecting data (2 of 3 races captured)" in md   # trajectory
    assert "Bathurst / 992 — collecting data (1 session, 4 clean laps)" in md
