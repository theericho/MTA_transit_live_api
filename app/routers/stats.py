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
from app.models.tables import ArrivalEvent, Route, Station, StationComplex, Trip
from app.services import routes

router = APIRouter(tags=["stats"])


@router.get("/stats/stations/{station_id}/headways", response_model=StationHeadways)
def station_headways(
    station_id: str,
    hours: int = Query(24, ge=1, le=168, description="Look-back window"),
    route: str | None = Query(None, description="Filter to one route by name or "
                                                "GTFS id, e.g. N, S, GS"),
    direction: str | None = Query(None, pattern="^[NSns]$"),
    session: Session = Depends(db.get_session),
) -> StationHeadways:
    station = session.scalar(select(Station).where(Station.gtfs_stop_id == station_id))
    if station is None:
        raise HTTPException(
            status_code=404,
            detail=f"No archived data for station: {station_id}",
        )
    return _headways(session, [station.id], station.gtfs_stop_id, station.name,
                     hours, route, direction)


@router.get("/stats/complexes/{complex_id}/headways", response_model=StationHeadways)
def complex_headways(
    complex_id: int,
    hours: int = Query(24, ge=1, le=168, description="Look-back window"),
    route: str | None = Query(None, description="Filter to one route by name or "
                                                "GTFS id, e.g. N, S, GS"),
    direction: str | None = Query(None, pattern="^[NSns]$"),
    session: Session = Depends(db.get_session),
) -> StationHeadways:
    """Headways across every station in a complex.

    Routes rarely overlap between a complex's members, so grouping by
    (route, direction) keeps the numbers meaningful even when pooling stations.
    """
    complex_ = session.get(StationComplex, complex_id)
    members = session.scalars(
        select(Station).where(Station.complex_id == complex_id)).all()
    if complex_ is None or not members:
        raise HTTPException(
            status_code=404,
            detail=f"No archived data for complex: {complex_id}",
        )
    return _headways(session, [m.id for m in members], str(complex_id),
                     complex_.name, hours, route, direction)


def _headways(session: Session, station_ids: list[int], out_id: str, out_name: str,
              hours: int, route: str | None, direction: str | None) -> StationHeadways:
    since = db.utcnow_naive() - timedelta(hours=hours)
    stmt = (
        select(ArrivalEvent.arrival_time, Route.gtfs_route_id, Trip.direction)
        .join(Trip, ArrivalEvent.trip_id == Trip.id)
        .join(Route, Trip.route_id == Route.id)
        .where(ArrivalEvent.station_id.in_(station_ids),
               ArrivalEvent.arrival_time >= since)
        .order_by(ArrivalEvent.arrival_time)
    )
    if route:
        # Accepts what the response advertises, not just the raw id: "S" has to
        # find the GS/FS/H shuttles, and "F" both the F and its FX express.
        stmt = stmt.where(Route.gtfs_route_id.in_(routes.ids_for(route)))
    if direction:
        stmt = stmt.where(Trip.direction == direction.upper())
    rows = session.execute(stmt).all()

    by_group: dict[tuple[str, str], list] = {}
    for arrival_time, route_id, trip_direction in rows:
        by_group.setdefault((route_id, trip_direction), []).append(arrival_time)

    groups = []
    for (route_id, trip_direction), times in sorted(by_group.items()):
        mean, median, regularity = _headway_stats(times)
        # Grouping stays keyed on the raw id so F and FX remain separate rows:
        # they are genuinely different service patterns.
        brand = routes.branding(route_id)
        groups.append(HeadwayGroup(
            route=route_id, route_name=brand.name,
            route_long_name=brand.long_name, express=brand.express,
            direction=trip_direction, arrivals=len(times),
            mean_headway_minutes=mean, median_headway_minutes=median,
            regularity_pct=regularity,
        ))

    return StationHeadways(
        station=StationSchema(
            id=out_id,
            name=out_name,
            routes=sorted({g.route_name for g in groups}),
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
