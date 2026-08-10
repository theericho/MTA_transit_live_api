"""Route branding: translate GTFS route ids into what riders actually see.

Two separate mechanisms, because the data only covers half the problem:

1. A lookup, loaded from routes.txt into the routes table. GS, FS and H are
   three unrelated shuttles that GTFS must keep distinct but the MTA signs
   identically as "S"; SI is signed "SIR". No station is served by more than
   one shuttle, so a single board can never show an ambiguous "S".
2. A convention. The express variants FX, 6X and 7X carry their own id as
   their short name, so routes.txt cannot tell us they are the F, 6 and 7.
   MTA signage renders express service as a diamond bullet, so the rule is:
   a trailing X on a known route means "that route, express".

Raw ids stay the join key everywhere in the database; translation happens on
read (README, design decision 14).
"""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Branding:
    name: str            # what the bullet reads: "S", "F", "6"
    long_name: str | None  # "42 St Shuttle", for a tooltip
    express: bool        # render as a diamond rather than a circle


# gtfs_route_id -> (short_name, long_name), loaded from the database.
_routes: dict[str, tuple[str, str | None]] = {}


def load_from_db() -> int:
    """Read route branding into memory. Called at API startup.

    The worker does not need it: it writes raw GTFS ids, and translation
    happens on read. Returns how many routes are known; zero simply means the
    static GTFS load has not been run yet, in which case raw ids are shown
    unchanged.
    """
    from sqlalchemy import select

    from app import db
    from app.models.tables import Route

    with db.SessionLocal() as session:
        rows = session.scalars(select(Route)).all()
    _routes.update({r.gtfs_route_id: (r.short_name or r.gtfs_route_id, r.long_name)
                    for r in rows})
    if _routes:
        log.info("loaded branding for %d routes", len(_routes))
    return len(_routes)


def branding(route_id: str) -> Branding:
    """How a route should be presented. Unknown ids pass through unchanged."""
    short, long_name = _routes.get(route_id, (route_id, None))

    # An X suffix means express, but only when the base route actually exists:
    # that keeps a genuine route ending in X from being silently truncated.
    if len(short) > 1 and short.endswith("X") and short[:-1] in _routes:
        base, base_long = _routes[short[:-1]]
        return Branding(name=base, long_name=long_name or base_long, express=True)

    return Branding(name=short, long_name=long_name, express=False)


def display_names(route_ids) -> list[str]:
    """Sorted, deduplicated display names: F and FX collapse to one F."""
    return sorted({branding(r).name for r in route_ids})


def ids_for(name: str) -> list[str]:
    """Raw ids a rider-facing name refers to: "S" -> GS, FS, H; "F" -> F, FX.

    The inverse of branding(), for query filters: a caller who reads "S" off a
    response has to be able to filter by it. The name itself is always included,
    so raw ids keep working, as does every filter before the static load has run.
    """
    wanted = name.upper()
    return sorted({r for r in _routes if branding(r).name.upper() == wanted} | {wanted})


def reset() -> None:
    """Clear loaded branding. Test hook."""
    _routes.clear()
