"""Read side of the arrivals pipeline: shape cache records into responses.

Runs in the API process. Reads the per-station records the worker wrote to
Redis (app/cache.py) and turns them into the StationArrivals response model.
The unknown-vs-quiet contract is unchanged from v2: None means the station
is unknown everywhere (404 upstream); a known station with nothing upcoming
returns an empty list (README, design decision 6).
"""
import time
from datetime import datetime, timezone

from app import cache
from app.models.schemas import Arrival, Station, StationArrivals
from app.services import routes
from app.services.stations import station_name

ARRIVALS_LIMIT = 10


async def get_arrivals(station_id: str,
                       limit: int | None = ARRIVALS_LIMIT) -> StationArrivals | None:
    """Shape one station's cached records into a response; None if unknown.

    `limit=None` returns every upcoming arrival, which the complex endpoint
    uses so it can merge members before clipping.
    """
    now = time.time()
    recs = await cache.read_station(station_id) or []
    name = station_name(station_id)
    if not recs and name is None:
        return None

    upcoming = [r for r in recs if r.time >= now][:limit]
    if upcoming:
        oldest_fetch = min(r.fetched_at for r in upcoming)
    else:
        oldest_fetch = await cache.updated_at() or now

    return StationArrivals(
        station=Station(
            id=station_id,
            name=name or station_id,
            routes=routes.display_names(r.route for r in recs),
        ),
        arrivals=[_arrival(r, now) for r in upcoming],
        data_age_seconds=round(now - oldest_fetch, 1),
    )


def _arrival(rec, now: float) -> Arrival:
    """Shape one cached record, translating the raw route id for display."""
    brand = routes.branding(rec.route)
    return Arrival(
        route=rec.route,
        route_name=brand.name,
        route_long_name=brand.long_name,
        express=brand.express,
        direction=rec.direction,
        arrival_time=datetime.fromtimestamp(rec.time, tz=timezone.utc),
        minutes_away=round(max(0.0, (rec.time - now) / 60), 1),
    )
