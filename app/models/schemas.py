"""Pydantic response models. These define the API's public contract."""
from datetime import datetime

from pydantic import BaseModel, Field


class Station(BaseModel):
    id: str = Field(description="GTFS stop id, e.g. 'R16'")
    name: str = Field(description="Human-readable station name")
    routes: list[str] = Field(description="Routes serving this station")


class Arrival(BaseModel):
    route: str = Field(description="Route name, e.g. 'N'")
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
