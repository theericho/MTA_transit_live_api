"""Feed ingestion: fetch and normalize the MTA GTFS-realtime feeds.

This module is the ingestion half of the pipeline and runs inside the worker
process (app/worker.py). Each poll fetches all subway feeds concurrently,
merges them with the previous cycle (a failed feed keeps its last payload -
stale beats absent, README design decision 7), and inverts the per-trip
feeds into a per-station index. The worker then writes that index to the
Redis snapshot store (app/cache.py) for the API process to read.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

import httpx
from google.transit import gtfs_realtime_pb2

log = logging.getLogger(__name__)

_BASE = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F"
FEEDS = {
    "1-7S": _BASE + "gtfs",
    "ACE": _BASE + "gtfs-ace",
    "BDFM": _BASE + "gtfs-bdfm",
    "G": _BASE + "gtfs-g",
    "JZ": _BASE + "gtfs-jz",
    "NQRW": _BASE + "gtfs-nqrw",
    "L": _BASE + "gtfs-l",
    "SI": _BASE + "gtfs-si",
}

POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "30"))


@dataclass(frozen=True)
class ArrivalRecord:
    time: float          # epoch seconds
    route: str
    direction: str       # "N" / "S" / "?"
    trip_id: str
    fetched_at: float    # when the feed containing this record was fetched


# Last successful payload per feed: name -> (FeedMessage, fetched_at).
_last: dict[str, tuple[gtfs_realtime_pb2.FeedMessage, float]] = {}


def split_stop_id(stop_id: str) -> tuple[str, str]:
    """Split a platform stop id into (parent station, direction).

    Realtime stop ids carry a direction suffix: R16N -> ("R16", "N").
    """
    if stop_id and stop_id[-1] in ("N", "S"):
        return stop_id[:-1], stop_id[-1]
    return stop_id, "?"


def normalize(
    feeds: list[tuple[gtfs_realtime_pb2.FeedMessage, float]],
) -> dict[str, list[ArrivalRecord]]:
    """Invert per-trip feeds into a per-station arrival index.

    The feed lists every stop each *trip* will make; clients ask per *station*.
    Records are deduped on (trip_id, stop_id) because the live feeds sometimes
    repeat a trip update - last occurrence wins.
    """
    seen: dict[tuple[str, str], ArrivalRecord] = {}
    for feed, fetched_at in feeds:
        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue  # vehicle positions / alerts
            trip = entity.trip_update.trip
            for stu in entity.trip_update.stop_time_update:
                t = stu.arrival.time or stu.departure.time
                if not t:
                    continue
                _, direction = split_stop_id(stu.stop_id)
                seen[(trip.trip_id, stu.stop_id)] = ArrivalRecord(
                    time=float(t), route=trip.route_id, direction=direction,
                    trip_id=trip.trip_id, fetched_at=fetched_at,
                )

    index: dict[str, list[ArrivalRecord]] = {}
    for (_, stop_id), rec in seen.items():
        station, _ = split_stop_id(stop_id)
        index.setdefault(station, []).append(rec)
    for recs in index.values():
        recs.sort(key=lambda r: r.time)
    return index


def merge(fetched: dict[str, tuple[gtfs_realtime_pb2.FeedMessage, float]]) -> dict[str, list[ArrivalRecord]]:
    """Fold newly fetched feeds into `_last` and return the fresh index."""
    _last.update(fetched)
    return normalize(list(_last.values()))


async def _fetch_feed(client: httpx.AsyncClient, url: str) -> gtfs_realtime_pb2.FeedMessage:
    resp = await client.get(url, timeout=30)
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


async def poll_once(client: httpx.AsyncClient) -> tuple[int, dict[str, list[ArrivalRecord]]]:
    """Fetch every feed concurrently; return (feeds_ok, merged station index).

    Failures are logged and that feed's previous payload is kept (stale beats
    absent - clients see honest `data_age_seconds` either way).
    """
    now = time.time()
    results = await asyncio.gather(
        *(_fetch_feed(client, url) for url in FEEDS.values()),
        return_exceptions=True,
    )
    fetched = {}
    for name, res in zip(FEEDS, results):
        if isinstance(res, BaseException):
            log.warning("feed %s failed: %s", name, res)
        else:
            fetched[name] = (res, now)
    return len(fetched), merge(fetched)


def reset() -> None:
    """Clear all state. Test hook."""
    _last.clear()
