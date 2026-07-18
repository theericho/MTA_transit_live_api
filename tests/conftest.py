import time

import pytest
from google.transit import gtfs_realtime_pb2

from app.services import feed


@pytest.fixture(autouse=True)
def clean_feed_state():
    """Every test starts with an empty snapshot."""
    feed.reset()
    yield
    feed.reset()


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
