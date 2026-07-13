"""Phase 4 feasibility spike: what does the iRacing Data API expose PRE-race?

READ-ONLY exploration. Caches every response to data/api_spike/ so re-runs
never re-fetch. Run stages individually to keep call volume low:

    .venv/Scripts/python.exe scripts/spike_phase4_api.py stage1
    .venv/Scripts/python.exe scripts/spike_phase4_api.py stage2 ...
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from core.benchmark.iracing_api import LiveIRacingAPI

SPIKE_DIR = Path(__file__).resolve().parents[1] / "data" / "api_spike"
SPIKE_DIR.mkdir(parents=True, exist_ok=True)

CUST_ID = 1226848


def make_api() -> LiveIRacingAPI:
    return LiveIRacingAPI(
        os.environ["IRACING_CLIENT_ID"],
        os.environ["IRACING_CLIENT_SECRET"],
        os.environ["IRACING_USERNAME"],
        os.environ["IRACING_PASSWORD"],
    )


def cached_fetch(api: LiveIRacingAPI, name: str, endpoint: str,
                 params: dict | None = None, chunked: bool = False):
    """Fetch endpoint, cache raw JSON to data/api_spike/{name}.json."""
    path = SPIKE_DIR / f"{name}.json"
    if path.exists():
        print(f"[cache] {name}")
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"[fetch] {name}: {endpoint} {params or ''}")
    data = api._api_get(endpoint, params)
    if chunked:
        # search_series nests chunk_info under data.data
        ci_holder = data.get("data", data) if isinstance(data, dict) else data
        data = api._fetch_chunked(ci_holder)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"        saved {path.name} ({path.stat().st_size:,} bytes)")
    return data


def stage1(api):
    """Doc index, member info, race guide, series seasons."""
    doc = cached_fetch(api, "doc_index", "/data/doc")
    print("doc top-level keys:", sorted(doc.keys()))

    info = cached_fetch(api, "member_info", "/data/member/info")
    print("member_info keys:", sorted(info.keys()))

    guide = cached_fetch(api, "race_guide", "/data/season/race_guide")
    if isinstance(guide, dict):
        print("race_guide keys:", sorted(guide.keys()))
        sessions = guide.get("sessions", [])
        print("race_guide sessions:", len(sessions))
        if sessions:
            print("first session:", json.dumps(sessions[0], indent=1)[:1500])

    seasons = cached_fetch(api, "series_seasons", "/data/series/seasons",
                           {"include_series": True})
    print("series_seasons count:", len(seasons) if isinstance(seasons, list) else seasons.keys())


def stage2(api):
    """Split history for BMW M2 Cup week 3 + race guide lookahead probe."""
    rows = cached_fetch(api, "search_series_571_wk3", "/data/results/search_series",
                        {"season_year": 2026, "season_quarter": 3,
                         "series_id": 571, "race_week_num": 3,
                         "official_only": True, "event_types": 5},
                        chunked=True)
    print("search_series rows:", len(rows))
    if rows:
        print("row keys:", sorted(rows[0].keys()))
        print("sample row:", json.dumps(rows[0], indent=1)[:1200])

    # How far ahead can the race guide look?
    guide_tmrw = cached_fetch(api, "race_guide_from_tomorrow",
                              "/data/season/race_guide",
                              {"from": "2026-07-14T18:00:00Z"})
    if isinstance(guide_tmrw, dict):
        print("guide from tomorrow block:",
              guide_tmrw.get("block_begin_time"), "->",
              guide_tmrw.get("block_end_time"),
              "sessions:", len(guide_tmrw.get("sessions", [])))


def stage3(api):
    """One subsession's full results + reg_drivers_list roster probes."""
    rows = json.loads((SPIKE_DIR / "search_series_571_wk3.json").read_text(encoding="utf-8"))
    # pick a subsession near his 1409 iR: SoF closest below ~1500
    rows_sof = sorted(rows, key=lambda r: abs(r.get("event_strength_of_field", 0) - 1400))
    target = rows_sof[0]
    print("target subsession:", target["subsession_id"],
          "SoF", target.get("event_strength_of_field"))
    res = cached_fetch(api, f"results_get_{target['subsession_id']}",
                       "/data/results/get",
                       {"subsession_id": target["subsession_id"]})
    print("results keys:", sorted(res.keys()))

    # roster probe 1: completed subsession
    try:
        reg = cached_fetch(api, "reg_drivers_completed",
                           "/data/session/reg_drivers_list",
                           {"subsession_id": target["subsession_id"]})
        print("reg_drivers (completed):", json.dumps(reg, indent=1)[:1500])
    except Exception as e:
        print("reg_drivers (completed) FAILED:", e)

    # roster probe 2: upcoming session_id from race guide (wrong id kind, expect fail)
    guide = json.loads((SPIKE_DIR / "race_guide.json").read_text(encoding="utf-8"))
    upcoming = next((s for s in guide["sessions"] if "session_id" in s), None)
    if upcoming:
        try:
            reg2 = cached_fetch(api, "reg_drivers_upcoming",
                                "/data/session/reg_drivers_list",
                                {"subsession_id": upcoming["session_id"]})
            print("reg_drivers (upcoming session_id):", json.dumps(reg2, indent=1)[:1500])
        except Exception as e:
            print("reg_drivers (upcoming session_id) FAILED:", e)

    # roster probe 3: live subsessions via spectator endpoint
    try:
        spec = cached_fetch(api, "spectator_subsession_detail",
                            "/data/season/spectator_subsessionids_detail",
                            {"event_types": 5})
        if isinstance(spec, dict):
            subs = spec.get("subsession_ids") or spec.get("subsessions") or []
            print("spectator detail keys:", sorted(spec.keys()), "count:", len(subs))
            if subs:
                print("first:", json.dumps(subs[0], indent=1)[:800])
    except Exception as e:
        print("spectator detail FAILED:", e)


def stage4(api):
    """reg_drivers_list on a LIVE subsession + opponent-card endpoints."""
    spec = json.loads((SPIKE_DIR / "spectator_subsession_detail.json").read_text(encoding="utf-8"))
    live = spec["subsessions"][0]
    try:
        reg = cached_fetch(api, f"reg_drivers_live_{live['subsession_id']}",
                           "/data/session/reg_drivers_list",
                           {"subsession_id": live["subsession_id"]})
        entries = reg.get("entries", [])
        print(f"reg_drivers (LIVE {live['subsession_id']}): {len(entries)} entries")
        if entries:
            print("first entry:", json.dumps(entries[0], indent=1)[:1200])
    except Exception as e:
        print("reg_drivers (live) FAILED:", e)

    # opponent card: pick an opponent from the fetched results
    res = json.loads((SPIKE_DIR / "results_get_87047287.json").read_text(encoding="utf-8"))
    race = next(s for s in res["session_results"] if s["simsession_number"] == 0)
    opp = race["results"][0]  # the winner
    cid = opp["cust_id"]
    print(f"\nopponent: {opp['display_name']} cust_id={cid}")

    prof = cached_fetch(api, f"member_profile_{cid}", "/data/member/profile",
                        {"cust_id": cid})
    print("profile keys:", sorted(prof.keys()) if isinstance(prof, dict) else type(prof))

    chart = cached_fetch(api, f"chart_data_{cid}", "/data/member/chart_data",
                         {"cust_id": cid, "category_id": 5, "chart_type": 1})
    if isinstance(chart, dict):
        pts = chart.get("data", [])
        print(f"chart_data (sports car iR): {len(pts)} points; last 3: {pts[-3:]}")

    recent = cached_fetch(api, f"recent_races_{cid}",
                          "/data/stats/member_recent_races", {"cust_id": cid})
    races = recent.get("races", []) if isinstance(recent, dict) else recent
    print(f"recent_races: {len(races)}")
    if races:
        print("first:", json.dumps(races[0], indent=1)[:900])

    career = cached_fetch(api, f"member_career_{cid}",
                          "/data/stats/member_career", {"cust_id": cid})
    print("career:", json.dumps(career, indent=1)[:900])

    bests = cached_fetch(api, "member_bests_self_m2",
                         "/data/stats/member_bests",
                         {"cust_id": CUST_ID, "car_id": 4108})
    print("member_bests keys:", sorted(bests.keys()) if isinstance(bests, dict) else len(bests))
    if isinstance(bests, dict):
        print(json.dumps(bests, indent=1)[:900])


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "stage1"
    with make_api() as api:
        globals()[stage](api)
