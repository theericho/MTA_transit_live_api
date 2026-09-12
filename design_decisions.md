# Design decisions

The reasoning behind the architecture. Code comments throughout the project
cite these by number.

1. **Polling, not streaming.** GTFS-rt is a pull model - the MTA republishes
   the file every ~30s and there is nothing to subscribe to. The poller runs
   every 30s to match the upstream cadence: faster wastes bandwidth, slower
   serves stale data.
2. **Ingestion is a separate process.** The worker owns all writes (feeds,
   Redis, database); the API is read-only. Ingestion uptime is decoupled
   from API uptime, and API replicas can scale without multiplying polls
   against the MTA. Single-writer also keeps the merge state trivially
   consistent.
3. **Redis snapshot behind a small interface.** Live reads go through
   `app/cache.py` (per-station keys, pipelined writes, TTL). The v1/v2
   in-process dict became Redis without touching the API layer, which is the
   payoff of keeping reads behind one interface.
4. **Normalized history schema.** Stations, routes, trips, and arrival events
   in separate tables with foreign keys, so reference data lives once and
   orphan events are impossible. SQLite by default, PostgreSQL via
   `DATABASE_URL`; schema and queries are portable across both. The arrivals
   table grows fast; partitioning or a retention policy is future work.
5. **Async ingestion.** Fetching 8 feeds is concurrent network I/O, so it uses
   `httpx.AsyncClient` with `asyncio.gather`. Protobuf parsing is cheap enough
   to stay inline; database writes run off the event loop in a thread.
6. **Explicit response semantics.** Versioned under `/v1` with Pydantic
   response models throughout. 503 until the worker's first snapshot exists,
   404 for an unknown station, 200 with an empty list for a known-but-quiet
   one - "no data yet", "no such place", and "no trains right now" are
   different answers.
7. **Stale beats absent.** If a feed fetch fails, its previous payload is kept
   and served; if the whole worker dies, Redis keeps serving the last
   snapshot for an hour. Every response carries `data_age_seconds` so clients
   judge freshness themselves instead of the API pretending or failing.
8. **Service-free tests.** Feed fixtures are constructed protobuf messages,
   Redis is `fakeredis`, and database tests use per-test in-memory SQLite.
   The poll cycle is tested by faking the fetch function, including the
   all-feeds-down case and the dead-worker case.
9. **One image, two commands.** A single Dockerfile serves both services;
   Compose runs it as the API (default command) and the worker (command
   override). CI runs the full test suite on every push. Cloud deployment is
   deliberately deferred: the Compose file is the deployable artifact, and
   any host that runs Compose (a VM, Render, Fly.io) can take it as is.
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
12. **Complexes, because GTFS models platforms and riders do not.** 34 St-Herald
    Sq is two GTFS stations (R17 for N/Q/R/W, D17 for B/D/F/M) and Times Sq is
    five, including Port Authority. Search groups members into one entry and
    `/v1/complexes/{id}/arrivals` merges their boards, reporting the **oldest**
    member's `data_age_seconds` so the number is never flattering. The
    per-station endpoints are untouched: a published contract does not change
    because a better one arrived, so each search result carries a `kind`
    telling the client which to call. Stations keep working with no complex
    assigned, which is the state before `load_gtfs_static.py` has run.
13. **The dashboard ships inside the API image.** A Node stage builds the
    bundle and the Python stage copies it in, so there is still one image, one
    origin, and no CORS configuration. `npm run dev` reproduces that in
    development with a Vite proxy rather than a second set of rules.
14. **Route branding needs two mechanisms, not one.** The feed identifies a
    train by `route_id`, which is an internal identifier rather than what is
    printed on the train. Half the problem is a data lookup: `routes.txt` says
    `GS`, `FS` and `H` are all signed **S**. The other half is a convention
    the data does not encode, since `FX`, `6X` and `7X` carry their own id as
    their short name; MTA signage renders express service as a diamond, so a
    trailing `X` on a known route means "that route, express". Translation
    happens on read and the raw id stays in the response and in the database,
    so nothing that already depended on `route` breaks and history stays
    joinable. Showing all three shuttles as **S** is unambiguous because no
    station is served by more than one of them, and the full service name is
    carried alongside for a tooltip. Because the response now speaks two
    vocabularies, filtering does too: `?route=` is the exact GTFS id and
    `?route_name=` is the rider-facing name, so `route_name=S` finds all three
    shuttles and `route=FX` selects the Brooklyn express alone. One parameter
    covering both cannot tell "the F line" from "the id F", and whichever it
    picks, a station reachable only under the other name silently returns
    nothing. Passing a name that is not also an id (`S`, `SIR`) to `?route=`
    is rejected with a 400 naming the other parameter, because an empty result
    there reads as "no service". Where the two overlap, as with `F`, the id
    wins and is filtered exactly; `route_name=F` is how you ask for the line.
15. **The browser polls; it is not pushed to.** The upstream feeds only change
    every ~30s, so a 15s poll is never more than one cycle behind. WebSockets
    would add Redis pub/sub, connection lifecycle, and reconnect logic to
    deliver data that changes twice a minute, and polling has the side benefit
    of proving the public REST contract is genuinely usable.
