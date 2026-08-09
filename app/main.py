"""App entry point: creates the FastAPI app, wires routers, serves the UI.

This is the read side of the system: ingestion runs in a separate worker
process (app/worker.py) and communicates through Redis (README, design
decision 2). This process never talks to the MTA.

The built dashboard is served from this same app so the browser talks to one
origin and no CORS configuration is needed (README, design decision 13).
"""
import contextlib
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import cache, db
from app.routers import arrivals, stats
from app.routers import stations as stations_router
from app.services import stations

# Populated by the frontend build stage in the Dockerfile; absent when running
# the API straight from a checkout, which is fine - the JSON API still works.
STATIC_DIR = Path(__file__).parent / "static"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    stations.load_names_from_db()
    yield
    await cache.close()


app = FastAPI(
    title="MTA Transit Live API",
    description="Live NYC subway arrivals, station-indexed, from the MTA's "
                "GTFS-realtime feeds. See the project README for the design.",
    version="0.4.0",
    lifespan=lifespan,
)

app.include_router(arrivals.router, prefix="/v1")
app.include_router(stations_router.router, prefix="/v1")
app.include_router(stats.router, prefix="/v1")


@app.get("/health")
async def health():
    updated = await cache.updated_at()
    return {
        "status": "ok",
        "version": app.version,
        "redis_ok": await cache.ping(),
        "snapshot_ready": updated is not None,
        "snapshot_age_seconds": None if updated is None else round(time.time() - updated, 1),
    }


# Mounted last so /v1, /health, and /docs keep priority over the SPA.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
