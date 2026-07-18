"""App entry point: creates the FastAPI app, wires routers, runs the poller."""
import asyncio
import contextlib

from fastapi import FastAPI

from app.routers import arrivals
from app.services import feed


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # The poller lives inside the API process for now (README, design
    # decision 2) - one deployable, no shared infra. Moves to a separate
    # worker alongside Redis.
    task = asyncio.create_task(feed.poller_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="MTA Transit Live API",
    description="Live NYC subway arrivals, station-indexed, from the MTA's "
                "GTFS-realtime feeds. See the project README for the design.",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(arrivals.router, prefix="/v1")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "snapshot_ready": feed.snapshot_ready(),
    }
