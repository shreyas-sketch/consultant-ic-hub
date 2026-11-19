"""The MongoDB client: one pooled client per process.

QA mode and tests use an in-memory MongoDB (mongomock-motor). Production uses a
real MongoDB (Railway's MongoDB service or Atlas). Code never relies on
multi-document transactions: money and sends are made safe with unique keys,
so the same code is correct on both.
"""
import time

from app.core import settings

_client = None
_db = None


def _real_client():
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(
        settings.MONGO_URL,
        appname=f"{settings.BRAND_NAME}-{settings.ENVIRONMENT}",
        maxPoolSize=settings.MONGO_MAX_POOL,
        minPoolSize=settings.MONGO_MIN_POOL,
        serverSelectionTimeoutMS=settings.MONGO_TIMEOUT_MS,
        connectTimeoutMS=settings.MONGO_TIMEOUT_MS,
        socketTimeoutMS=settings.MONGO_SOCKET_TIMEOUT_MS,
        retryWrites=True,
        retryReads=True,
        tz_aware=True,
        uuidRepresentation="standard",
    )


def get_db():
    global _client, _db
    if _db is None:
        if settings.QA_MODE and settings.QA_DB != "mongo":
            from mongomock_motor import AsyncMongoMockClient
            _client = AsyncMongoMockClient()
        else:
            _client = _real_client()
        _db = _client[settings.DB_NAME]
    return _db


def reporting_db():
    """Same database, but reads may come from a secondary (reports, admin stats).

    Only for reads that tolerate a few seconds of replication lag.
    """
    db = get_db()
    if settings.QA_MODE or settings.MONGO_READ_PREFERENCE == "primary":
        return db
    from pymongo import ReadPreference
    rp = {"primaryPreferred": ReadPreference.PRIMARY_PREFERRED, "secondary": ReadPreference.SECONDARY,
          "secondaryPreferred": ReadPreference.SECONDARY_PREFERRED, "nearest": ReadPreference.NEAREST}
    return db.with_options(read_preference=rp.get(settings.MONGO_READ_PREFERENCE, ReadPreference.PRIMARY))


async def ping() -> float:
    """Round trip to the database in milliseconds (readiness probe)."""
    t0 = time.perf_counter()
    await get_db().command("ping")
    return round((time.perf_counter() - t0) * 1000, 1)


def close():
    global _client, _db
    if _client is not None and hasattr(_client, "close"):
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _db = None


def reset_db():
    """Tests only: start from an empty in-memory database."""
    global _client, _db
    _client = None
    _db = None
