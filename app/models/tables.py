"""ORM tables for the arrival history (README, design decision 4).

Normalized: reference data (stations, routes, trips) lives once, enforced by
unique keys; arrival events are compact rows of foreign keys plus timestamps.
Foreign keys make orphan events impossible.

All datetimes are stored timezone-naive in UTC.
"""
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class StationComplex(Base):
    """A rider-facing station: one or more GTFS stations joined by passageways.

    GTFS models platforms - 34 St-Herald Sq is two stations (R17 for N/Q/R/W,
    D17 for B/D/F/M) and Times Sq is five. Riders think in complexes, so the
    MTA's Stations.csv complex mapping is loaded here and the API answers per
    complex (README, design decision 12).
    """
    __tablename__ = "complexes"

    id: Mapped[int] = mapped_column(primary_key=True)  # the MTA's Complex ID
    name: Mapped[str] = mapped_column(String(200))


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    gtfs_stop_id: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    # Both are populated by scripts/load_gtfs_static.py from Stations.csv and
    # stay null if that load never ran: each station is then its own complex.
    complex_id: Mapped[int | None] = mapped_column(
        ForeignKey("complexes.id"), index=True, default=None)
    daytime_routes: Mapped[str | None] = mapped_column(String(64), default=None)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    gtfs_route_id: Mapped[str] = mapped_column(String(8), unique=True)
    # Rider-facing branding from routes.txt: GS/FS/H are all signed "S", SI is
    # signed "SIR". Null until scripts/load_gtfs_static.py has run, or for a
    # route the archiver saw in the feed before the static data described it.
    short_name: Mapped[str | None] = mapped_column(String(8), default=None)
    long_name: Mapped[str | None] = mapped_column(String(64), default=None)


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    gtfs_trip_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"))
    direction: Mapped[str] = mapped_column(String(1))

    route: Mapped[Route] = relationship()


class ArrivalEvent(Base):
    __tablename__ = "arrival_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    arrival_time: Mapped[datetime] = mapped_column(index=True)
    recorded_at: Mapped[datetime]

    trip: Mapped[Trip] = relationship()
    station: Mapped[Station] = relationship()
