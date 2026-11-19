"""File storage behind one async interface.

- `local`: files under UPLOAD_DIR. Fine for QA and a single web replica with a
  Railway volume mounted at UPLOAD_DIR.
- `s3`: any S3-compatible bucket (Railway Storage Buckets, Cloudflare R2, AWS S3,
  MinIO). Required as soon as web and worker run as separate services or web
  has more than one replica, because they don't share a disk.

boto3 is synchronous, so every S3 call runs in a worker thread and never blocks
the event loop.
"""
import asyncio
import os
from functools import lru_cache

from app.core import settings


class StorageError(Exception):
    pass


class LocalStorage:
    name = "local"

    def __init__(self, root: str):
        self.root = os.path.realpath(root)

    def _path(self, key: str) -> str:
        path = os.path.realpath(os.path.join(self.root, key))
        if not path.startswith(self.root + os.sep):
            raise StorageError(f"Key escapes the storage root: {key!r}")
        return path

    def _put(self, key, data):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)  # atomic: readers never see half a file

    def _get(self, key):
        try:
            with open(self._path(key), "rb") as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(key) from None

    def _delete(self, key):
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    async def put(self, key: str, data: bytes, content_type: str):
        await asyncio.to_thread(self._put, key, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    async def delete(self, key: str):
        await asyncio.to_thread(self._delete, key)


class S3Storage:
    name = "s3"

    def __init__(self, bucket: str):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region_name=settings.S3_REGION or None,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY or None,
            config=Config(retries={"max_attempts": 4, "mode": "standard"},
                          s3={"addressing_style": settings.S3_ADDRESSING_STYLE}),
        )

    async def put(self, key: str, data: bytes, content_type: str):
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> bytes:
        def _get():
            try:
                return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except self.client.exceptions.NoSuchKey:
                raise FileNotFoundError(key) from None
        return await asyncio.to_thread(_get)

    async def delete(self, key: str):
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)


@lru_cache(maxsize=1)
def backend():
    if settings.vendor_mode("storage") == "live" and settings.S3_BUCKET:
        return S3Storage(settings.S3_BUCKET)
    return LocalStorage(settings.UPLOAD_DIR)


def reset():
    """Tests: pick the backend again after settings change."""
    backend.cache_clear()


def safe_name(name: str, limit: int = 60) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in (name or "file"))
    return keep.strip(".-")[:limit] or "file"
