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


def test_route_name_filter_finds_the_name_the_response_advertises(db_session):
    """station.routes reports "S", so ?route_name=S has to find the GS shuttle."""
    _seed(db_session, gaps_minutes=[5, 5], route_id="GS", short_name="S")

    body = client.get("/v1/stats/stations/R16/headways?hours=2").json()
    assert body["station"]["routes"] == ["S"]

    url = "/v1/stats/stations/R16/headways?hours=2&route_name=S"
    filtered = client.get(url).json()
    assert filtered["total_arrivals"] == 3
    (group,) = filtered["groups"]
    assert group["route"] == "GS"      # grouping stays on the raw id
    assert group["route_name"] == "S"


def _seed_express_only(session_factory):
    """A station served only by the FX express, in a system where F exists.

    The express convention needs the base route to be known, so registering F
    is what makes this the real-world case rather than an unknown id ending X.
    """
    _seed(session_factory, gaps_minutes=[5, 5], route_id="FX", short_name="FX")
    with session_factory() as session:
        session.add(Route(gtfs_route_id="F", short_name="F"))
        session.commit()
    routes.load_from_db()


def test_route_name_finds_an_express_only_station(db_session):
    """An FX-only station advertises "F"; that name must return its arrivals."""
    _seed_express_only(db_session)

    body = client.get("/v1/stats/stations/R16/headways?hours=2").json()
    assert body["station"]["routes"] == ["F"]

    url = "/v1/stats/stations/R16/headways?hours=2&route_name=F"
    assert client.get(url).json()["total_arrivals"] == 3


def test_route_filter_is_an_exact_id(db_session):
    """The id axis stays exact, which is how you select FX alone."""
    _seed_express_only(db_session)

    base = "/v1/stats/stations/R16/headways?hours=2"
    assert client.get(base + "&route=FX").json()["total_arrivals"] == 3
    assert client.get(base + "&route=F").json()["total_arrivals"] == 0


def test_route_and_route_name_together_are_rejected(db_session):
    _seed(db_session, gaps_minutes=[5, 5], route_id="GS", short_name="S")

    url = "/v1/stats/stations/R16/headways?route=GS&route_name=S"
    assert client.get(url).status_code == 400


def test_route_rejects_a_rider_facing_name(db_session):
    """?route=S is the wrong axis, and silence would read as "no service"."""
    _seed(db_session, gaps_minutes=[5, 5], route_id="GS", short_name="S")

    resp = client.get("/v1/stats/stations/R16/headways?hours=2&route=S")
    assert resp.status_code == 400
    assert "route_name=S" in resp.json()["detail"]


def test_route_filter_on_an_unserved_route_is_empty(db_session):
    """An id this station simply has no arrivals for is data, not an error."""
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
