import asyncio
import time

import fakeredis
import pytest
from google.transit import gtfs_realtime_pb2
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import cache, db
from app.services import archive, feed, routes, stations


@pytest.fixture(autouse=True)
def clean_feed_state():
    """Every test starts with empty feed merge state and no route branding."""
    feed.reset()
    routes.reset()
    yield
    feed.reset()
    routes.reset()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """In-memory Redis for every test.

    A fresh FakeRedis client is handed out per call (connections are bound to
    the calling event loop, and TestClient requests each run their own loop);
    the FakeServer behind them shares the data.
    """
    server = fakeredis.FakeServer()

    def _get_client():
        return fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "get_client", _get_client)
    yield server


def seed_cache(snapshot):
    """Write a snapshot into the (fake) cache, as the worker would."""
    asyncio.run(cache.write_snapshot(snapshot))


@pytest.fixture()
def db_session(monkeypatch):
    """Fresh in-memory database per test.

    Patches db.SessionLocal, so the archiver, the stations loader, and the
    FastAPI get_session dependency all hit the test database.
    """
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", TestingSession)
    db.Base.metadata.create_all(engine)
    archive.reset()
    stations._db_names.clear()
    yield TestingSession
    archive.reset()
    stations._db_names.clear()


def make_feed(trips, ts=None):
    """Build a GTFS-realtime FeedMessage in memory.

    trips: list of (trip_id, route, [(stop_id, epoch_time), ...])
    """
    msg = gtfs_realtime_pb2.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    msg.header.timestamp = int(ts or time.time())
    for trip_id, route, stops in trips:
        ent = msg.entity.add()
        ent.id = trip_id
        ent.trip_update.trip.trip_id = trip_id
        ent.trip_update.trip.route_id = route
        for stop_id, t in stops:
            stu = ent.trip_update.stop_time_update.add()
            stu.stop_id = stop_id
            stu.arrival.time = int(t)
    return msg
