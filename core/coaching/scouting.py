"""Scouting report generation orchestrator.

Coordinates between the synthesizer (Claude API), track database,
and driver profile to produce a complete scouting report.
"""

from core.coaching.synthesizer import ScoutingReport, Synthesizer


def generate_scouting_report(
    synthesizer: Synthesizer,
    car_name: str,
    track_name: str,
    track_config: str | None = None,
    irating: int | None = None,
) -> ScoutingReport:
    """Generate a scouting report for a car/track combination.

    Currently delegates directly to the synthesizer with web search.
    As more data sources come online (iRacing API, track DB, driver profile),
    this function will aggregate data from multiple sources before synthesis.
    """
    return synthesizer.generate_scouting_report(
        car_name=car_name,
        track_name=track_name,
        track_config=track_config,
        irating=irating,
    )
