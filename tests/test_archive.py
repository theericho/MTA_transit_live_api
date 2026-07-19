"""Archiver tests: predictions become arrival events once their time passes."""
import time

from sqlalchemy import select

from app.models.tables import ArrivalEvent, Route, Station, Trip
from app.services import archive
from app.services.feed import ArrivalRecord


def _rec(trip_id, t, fetched_at, route="N", direction="N"):
    return ArrivalRecord(time=t, route=route, direction=direction,
                         trip_id=trip_id, fetched_at=fetched_at)


def test_passed_arrival_is_archived_with_fk_rows(db_session):
    now = time.time()
    # Future prediction first, then it passes on a later poll.
    archive.record_snapshot({"R16": [_rec("t1", now + 5, now)]}, now=now)
    with db_session() as session:
        assert session.scalars(select(ArrivalEvent)).all() == []

    archived = archive.record_snapshot({}, now=now + 60)
    assert archived == 1
    with db_session() as session:
        event = session.scalars(select(ArrivalEvent)).one()
        assert event.station.gtfs_stop_id == "R16"
        assert event.station.name == "Times Sq-42 St"  # fallback name map
        assert event.trip.gtfs_trip_id == "t1"
        assert event.trip.route.gtfs_route_id == "N"

    # Already flushed: a later cycle must not archive it again.
    assert archive.record_snapshot({}, now=now + 120) == 0


def test_train_lingering_in_feed_is_archived_once(db_session):
    # Regression: after a train's arrival time passes, the feed often keeps
    # listing it for a poll or two. It must not be archived again.
    now = time.time()
    rec = _rec("t9", now + 5, now)
    archive.record_snapshot({"R16": [rec]}, now=now)
    assert archive.record_snapshot({"R16": [rec]}, now=now + 40) == 1

    still_listed = _rec("t9", now + 5, now + 70)
    assert archive.record_snapshot({"R16": [still_listed]}, now=now + 70) == 0
    assert archive.record_snapshot({"R16": [still_listed]}, now=now + 100) == 0
    with db_session() as session:
        assert len(session.scalars(select(ArrivalEvent)).all()) == 1


def test_stale_prediction_is_dropped_not_archived(db_session):
    now = time.time()
    # Prediction fetched long before its arrival time, then the trip vanished
    # from the feed: a cancelled train, not an observed arrival.
    stale = _rec("t2", now + archive.FRESHNESS_WINDOW + 600,
                 fetched_at=now)
    archive.record_snapshot({"R16": [stale]}, now=now)

    archived = archive.record_snapshot({}, now=now + archive.FRESHNESS_WINDOW + 700)
    assert archived == 0
    with db_session() as session:
        assert session.scalars(select(ArrivalEvent)).all() == []


def test_ghost_entry_is_never_archived(db_session):
    # Regression: some feeds keep listing stops whose arrival time is long
    # past. Those were never observed as upcoming and must not enter history,
    # no matter how many polls list them.
    now = time.time()
    ghost = _rec("t8", now - 4000, fetched_at=now)
    for cycle in range(3):
        assert archive.record_snapshot({"201": [ghost]}, now=now + cycle * 30) == 0
    with db_session() as session:
        assert session.scalars(select(ArrivalEvent)).all() == []


def test_reference_rows_are_reused(db_session):
    now = time.time()
    snapshot = {"R16": [_rec("t3", now - 1, now), _rec("t4", now - 2, now)]}
    assert archive.record_snapshot(snapshot, now=now) == 2
    with db_session() as session:
        assert len(session.scalars(select(ArrivalEvent)).all()) == 2
        assert len(session.scalars(select(Station)).all()) == 1
        assert len(session.scalars(select(Route)).all()) == 1
        assert len(session.scalars(select(Trip)).all()) == 2
