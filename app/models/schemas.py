"""Pydantic response models. These define the API's public contract."""
from datetime import datetime

from pydantic import BaseModel, Field


class Station(BaseModel):
    id: str = Field(description="GTFS stop id, e.g. 'R16'")
    name: str = Field(description="Human-readable station name")
    routes: list[str] = Field(description="Routes serving this station")


class StationSearchResult(BaseModel):
    id: str = Field(description="Id to request arrivals for, per `kind`")
    kind: str = Field(
        description="'complex' when the entry groups several GTFS stations "
                    "(request /v1/complexes/{id}/arrivals), 'station' when it "
                    "is a lone GTFS station (/v1/stations/{id}/arrivals). "
                    "Everything is a complex once Stations.csv is loaded."
    )
    name: str
    routes: list[str] = Field(description="Daytime routes from static GTFS data")
    station_ids: list[str] = Field(description="GTFS stations covered by this entry")


class Arrival(BaseModel):
    route: str = Field(description="Raw GTFS route id, e.g. 'GS'")
    route_name: str = Field(
        description="What riders see on the bullet, e.g. 'S'. The three "
                    "shuttles are all signed S; express variants show the "
                    "base route with `express` set."
    )
    route_long_name: str | None = Field(
        default=None, description="Full service name, e.g. '42 St Shuttle'"
    )
    express: bool = Field(
        default=False, description="True when MTA signage uses a diamond bullet"
    )
    direction: str = Field(description="'N' (uptown) or 'S' (downtown)")
    arrival_time: datetime
    minutes_away: float = Field(ge=0)


class StationArrivals(BaseModel):
    station: Station
    arrivals: list[Arrival]
    data_age_seconds: float = Field(
        description="Seconds since the underlying feed data was fetched. "
                    "Lets clients judge staleness instead of us hiding it."
    )


class HeadwayGroup(BaseModel):
    route: str = Field(description="Raw GTFS route id")
    route_name: str = Field(description="What riders see on the bullet")
    route_long_name: str | None = None
    express: bool = False
    direction: str = Field(description="'N' (uptown) or 'S' (downtown)")
    arrivals: int = Field(description="Observed arrivals in the window")
    mean_headway_minutes: float | None = Field(
        description="Average gap between consecutive arrivals; null if fewer "
                    "than 2 arrivals"
    )
    median_headway_minutes: float | None
    regularity_pct: float | None = Field(
        description="Share of headways within 1.25x the median. The standard "
                    "reliability measure for high-frequency service, where "
                    "even spacing matters more than a printed schedule."
    )


class StationHeadways(BaseModel):
    station: Station
    window_hours: int
    total_arrivals: int
    groups: list[HeadwayGroup] = Field(
        description="Stats per (route, direction) pair observed at the station"
    )
