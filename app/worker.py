"""Ingestion worker: polls the MTA feeds, writes Redis, archives history.

Run with: python -m app.worker

This is the write side of the system (README, design decision 2): it owns
feed polling, the Redis snapshot, and database writes. The API process only
reads. Killing the worker does not take the API down - clients keep getting
the last snapshot with an honest, growing data_age_seconds.
"""
import asyncio
import contextlib
import logging
import signal

import httpx

from app import cache, db
from app.services import archive, feed, stations

log = logging.getLogger(__name__)


async def run(stop: asyncio.Event) -> None:
    db.init_db()
    stations.load_names_from_db()
    async with httpx.AsyncClient() as client:
        while not stop.is_set():
            try:
                ok, snapshot = await feed.poll_once(client)
                await cache.write_snapshot(snapshot)
                # DB writes are sync; run them off the event loop.
                archived = await asyncio.to_thread(archive.record_snapshot, snapshot)
                log.info("poll complete: %d/%d feeds ok, %d stations, %d arrivals archived",
                         ok, len(feed.FEEDS), len(snapshot), archived)
            except Exception:
                log.exception("poll cycle failed")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=feed.POLL_INTERVAL)
    await cache.close()


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # add_signal_handler is unavailable on Windows; Ctrl+C still raises
        # KeyboardInterrupt there, and Docker (Linux) gets clean SIGTERM.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await run(stop)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
