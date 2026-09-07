"""Object storage for raw ingested files (PDFs, DOCX, CSV, ...), backed by
MinIO -- an S3-compatible store, per plan section 2's ingestion pipeline.
Mirrors `database/core.py`'s shape: one cached client + a dependency-style
getter, so callers never construct a Minio() themselves.
"""
from functools import lru_cache
from io import BytesIO
from minio import Minio
from minio.error import S3Error
from ..config import get_settings


@lru_cache
def get_minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket(client: Minio | None = None) -> str:
    """Creates the configured bucket if it doesn't exist yet. Returns the
    bucket name. Safe to call repeatedly (idempotent) -- e.g. once at API
    startup and once at worker startup, since either process could be the
    first to touch a fresh MinIO instance.
    """
    settings = get_settings()
    client = client or get_minio_client()
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    return bucket


def upload_bytes(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Uploads raw bytes under `object_key` in the configured bucket.
    Returns the object_key so callers can persist it on the owning row
    (e.g. Document.storage_key) for later retrieval.
    """
    client = get_minio_client()
    bucket = ensure_bucket(client)
    client.put_object(
        bucket,
        object_key,
        data=BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return object_key


def download_bytes(object_key: str) -> bytes:
    client = get_minio_client()
    bucket = ensure_bucket(client)
    response = client.get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def object_exists(object_key: str) -> bool:
    client = get_minio_client()
    bucket = ensure_bucket(client)
    try:
        client.stat_object(bucket, object_key)
        return True
    except S3Error as e:
        if e.code == "NoSuchKey":
            return False
        raise
