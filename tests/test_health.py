"""Endpoint tests. TestClient calls the app in-process; no worker runs here,
so tests seed the (fake) Redis cache directly, as the worker would."""
import time

from fastapi.testclient import TestClient

from app.main import app
from app.services import feed
from tests.conftest import make_feed, seed_cache

client = TestClient(app)


def test_health_before_any_snapshot():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["redis_ok"] is True
    assert body["snapshot_ready"] is False
    assert body["snapshot_age_seconds"] is None


def test_health_reports_snapshot_age():
    seed_cache({})
    body = client.get("/health").json()
    assert body["snapshot_ready"] is True
    assert body["snapshot_age_seconds"] >= 0


def test_arrivals_503_before_first_snapshot():
    resp = client.get("/v1/stations/R16/arrivals")
    assert resp.status_code == 503


def test_arrivals_for_seeded_station():
    now = time.time()
    msg = make_feed([("t1", "N", [("R16N", now + 120)]),
                     ("t2", "Q", [("R16S", now + 300)])])
    seed_cache(feed.normalize([(msg, now)]))

    resp = client.get("/v1/stations/R16/arrivals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["station"]["name"] == "Times Sq-42 St"
    assert body["station"]["routes"] == ["N", "Q"]
    assert [a["route"] for a in body["arrivals"]] == ["N", "Q"]
    assert body["data_age_seconds"] >= 0


def test_unknown_station_404s():
    now = time.time()
    seed_cache(feed.normalize([(make_feed([("t1", "N", [("R16N", now + 60)])]), now)]))
    resp = client.get("/v1/stations/NOPE/arrivals")
    assert resp.status_code == 404
