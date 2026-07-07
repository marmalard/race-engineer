# Race fixtures (gitignored)

Real official-race fixtures for `tests/test_race_ingest.py` integration
tests. Recorded with:

    .venv/Scripts/python.exe scripts/record_race_fixture.py <race.ibt>

Contents: `race.ibt` (the race session IBT) and `cache/{subsession_id}/`
(recorded Data API JSON: results.json, lap_chart.json, lap_data_*.json).
Tests skip when these are absent. Current recording: MX-5 at Oulton
International, 2026-06-26, subsession 86748877.
