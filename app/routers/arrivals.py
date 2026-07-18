"""Arrival endpoints. Reads go through the feed service's snapshot, never to
the MTA directly - that separation keeps reads fast and the service testable.

Response semantics (README, design decisions 6 and 7):
- 503 until the first poll completes (no data yet is not the same as no trains)
- 404 for a station id we've never seen
- 200 with an empty list for a known-but-quiet station
"""
from fastapi import APIRouter, HTTPException

from app.models.schemas import StationArrivals
from app.services import feed

router = APIRouter(tags=["arrivals"])


@router.get("/stations/{station_id}/arrivals", response_model=StationArrivals)
async def get_station_arrivals(station_id: str) -> StationArrivals:
    if not feed.snapshot_ready():
        raise HTTPException(
            status_code=503,
            detail="Feed snapshot is warming up; retry in a few seconds.",
        )
    result = feed.get_arrivals(station_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown station: {station_id}")
    return result
