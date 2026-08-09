"""Station search: grouping by complex, matching, and limits."""
from fastapi.testclient import TestClient

from app.main import app
from app.models.tables import Station, StationComplex

client = TestClient(app)


def seed_stations(session_factory):
    """Herald Sq as a two-station complex, plus one unlinked station."""
    with session_factory() as session:
        session.add(StationComplex(id=607, name="34 St-Herald Sq"))
        session.flush()
        session.add_all([
            Station(gtfs_stop_id="R17", name="34 St-Herald Sq",
                    complex_id=607, daytime_routes="N Q R W"),
            Station(gtfs_stop_id="D17", name="34 St-Herald Sq",
                    complex_id=607, daytime_routes="B D F M"),
            Station(gtfs_stop_id="L08", name="Bedford Av"),  # no complex loaded
        ])
        session.commit()


def test_complex_members_collapse_into_one_result(db_session):
    seed_stations(db_session)
    body = client.get("/v1/stations?search=herald").json()

    assert len(body) == 1  # not two rows both named "34 St-Herald Sq"
    entry = body[0]
    assert entry["kind"] == "complex"
    assert entry["id"] == "607"
    assert entry["station_ids"] == ["D17", "R17"]
    assert entry["routes"] == ["B", "D", "F", "M", "N", "Q", "R", "W"]


def test_station_without_complex_stands_alone(db_session):
    seed_stations(db_session)
    (entry,) = client.get("/v1/stations?search=bedford").json()
    assert entry["kind"] == "station"
    assert entry["id"] == "L08"
    assert entry["station_ids"] == ["L08"]
    assert entry["routes"] == []


def test_search_is_case_insensitive_and_empty_lists_everything(db_session):
    seed_stations(db_session)
    assert len(client.get("/v1/stations?search=HERALD").json()) == 1
    assert len(client.get("/v1/stations").json()) == 2  # complex + lone station


def test_no_match_returns_empty_list(db_session):
    seed_stations(db_session)
    assert client.get("/v1/stations?search=nowhere").json() == []


def test_limit_caps_results(db_session):
    seed_stations(db_session)
    assert len(client.get("/v1/stations?limit=1").json()) == 1
