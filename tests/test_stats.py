"""Stats endpoint tests against a seeded history database."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.models.tables import ArrivalEvent, Route, Station, Trip
from app.services import routes

client = TestClient(app)


def _seed(session_factory, gaps_minutes, route_id="N", short_name=None):
    """Insert one station with arrivals spaced by the given gaps.

    Passing short_name also loads route branding, so the station reports a
    rider-facing name that differs from the GTFS id.
    """
    with session_factory() as session:
        station = Station(gtfs_stop_id="R16", name="Times Sq-42 St")
        route = Route(gtfs_route_id=route_id, short_name=short_name)
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
    if short_name:
        routes.load_from_db()


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


def test_route_filter_accepts_the_name_the_response_advertises(db_session):
    """station.routes reports "S", so ?route=S has to find the GS shuttle."""
    _seed(db_session, gaps_minutes=[5, 5], route_id="GS", short_name="S")

    body = client.get("/v1/stats/stations/R16/headways?hours=2").json()
    assert body["station"]["routes"] == ["S"]

    filtered = client.get("/v1/stats/stations/R16/headways?hours=2&route=S").json()
    assert filtered["total_arrivals"] == 3
    (group,) = filtered["groups"]
    assert group["route"] == "GS"      # grouping stays on the raw id
    assert group["route_name"] == "S"


def test_route_filter_still_accepts_the_raw_id(db_session):
    _seed(db_session, gaps_minutes=[5, 5], route_id="GS", short_name="S")

    body = client.get("/v1/stats/stations/R16/headways?hours=2&route=GS").json()
    assert body["total_arrivals"] == 3


def test_route_filter_on_an_unserved_route_is_empty(db_session):
    _seed(db_session, gaps_minutes=[5, 5], route_id="GS", short_name="S")

    body = client.get("/v1/stats/stations/R16/headways?hours=2&route=Q").json()
    assert body["groups"] == []
    assert body["total_arrivals"] == 0


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
