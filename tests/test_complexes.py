"""Complex arrivals: merging members into one rider-facing board."""
import time

from fastapi.testclient import TestClient

from app.main import app
from app.models.tables import Station, StationComplex
from app.services import feed
from tests.conftest import make_feed, seed_cache

client = TestClient(app)


def seed_herald(session_factory):
    with session_factory() as session:
        session.add(StationComplex(id=607, name="34 St-Herald Sq"))
        session.flush()
        session.add_all([
            Station(gtfs_stop_id="R17", name="34 St-Herald Sq",
                    complex_id=607, daytime_routes="N Q R W"),
            Station(gtfs_stop_id="D17", name="34 St-Herald Sq",
                    complex_id=607, daytime_routes="B D F M"),
        ])
        session.commit()


def test_members_merge_and_sort_by_time(db_session):
    seed_herald(db_session)
    now = time.time()
    # Interleaved so a naive concatenation would come back out of order.
    msg = make_feed([
        ("t1", "N", [("R17N", now + 240)]),
        ("t2", "F", [("D17S", now + 60)]),
        ("t3", "Q", [("R17S", now + 300)]),
        ("t4", "B", [("D17N", now + 120)]),
    ])
    seed_cache(feed.normalize([(msg, now)]))

    body = client.get("/v1/complexes/607/arrivals").json()
    assert body["station"]["name"] == "34 St-Herald Sq"
    assert [a["route"] for a in body["arrivals"]] == ["F", "B", "N", "Q"]
    assert body["station"]["routes"] == ["B", "F", "N", "Q"]


def test_reported_age_is_the_worst_member(db_session):
    seed_herald(db_session)
    now = time.time()
    fresh = feed.normalize([(make_feed([("t1", "N", [("R17N", now + 120)])]), now)])
    stale = feed.normalize([(make_feed([("t2", "F", [("D17N", now + 120)])]), now - 200)])
    seed_cache({**fresh, **stale})

    body = client.get("/v1/complexes/607/arrivals").json()
    assert body["data_age_seconds"] >= 200  # not the flattering 0


def test_unknown_complex_404s(db_session):
    seed_herald(db_session)
    now = time.time()
    seed_cache(feed.normalize([(make_feed([("t1", "N", [("R17N", now + 60)])]), now)]))
    assert client.get("/v1/complexes/999/arrivals").status_code == 404


def test_503_before_first_snapshot(db_session):
    seed_herald(db_session)
    assert client.get("/v1/complexes/607/arrivals").status_code == 503
