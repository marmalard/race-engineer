"""Tests for Crew Chief track database seeder."""

import json

import pytest

from core.track.crew_chief_seeder import (
    format_corner_name,
    landmarks_to_corners,
    load_crew_chief_data,
    seed_track,
    seed_track_by_id,
    seed_all_tracks,
    _match_cross_sim,
    IRACING_TRACK_MAP,
    CROSS_SIM_MAP,
)
from core.track.models import Corner, Track, TrackType
from core.track.track_db import TrackDB


# --- format_corner_name ---


class TestFormatCornerName:
    def test_simple_snake_case(self):
        assert format_corner_name("canada_corner") == "Canada Corner"

    def test_single_word(self):
        assert format_corner_name("blanchimont") == "Blanchimont"

    def test_override_eau_rouge(self):
        assert format_corner_name("eau_rouge") == "Eau Rouge"

    def test_override_raidillon(self):
        assert format_corner_name("radillion") == "Raidillon"

    def test_override_mcphillamy(self):
        assert format_corner_name("mcphillamy_park") == "McPhillamy Park"

    def test_override_les_combes(self):
        assert format_corner_name("les_combes") == "Les Combes"

    def test_override_lesmo(self):
        assert format_corner_name("lesmos1") == "Lesmo 1"
        assert format_corner_name("lesmos2") == "Lesmo 2"

    def test_numbered_turn(self):
        assert format_corner_name("turn1") == "Turn1"

    def test_multi_word(self):
        assert format_corner_name("hell_corner") == "Hell Corner"
        assert format_corner_name("griffins_bend") == "Griffins Bend"


# --- landmarks_to_corners ---


SAMPLE_LANDMARKS = [
    {
        "landmarkName": "la_source",
        "distanceRoundLapStart": 360,
        "distanceRoundLapEnd": 430,
        "isCommonOvertakingSpot": True,
    },
    {
        "landmarkName": "eau_rouge",
        "distanceRoundLapStart": 1000,
        "distanceRoundLapEnd": 1230,
        "isCommonOvertakingSpot": False,
    },
]


class TestLandmarksToCorners:
    def test_converts_landmarks(self):
        corners = landmarks_to_corners("523", SAMPLE_LANDMARKS)
        assert len(corners) == 2

        assert corners[0].name == "La Source"
        assert corners[0].track_id == "523"
        assert corners[0].corner_number == 1
        assert corners[0].distance_start_meters == 360
        assert corners[0].distance_end_meters == 430
        assert corners[0].notes == "Common overtaking spot"

        assert corners[1].name == "Eau Rouge"
        assert corners[1].corner_number == 2
        assert corners[1].notes is None

    def test_corner_ids_are_none(self):
        corners = landmarks_to_corners("523", SAMPLE_LANDMARKS)
        for c in corners:
            assert c.corner_id is None

    def test_empty_landmarks(self):
        corners = landmarks_to_corners("123", [])
        assert corners == []


# --- load_crew_chief_data ---


BRANDS_HATCH_LANDMARKS = [
    {"landmarkName": "paddock_hill", "distanceRoundLapStart": 200,
     "distanceRoundLapEnd": 380, "isCommonOvertakingSpot": False},
    {"landmarkName": "druids", "distanceRoundLapStart": 550,
     "distanceRoundLapEnd": 670, "isCommonOvertakingSpot": True},
]

SAMPLE_CC_JSON = {
    "TrackLandmarksData": [
        {
            "irTrackName": "bathurst",
            "trackLandmarks": [
                {
                    "landmarkName": "hell_corner",
                    "distanceRoundLapStart": 210,
                    "distanceRoundLapEnd": 310,
                    "isCommonOvertakingSpot": True,
                }
            ],
        },
        {
            "pcarsTrackName": "some_pcars_track",
            "trackLandmarks": [
                {
                    "landmarkName": "turn1",
                    "distanceRoundLapStart": 100,
                    "distanceRoundLapEnd": 200,
                }
            ],
        },
        {
            "irTrackName": "spa up",
            "trackLandmarks": SAMPLE_LANDMARKS,
        },
        {
            # Cross-sim entry: Brands Hatch GP (no irTrackName)
            "pcarsTrackName": "Brands Hatch:GP",
            "acTrackNames": ["ks_brands_hatch"],
            "trackLandmarks": BRANDS_HATCH_LANDMARKS,
        },
    ]
}


class TestLoadCrewChiefData:
    def test_loads_from_cache(self, tmp_path):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(SAMPLE_CC_JSON), encoding="utf-8")

        tracks = load_crew_chief_data(cache_path=cache)
        # Returns iRacing entries + cross-sim matched entries
        names = {t.ir_track_name for t in tracks}
        assert "bathurst" in names
        assert "spa up" in names
        assert "xsim_brands_gp" in names
        assert len(tracks) == 3

    def test_filters_entries_without_ir_name(self, tmp_path):
        cache = tmp_path / "cache.json"
        data = {
            "TrackLandmarksData": [
                {"pcarsTrackName": "x", "trackLandmarks": [{"landmarkName": "t"}]},
                {"irTrackName": "", "trackLandmarks": [{"landmarkName": "t"}]},
            ]
        }
        cache.write_text(json.dumps(data), encoding="utf-8")
        tracks = load_crew_chief_data(cache_path=cache)
        assert len(tracks) == 0

    def test_handles_empty_data(self, tmp_path):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({"TrackLandmarksData": []}), encoding="utf-8")
        tracks = load_crew_chief_data(cache_path=cache)
        assert tracks == []


# --- seed_track ---


class TestSeedTrack:
    def test_seeds_known_track(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = TrackDB(db_path)

        seeded = seed_track(db, "bathurst", SAMPLE_CC_JSON["TrackLandmarksData"][0]["trackLandmarks"])
        assert seeded is True

        corners = db.get_corners("219")
        assert len(corners) == 1
        assert corners[0].name == "Hell Corner"
        assert corners[0].distance_start_meters == 210
        assert corners[0].notes == "Common overtaking spot"

    def test_creates_track_record(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = TrackDB(db_path)

        seed_track(db, "bathurst", [
            {"landmarkName": "hell_corner", "distanceRoundLapStart": 210,
             "distanceRoundLapEnd": 310, "isCommonOvertakingSpot": True},
        ])

        track = db.get_track("219")
        assert track is not None
        assert track.name == "Mount Panorama Circuit"

    def test_skips_unknown_ir_track_name(self, tmp_path):
        db = TrackDB(tmp_path / "test.db")
        seeded = seed_track(db, "unknown_track", [{"landmarkName": "t", "distanceRoundLapStart": 0, "distanceRoundLapEnd": 1}])
        assert seeded is False

    def test_skips_existing_named_corners(self, tmp_path):
        db = TrackDB(tmp_path / "test.db")

        # First seed
        landmarks = [
            {"landmarkName": "hell_corner", "distanceRoundLapStart": 210,
             "distanceRoundLapEnd": 310, "isCommonOvertakingSpot": True},
        ]
        seed_track(db, "bathurst", landmarks)

        # Second seed should skip
        seeded = seed_track(db, "bathurst", landmarks)
        assert seeded is False

    def test_force_overwrites(self, tmp_path):
        db = TrackDB(tmp_path / "test.db")

        landmarks = [
            {"landmarkName": "hell_corner", "distanceRoundLapStart": 210,
             "distanceRoundLapEnd": 310, "isCommonOvertakingSpot": True},
        ]
        seed_track(db, "bathurst", landmarks)

        new_landmarks = [
            {"landmarkName": "hell_corner", "distanceRoundLapStart": 210,
             "distanceRoundLapEnd": 310, "isCommonOvertakingSpot": True},
            {"landmarkName": "griffins_bend", "distanceRoundLapStart": 1300,
             "distanceRoundLapEnd": 1490, "isCommonOvertakingSpot": True},
        ]
        seeded = seed_track(db, "bathurst", new_landmarks, force=True)
        assert seeded is True
        corners = db.get_corners("219")
        assert len(corners) == 2


# --- seed_track_by_id ---


class TestSeedTrackById:
    def test_seeds_by_numeric_id(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = TrackDB(db_path)
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(SAMPLE_CC_JSON), encoding="utf-8")

        seeded = seed_track_by_id(db, "219", cache_path=cache)
        assert seeded is True
        corners = db.get_corners("219")
        assert len(corners) == 1
        assert corners[0].name == "Hell Corner"

    def test_returns_false_for_unknown_id(self, tmp_path):
        db = TrackDB(tmp_path / "test.db")
        seeded = seed_track_by_id(db, "99999")
        assert seeded is False

    def test_seeds_spa_by_id(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = TrackDB(db_path)
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(SAMPLE_CC_JSON), encoding="utf-8")

        seeded = seed_track_by_id(db, "523", cache_path=cache)
        assert seeded is True
        corners = db.get_corners("523")
        assert len(corners) == 2
        assert corners[0].name == "La Source"
        assert corners[1].name == "Eau Rouge"


# --- seed_all_tracks ---


class TestSeedAllTracks:
    def test_seeds_multiple_tracks(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = TrackDB(db_path)
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(SAMPLE_CC_JSON), encoding="utf-8")

        results = seed_all_tracks(db, cache_path=cache)
        assert results["bathurst"] is True
        assert results["spa up"] is True

    def test_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = TrackDB(db_path)
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(SAMPLE_CC_JSON), encoding="utf-8")

        seed_all_tracks(db, cache_path=cache)
        results = seed_all_tracks(db, cache_path=cache)
        # Second run should skip all
        assert results["bathurst"] is False
        assert results["spa up"] is False


# --- IRACING_TRACK_MAP validation ---


class TestTrackMap:
    def test_verified_track_ids(self):
        """Verified track IDs from actual IBT files."""
        assert IRACING_TRACK_MAP["bathurst"][0] == "219"
        assert IRACING_TRACK_MAP["spa up"][0] == "523"
        assert IRACING_TRACK_MAP["roadamerica full"][0] == "18"
        assert IRACING_TRACK_MAP["lagunaseca"][0] == "47"
        assert IRACING_TRACK_MAP["monza full"][0] == "239"
        assert IRACING_TRACK_MAP["sebring international"][0] == "95"

    def test_all_entries_have_required_fields(self):
        for ir_name, (track_id, display_name, config) in IRACING_TRACK_MAP.items():
            assert track_id, f"{ir_name} missing track_id"
            assert display_name, f"{ir_name} missing display_name"
            # config can be None

    def test_cross_sim_keys_exist_in_track_map(self):
        """Every canonical key in CROSS_SIM_MAP should exist in IRACING_TRACK_MAP."""
        for canonical_key in CROSS_SIM_MAP:
            assert canonical_key in IRACING_TRACK_MAP, (
                f"CROSS_SIM_MAP key '{canonical_key}' missing from IRACING_TRACK_MAP"
            )


# --- Cross-sim matching ---


class TestCrossSimMatching:
    def test_matches_pcars_brands_hatch(self):
        entry = {"pcarsTrackName": "Brands Hatch:GP", "trackLandmarks": []}
        assert _match_cross_sim(entry) == "xsim_brands_gp"

    def test_matches_rf1_list_field(self):
        entry = {"rf1TrackNames": ["VIR Grand Course"], "trackLandmarks": []}
        assert _match_cross_sim(entry) == "xsim_vir_grand"

    def test_no_match_unknown_entry(self):
        entry = {"pcarsTrackName": "Unknown Track:GP", "trackLandmarks": []}
        assert _match_cross_sim(entry) is None

    def test_no_match_empty_entry(self):
        entry = {"trackLandmarks": []}
        assert _match_cross_sim(entry) is None

    def test_load_includes_cross_sim_entries(self, tmp_path):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(SAMPLE_CC_JSON), encoding="utf-8")

        tracks = load_crew_chief_data(cache_path=cache)
        names = {t.ir_track_name for t in tracks}
        # Should have iRacing entries + the Brands Hatch cross-sim entry
        assert "bathurst" in names
        assert "spa up" in names
        assert "xsim_brands_gp" in names
        # The unmatched pcars entry should NOT be included
        assert len(tracks) == 3

    def test_seed_cross_sim_track(self, tmp_path):
        db = TrackDB(tmp_path / "test.db")
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(SAMPLE_CC_JSON), encoding="utf-8")

        results = seed_all_tracks(db, cache_path=cache)
        assert results.get("xsim_brands_gp") is True

        corners = db.get_corners("145")
        assert len(corners) == 2
        assert corners[0].name == "Paddock Hill Bend"
        assert corners[1].name == "Druids"

    def test_seed_cross_sim_by_id(self, tmp_path):
        db = TrackDB(tmp_path / "test.db")
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps(SAMPLE_CC_JSON), encoding="utf-8")

        seeded = seed_track_by_id(db, "145", cache_path=cache)
        assert seeded is True
        corners = db.get_corners("145")
        assert len(corners) == 2
