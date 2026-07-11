"""Assemble the DriverProfile from the stores — the package's only I/O.

Derive-on-demand: dozens of narratives + hundreds of lap rows, cheap to
recompute every render; no profile table, no staleness. Any store failure
degrades to an empty profile — the profile must never break a page.
"""

import logging

from core.profile.models import DriverProfile
from core.profile.pace import build_readiness
from core.profile.racecraft import build_racecraft
from core.race.race_store import RaceStore
from core.track.track_db import TrackDB

logger = logging.getLogger(__name__)


def load_profile(
    race_store: RaceStore, track_db: TrackDB, cust_id: int
) -> DriverProfile:
    """The driver's current profile, derived fresh from both stores."""
    try:
        narratives = race_store.get_narratives(cust_id)
    except Exception:  # noqa: BLE001 — profile must never break a page
        logger.exception("Profile: narrative load failed")
        narratives = []
    try:
        sessions = track_db.list_session_history()
        laps = {s.session_id: track_db.get_session_laps(s.session_id)
                for s in sessions}
    except Exception:  # noqa: BLE001
        logger.exception("Profile: session-history load failed")
        sessions, laps = [], {}

    readiness = build_readiness(sessions, laps)
    return DriverProfile(
        cust_id=cust_id,
        driver_name=(narratives[0].header.driver_name if narratives else ""),
        races_captured=len(narratives),
        combos_tracked=len(readiness),
        racecraft=build_racecraft(narratives),
        readiness=readiness,
    )
