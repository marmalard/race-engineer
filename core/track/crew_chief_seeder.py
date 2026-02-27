"""Seed track database from Crew Chief trackLandmarksData.json.

Crew Chief maintains an open-source database of track corner names with
distance-based positioning. This module downloads, parses, and imports
that data into our TrackDB for use in coaching.

Source: https://gitlab.com/mr_belowski/CrewChiefV4
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from core.track.models import Corner, Track, TrackType
from core.track.track_db import TrackDB

logger = logging.getLogger(__name__)

CREW_CHIEF_URL = (
    "https://gitlab.com/mr_belowski/CrewChiefV4/-/raw/master/"
    "CrewChiefV4/trackLandmarksData.json"
)

# Crew Chief irTrackName -> (iRacing numeric track_id, display_name, config)
# Track IDs verified from actual IBT files where available.
IRACING_TRACK_MAP: dict[str, tuple[str, str, str | None]] = {
    # User's tracks (verified IDs)
    "bathurst": ("219", "Mount Panorama Circuit", None),
    "spa up": ("523", "Circuit de Spa-Francorchamps", "Grand Prix"),
    "roadamerica full": ("18", "Road America", "Full Course"),
    "lagunaseca": ("47", "WeatherTech Raceway Laguna Seca", None),
    "monza full": ("239", "Autodromo Nazionale Monza", None),
    "sebring international": ("95", "Sebring International Raceway", "International"),
    # Remaining Crew Chief tracks (IDs to be verified when user drives them)
    "sebring club course": ("233", "Sebring International Raceway", "Club"),
    "phillipisland": ("167", "Phillip Island Circuit", None),
    "hungaroring": ("225", "Hungaroring", None),
    "imola gp": ("283", "Autodromo Enzo e Dino Ferrari", "Grand Prix"),
    "spielberg gp": ("299", "Red Bull Ring", "Grand Prix"),
    "zandvoort grandprix": ("341", "Circuit Zandvoort", "Grand Prix"),
    "knockhill international": ("353", "Knockhill Racing Circuit", "International"),
    "montreal": ("125", "Circuit Gilles Villeneuve", None),
    "limerock full": ("111", "Lime Rock Park", "Full Course"),
    "limerock chicane": ("112", "Lime Rock Park", "Chicane"),
    "zolder gp": ("343", "Circuit Zolder", "Grand Prix"),
    "oulton fosters": ("293", "Oulton Park", "Fosters"),
    "oulton international": ("294", "Oulton Park", "International"),
    "oulton inthislop": ("295", "Oulton Park", "International with Hislop"),
    "oulton islandhistoric": ("296", "Oulton Park", "Island Historic"),
    # Cross-sim entries (no irTrackName in CC, matched by other name fields)
    "xsim_brands_gp": ("145", "Brands Hatch Circuit", "Grand Prix"),
    "xsim_nurburgring_gp": ("187", "Nürburgring Grand-Prix-Strecke", None),
    "xsim_silverstone_national": ("268", "Silverstone Circuit", "National"),
    "xsim_lemans_24h": ("169", "Circuit des 24 Heures du Mans", None),
    "xsim_vir_grand": ("371", "Virginia International Raceway", "Grand Course"),
    "xsim_donington_gp": ("351", "Donington Park Racing Circuit", "Grand Prix"),
    "xsim_suzuka": ("310", "Suzuka International Racing Course", None),
    "xsim_hockenheim_gp": ("207", "Hockenheimring Baden-Württemberg", "Grand Prix"),
    "xsim_mid_ohio_chicane": ("281", "Mid-Ohio Sports Car Course", "Full Course"),
}

# Match Crew Chief entries WITHOUT irTrackName to our canonical keys.
# Maps (json_field, value) -> canonical key in IRACING_TRACK_MAP.
# Only the first match per canonical key is used.
CROSS_SIM_MAP: dict[str, dict[str, str]] = {
    # key: canonical map key, value: dict of {field_name: value_to_match}
    "xsim_brands_gp": {"pcarsTrackName": "Brands Hatch:GP"},
    "xsim_nurburgring_gp": {"pcarsTrackName": "Nurburgring:Grand Prix"},
    "xsim_silverstone_national": {"pcarsTrackName": "Silverstone:National"},
    "xsim_lemans_24h": {"pcarsTrackName": "Le Mans:Circuit des 24 Heures du Mans"},
    "xsim_vir_grand": {"rf1TrackNames": "VIR Grand Course"},
    "xsim_donington_gp": {"pcarsTrackName": "Donington Park:Grand Prix"},
    "xsim_suzuka": {"acTrackNames": "ks_suzuka"},
    "xsim_hockenheim_gp": {"pcarsTrackName": "Hockenheim:Grand Prix"},
    "xsim_mid_ohio_chicane": {"rf1TrackNames": "Mid-Ohio Sports Car Course with Chicane"},
}

# Name formatting overrides for proper capitalization
NAME_OVERRIDES: dict[str, str] = {
    "eau_rouge": "Eau Rouge",
    "radillion": "Raidillon",
    "mcphillamy_park": "McPhillamy Park",
    "les_combes": "Les Combes",
    "lesmos1": "Lesmo 1",
    "lesmos2": "Lesmo 2",
    "la_source": "La Source",
    "variante_del_rettifilo": "Variante del Rettifilo",
    "variante_della_roggia": "Variante della Roggia",
    "curva_grande": "Curva Grande",
    "curva_parabolica": "Curva Parabolica",
    "fangio_chicane": "Fangio Chicane",
    "the_andretti_hairpin": "Andretti Hairpin",
    "the_corkscrew": "The Corkscrew",
    "the_cutting": "The Cutting",
    "the_dipper": "The Dipper",
    "the_esses": "The Esses",
    "the_chase": "The Chase",
    "the_sweep": "The Sweep",
    "the_kink": "The Kink",
    "the_carousel": "The Carousel",
    "the_hairpin": "The Hairpin",
    "le_mans": "Le Mans",
    "rainey_curve": "Rainey Curve",
    "bill_mitchell_bend": "Bill Mitchell Bend",
    # Brands Hatch
    "paddock_hill": "Paddock Hill Bend",
    "graham_hill_bend": "Graham Hill Bend",
    "dingle_dell": "Dingle Dell",
    # Nurburgring
    "the_chicane": "The Chicane",
    # Le Mans
    "dunlop_curve": "Dunlop Curve",
    "dunlop_chicane": "Dunlop Chicane",
    "tetre_rouge": "Tertre Rouge",
    "playstation_chicane": "Playstation Chicane",
    "michelin_chicane": "Michelin Chicane",
    "porsche_curves": "Porsche Curves",
    "the_first_ford_chicane": "Ford Chicane 1",
    "the_second_ford_chicane": "Ford Chicane 2",
    # VIR
    "nascar_bend": "NASCAR Bend",
    "left_hook": "Left Hook",
    "south_bend": "South Bend",
    "oak_tree": "Oak Tree",
    "the_bitch": "The Bitch",
    "roller_coaster": "Roller Coaster",
    "hog_pen": "Hog Pen",
    # Donington
    "the_craner_curves": "Craner Curves",
    "the_old_hairpin": "Old Hairpin",
    "melbourne_hairpin": "Melbourne Hairpin",
    # Suzuka
    "degner1": "Degner 1",
    "degner2": "Degner 2",
    "130R": "130R",
    "spoon_curve": "Spoon Curve",
    # Hockenheim
    "nord_kurve": "Nordkurve",
    "mobile_1": "Mobil 1",
    "sud_kurve": "Südkurve",
    # Mid-Ohio
    "thunder_valley": "Thunder Valley",
    "the_carousel": "The Carousel",
}


def format_corner_name(raw_name: str) -> str:
    """Convert Crew Chief snake_case landmark name to display name.

    Uses overrides for proper names, falls back to title-casing with
    underscores replaced by spaces.
    """
    if raw_name in NAME_OVERRIDES:
        return NAME_OVERRIDES[raw_name]
    return raw_name.replace("_", " ").title()


@dataclass
class CrewChiefTrack:
    """Parsed track data from Crew Chief JSON."""

    ir_track_name: str
    landmarks: list[dict]


def _match_cross_sim(entry: dict) -> str | None:
    """Try to match a CC entry without irTrackName via cross-sim name fields.

    Returns a canonical key from IRACING_TRACK_MAP, or None if no match.
    """
    for canonical_key, match_criteria in CROSS_SIM_MAP.items():
        for field_name, expected_value in match_criteria.items():
            actual = entry.get(field_name)
            if actual is None:
                continue
            # Some fields are lists (acTrackNames, rf1TrackNames, rf2TrackNames)
            values = actual if isinstance(actual, list) else [actual]
            if expected_value in values:
                return canonical_key
    return None


def load_crew_chief_data(
    cache_path: Path | None = None,
) -> list[CrewChiefTrack]:
    """Load Crew Chief track landmarks data.

    Downloads from GitLab if no cache exists, otherwise reads cache.
    Returns entries with irTrackName and cross-sim matched entries.
    """
    raw = None

    if cache_path and cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cache read failed (%s), will re-download", exc)

    if raw is None:
        resp = httpx.get(CREW_CHIEF_URL, timeout=30.0)
        resp.raise_for_status()
        raw = resp.json()
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(raw), encoding="utf-8")

    tracks: list[CrewChiefTrack] = []
    matched_xsim_keys: set[str] = set()

    for entry in raw.get("TrackLandmarksData", []):
        if not entry.get("trackLandmarks"):
            continue

        # Primary: direct iRacing match
        ir_name = (entry.get("irTrackName") or "").strip()
        if ir_name:
            tracks.append(
                CrewChiefTrack(
                    ir_track_name=ir_name,
                    landmarks=entry["trackLandmarks"],
                )
            )
            continue

        # Secondary: cross-sim match (only first match per canonical key)
        xsim_key = _match_cross_sim(entry)
        if xsim_key and xsim_key not in matched_xsim_keys:
            matched_xsim_keys.add(xsim_key)
            tracks.append(
                CrewChiefTrack(
                    ir_track_name=xsim_key,
                    landmarks=entry["trackLandmarks"],
                )
            )

    return tracks


def landmarks_to_corners(
    track_id: str,
    landmarks: list[dict],
) -> list[Corner]:
    """Convert Crew Chief landmarks to Corner model objects."""
    corners: list[Corner] = []
    for i, lm in enumerate(landmarks, 1):
        name = format_corner_name(lm["landmarkName"])
        is_overtaking = lm.get("isCommonOvertakingSpot", False)
        notes = "Common overtaking spot" if is_overtaking else None

        corners.append(
            Corner(
                corner_id=None,
                track_id=track_id,
                corner_number=i,
                name=name,
                distance_start_meters=lm["distanceRoundLapStart"],
                distance_end_meters=lm["distanceRoundLapEnd"],
                corner_type=None,
                notes=notes,
            )
        )
    return corners


def seed_track(
    db: TrackDB,
    ir_track_name: str,
    landmarks: list[dict],
    force: bool = False,
) -> bool:
    """Seed a single track from Crew Chief data.

    Returns True if seeded, False if skipped (already has named corners
    or no mapping exists for this irTrackName).
    """
    mapping = IRACING_TRACK_MAP.get(ir_track_name)
    if mapping is None:
        return False

    track_id, display_name, config = mapping

    # Skip if track already has named corners (unless forced)
    existing = db.get_corners(track_id)
    if existing and any(c.name for c in existing) and not force:
        return False

    # Upsert the track record
    db.upsert_track(
        Track(
            track_id=track_id,
            name=display_name,
            config=config,
            length_meters=0.0,
            track_type=TrackType.ROAD,
            character=None,
            notes=None,
            corners=[],
        )
    )

    # Convert and store corners
    corners = landmarks_to_corners(track_id, landmarks)
    db.upsert_corners(track_id, corners)
    logger.info(
        "Seeded %d corners for %s (track_id=%s)", len(corners), display_name, track_id
    )
    return True


def seed_all_tracks(
    db: TrackDB,
    cache_path: Path | None = None,
    force: bool = False,
) -> dict[str, bool]:
    """Seed all available tracks from Crew Chief data.

    Returns dict of irTrackName -> seeded (True/False).
    """
    cc_tracks = load_crew_chief_data(cache_path)
    results: dict[str, bool] = {}
    for cc_track in cc_tracks:
        results[cc_track.ir_track_name] = seed_track(
            db, cc_track.ir_track_name, cc_track.landmarks, force
        )
    return results


def seed_track_by_id(
    db: TrackDB,
    track_id: str,
    cache_path: Path | None = None,
) -> bool:
    """Seed a specific track by iRacing numeric track_id.

    This is the lazy-seeding entry point called from the coaching pipeline.
    Looks up the Crew Chief irTrackName for this track_id and seeds if found.
    """
    # Reverse lookup: find the irTrackName for this numeric track_id
    ir_name: str | None = None
    for name, (tid, _, _) in IRACING_TRACK_MAP.items():
        if tid == track_id:
            ir_name = name
            break

    if ir_name is None:
        return False

    cc_tracks = load_crew_chief_data(cache_path)
    for cc_track in cc_tracks:
        if cc_track.ir_track_name == ir_name:
            return seed_track(db, ir_name, cc_track.landmarks)

    return False
