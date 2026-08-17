"""Route branding: translate GTFS route ids into what riders actually see.

Two separate mechanisms, because the data only covers half the problem:

1. A lookup, loaded from routes.txt into the routes table. GS, FS and H are
   three unrelated shuttles that GTFS must keep distinct but the MTA signs
   identically as "S"; SI is signed "SIR". No station is served by more than
   one shuttle, so a single board can never show an ambiguous "S". Those four
   ids also have a hardcoded fallback, so they are named correctly on a
   database the static load has never touched.
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


# gtfs_route_id -> (short_name, long_name), for the rows that carry branding.
_routes: dict[str, tuple[str, str | None]] = {}

# Every route id the database knows, branded or not. branding() answers for all
# of them, so ids_for() has to search the same set: anything narrower can
# advertise a name on a bullet that no filter can then resolve.
_ids: set[str] = set()

# The four ids riders never see, so a name is right before routes.txt has been
# loaded - the same hand-checked fallback stations.py keeps for station names.
# load_from_db() replaces these with the real values and their long names.
_FALLBACK = {"GS": "S", "FS": "S", "H": "S", "SI": "SIR"}


def load_from_db() -> int:
    """Read route branding into memory. Called at API startup.

    The worker does not need it: it writes raw GTFS ids, and translation
    happens on read. Returns how many routes are branded; zero simply means the
    static GTFS load has not been run yet, in which case raw ids are shown
    unchanged.

    Only rows carrying a short_name count. The archiver creates bare Route rows
    for whatever it observes, and letting those in would register an id as its
    own branding, shadowing _FALLBACK on exactly the databases it exists for.
    """
    from sqlalchemy import select

    from app import db
    from app.models.tables import Route

    with db.SessionLocal() as session:
        rows = session.scalars(select(Route)).all()
    _ids.update(r.gtfs_route_id for r in rows)
    _routes.update({r.gtfs_route_id: (r.short_name, r.long_name)
                    for r in rows if r.short_name})
    if _routes:
        log.info("loaded branding for %d routes", len(_routes))
    return len(_routes)


def _known() -> set[str]:
    """Every route id the system can be asked about, branded or not."""
    return _ids | set(_FALLBACK)


def _resolve(route_id: str) -> tuple[str, str | None]:
    """(short_name, long_name) for one id, before the express convention."""
    if route_id in _routes:
        return _routes[route_id]
    return _FALLBACK.get(route_id, route_id), None


def branding(route_id: str) -> Branding:
    """How a route should be presented. Unknown ids pass through unchanged."""
    short, long_name = _resolve(route_id)

    # An X suffix means express, but only when the base route actually exists:
    # that keeps a genuine route ending in X from being silently truncated.
    # Existing means the database has seen it, branded or not - the archiver
    # records real service long before routes.txt is ever loaded.
    base_id = short[:-1]
    if len(short) > 1 and short.endswith("X") and base_id in _known():
        base, base_long = _resolve(base_id)
        return Branding(name=base, long_name=long_name or base_long, express=True)

    return Branding(name=short, long_name=long_name, express=False)


def display_names(route_ids) -> list[str]:
    """Sorted, deduplicated display names: F and FX collapse to one F."""
    return sorted({branding(r).name for r in route_ids})


def ids_for(name: str) -> list[str]:
    """Raw ids a rider-facing name refers to: "S" -> GS, FS, H; "F" -> F, FX.

    The inverse of branding(), backing the route_name filter: whatever a
    response advertises has to be filterable by the same word. Exact-id
    filtering is a separate parameter, so this one never has to guess which
    vocabulary the caller meant. Unknown input passes through, which keeps
    filtering working before the static load has run.
    """
    wanted = name.upper()
    return sorted({r for r in _known() if branding(r).name.upper() == wanted} | {wanted})


def is_display_name(value: str) -> bool:
    """True if this is what a bullet reads rather than a GTFS id.

    Lets the exact-id filter reject a rider-facing name outright instead of
    answering an empty 200 that looks like "no service". Deliberately narrow:
    an id the database has seen is never a name, and an unrecognised value is
    left alone, so nothing is rejected merely because the static load has not
    run yet.
    """
    wanted = value.upper()
    if wanted in _ids:
        return False
    return any(branding(r).name.upper() == wanted for r in _known())


def reset() -> None:
    """Clear loaded branding. Test hook."""
    _routes.clear()
    _ids.clear()
