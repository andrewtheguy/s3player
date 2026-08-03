from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from app.config import get_settings


@lru_cache
def get_s3_client() -> Any:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 3, "mode": "standard"},
            response_checksum_validation="when_required",
        ),
    )


def reset_s3_client() -> None:
    """Drop the cached client so the next caller builds a fresh connection pool.

    A connection that dies mid-response can be left behind in the shared client's
    pool; every later `get_object` then returns valid headers with an empty body.
    Rebuilding the client is the only way back out of that state.
    """
    get_s3_client.cache_clear()
