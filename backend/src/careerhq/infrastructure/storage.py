"""S3-compatible object storage.

MinIO locally, any S3-compatible provider in production. Holds exported resume
PDFs and uploaded files; nothing in this slice writes to it yet.

boto3 is synchronous, so calls are pushed to a worker thread rather than
blocking the event loop.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from careerhq.config import get_settings

# boto3 ships no type stubs and the third-party ones add a heavy dependency for
# a client we call in three places. Any is the honest annotation here.
S3Client = Any


@lru_cache
def get_s3_client() -> S3Client:
    """Return the process-wide S3 client."""
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            connect_timeout=2,
            read_timeout=2,
            retries={"max_attempts": 1},
        ),
    )


async def head_bucket() -> None:
    """Raise if the configured bucket is unreachable or does not exist."""
    settings = get_settings()
    await asyncio.to_thread(get_s3_client().head_bucket, Bucket=settings.s3_bucket)


async def ensure_bucket() -> None:
    """Create the configured bucket when it is absent. Safe to call repeatedly."""
    settings = get_settings()
    client = get_s3_client()

    def _create() -> None:
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
        except client.exceptions.ClientError:
            client.create_bucket(Bucket=settings.s3_bucket)

    await asyncio.to_thread(_create)
