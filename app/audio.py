import asyncio
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.s3_client import get_s3_client, reset_s3_client

logger = logging.getLogger(__name__)

AUDIO_CHUNK_SIZE = 64 * 1024
AUDIO_URL_EXPIRES_IN = 3600
_AUDIO_MEDIA_TYPES = {".m4a": "audio/mp4", ".ogg": "audio/ogg"}
_DEFAULT_AUDIO_MEDIA_TYPE = "application/octet-stream"


def _media_type_for_key(s3_key: str) -> str:
    for ext, media_type in _AUDIO_MEDIA_TYPES.items():
        if s3_key.endswith(ext):
            return media_type
    return _DEFAULT_AUDIO_MEDIA_TYPE


class AudioRangeNotSatisfiable(Exception):
    detail = "range not satisfiable"


class AudioNotFound(Exception):
    detail = "audio not found"


class AudioUpstreamError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class PresignedAudioUrl:
    url: str
    expires_in: int


@dataclass(frozen=True)
class AudioStream:
    body: Iterator[bytes]
    status_code: int
    headers: dict[str, str]
    media_type: str


def _stream_body(body: Any, s3_key: str, expected_length: int | None) -> Iterator[bytes]:
    """Yield the S3 body in chunks, healing the client pool if upstream fails.

    A stream that raises or ends short of `Content-Length` means the connection
    broke mid-response. uvicorn aborts such a response without finishing it,
    which cloudflared reports as `unexpected EOF` and Cloudflare turns into a
    520 -- and the dead connection stays in the shared client's pool, so every
    later request is truncated the same way until the process restarts. Dropping
    the cached client here keeps the damage to the one request that hit it.

    A client that disconnects mid-playback (seeking) closes this generator and
    raises `GeneratorExit`, which is deliberately not treated as upstream
    breakage -- it is routine and the connection is still fine.
    """
    sent = 0
    try:
        while True:
            chunk = body.read(AUDIO_CHUNK_SIZE)
            if not chunk:
                break
            sent += len(chunk)
            yield chunk
    except Exception:
        logger.warning("audio stream for %s failed after %d bytes", s3_key, sent, exc_info=True)
        reset_s3_client()
        raise
    else:
        if expected_length is not None and sent < expected_length:
            logger.warning(
                "audio stream for %s ended early: sent %d of %d bytes",
                s3_key,
                sent,
                expected_length,
            )
            reset_s3_client()
    finally:
        body.close()


async def presign_audio_url(s3_key: str) -> PresignedAudioUrl:
    settings = get_settings()
    client = get_s3_client()
    try:
        url = await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": s3_key},
            ExpiresIn=AUDIO_URL_EXPIRES_IN,
        )
    except ClientError as e:
        raise AudioUpstreamError(str(e)) from e
    return PresignedAudioUrl(url=url, expires_in=AUDIO_URL_EXPIRES_IN)


async def open_audio_stream(s3_key: str, range_header: str | None) -> AudioStream:
    settings = get_settings()
    client = get_s3_client()
    get_kwargs: dict[str, Any] = {"Bucket": settings.s3_bucket, "Key": s3_key}
    if range_header:
        get_kwargs["Range"] = range_header

    try:
        s3_response = await asyncio.to_thread(client.get_object, **get_kwargs)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "") if e.response else ""
        if code in {"InvalidRange", "InvalidArgument"}:
            raise AudioRangeNotSatisfiable from e
        if code in {"NoSuchKey", "404"}:
            raise AudioNotFound from e
        raise AudioUpstreamError(str(e)) from e
    except BotoCoreError as e:
        # Connection-level failures (closed/refused/timed out) mean the pooled
        # connection is unusable; rebuild the client so the retry can succeed.
        logger.warning("audio fetch for %s failed to connect", s3_key, exc_info=True)
        reset_s3_client()
        raise AudioUpstreamError(str(e)) from e

    content_length: int | None = s3_response.get("ContentLength")
    headers: dict[str, str] = {"Accept-Ranges": "bytes"}
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    if "ContentRange" in s3_response:
        headers["Content-Range"] = s3_response["ContentRange"]

    return AudioStream(
        body=_stream_body(s3_response["Body"], s3_key, content_length),
        status_code=206 if "ContentRange" in s3_response else 200,
        headers=headers,
        media_type=_media_type_for_key(s3_key),
    )
