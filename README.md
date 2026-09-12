# MTA Transit Live API

A real-time NYC subway arrivals API built with [FastAPI](https://fastapi.tiangolo.com/).
Ingests the MTA's GTFS-realtime feeds, serves live arrival lookups per station,
and archives observed arrivals for reliability analytics.

**Status: v4 - dashboard.** A React dashboard ships with the API: search any
of the 496 stations, watch live arrivals, and see how evenly trains have
actually been running. Ingestion runs in a dedicated worker process that polls
all 8 subway feeds every 30 seconds into a Redis snapshot; the API process is
read-only; arrival history lands in Postgres. Everything runs under Docker
Compose. See the [roadmap](#roadmap) below.

## Run it (Docker Compose)

```bash
docker compose up --build
docker compose run --rm worker python scripts/load_gtfs_static.py   # once: stations, complexes, route branding
docker compose restart api   # only if the stack was already running: names and branding load at startup
```

Four services start: the API (port 8000), the ingestion worker, Redis, and
Postgres. Then open:

- **<http://localhost:8000> - the dashboard**
- <http://localhost:8000/docs> - interactive API docs (auto-generated)
- <http://localhost:8000/health> - health check (redis status + snapshot age)
- <http://localhost:8000/v1/stations?search=herald> - station search
- <http://localhost:8000/v1/complexes/607/arrivals> - live arrivals, Herald Sq
- <http://localhost:8000/v1/stats/complexes/607/headways> - headway stats
  (needs some uptime first: history accumulates while the worker runs)

Until the worker completes its first poll, arrival endpoints return **503**.
Unknown stations return **404**; known-but-quiet stations return an empty
list.

### The dashboard

Search collapses each station complex into one entry, so "Herald" returns a
single result covering B/D/F/M **and** N/Q/R/W rather than two rows with the
same name. Arrivals are split into uptown and downtown columns with the
official route bullets, and a freshness badge in the corner reports the API's
own `data_age_seconds`.

That badge is the most honest thing on the page. Run `docker compose stop
worker` and watch it walk from green ("live") to amber ("data 2m old") while
the trains stay listed, then `docker compose start worker` and watch it snap
back. Nothing errors, nothing pretends to be current: exactly the contract in
[decision 7](design_decisions.md), made visible.

### Run it without Docker

Requires **Python 3.10+** and a Redis to point at (`docker compose up redis`
works fine on its own):

```bash
pip install -r requirements.txt
python scripts/load_gtfs_static.py     # once: stations, complexes, branding into SQLite
python -m app.worker                   # terminal 1: ingestion
uvicorn app.main:app --reload          # terminal 2: API
```

For dashboard development, run Vite's dev server in a third terminal
(Node 22.12+). It serves the UI on <http://localhost:5173> with hot reload and
proxies `/v1` and `/health` to the API above, so there is no CORS to
configure:

```bash
cd frontend
npm install
npm run dev
```

Configuration (all optional):
- `REDIS_URL` - default `redis://localhost:6379/0`
- `DATABASE_URL` - SQLAlchemy URL; defaults to `sqlite:///./transit.db`,
  Compose wires it to Postgres
- `POLL_INTERVAL` - seconds between feed polls (default 30)

## Try the raw feed

```bash
python scripts/fetch_feed.py        # live arrivals at Times Sq-42 St
python scripts/fetch_feed.py R14    # any stop id on the N/Q/R/W feed
```

A standalone script that fetches the MTA's N/Q/R/W GTFS-realtime feed and
prints upcoming arrivals - the v0 proof of concept the API grew out of.

## Test

```bash
pytest
```

Tests are fully service-free: protobuf feed fixtures are built in memory,
Redis is faked with `fakeredis`, and database tests run against per-test
in-memory SQLite, so the parser, cache, archiver, reader, and endpoint
layers are each tested in isolation. CI (GitHub Actions) runs this suite and
builds the dashboard on every push.

## Data source

- **GTFS-realtime feeds.** The MTA publishes one protobuf feed per line group
  (1-6+S, A/C/E, N/Q/R/W, and so on), updated roughly every 30 seconds.
  Parsed with `gtfs-realtime-bindings`. The feeds are free to access.
- **Static GTFS.** A zip of CSVs (stops, routes, trips) with station names
  and metadata. `scripts/load_gtfs_static.py` loads all 496 parent stations
  into the database; a small hand-checked name map covers the gap before that
  first load.
- **Stations.csv.** The MTA's station list, which carries the Complex ID
  grouping and daytime routes. The same script loads it into the `complexes`
  table: 445 complexes, 35 of which span more than one GTFS station.
- **routes.txt**, from the same zip, supplies rider-facing route branding.
  Four of the 29 route ids are signed differently from their id: `GS`, `FS`
  and `H` are three unrelated shuttles all signed **S**, and `SI` is signed
  **SIR**.

The feed is organized per *line group* and per *trip*, but clients ask per
*station* - so the service must ingest everything and re-index by station.
That inversion is the core of the data model.

## Architecture

```
                                                   browser (React dashboard)
                                                        |  polls every 15s
                                                        |  same origin, no CORS
                                                        v
 MTA GTFS-rt ----> [worker process]                [api process]
 (protobuf)        poll all feeds every ~30s       FastAPI, read-only,
                   normalize + merge + archive     also serves the built UI
                        |            |             |         |
                        v            v             v         v
                   [ Redis ]    [ Postgres ] <-- stats    [ Redis ]
                   snapshot:    arrival history           snapshot reads
                   one key per  + stations/complexes
                   station      (SQLite outside Docker)
```

- **Worker** (`app/worker.py`): owns all writes. Fetches each feed on an
  interval, parses protobuf, merges with the previous cycle, writes the
  station index to Redis, and archives passed arrivals to the database.
- **Redis snapshot**: one key per station plus a meta key with the last
  write time; keys carry a TTL so a dead worker's data ages visibly instead
  of vanishing. Every live read hits Redis, never the upstream - the MTA is
  never in the request path.
- **Archiver** (`app/services/archive.py`): watches each (trip, station)
  prediction across polls; once its arrival time passes while still current,
  it is recorded as an observed arrival event.
- **Database**: append-only arrival history plus the station/route/trip
  reference tables. Stats endpoints query it.
- **API** (`app/main.py`): read-only REST endpoints over the Redis snapshot
  (live) and the database (stats). Kill the worker and the API keeps
  serving, with `data_age_seconds` growing.

## Design decisions

The reasoning behind the architecture lives in
[design_decisions.md](design_decisions.md): fifteen numbered entries covering
polling, the process split, caching, the history schema, and API semantics.
Code comments throughout the project cite them by number.

## Roadmap

| Version | Goal |
|---------|------|
| **v0** (done) | Standalone script: fetch one feed, parse, print arrivals (`scripts/fetch_feed.py`) |
| **v1** (done) | FastAPI app: poller + in-memory snapshot + live endpoints + tests |
| **v2** (done) | SQL arrival history + headway stats endpoints + static GTFS station data |
| **v3** (done) | Redis cache, separate ingestion worker, Docker Compose, CI (cloud deploy deferred by choice; the Compose stack is the deployable artifact) |
| **v4** (done) | React dashboard (search, live board, freshness badge, headway panel), station search endpoint, and station-complex merging via the MTA's Stations.csv |

## Layout

```
app/
├── main.py          # API entry (read-only), health endpoint, serves the UI
├── worker.py        # ingestion entrypoint: poll -> Redis -> archive
├── cache.py         # Redis snapshot store (worker writes, API reads)
├── db.py            # SQLAlchemy engine/session, DATABASE_URL switch
├── routers/
│   ├── arrivals.py  # live endpoints, per station and per complex
│   ├── stations.py  # station search, grouped by complex
│   └── stats.py     # headway stats from archived history
├── models/
│   ├── schemas.py   # Pydantic response models (the API contract)
│   └── tables.py    # ORM: complexes, stations, routes, trips, arrival_events
└── services/
    ├── feed.py            # fetch + normalize + merge (ingestion half)
    ├── arrivals_reader.py # cache records -> API responses (read half)
    ├── archive.py         # predictions -> observed arrival events
    ├── routes.py          # route branding: GTFS ids -> what riders see
    └── stations.py        # station names (DB-backed after static GTFS load)
frontend/            # React + Vite dashboard, built into app/static/
├── vite.config.js   # dev proxy to the API
└── src/
    ├── App.jsx      # polling, selection, layout
    ├── api.js       # REST wrapper (same origin)
    └── components/  # search, board, freshness badge, headway panel
scripts/
├── fetch_feed.py        # v0 standalone fetch/parse demo
└── load_gtfs_static.py  # one-time load: stops.txt + Stations.csv complexes
tests/                   # service-free: protobuf fixtures + fakeredis + in-memory SQLite
Dockerfile               # node build stage + python image (api and worker)
docker-compose.yml       # api + worker + redis + postgres
.github/workflows/ci.yml # pytest and dashboard build on every push
```
