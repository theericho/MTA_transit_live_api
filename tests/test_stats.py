"""Stats endpoint tests against a seeded history database."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.models.tables import ArrivalEvent, Route, Station, Trip

client = TestClient(app)


def _seed(session_factory, gaps_minutes):
    """Insert one station with arrivals spaced by the given gaps."""
    with session_factory() as session:
        station = Station(gtfs_stop_id="R16", name="Times Sq-42 St")
        route = Route(gtfs_route_id="N")
        session.add_all([station, route])
        session.flush()

        t = db.utcnow_naive() - timedelta(minutes=sum(gaps_minutes) + 5)
        times = [t]
        for gap in gaps_minutes:
            times.append(times[-1] + timedelta(minutes=gap))
        for i, arrival_time in enumerate(times):
            trip = Trip(gtfs_trip_id=f"trip{i}", route_id=route.id, direction="N")
            session.add(trip)
            session.flush()
            session.add(ArrivalEvent(trip_id=trip.id, station_id=station.id,
                                     arrival_time=arrival_time,
                                     recorded_at=arrival_time))
        session.commit()


def test_headways_math(db_session):
    _seed(db_session, gaps_minutes=[5, 5, 10])

    resp = client.get("/v1/stats/stations/R16/headways?hours=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["station"]["name"] == "Times Sq-42 St"
    assert body["total_arrivals"] == 4
    (group,) = body["groups"]
    assert group["route"] == "N"
    assert group["arrivals"] == 4
    assert group["mean_headway_minutes"] == pytest.approx(6.7)
    assert group["median_headway_minutes"] == pytest.approx(5.0)
    # Gaps 5, 5, 10 vs 1.25 * median (6.25): two of three qualify.
    assert group["regularity_pct"] == pytest.approx(66.7)


def test_headways_unknown_station_404s(db_session):
    resp = client.get("/v1/stats/stations/NOPE/headways")
    assert resp.status_code == 404


def test_headways_single_arrival_has_null_stats(db_session):
    _seed(db_session, gaps_minutes=[])
    resp = client.get("/v1/stats/stations/R16/headways")
    assert resp.status_code == 200
    (group,) = resp.json()["groups"]
    assert group["arrivals"] == 1
    assert group["mean_headway_minutes"] is None
    assert group["regularity_pct"] is None
