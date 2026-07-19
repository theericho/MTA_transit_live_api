"""Station-name directory.

Full station metadata comes from the MTA's static GTFS: run
scripts/load_gtfs_static.py once to load every parent station into the
database, and the names are read into memory at app startup. A small
hand-checked map remains as a fallback so the API works before that load.

A stop id here is the *parent* station id - platform ids in the realtime feed
add a direction suffix (R16N / R16S -> R16).
"""
import logging

log = logging.getLogger(__name__)

STATION_NAMES = {
    "R16": "Times Sq-42 St",       # N/Q/R/W platforms
    "127": "Times Sq-42 St",       # 1/2/3 platforms
    "631": "Grand Central-42 St",  # 4/5/6 platforms
    "L08": "Bedford Av",           # L
}

# Names loaded from the stations table at startup (see load_names_from_db).
_db_names: dict[str, str] = {}


def station_name(station_id: str) -> str | None:
    return _db_names.get(station_id) or STATION_NAMES.get(station_id)


def load_names_from_db() -> int:
    """Read all station names from the database into memory.

    Called at app startup. Returns how many names are loaded; zero simply
    means the static GTFS load has not been run yet.
    """
    from sqlalchemy import select

    from app import db
    from app.models.tables import Station

    with db.SessionLocal() as session:
        rows = session.scalars(select(Station)).all()
    _db_names.update({s.gtfs_stop_id: s.name for s in rows})
    if _db_names:
        log.info("loaded %d station names from the database", len(_db_names))
    return len(_db_names)
