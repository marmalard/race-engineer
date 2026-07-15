"""Record a real briefing harvest as test fixtures.

Usage: .venv/Scripts/python.exe scripts/record_briefing_fixture.py <season_id> <race_week>

Runs harvest_field against the live Data API with the briefing cache
pointed at tests/fixtures/briefing/ - the cached subsession JSONs ARE the
fixtures (race-fixture precedent; gitignored except README).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

from dotenv import load_dotenv

load_dotenv()

from core.benchmark.iracing_api import LiveIRacingAPI
from core.briefing.ingest import harvest_field

FIXTURE_DIR = Path("tests/fixtures/briefing")


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(1)
    season_id, race_week = int(sys.argv[1]), int(sys.argv[2])
    api = LiveIRacingAPI(
        client_id=os.environ["IRACING_CLIENT_ID"],
        client_secret=os.environ["IRACING_CLIENT_SECRET"],
        username=os.environ["IRACING_USERNAME"],
        password=os.environ["IRACING_PASSWORD"],
    )
    try:
        # search_series needs season_year+quarter (season_id alone is a
        # 400) — resolve them from the season calendar first.
        season = next(
            (s for s in api.get_series_seasons() if s.season_id == season_id),
            None,
        )
        if season is None:
            print(f"season_id {season_id} not found in the active calendar")
            raise SystemExit(1)
        curve, stats = harvest_field(
            api,
            season_id,
            race_week,
            cache_dir=FIXTURE_DIR,
            season_year=season.season_year or None,
            season_quarter=season.season_quarter or None,
        )
    finally:
        api.close()
    print(f"Recorded {curve.subsessions_used} subsessions, "
          f"{len(curve.points)} pace points -> {FIXTURE_DIR}")
    if stats:
        print(f"SoF median {stats.sof_median}, "
              f"field ~{stats.field_size_median}")


if __name__ == "__main__":
    main()
