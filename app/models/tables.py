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


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    gtfs_stop_id: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    gtfs_route_id: Mapped[str] = mapped_column(String(8), unique=True)


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
