"""Historical stats endpoints, computed from archived arrival events.

Headway (the gap between consecutive trains) is the natural reliability
metric for the subway: most lines run frequency-based service, so riders
care about even spacing, not a printed schedule. Regularity is reported as
the share of headways within 1.25x the median (README, design decision 10).

The gap arithmetic happens in Python after an indexed, filtered, joined
query. It could be pushed into SQL with window functions (LAG); it is kept
in Python to stay portable across SQLite and Postgres.
"""
import statistics
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.models.schemas import HeadwayGroup, Station as StationSchema, StationHeadways
from app.models.tables import ArrivalEvent, Route, Station, Trip

router = APIRouter(tags=["stats"])


@router.get("/stats/stations/{station_id}/headways", response_model=StationHeadways)
def station_headways(
    station_id: str,
    hours: int = Query(24, ge=1, le=168, description="Look-back window"),
    route: str | None = Query(None, description="Filter to one route, e.g. N"),
    direction: str | None = Query(None, pattern="^[NSns]$"),
    session: Session = Depends(db.get_session),
) -> StationHeadways:
    station = session.scalar(select(Station).where(Station.gtfs_stop_id == station_id))
    if station is None:
        raise HTTPException(
            status_code=404,
            detail=f"No archived data for station: {station_id}",
        )

    since = db.utcnow_naive() - timedelta(hours=hours)
    stmt = (
        select(ArrivalEvent.arrival_time, Route.gtfs_route_id, Trip.direction)
        .join(Trip, ArrivalEvent.trip_id == Trip.id)
        .join(Route, Trip.route_id == Route.id)
        .where(ArrivalEvent.station_id == station.id,
               ArrivalEvent.arrival_time >= since)
        .order_by(ArrivalEvent.arrival_time)
    )
    if route:
        stmt = stmt.where(Route.gtfs_route_id == route.upper())
    if direction:
        stmt = stmt.where(Trip.direction == direction.upper())
    rows = session.execute(stmt).all()

    by_group: dict[tuple[str, str], list] = {}
    for arrival_time, route_id, trip_direction in rows:
        by_group.setdefault((route_id, trip_direction), []).append(arrival_time)

    groups = []
    for (route_id, trip_direction), times in sorted(by_group.items()):
        mean, median, regularity = _headway_stats(times)
        groups.append(HeadwayGroup(
            route=route_id, direction=trip_direction, arrivals=len(times),
            mean_headway_minutes=mean, median_headway_minutes=median,
            regularity_pct=regularity,
        ))

    return StationHeadways(
        station=StationSchema(
            id=station.gtfs_stop_id,
            name=station.name,
            routes=sorted({g.route for g in groups}),
        ),
        window_hours=hours,
        total_arrivals=len(rows),
        groups=groups,
    )


def _headway_stats(times: list) -> tuple[float | None, float | None, float | None]:
    """(mean, median, regularity %) of the gaps between consecutive arrivals."""
    if len(times) < 2:
        return None, None, None
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
    median = statistics.median(gaps)
    regularity = 100 * sum(1 for g in gaps if g <= 1.25 * median) / len(gaps)
    return round(sum(gaps) / len(gaps), 1), round(median, 1), round(regularity, 1)
