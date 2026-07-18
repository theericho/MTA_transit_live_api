"""v0: fetch one MTA GTFS-realtime feed and print upcoming arrivals for one station.

Standalone proof that we can pull and decode the real feed. Not wired into the
API yet - v1 moves this logic into app/services/feed.py behind a poller.

Usage:
    python scripts/fetch_feed.py           # Times Sq-42 St (N/Q/R/W)
    python scripts/fetch_feed.py R14       # any stop id on the N/Q/R/W feed
"""
import sys
import time
from datetime import datetime

import httpx
from google.transit import gtfs_realtime_pb2

# The subway feeds are split by line group; this one covers N/Q/R/W.
FEED_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw"

# GTFS stop id for Times Sq-42 St on the N/Q/R/W platforms. Platform-level
# stop ids in the feed carry a direction suffix: R16N (uptown) / R16S (downtown).
DEFAULT_STATION = "R16"

STATION_NAMES = {
    "R16": "Times Sq-42 St",
}


def fetch_feed(url: str = FEED_URL) -> gtfs_realtime_pb2.FeedMessage:
    """Download and decode one GTFS-realtime protobuf feed."""
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


def arrivals_for_station(feed: gtfs_realtime_pb2.FeedMessage, station: str):
    """Pull (epoch_seconds, route, direction) tuples for one station.

    The feed is organized per *trip*: each trip_update lists every stop that
    trip will make. We invert that here - scan all trips, keep the stops that
    match our station. This re-indexing is the core of the whole project.
    """
    now = time.time()
    arrivals = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue  # skip vehicle positions / alerts
        route = entity.trip_update.trip.route_id
        for stu in entity.trip_update.stop_time_update:
            if not stu.stop_id.startswith(station):
                continue
            t = stu.arrival.time or stu.departure.time
            if t and t >= now:
                direction = stu.stop_id[len(station):] or "?"
                arrivals.append((t, route, direction))
    return sorted(arrivals)


def main() -> None:
    station = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STATION
    name = STATION_NAMES.get(station, station)

    feed = fetch_feed()
    feed_time = datetime.fromtimestamp(feed.header.timestamp)
    age = time.time() - feed.header.timestamp
    print(f"Feed generated {feed_time:%H:%M:%S} ({age:.0f}s ago), "
          f"{len(feed.entity)} entities\n")

    arrivals = arrivals_for_station(feed, station)
    if not arrivals:
        print(f"No upcoming arrivals found for {name} on this feed.")
        return

    print(f"Upcoming arrivals at {name}:")
    for t, route, direction in arrivals[:10]:
        mins = (t - time.time()) / 60
        label = {"N": "uptown", "S": "downtown"}.get(direction, direction)
        print(f"  ({route}) {label:<8} {datetime.fromtimestamp(t):%H:%M:%S}"
              f"  ~{mins:4.1f} min")


if __name__ == "__main__":
    main()
