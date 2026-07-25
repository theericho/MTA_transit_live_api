"""Integration tests for the worker cycle and worker-death behavior."""
import asyncio
import time

from sqlalchemy import select

from app.services import archive, arrivals_reader, feed
from app.models.tables import ArrivalEvent
from tests.conftest import make_feed, seed_cache


def test_one_worker_cycle_end_to_end(db_session, monkeypatch):
    """One poll cycle: fetch -> cache write -> readable arrivals -> archive."""
    now = time.time()
    msg = make_feed([
        ("t1", "N", [("R16N", now + 90)]),    # upcoming: served, not archived
        ("t2", "Q", [("R16S", now - 5)]),     # just passed: archived
    ])

    async def fake_fetch(client, url):
        if url.endswith("gtfs-nqrw"):
            return msg
        raise ConnectionError("feed down")

    monkeypatch.setattr(feed, "_fetch_feed", fake_fetch)

    async def one_cycle():
        ok, snapshot = await feed.poll_once(client=None)
        from app import cache
        await cache.write_snapshot(snapshot)
        return ok, archive.record_snapshot(snapshot, now=now + 1)

    ok, archived = asyncio.run(one_cycle())
    assert ok == 1
    assert archived == 1  # only the passed arrival

    result = asyncio.run(arrivals_reader.get_arrivals("R16"))
    assert [a.route for a in result.arrivals] == ["N"]

    with db_session() as session:
        event = session.scalars(select(ArrivalEvent)).one()
        assert event.trip.gtfs_trip_id == "t2"


def test_dead_worker_still_serves_with_growing_age():
    """If the worker stops, the API keeps answering from the last snapshot
    and data_age_seconds reflects how stale it is."""
    now = time.time()
    stale_fetch = now - 300  # worker died 5 minutes ago
    msg = make_feed([("t1", "N", [("R16N", now + 600)])])
    seed_cache(feed.normalize([(msg, stale_fetch)]))

    result = asyncio.run(arrivals_reader.get_arrivals("R16"))
    assert result is not None
    assert len(result.arrivals) == 1
    assert result.data_age_seconds >= 300
