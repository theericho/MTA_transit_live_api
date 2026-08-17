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


def test_signed_ids_are_branded_before_the_static_load():
    # The four ids riders never see are right even on a fresh database, so a
    # bullet never renders a GTFS id the color map has no entry for.
    assert routes.branding("GS").name == "S"
    assert routes.branding("FS").name == "S"
    assert routes.branding("H").name == "S"
    assert routes.branding("SI").name == "SIR"
    assert routes.branding("GS").long_name is None  # tooltips need routes.txt


def test_other_ids_pass_through_on_an_empty_database():
    assert routes.branding("N").name == "N"
    # Nothing has ever been seen, so there is no evidence an F exists.
    assert routes.branding("FX").name == "FX"
    assert routes.branding("FX").express is False


def test_express_works_from_archiver_rows_alone(db_session):
    """A bare F row is evidence the F exists, which is all the express rule
    needs: diamonds work before routes.txt has ever been loaded."""
    with db_session() as session:
        session.add_all([Route(gtfs_route_id=r) for r in ("F", "FX")])
        session.commit()
    routes.load_from_db()

    brand = routes.branding("FX")
    assert brand.name == "F"
    assert brand.express is True
    assert brand.long_name is None       # the tooltip still needs routes.txt
    assert routes.ids_for("F") == ["F", "FX"]


def test_invariant_holds_on_an_unbranded_database(db_session):
    """The filterability invariant again, with nothing branded at all."""
    ids = ["F", "FX", "6", "6X", "GS", "FS", "H", "SI", "N"]
    with db_session() as session:
        session.add_all([Route(gtfs_route_id=r) for r in ids])
        session.commit()
    routes.load_from_db()

    for route_id in ids:
        name = routes.branding(route_id).name
        assert route_id in routes.ids_for(name), (
            f"{route_id} is shown as {name!r}, but ids_for({name!r}) "
            f"returns {routes.ids_for(name)}")


def test_display_names_collapse_local_and_express(branded):
    assert routes.display_names(["F", "FX", "N"]) == ["F", "N"]


def test_ids_for_finds_every_shuttle_behind_one_s(branded):
    assert routes.ids_for("S") == ["FS", "GS", "H", "S"]


def test_ids_for_covers_local_and_express(branded):
    # The bullet reads "F" for both, so the name has to find both. Selecting
    # only one of them is what the exact-id `route` parameter is for.
    assert routes.ids_for("F") == ["F", "FX"]


def test_ids_for_expands_a_name_that_is_not_also_an_id(branded):
    assert routes.ids_for("SIR") == ["SI", "SIR"]


def test_ids_for_passes_unknown_input_through(branded):
    assert routes.ids_for("ZZ") == ["ZZ"]


def test_is_display_name_separates_the_two_axes(branded):
    assert routes.is_display_name("S") is True
    assert routes.is_display_name("SIR") is True
    assert routes.is_display_name("F") is False    # a real id, and also a name
    assert routes.is_display_name("GS") is False   # a real id
    assert routes.is_display_name("FX") is False
    assert routes.is_display_name("ZZZ") is False  # unknown: leave it alone


def test_is_display_name_before_the_static_load():
    # Only the fallback can identify a name here, and an id must not be called
    # a name just because the database is empty.
    assert routes.is_display_name("S") is True
    assert routes.is_display_name("SIR") is True
    assert routes.is_display_name("GS") is False
    assert routes.is_display_name("N") is False


def test_ids_for_follows_the_fallback_before_the_static_load():
    # Whatever branding() advertises has to be filterable in the same state.
    assert routes.ids_for("S") == ["FS", "GS", "H", "S"]
    assert routes.ids_for("SIR") == ["SI", "SIR"]
    assert routes.ids_for("N") == ["N"]


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


def test_every_advertised_name_is_filterable(db_session):
    """The invariant tying the two halves together: whatever branding() puts on
    a bullet, ids_for() has to map back to the id it came from. Mixed state on
    purpose - routes.txt covered most rows, the archiver created the rest.
    """
    with db_session() as session:
        session.add_all([Route(gtfs_route_id=r, short_name=s, long_name=l)
                         for r, s, l in REAL_ROUTES if r != "FX"])
        session.add_all([Route(gtfs_route_id=r) for r in ("FX", "6X")])
        session.commit()
    routes.load_from_db()

    for route_id in [r for r, _, _ in REAL_ROUTES] + ["6X"]:
        name = routes.branding(route_id).name
        assert route_id in routes.ids_for(name), (
            f"{route_id} is shown as {name!r}, but ids_for({name!r}) "
            f"returns {routes.ids_for(name)}")


def test_archiver_rows_do_not_shadow_the_fallback(db_session):
    """The archiver creates bare Route rows for whatever it observes, which on
    a fresh database happens long before load_gtfs_static.py is ever run."""
    with db_session() as session:
        session.add_all([Route(gtfs_route_id=r) for r in ("GS", "N")])
        session.commit()

    assert routes.load_from_db() == 0          # nothing is branded yet
    assert routes.branding("GS").name == "S"   # the fallback still applies
    assert routes.branding("N").name == "N"
    assert routes.ids_for("S") == ["FS", "GS", "H", "S"]


def test_route_rows_survive_reload(branded):
    """The archiver creates bare Route rows; the loader fills them in."""
    with branded() as session:
        row = session.scalar(select(Route).where(Route.gtfs_route_id == "GS"))
        assert (row.short_name, row.long_name) == ("S", "42 St Shuttle")
