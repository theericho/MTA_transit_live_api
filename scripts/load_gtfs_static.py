"""Load station metadata from the MTA's static data into the database.

Usage:
    python scripts/load_gtfs_static.py

Two passes:
1. The static GTFS zip (a few MB) -> stops.txt -> every parent station
   (location_type = 1) upserted into the stations table.
2. Stations.csv -> the complex mapping and daytime routes, so the API can
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
from app.models.tables import Station, StationComplex  # noqa: E402

STATIC_GTFS_URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"

# The MTA's station list, which carries the Complex ID grouping. The legacy
# path http://web.mta.info/developers/data/nyct/subway/Stations.csv still
# serves the same data if this one ever moves.
STATIONS_CSV_URL = "https://data.ny.gov/api/views/39hk-dx4f/rows.csv?accessType=DOWNLOAD"


def load_stops() -> int:
    """Upsert parent stations from the static GTFS zip. Returns rows seen."""
    print(f"downloading {STATIC_GTFS_URL} ...")
    resp = httpx.get(STATIC_GTFS_URL, timeout=120, follow_redirects=True)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open("stops.txt") as f:
            rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))

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
    load_stops()
    load_complexes()


if __name__ == "__main__":
    main()
