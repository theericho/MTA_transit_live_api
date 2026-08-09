"""Arrival endpoints. Reads go through the Redis snapshot, never to the MTA
directly - the worker process owns ingestion (README, design decision 2).

Response semantics (README, design decisions 6 and 7):
- 503 until the worker has written its first snapshot
- 404 for a station id we've never seen
- 200 with an empty list for a known-but-quiet station
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cache, db
from app.models.schemas import Station, StationArrivals
from app.models.tables import Station as StationRow, StationComplex
from app.services import arrivals_reader

router = APIRouter(tags=["arrivals"])


@router.get("/stations/{station_id}/arrivals", response_model=StationArrivals)
async def get_station_arrivals(station_id: str) -> StationArrivals:
    if await cache.updated_at() is None:
        raise HTTPException(
            status_code=503,
            detail="No snapshot yet; the ingestion worker has not completed "
                   "a poll. Retry in a few seconds.",
        )
    result = await arrivals_reader.get_arrivals(station_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown station: {station_id}")
    return result


@router.get("/complexes/{complex_id}/arrivals", response_model=StationArrivals)
async def get_complex_arrivals(
    complex_id: int,
    session: Session = Depends(db.get_session),
) -> StationArrivals:
    """Arrivals across every GTFS station in a complex, merged and re-sorted.

    Herald Sq answers with B/D/F/M and N/Q/R/W together instead of forcing the
    caller to know it is two stations. The reported `data_age_seconds` is the
    worst (oldest) of the members, never the most flattering.
    """
    if await cache.updated_at() is None:
        raise HTTPException(
            status_code=503,
            detail="No snapshot yet; the ingestion worker has not completed "
                   "a poll. Retry in a few seconds.",
        )

    complex_ = session.get(StationComplex, complex_id)
    members = session.scalars(
        select(StationRow).where(StationRow.complex_id == complex_id)).all()
    if complex_ is None or not members:
        raise HTTPException(status_code=404, detail=f"Unknown complex: {complex_id}")

    # Read every member unclipped, then merge and clip once, so one busy
    # station cannot crowd the others out of the board.
    per_station = []
    for member in members:
        result = await arrivals_reader.get_arrivals(member.gtfs_stop_id, limit=None)
        if result is not None:
            per_station.append(result)

    arrivals = sorted((a for r in per_station for a in r.arrivals),
                      key=lambda a: a.arrival_time)
    return StationArrivals(
        station=Station(
            id=str(complex_id),
            name=complex_.name,
            routes=sorted({r for result in per_station for r in result.station.routes}),
        ),
        arrivals=arrivals[:arrivals_reader.ARRIVALS_LIMIT],
        data_age_seconds=max((r.data_age_seconds for r in per_station), default=0.0),
    )
