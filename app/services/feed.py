"""Feed ingestion: poll the MTA GTFS-realtime feeds, serve an in-memory snapshot.

How it works (README, design decisions 1-3 and 7):

- A background asyncio task (started from the app's lifespan) fetches all
  subway feeds concurrently every POLL_INTERVAL seconds.
- Each successful fetch is remembered per feed in `_last`; a failed fetch
  keeps that feed's previous payload, so one bad feed degrades to stale data
  instead of missing stations. Staleness is surfaced to clients as
  `data_age_seconds` rather than hidden.
- The per-trip feeds are inverted into a per-station index (`_snapshot`).
  The index is rebuilt as a fresh dict and swapped in with a single reference
  assignment, so readers never see a half-built index and no locks are needed.
- API reads only ever touch the snapshot - the MTA is never in the request path.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from google.transit import gtfs_realtime_pb2

from app.models.schemas import Arrival, Station, StationArrivals
from app.services.stations import station_name

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
ARRIVALS_LIMIT = 10


@dataclass(frozen=True)
class ArrivalRecord:
    time: float          # epoch seconds
    route: str
    direction: str       # "N" / "S" / "?"
    trip_id: str
    fetched_at: float    # when the feed containing this record was fetched


# Last successful payload per feed: name -> (FeedMessage, fetched_at).
_last: dict[str, tuple[gtfs_realtime_pb2.FeedMessage, float]] = {}

# Current station index: parent station id -> arrivals sorted by time.
_snapshot: dict[str, list[ArrivalRecord]] = {}


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


def apply_feeds(fetched: dict[str, tuple[gtfs_realtime_pb2.FeedMessage, float]]) -> None:
    """Merge newly fetched feeds into `_last` and swap in a fresh snapshot."""
    global _snapshot
    _last.update(fetched)
    _snapshot = normalize(list(_last.values()))


async def _fetch_feed(client: httpx.AsyncClient, url: str) -> gtfs_realtime_pb2.FeedMessage:
    resp = await client.get(url, timeout=30)
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


async def poll_once(client: httpx.AsyncClient) -> int:
    """Fetch every feed concurrently; returns how many succeeded.

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
    if fetched:
        apply_feeds(fetched)
    return len(fetched)


async def poller_loop() -> None:
    """Background task: refresh the snapshot forever."""
    async with httpx.AsyncClient() as client:
        while True:
            try:
                n = await poll_once(client)
                log.info("poll complete: %d/%d feeds ok", n, len(FEEDS))
            except Exception:
                log.exception("poll cycle failed")
            await asyncio.sleep(POLL_INTERVAL)


def snapshot_ready() -> bool:
    """False until the first successful poll (API answers 503 meanwhile)."""
    return bool(_last)


def reset() -> None:
    """Clear all state. Test hook."""
    global _snapshot
    _last.clear()
    _snapshot = {}


def get_arrivals(station_id: str, limit: int = ARRIVALS_LIMIT) -> StationArrivals | None:
    """Read the snapshot for one station; None means 'unknown station' (404).

    A station with a known name but no current arrivals returns an empty list
    (it exists, it's just quiet) - unknown-vs-quiet is a deliberate contract
    distinction (README, design decision 6).
    """
    now = time.time()
    recs = _snapshot.get(station_id, [])
    name = station_name(station_id)
    if not recs and name is None:
        return None

    upcoming = [r for r in recs if r.time >= now][:limit]
    if upcoming:
        oldest_fetch = min(r.fetched_at for r in upcoming)
    else:
        oldest_fetch = min((at for _, at in _last.values()), default=now)

    return StationArrivals(
        station=Station(
            id=station_id,
            name=name or station_id,
            routes=sorted({r.route for r in recs}),
        ),
        arrivals=[
            Arrival(
                route=r.route,
                direction=r.direction,
                arrival_time=datetime.fromtimestamp(r.time, tz=timezone.utc),
                minutes_away=round(max(0.0, (r.time - now) / 60), 1),
            )
            for r in upcoming
        ],
        data_age_seconds=round(now - oldest_fetch, 1),
    )
