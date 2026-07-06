"""Tests for race narrative data models."""

from core.race.models import (
    CautionSegment,
    GapPoint,
    IncidentEvent,
    IRatingAttribution,
    Lap1Story,
    NarrativeHeader,
    PaceSummary,
    PlaceChange,
    PositionPoint,
    RaceNarrative,
    RivalGaps,
    Stint,
)


def _minimal_narrative() -> RaceNarrative:
    return RaceNarrative(
        header=NarrativeHeader(
            subsession_id=86748877,
            cust_id=1226848,
            driver_name="Anthony Moorman",
            track_id=180,
            track_name="Oulton Park Circuit",
            track_config="International",
            car_name="Mazda MX-5 Cup",
            series_name="MX-5 Cup",
            session_date="2026-06-26",
            sof=1350,
            field_size=13,
            start_position=8,
            finish_position=6,
            incidents=5,
            irating_old=1420,
            irating_new=1445,
        ),
        position_timeline=[PositionPoint(lap=1, position=7)],
        lap1=Lap1Story(
            grid_position=8,
            position_after_lap1=7,
            position_after_lap2=7,
            place_changes=[
                PlaceChange(
                    lap=1,
                    lap_dist_pct=0.31,
                    corner_name="Island Bend",
                    from_position=8,
                    to_position=7,
                )
            ],
        ),
        gaps=[
            RivalGaps(
                cust_id=999,
                display_name="Rival One",
                finish_position=5,
                gaps=[GapPoint(lap=1, gap_s=1.2)],
            )
        ],
        incidents=[
            IncidentEvent(
                lap=9,
                lap_dist_pct=0.62,
                corner_name="Knickerbrook",
                delta_incidents=2,
                position_before=6,
                position_after=8,
                time_lost_estimate_s=4.1,
            )
        ],
        stints=[Stint(start_lap=1, end_lap=14, median_clean_pace=113.4, trend_s=0.2)],
        cautions=[CautionSegment(start_lap=3, end_lap=4)],
        pace=PaceSummary(
            median_clean_lap=113.4,
            best_lap=112.9,
            consistency_stdev=0.45,
            clean_lap_count=9,
            pace_rank=5,
            ranked_drivers=11,
            unranked_drivers=2,
        ),
        attribution=IRatingAttribution(
            irating_old=1420,
            irating_new=1445,
            irating_delta=25,
            pace_deserved_position=5,
            actual_position=6,
            incident_time_lost_s=6.3,
            lap1_net_positions=1,
            summary_lines=["Pace deserved ~P5; finished P6."],
        ),
        key_rivals=[999],
    )


def test_narrative_round_trips_through_dict():
    narrative = _minimal_narrative()
    d = narrative.to_dict()
    restored = RaceNarrative.from_dict(d)
    assert restored == narrative


def test_narrative_dict_is_json_serializable():
    import json

    text = json.dumps(_minimal_narrative().to_dict())
    assert "Knickerbrook" in text


def test_optional_sections_survive_round_trip():
    narrative = _minimal_narrative()
    narrative.lap1 = None
    narrative.cautions = []
    restored = RaceNarrative.from_dict(narrative.to_dict())
    assert restored.lap1 is None
    assert restored.cautions == []
