"""Load station metadata from the MTA's static data into the database.

Usage:
    python scripts/load_gtfs_static.py

Three passes, from two downloads:
1. The static GTFS zip (a few MB) -> stops.txt -> every parent station
   (location_type = 1) upserted into the stations table.
2. The same zip -> routes.txt -> rider-facing route branding, so the API can
   report the 42 St Shuttle as "S" rather than its GTFS id "GS".
3. Stations.csv -> the complex mapping and daytime routes, so the API can
   answer per rider-facing complex (34 St-Herald Sq is R17 + D17) instead of
   per GTFS platform group.

Run once before starting the API; rerun when the MTA updates its stop list.
Idempotent: safe to run repeatedly. If Stations.csv is unreachable the first
pass still applies and every station simply stays its own complex.
"""
import csv
import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import db  # noqa: E402
from app.models.tables import Route, Station, StationComplex  # noqa: E402

STATIC_GTFS_URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"

# The MTA's station list, which carries the Complex ID grouping. The legacy
# path http://web.mta.info/developers/data/nyct/subway/Stations.csv still
# serves the same data if this one ever moves.
STATIONS_CSV_URL = "https://data.ny.gov/api/views/39hk-dx4f/rows.csv?accessType=DOWNLOAD"


def fetch_static_gtfs() -> zipfile.ZipFile:
    """Download the static GTFS zip once; both passes read from it."""
    print(f"downloading {STATIC_GTFS_URL} ...")
    resp = httpx.get(STATIC_GTFS_URL, timeout=120, follow_redirects=True)
    resp.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(resp.content))


def read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    with zf.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def load_stops(zf: zipfile.ZipFile) -> int:
    """Upsert parent stations from stops.txt. Returns rows seen."""
    rows = read_csv(zf, "stops.txt")
    parents = [r for r in rows if r.get("location_type") == "1"]
    print(f"stops.txt: {len(rows)} rows, {len(parents)} parent stations")

    created = updated = 0
    with db.SessionLocal() as session:
        for row in parents:
            stop_id, name = row["stop_id"], row["stop_name"]
            station = session.scalar(select(Station).where(Station.gtfs_stop_id == stop_id))
            if station is None:
                session.add(Station(gtfs_stop_id=stop_id, name=name))
                created += 1
            elif station.name != name:
                station.name = name
                updated += 1
        session.commit()
    print(f"stations table: {created} created, {updated} updated")
    return len(parents)


def load_routes(zf: zipfile.ZipFile) -> None:
    """Upsert rider-facing route branding from routes.txt.

    Only four ids differ from what riders see: GS, FS and H are all signed "S",
    and SI is signed "SIR". The express variants (FX, 6X, 7X) carry their own
    id as the short name, so the diamond treatment is a display convention
    rather than something this file can tell us (see app/services/routes.py).
    """
    rows = read_csv(zf, "routes.txt")
    renamed = sum(1 for r in rows if r["route_id"] != r.get("route_short_name"))
    print(f"routes.txt: {len(rows)} routes, {renamed} signed differently from "
          f"their GTFS id")

    created = updated = 0
    with db.SessionLocal() as session:
        for row in rows:
            route_id = row["route_id"]
            short = row.get("route_short_name") or route_id
            long_name = row.get("route_long_name") or None
            route = session.scalar(select(Route).where(Route.gtfs_route_id == route_id))
            if route is None:
                session.add(Route(gtfs_route_id=route_id, short_name=short,
                                  long_name=long_name))
                created += 1
            elif (route.short_name, route.long_name) != (short, long_name):
                route.short_name, route.long_name = short, long_name
                updated += 1
        session.commit()
    print(f"routes table: {created} created, {updated} updated")


def complex_name(names: list[str]) -> str:
    """Name a complex from its members, following MTA convention.

    Members usually share a name (34 St-Herald Sq); when they differ the MTA
    joins them with a slash (Lorimer St/Metropolitan Av).
    """
    unique = list(dict.fromkeys(names))
    return "/".join(unique)


def load_complexes() -> None:
    """Populate complexes and set complex_id / daytime_routes per station."""
    print(f"downloading {STATIONS_CSV_URL} ...")
    try:
        resp = httpx.get(STATIONS_CSV_URL, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(resp.text)))
    except Exception as exc:  # noqa: BLE001 - the first pass is still valid
        print(f"WARNING: could not load Stations.csv ({exc}).")
        print("Stations keep their names; each stays its own complex.")
        return

    members: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("Complex ID") and row.get("GTFS Stop ID"):
            members[int(row["Complex ID"])].append(row)
    multi = sum(1 for v in members.values() if len(v) > 1)
    print(f"Stations.csv: {len(rows)} rows, {len(members)} complexes "
          f"({multi} spanning more than one GTFS station)")

    linked = missing = 0
    with db.SessionLocal() as session:
        for complex_id, rows_for_complex in members.items():
            name = complex_name([r["Stop Name"] for r in rows_for_complex])
            existing = session.get(StationComplex, complex_id)
            if existing is None:
                session.add(StationComplex(id=complex_id, name=name))
            elif existing.name != name:
                existing.name = name
            session.flush()

            for row in rows_for_complex:
                station = session.scalar(select(Station).where(
                    Station.gtfs_stop_id == row["GTFS Stop ID"]))
                if station is None:
                    missing += 1  # in Stations.csv but not in stops.txt
                    continue
                station.complex_id = complex_id
                station.daytime_routes = row.get("Daytime Routes") or None
                linked += 1
        session.commit()
    print(f"complexes: {linked} stations linked" +
          (f", {missing} in Stations.csv had no GTFS parent station" if missing else ""))


def main() -> None:
    db.init_db()
    with fetch_static_gtfs() as zf:
        load_stops(zf)
        load_routes(zf)
    load_complexes()


if __name__ == "__main__":
    main()
