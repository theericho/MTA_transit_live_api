"""Arrival endpoints. Reads go through the Redis snapshot, never to the MTA
directly - the worker process owns ingestion (README, design decision 2).

Response semantics (README, design decisions 6 and 7):
- 503 until the worker has written its first snapshot
- 404 for a station id we've never seen
- 200 with an empty list for a known-but-quiet station
"""
from fastapi import APIRouter, HTTPException

from app import cache
from app.models.schemas import StationArrivals
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
