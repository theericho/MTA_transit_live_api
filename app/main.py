"""App entry point: creates the FastAPI app and wires up routers.

This is the read side of the system: ingestion runs in a separate worker
process (app/worker.py) and communicates through Redis (README, design
decision 2). This process never talks to the MTA.
"""
import contextlib
import time

from fastapi import FastAPI

from app import cache, db
from app.routers import arrivals, stats
from app.services import stations


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
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(arrivals.router, prefix="/v1")
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
