"""Load station metadata from the MTA's static GTFS into the database.

Usage:
    python scripts/load_gtfs_static.py

Downloads the subway static GTFS zip (a few MB), reads stops.txt, and
upserts every parent station (location_type = 1) into the stations table.
Run it once before starting the API to get full station names; rerun
whenever the MTA updates its stop list.
"""
import csv
import io
import sys
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import db  # noqa: E402
from app.models.tables import Station  # noqa: E402

STATIC_GTFS_URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"


def main() -> None:
    print(f"downloading {STATIC_GTFS_URL} ...")
    resp = httpx.get(STATIC_GTFS_URL, timeout=120, follow_redirects=True)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open("stops.txt") as f:
            rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))

    parents = [r for r in rows if r.get("location_type") == "1"]
    print(f"stops.txt: {len(rows)} rows, {len(parents)} parent stations")

    db.init_db()
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


if __name__ == "__main__":
    main()
