"""The page's one pure helper: candidate labels for the selectbox."""

from core.briefing.ingest import SeriesCandidate
from app.pages.briefing import candidate_label


def test_label_shows_practice_depth():
    c = SeriesCandidate(
        season_id=1, series_name="M2 Cup", season_name="M2 Cup S3",
        race_week=2, track_id=9, track_name="Summit Point Raceway",
        practice_sessions=3,
    )
    assert candidate_label(c) == (
        "M2 Cup - Summit Point Raceway (3 practice sessions)"
    )


def test_label_unpracticed():
    c = SeriesCandidate(
        season_id=1, series_name="FF1600", season_name="FF S3",
        race_week=4, track_id=439, track_name="Winton",
        practice_sessions=0,
    )
    assert candidate_label(c) == "FF1600 - Winton (new track for you)"
