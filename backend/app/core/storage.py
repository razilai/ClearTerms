"""Object storage wrapper (S3-compatible — MinIO in dev, real S3 in prod).

Leaf layer: imports only from app.core.config, never from db/services. All I/O
runs through boto3 in asyncio.to_thread so the event loop stays unblocked.

Key scheme: attachments/{attachment_id}/{variant}.{ext}
  variant = original | display | thumb
"""

import asyncio
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from app.core.config import settings

# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def _make_client(endpoint_url: str) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


# Internal client for put/get/delete (backend→MinIO container)
_client_internal: Any = None
# Client configured with the public endpoint for presigning (URLs the browser follows)
_client_public: Any = None


def _get_internal() -> Any:
    global _client_internal
    if _client_internal is None:
        _client_internal = _make_client(settings.s3_endpoint_url)
    return _client_internal


def _get_public() -> Any:
    global _client_public
    if _client_public is None:
        _client_public = _make_client(settings.s3_public_endpoint_url)
    return _client_public


# Allows tests to swap the backing store without touching boto3
_override: dict[str, bytes] | None = None


def set_fake_store(store: dict[str, bytes] | None) -> None:
    """Tests call this to activate the in-memory fake."""
    global _override
    _override = store


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def put_object(key: str, data: bytes, content_type: str) -> None:
    if _override is not None:
        _override[key] = data
        return
    client = _get_internal()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )


async def get_object(key: str) -> bytes:
    if _override is not None:
        return _override[key]
    client = _get_internal()
    response = await asyncio.to_thread(
        client.get_object,
        Bucket=settings.s3_bucket,
        Key=key,
    )
    return await asyncio.to_thread(response["Body"].read)


async def delete_objects(keys: list[str]) -> None:
    if not keys:
        return
    if _override is not None:
        for k in keys:
            _override.pop(k, None)
        return
    client = _get_internal()
    await asyncio.to_thread(
        client.delete_objects,
        Bucket=settings.s3_bucket,
        Delete={"Objects": [{"Key": k} for k in keys]},
    )


def presigned_get_url(key: str, ttl: int | None = None) -> str:
    """Returns a URL the browser can follow (uses public endpoint)."""
    if _override is not None:
        # In tests presigned URLs are not followed; return a stable placeholder
        return f"http://fake-storage/{key}"
    client = _get_public()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=ttl if ttl is not None else settings.media_url_ttl_seconds,
    )
