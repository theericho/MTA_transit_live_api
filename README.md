# MTA Transit Live API

A real-time NYC subway arrivals API built with [FastAPI](https://fastapi.tiangolo.com/).
Ingests the MTA's GTFS-realtime feeds, serves live arrival lookups per station,
and will archive history for trend analytics.

**Status: v1 - live data.** A background poller fetches all 8 subway feeds
every 30 seconds into an in-memory snapshot; the API serves station-indexed
arrivals from that snapshot. See the [roadmap](#roadmap) below.

## Run it

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open:
- <http://localhost:8000/docs> - interactive API docs (auto-generated)
- <http://localhost:8000/health> - health check (includes `snapshot_ready`)
- <http://localhost:8000/v1/stations/R16/arrivals> - live arrivals at Times Sq
- <http://localhost:8000/v1/stations/631/arrivals> - live arrivals at Grand Central

The first poll takes a few seconds; until it completes, arrival endpoints
return **503**. Unknown stations return **404**; known-but-quiet stations
return an empty list. Set `POLL_INTERVAL` (seconds, default 30) to tune the
refresh cadence.

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

Tests are fully network-free: protobuf feed fixtures are built in memory and
the snapshot is seeded directly, so the parser, cache, and endpoint layers are
each tested in isolation.

## Data source

- **GTFS-realtime feeds.** The MTA publishes one protobuf feed per line group
  (1-6+S, A/C/E, N/Q/R/W, and so on), updated roughly every 30 seconds.
  Parsed with `gtfs-realtime-bindings`. The feeds are free to access.
- **Static GTFS** (planned, v2). A zip of CSVs (stops, routes, trips) with
  station names and coordinates. Until it lands, a small hand-checked name map
  covers popular stations.

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
                |  PostgreSQL (planned, v2)                   |
                |  append-only arrival history                |
                +---------------------------------------------+
```

- **Poller**: a background asyncio task inside the app, fetching each feed on
  an interval, parsing protobuf, and updating state.
- **Snapshot cache**: the current arrivals, indexed by station - every API
  read hits this, never the upstream, so reads are fast and the MTA is never
  in the request path.
- **Database** (planned, v2): append-only history of observed arrivals for
  analytics, plus the static station/route reference tables.
- **API**: read-only REST endpoints over the cache (live) and, later, the DB
  (history).

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
4. **Normalized history schema** (planned, v2). Stations, routes, trips, and
   arrival events in separate tables with foreign keys, so reference data
   lives once and orphan events are impossible. The arrivals table grows fast;
   partitioning or a retention policy is part of the design.
5. **Async ingestion.** Fetching 8 feeds is concurrent network I/O, so it uses
   `httpx.AsyncClient` with `asyncio.gather`. Protobuf parsing is cheap enough
   to stay inline.
6. **Explicit response semantics.** Versioned under `/v1` with Pydantic
   response models throughout. 503 until the first poll completes, 404 for an
   unknown station, 200 with an empty list for a known-but-quiet one - "no
   data yet", "no such place", and "no trains right now" are different answers.
7. **Stale beats absent.** If a feed fetch fails, its previous payload is kept
   and served; every response carries `data_age_seconds` so clients judge
   freshness themselves instead of the API pretending or failing.
8. **Network-free tests.** Feed fixtures are constructed protobuf messages;
   the poll cycle is tested by faking the fetch function, including the
   all-feeds-down case.
9. **Deployment** (planned, v3). Dockerfile plus CI running lint and tests,
   then a free-tier host with managed Postgres.

## Roadmap

| Version | Goal |
|---------|------|
| **v0** (done) | Standalone script: fetch one feed, parse, print arrivals (`scripts/fetch_feed.py`) |
| **v1** (done) | FastAPI app: poller + in-memory snapshot + live endpoints + tests |
| **v2** | Postgres history + stats endpoints (average headway, on-time %) + static GTFS station data |
| **v3** | Redis cache, separate ingestion worker, Docker Compose, deploy |
| **v4** (stretch) | Minimal dashboard or WebSocket push |

## Layout

```
app/
├── main.py          # app entry, lifespan (starts poller), health endpoint
├── routers/         # HTTP endpoints (503/404/empty-list semantics)
├── models/          # Pydantic schemas (the API contract)
└── services/
    ├── feed.py      # poller, normalizer, snapshot cache
    └── stations.py  # station names (static GTFS load comes in v2)
scripts/
└── fetch_feed.py    # v0 standalone fetch/parse demo
tests/               # network-free: in-memory protobuf fixtures
```
