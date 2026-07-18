"""Minimal station-name directory.

Real station metadata (names, coordinates, the full stop list) comes from the
MTA's static GTFS zip and lands in the database in v2. Until then we keep a
small hand-checked map of popular stations and fall back to the raw stop id.

A stop id here is the *parent* station id - platform ids in the realtime feed
add a direction suffix (R16N / R16S -> R16).
"""

STATION_NAMES = {
    "R16": "Times Sq-42 St",       # N/Q/R/W platforms
    "127": "Times Sq-42 St",       # 1/2/3 platforms
    "631": "Grand Central-42 St",  # 4/5/6 platforms
    "L08": "Bedford Av",           # L
}


def station_name(station_id: str) -> str | None:
    return STATION_NAMES.get(station_id)
