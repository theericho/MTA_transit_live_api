"""Station directory: the search endpoint the dashboard's picker depends on.

Results are grouped by station complex, so "Herald" returns one entry covering
both R17 (N/Q/R/W) and D17 (B/D/F/M) rather than two identical-looking rows
(README, design decision 12). Stations without a complex - the state before
scripts/load_gtfs_static.py has run - come back as their own entries, which is
why each result carries a `kind` telling the client which endpoint to call.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import db
from app.models.schemas import StationSearchResult
from app.models.tables import Station, StationComplex

router = APIRouter(tags=["stations"])


@router.get("/stations", response_model=list[StationSearchResult])
def search_stations(
    search: str = Query("", description="Case-insensitive substring of the name"),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(db.get_session),
) -> list[StationSearchResult]:
    stmt = select(Station, StationComplex).outerjoin(
        StationComplex, Station.complex_id == StationComplex.id)
    term = search.strip()
    if term:
        pattern = f"%{term}%"
        stmt = stmt.where(or_(Station.name.ilike(pattern),
                              StationComplex.name.ilike(pattern)))

    grouped: dict[tuple[str, str], dict] = {}
    for station, complex_ in session.execute(stmt).all():
        if complex_ is not None:
            key = ("complex", str(complex_.id))
            name = complex_.name
        else:
            key = ("station", station.gtfs_stop_id)
            name = station.name
        entry = grouped.setdefault(key, {"name": name, "routes": set(), "stations": []})
        entry["stations"].append(station.gtfs_stop_id)
        entry["routes"].update((station.daytime_routes or "").split())

    results = [
        StationSearchResult(
            id=key_id,
            kind=kind,
            name=entry["name"],
            routes=sorted(entry["routes"]),
            station_ids=sorted(entry["stations"]),
        )
        for (kind, key_id), entry in grouped.items()
    ]
    results.sort(key=lambda r: r.name)
    return results[:limit]
