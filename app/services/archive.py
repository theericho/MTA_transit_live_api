"""Arrival archiver: turns live predictions into historical arrival events.

The realtime feed only says what is about to happen. To build history we
track the latest prediction per (trip, station) across polls and, once its
arrival time passes, record it as an observed arrival (README, design
decision 4).

A prediction is only archived if the feed data behind it was still fresh
close to the arrival moment (FRESHNESS_WINDOW). A train that vanished from
the feed long before its predicted arrival was likely cancelled or rerouted,
so its pending prediction is dropped instead of archived.
"""
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.models.tables import ArrivalEvent, Route, Station, Trip
from app.services.feed import ArrivalRecord
from app.services.stations import station_name

log = logging.getLogger(__name__)

# Latest prediction per (trip_id, parent station id), refreshed each poll.
_pending: dict[tuple[str, str], ArrivalRecord] = {}

# Keys already flushed, mapped to the time we flushed them. A train often
# stays in the feed after its arrival time passes; without this guard it
# would be re-added to _pending and archived once per poll.
_done: dict[tuple[str, str], float] = {}

# Archive only if the prediction was fetched within this many seconds of the
# arrival time (the train was still on the board when it arrived).
FRESHNESS_WINDOW = 120.0

# Forget flushed keys after this long; by then the trip is gone from the feed.
DONE_RETENTION = 3600.0

# Never archive an arrival already this far in the past when it comes due.
# Some feeds keep long-past stops listed (ghost entries); history should only
# contain arrivals we actually observed as upcoming.
MAX_ARRIVAL_AGE = 300.0


def record_snapshot(snapshot: dict[str, list[ArrivalRecord]], now: float | None = None) -> int:
    """Refresh pending predictions from a snapshot, then archive passed ones.

    Returns the number of arrival events written.
    """
    now = now if now is not None else time.time()
    for station_id, recs in snapshot.items():
        for rec in recs:
            key = (rec.trip_id, station_id)
            if key not in _done:
                _pending[key] = rec
    return _flush(now)


def _flush(now: float) -> int:
    due = [(key, rec) for key, rec in _pending.items() if rec.time <= now]
    for key, flushed_at in list(_done.items()):
        if flushed_at < now - DONE_RETENTION:
            del _done[key]
    if not due:
        return 0

    archived = 0
    with db.SessionLocal() as session:
        for key, rec in due:
            del _pending[key]
            _done[key] = now
            if now - rec.time > MAX_ARRIVAL_AGE:
                continue  # ghost entry: arrival was already old when it came due
            if rec.fetched_at < rec.time - FRESHNESS_WINDOW:
                continue  # prediction went stale before arrival: likely cancelled
            station_gtfs = key[1]
            session.add(ArrivalEvent(
                trip=_get_or_create_trip(session, rec),
                station=_get_or_create_station(session, station_gtfs),
                arrival_time=datetime.fromtimestamp(rec.time, tz=timezone.utc).replace(tzinfo=None),
                recorded_at=db.utcnow_naive(),
            ))
            archived += 1
        session.commit()
    if archived:
        log.info("archived %d arrivals", archived)
    return archived


def _get_or_create_station(session: Session, gtfs_stop_id: str) -> Station:
    station = session.scalar(select(Station).where(Station.gtfs_stop_id == gtfs_stop_id))
    if station is None:
        station = Station(gtfs_stop_id=gtfs_stop_id,
                          name=station_name(gtfs_stop_id) or gtfs_stop_id)
        session.add(station)
        session.flush()
    return station


def _get_or_create_trip(session: Session, rec: ArrivalRecord) -> Trip:
    trip = session.scalar(select(Trip).where(Trip.gtfs_trip_id == rec.trip_id))
    if trip is None:
        route = session.scalar(select(Route).where(Route.gtfs_route_id == rec.route))
        if route is None:
            route = Route(gtfs_route_id=rec.route)
            session.add(route)
            session.flush()
        trip = Trip(gtfs_trip_id=rec.trip_id, route_id=route.id, direction=rec.direction)
        session.add(trip)
        session.flush()
    return trip


def reset() -> None:
    """Clear pending predictions. Test hook."""
    _pending.clear()
    _done.clear()
