import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from app.config import get_settings
from app.s3_client import get_s3_client

AUDIO_CHUNK_SIZE = 64 * 1024
AUDIO_CONTENT_TYPE = "audio/mp4"
AUDIO_URL_EXPIRES_IN = 3600


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


def _stream_body(body: Any) -> Iterator[bytes]:
    try:
        while True:
            chunk = body.read(AUDIO_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
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

    headers: dict[str, str] = {"Accept-Ranges": "bytes"}
    if "ContentLength" in s3_response:
        headers["Content-Length"] = str(s3_response["ContentLength"])
    if "ContentRange" in s3_response:
        headers["Content-Range"] = s3_response["ContentRange"]

    return AudioStream(
        body=_stream_body(s3_response["Body"]),
        status_code=206 if range_header else 200,
        headers=headers,
        media_type=AUDIO_CONTENT_TYPE,
    )
