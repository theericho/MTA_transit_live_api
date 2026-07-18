"""Unit tests for the ingestion layer: normalization, dedup, polling."""
import asyncio
import time

from app.services import feed
from tests.conftest import make_feed


def test_normalize_indexes_by_station_and_splits_direction():
    now = time.time()
    msg = make_feed([
        ("trip1", "N", [("R16N", now + 120), ("R15N", now + 300)]),
        ("trip2", "Q", [("R16S", now + 60)]),
    ])
    index = feed.normalize([(msg, now)])

    assert set(index) == {"R16", "R15"}
    assert [r.route for r in index["R16"]] == ["Q", "N"]  # sorted by time
    assert index["R16"][0].direction == "S"
    assert index["R16"][1].direction == "N"


def test_normalize_dedupes_repeated_trip_updates():
    # The live feeds sometimes list the same trip twice (seen in v0).
    now = time.time()
    msg = make_feed([
        ("trip1", "N", [("R16N", now + 120)]),
        ("trip1", "N", [("R16N", now + 120)]),
    ])
    index = feed.normalize([(msg, now)])
    assert len(index["R16"]) == 1


def test_get_arrivals_filters_past_and_limits():
    now = time.time()
    # 1 already-departed train + 14 distinct upcoming trips (a trip visits a
    # given stop once, so each arrival needs its own trip).
    trips = [("t0", "N", [("R16N", now - 60)])] + [
        (f"t{i}", "N", [("R16N", now + 60 * i)]) for i in range(1, 15)
    ]
    feed.apply_feeds({"NQRW": (make_feed(trips), now)})

    result = feed.get_arrivals("R16")
    assert result is not None
    assert len(result.arrivals) == feed.ARRIVALS_LIMIT  # capped, past dropped
    assert all(a.minutes_away >= 0 for a in result.arrivals)
    assert result.station.name == "Times Sq-42 St"
    assert result.data_age_seconds < 5


def test_get_arrivals_unknown_vs_quiet():
    now = time.time()
    feed.apply_feeds({"NQRW": (make_feed([("t1", "N", [("R16N", now + 60)])]), now)})

    assert feed.get_arrivals("XXXX") is None            # unknown -> 404 upstream
    quiet = feed.get_arrivals("631")                    # known name, no trains
    assert quiet is not None
    assert quiet.arrivals == []


def test_poll_once_keeps_last_good_payload_on_failure(monkeypatch):
    now = time.time()
    good = make_feed([("t1", "N", [("R16N", now + 60)])])

    async def fake_fetch(client, url):
        if url.endswith("gtfs-nqrw"):
            return good
        raise ConnectionError("feed down")

    monkeypatch.setattr(feed, "_fetch_feed", fake_fetch)
    ok = asyncio.run(feed.poll_once(client=None))
    assert ok == 1
    assert feed.snapshot_ready()
    assert feed.get_arrivals("R16") is not None

    # Next cycle: everything fails -> previous snapshot survives (stale > absent).
    async def all_fail(client, url):
        raise ConnectionError("feed down")

    monkeypatch.setattr(feed, "_fetch_feed", all_fail)
    ok = asyncio.run(feed.poll_once(client=None))
    assert ok == 0
    assert feed.get_arrivals("R16") is not None
