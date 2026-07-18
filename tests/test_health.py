"""Endpoint tests. TestClient calls the app in-process; the poller does not
run here (lifespan is not entered), so tests seed the snapshot directly."""
import time

from fastapi.testclient import TestClient

from app.main import app
from app.services import feed
from tests.conftest import make_feed

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["snapshot_ready"] is False


def test_arrivals_503_before_first_poll():
    resp = client.get("/v1/stations/R16/arrivals")
    assert resp.status_code == 503


def test_arrivals_for_seeded_station():
    now = time.time()
    feed.apply_feeds({
        "NQRW": (make_feed([("t1", "N", [("R16N", now + 120)]),
                            ("t2", "Q", [("R16S", now + 300)])]), now),
    })
    resp = client.get("/v1/stations/R16/arrivals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["station"]["name"] == "Times Sq-42 St"
    assert body["station"]["routes"] == ["N", "Q"]
    assert [a["route"] for a in body["arrivals"]] == ["N", "Q"]
    assert body["data_age_seconds"] >= 0


def test_unknown_station_404s():
    now = time.time()
    feed.apply_feeds({"NQRW": (make_feed([("t1", "N", [("R16N", now + 60)])]), now)})
    resp = client.get("/v1/stations/NOPE/arrivals")
    assert resp.status_code == 404
