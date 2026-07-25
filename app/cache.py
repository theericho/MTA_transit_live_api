"""Redis snapshot store: the shared cache between the worker and the API.

The worker is the only writer: after each poll it pipelines one key per
station (arrivals:{station_id}, a JSON list of arrival records) plus a
snapshot:updated_at meta key. The API only reads. Keys carry a TTL of
SNAPSHOT_TTL so a dead worker's data ages visibly (clients see
data_age_seconds grow) but does not vanish instantly - stale beats absent
(README, design decisions 3 and 7).

The client is created lazily from REDIS_URL; tests inject a fakeredis client
instead, so the suite needs no running Redis.
"""
import json
import os
import time

from redis import asyncio as aioredis

from app.services.feed import ArrivalRecord

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Keep snapshot keys alive this long after the last write.
SNAPSHOT_TTL = 3600

_KEY_PREFIX = "arrivals:"
_META_KEY = "snapshot:updated_at"

_client: aioredis.Redis | None = None


def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _dump(recs: list[ArrivalRecord]) -> str:
    return json.dumps([[r.time, r.route, r.direction, r.trip_id, r.fetched_at]
                       for r in recs])


def _load(raw: str) -> list[ArrivalRecord]:
    return [ArrivalRecord(time=t, route=route, direction=direction,
                          trip_id=trip_id, fetched_at=fetched_at)
            for t, route, direction, trip_id, fetched_at in json.loads(raw)]


async def write_snapshot(snapshot: dict[str, list[ArrivalRecord]]) -> None:
    """Write the full station index in one pipeline (worker side)."""
    client = get_client()
    pipe = client.pipeline(transaction=False)
    for station_id, recs in snapshot.items():
        pipe.set(_KEY_PREFIX + station_id, _dump(recs), ex=SNAPSHOT_TTL)
    pipe.set(_META_KEY, str(time.time()), ex=SNAPSHOT_TTL)
    await pipe.execute()


async def read_station(station_id: str) -> list[ArrivalRecord] | None:
    """Read one station's records (API side); None if the key is absent."""
    raw = await get_client().get(_KEY_PREFIX + station_id)
    return None if raw is None else _load(raw)


async def updated_at() -> float | None:
    """When the worker last wrote a snapshot; None if it never has."""
    raw = await get_client().get(_META_KEY)
    return None if raw is None else float(raw)


async def ping() -> bool:
    """True if Redis is reachable (used by /health)."""
    try:
        return bool(await get_client().ping())
    except Exception:
        return False
