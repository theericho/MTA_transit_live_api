# MTA Transit Live API

A real-time NYC subway arrivals API built with [FastAPI](https://fastapi.tiangolo.com/).
Ingests the MTA's GTFS-realtime feeds, serves live arrival lookups per station,
and archives observed arrivals for reliability analytics.

**Status: v2 - live data + history.** A background poller fetches all 8 subway
feeds every 30 seconds into an in-memory snapshot; the API serves
station-indexed arrivals from that snapshot. Passed arrivals are archived to a
SQL database, and stats endpoints report headway reliability per station. See
the [roadmap](#roadmap) below.

## Run it

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt
python scripts/load_gtfs_static.py     # once: load all 496 station names
uvicorn app.main:app --reload
```

Then open:
- <http://localhost:8000/docs> - interactive API docs (auto-generated)
- <http://localhost:8000/health> - health check (includes `snapshot_ready`)
- <http://localhost:8000/v1/stations/R16/arrivals> - live arrivals at Times Sq
- <http://localhost:8000/v1/stations/631/arrivals> - live arrivals at Grand Central
- <http://localhost:8000/v1/stats/stations/R16/headways> - headway stats
  (needs some uptime first: history accumulates while the server runs)

The first poll takes a few seconds; until it completes, arrival endpoints
return **503**. Unknown stations return **404**; known-but-quiet stations
return an empty list.

Configuration:
- `POLL_INTERVAL` - seconds between feed polls (default 30)
- `DATABASE_URL` - SQLAlchemy URL; defaults to `sqlite:///./transit.db` for
  zero-setup local use, point at PostgreSQL in production

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

Tests are fully network-free: protobuf feed fixtures are built in memory, the
snapshot is seeded directly, and database tests run against a per-test
in-memory SQLite, so the parser, cache, archiver, and endpoint layers are each
tested in isolation.

## Data source

- **GTFS-realtime feeds.** The MTA publishes one protobuf feed per line group
  (1-6+S, A/C/E, N/Q/R/W, and so on), updated roughly every 30 seconds.
  Parsed with `gtfs-realtime-bindings`. The feeds are free to access.
- **Static GTFS.** A zip of CSVs (stops, routes, trips) with station names
  and metadata. `scripts/load_gtfs_static.py` loads all parent stations into
  the database; a small hand-checked name map covers the gap before that
  first load.

The feed is organized per *line group* and per *trip*, but clients ask per
*station* - so the service must ingest everything and re-index by station.
That inversion is the core of the data model.

## Architecture

```
                +---------------------------------------------+
                |                FastAPI app                  |
                |                                             |
 MTA GTFS-rt -->|  Poller (async task, every ~30s)            |
 (protobuf)     |     |  parse + normalize                    |
                |     v                                       |
                |  Snapshot cache (in-memory dict)            |
                |     |  "current arrivals per station"       |
                |     |                                       |
                |     +----------> REST endpoints ----------->|--> clients
                |     v                                       |
                |  Archiver: passed predictions become        |
                |  arrival events in SQL                      |
                |  (SQLite dev / PostgreSQL via DATABASE_URL) |
                +---------------------------------------------+
```

- **Poller**: a background asyncio task inside the app, fetching each feed on
  an interval, parsing protobuf, and updating state.
- **Snapshot cache**: the current arrivals, indexed by station - every live
  read hits this, never the upstream, so reads are fast and the MTA is never
  in the request path.
- **Archiver**: watches each (trip, station) prediction across polls; once
  its arrival time passes while still current, it is recorded as an observed
  arrival event.
- **Database**: append-only arrival history plus the station/route/trip
  reference tables. Stats endpoints query it.
- **API**: read-only REST endpoints over the cache (live) and the DB (stats).

## Design decisions

1. **Polling, not streaming.** GTFS-rt is a pull model - the MTA republishes
   the file every ~30s and there is nothing to subscribe to. The poller runs
   every 30s to match the upstream cadence: faster wastes bandwidth, slower
   serves stale data.
2. **Poller lives in the API process (for now).** One deployable, no shared
   infrastructure. The tradeoff is that ingestion is coupled to API uptime and
   replicas would each poll; v3 moves ingestion to a separate worker once a
   shared cache exists.
3. **In-memory snapshot, atomically swapped.** The station index is rebuilt as
   a fresh dict each poll and swapped in with a single reference assignment,
   so readers never see a half-built index and no locks are needed. Reads go
   through one small interface (`get_arrivals`), so swapping in Redis later
   does not touch the API layer.
4. **Normalized history schema.** Stations, routes, trips, and arrival events
   in separate tables with foreign keys, so reference data lives once and
   orphan events are impossible. SQLite by default, PostgreSQL via
   `DATABASE_URL`; schema and queries are portable across both. The arrivals
   table grows fast; partitioning or a retention policy is future work.
5. **Async ingestion.** Fetching 8 feeds is concurrent network I/O, so it uses
   `httpx.AsyncClient` with `asyncio.gather`. Protobuf parsing is cheap enough
   to stay inline; database writes run off the event loop in a thread.
6. **Explicit response semantics.** Versioned under `/v1` with Pydantic
   response models throughout. 503 until the first poll completes, 404 for an
   unknown station, 200 with an empty list for a known-but-quiet one - "no
   data yet", "no such place", and "no trains right now" are different answers.
7. **Stale beats absent.** If a feed fetch fails, its previous payload is kept
   and served; every response carries `data_age_seconds` so clients judge
   freshness themselves instead of the API pretending or failing.
8. **Network-free tests.** Feed fixtures are constructed protobuf messages,
   and database tests use per-test in-memory SQLite. The poll cycle is tested
   by faking the fetch function, including the all-feeds-down case.
9. **Deployment** (planned, v3). Dockerfile plus CI running lint and tests,
   then a free-tier host with managed Postgres.
10. **History records observations, not raw feed rows.** The feed only says
    what is about to happen, so the archiver tracks each (trip, station)
    prediction across polls and records it once its arrival time passes.
    Guards learned from live data: a prediction that went stale long before
    its arrival time is treated as a cancelled train and dropped; "ghost"
    entries whose arrival time is already old when first seen are never
    archived; and a flushed (trip, station) pair is remembered so a train
    lingering in the feed after arrival is recorded exactly once.
11. **Headway regularity instead of schedule on-time %.** True on-time
    percentage requires the printed schedule, but most subway lines run
    frequency-based service where riders care about even spacing. The stats
    endpoint reports mean and median headway plus regularity: the share of
    headways within 1.25x the median, a standard reliability measure for
    high-frequency transit.

## Roadmap

| Version | Goal |
|---------|------|
| **v0** (done) | Standalone script: fetch one feed, parse, print arrivals (`scripts/fetch_feed.py`) |
| **v1** (done) | FastAPI app: poller + in-memory snapshot + live endpoints + tests |
| **v2** (done) | SQL arrival history + headway stats endpoints + static GTFS station data |
| **v3** | Redis cache, separate ingestion worker, Docker Compose, deploy |
| **v4** | Minimal dashboard or WebSocket push; station-complex merging (GTFS models platforms, riders think in complexes: R17 + D17 are both 34 St-Herald Sq and should answer as one station, via the MTA's Stations.csv complex mapping) |

## Layout

```
app/
├── main.py          # app entry, lifespan (DB init, poller), health endpoint
├── db.py            # SQLAlchemy engine/session, DATABASE_URL switch
├── routers/
│   ├── arrivals.py  # live endpoints (503/404/empty-list semantics)
│   └── stats.py     # headway stats from archived history
├── models/
│   ├── schemas.py   # Pydantic response models (the API contract)
│   └── tables.py    # ORM tables: stations, routes, trips, arrival_events
└── services/
    ├── feed.py      # poller, normalizer, snapshot cache
    ├── archive.py   # predictions -> observed arrival events
    └── stations.py  # station names (DB-backed after static GTFS load)
scripts/
├── fetch_feed.py        # v0 standalone fetch/parse demo
└── load_gtfs_static.py  # one-time station load from static GTFS
tests/               # network-free: protobuf fixtures + in-memory SQLite
```
