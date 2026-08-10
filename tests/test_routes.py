"""Route branding: the routes.txt lookup and the express-diamond convention."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models.tables import Route
from app.services import arrivals_reader, feed, routes
from tests.conftest import make_feed, seed_cache

client = TestClient(app)

# A slice of the real routes.txt: the four ids that are signed differently,
# plus a local and its express variant.
REAL_ROUTES = [
    ("GS", "S", "42 St Shuttle"),
    ("FS", "S", "Franklin Avenue Shuttle"),
    ("H", "S", "Rockaway Park Shuttle"),
    ("SI", "SIR", "Staten Island Railway"),
    ("F", "F", "Queens Blvd Express/6 Av Local"),
    ("FX", "FX", "Brooklyn F Express"),
    ("N", "N", "Broadway Local"),
]


@pytest.fixture()
def branded(db_session):
    """Seed the routes table and load branding, as startup would."""
    with db_session() as session:
        session.add_all([Route(gtfs_route_id=r, short_name=s, long_name=l)
                         for r, s, l in REAL_ROUTES])
        session.commit()
    routes.load_from_db()
    return db_session


def test_all_three_shuttles_are_signed_s(branded):
    for route_id, expected_long in [("GS", "42 St Shuttle"),
                                    ("FS", "Franklin Avenue Shuttle"),
                                    ("H", "Rockaway Park Shuttle")]:
        brand = routes.branding(route_id)
        assert brand.name == "S"
        assert brand.long_name == expected_long  # the tooltip disambiguates
        assert brand.express is False


def test_staten_island_railway_is_sir(branded):
    assert routes.branding("SI").name == "SIR"


def test_express_variant_shows_base_route_as_diamond(branded):
    brand = routes.branding("FX")
    assert brand.name == "F"
    assert brand.express is True
    assert brand.long_name == "Brooklyn F Express"

    local = routes.branding("F")
    assert local.name == "F"
    assert local.express is False


def test_unknown_route_passes_through_unchanged(branded):
    # A route the static load never described: show it rather than hide it.
    assert routes.branding("ZZ").name == "ZZ"
    assert routes.branding("ZZ").express is False


def test_x_suffix_without_a_known_base_is_not_truncated(branded):
    # "ZX" must not become "Z" just because it ends in X: the base has to exist.
    assert routes.branding("ZX").name == "ZX"
    assert routes.branding("ZX").express is False


def test_branding_is_a_no_op_before_the_static_load():
    # Nothing loaded: raw ids pass through, so the API still works.
    assert routes.branding("GS").name == "GS"
    assert routes.branding("GS").long_name is None


def test_display_names_collapse_local_and_express(branded):
    assert routes.display_names(["F", "FX", "N"]) == ["F", "N"]


def test_ids_for_finds_every_shuttle_behind_one_s(branded):
    assert routes.ids_for("S") == ["FS", "GS", "H", "S"]


def test_ids_for_includes_the_express_variant(branded):
    assert routes.ids_for("F") == ["F", "FX"]


def test_ids_for_accepts_a_raw_id(branded):
    # Filtering by the id in arrivals[].route must keep working.
    assert routes.ids_for("GS") == ["GS"]
    assert routes.ids_for("SI") == ["SI"]


def test_ids_for_is_a_no_op_before_the_static_load():
    assert routes.ids_for("GS") == ["GS"]
    assert routes.ids_for("s") == ["S"]


def test_arrivals_response_carries_branding(branded):
    now = time.time()
    msg = make_feed([("t1", "GS", [("127N", now + 120)])])
    seed_cache(feed.normalize([(msg, now)]))

    result = client.get("/v1/stations/127/arrivals").json()
    (arrival,) = result["arrivals"]
    assert arrival["route"] == "GS"          # raw id preserved for clients
    assert arrival["route_name"] == "S"      # what the bullet reads
    assert arrival["route_long_name"] == "42 St Shuttle"
    assert arrival["express"] is False
    assert result["station"]["routes"] == ["S"]


def test_express_arrival_is_flagged(branded):
    now = time.time()
    seed_cache(feed.normalize([(make_feed([("t1", "FX", [("127N", now + 60)])]), now)]))

    (arrival,) = client.get("/v1/stations/127/arrivals").json()["arrivals"]
    assert arrival["route_name"] == "F"
    assert arrival["express"] is True


def test_route_rows_survive_reload(branded):
    """The archiver creates bare Route rows; the loader fills them in."""
    with branded() as session:
        row = session.scalar(select(Route).where(Route.gtfs_route_id == "GS"))
        assert (row.short_name, row.long_name) == ("S", "42 St Shuttle")
