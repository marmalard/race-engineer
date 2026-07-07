"""Record real race fixtures for the integration tests.

Runs full ingestion (live Data API) on a race IBT, then copies the
IBT + cached API JSON into tests/fixtures/race/. Requires iRacing
credentials in .env.

Usage:
    .venv/Scripts/python.exe scripts/record_race_fixture.py <path-to-race.ibt>
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.pages.race_debrief import _make_api  # reuse env-cred construction
from core.race.ingest import DEFAULT_CACHE_DIR, ingest_race
from core.race.narrative import build_narrative

FIXTURE_DIR = Path("tests/fixtures/race")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    ibt_path = Path(sys.argv[1])
    api = _make_api()
    if api is None:
        print("ERROR: iRacing credentials missing from environment.")
        return 1

    try:
        data = ingest_race(ibt_path, api)
    finally:
        api.close()

    if not data.results:
        print("ERROR: API returned no results — fixture would be partial.")
        return 1

    narrative = build_narrative(data, corners=[])
    print(f"subsession {data.subsession_id}: "
          f"P{narrative.header.start_position} -> "
          f"P{narrative.header.finish_position}, "
          f"{len(narrative.incidents)} incident events, "
          f"{len(narrative.gaps)} rival gap series")

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ibt_path, FIXTURE_DIR / "race.ibt")
    cache_src = DEFAULT_CACHE_DIR / str(data.subsession_id)
    cache_dst = FIXTURE_DIR / "cache" / str(data.subsession_id)
    if cache_dst.exists():
        shutil.rmtree(cache_dst)
    shutil.copytree(cache_src, cache_dst)
    print(f"Fixtures written to {FIXTURE_DIR}/ — done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
