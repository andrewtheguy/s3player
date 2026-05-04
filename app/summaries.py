import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from app.config import get_settings
from app.s3_client import get_s3_client

logger = logging.getLogger(__name__)

_AUDIO_PREFIX = "shows/"
_SUMMARY_PREFIX = "summaries/"
_AUDIO_SUFFIX = ".m4a"
_SUMMARY_DIR_SUFFIX = "_summary/"
_CHAPTER_FILE_RE = re.compile(r"^chapter_(\d+)\.md$")


class SummaryUpstreamError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class ChapterSummary:
    """A single per-chapter markdown summary.

    `index` is the integer parsed from the source file name `chapter_NN.md`.
    With the canonical naming the first chapter is `chapter_01.md`, so
    indices are **1-based**.
    """

    index: int
    content: str


def derive_summary_prefix(audio_s3_key: str) -> str | None:
    """Map an episode audio S3 key to its parallel summaries directory prefix.

    Returns `summaries/<...>/<basename>_summary/` when the input starts with
    `shows/` and ends with `.m4a`; otherwise returns `None`.
    """
    if not audio_s3_key.startswith(_AUDIO_PREFIX):
        return None
    if not audio_s3_key.endswith(_AUDIO_SUFFIX):
        return None
    rest = audio_s3_key[len(_AUDIO_PREFIX) : -len(_AUDIO_SUFFIX)]
    return f"{_SUMMARY_PREFIX}{rest}{_SUMMARY_DIR_SUFFIX}"


def _list_keys(client: Any, bucket: str, prefix: str) -> list[str]:
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            keys.append(item["Key"])
    return keys


def _fetch_text(client: Any, bucket: str, key: str) -> str:
    obj = client.get_object(Bucket=bucket, Key=key)
    body_stream = obj["Body"]
    try:
        body = body_stream.read()
    finally:
        body_stream.close()
    return body.decode("utf-8")


async def list_chapter_summaries(audio_s3_key: str) -> list[ChapterSummary]:
    """List and fetch every `chapter_NN.md` summary for the given audio key.

    Returns an empty list if the audio key has no derivable summary prefix or
    if the prefix has no chapter files. Skips individual files whose body
    fetch fails so one bad object doesn't break the panel; raises
    `SummaryUpstreamError` if the listing call itself fails.
    """
    prefix = derive_summary_prefix(audio_s3_key)
    if prefix is None:
        return []

    settings = get_settings()
    client = get_s3_client()

    try:
        keys = await asyncio.to_thread(_list_keys, client, settings.s3_bucket, prefix)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "") if e.response else ""
        if code in {"NoSuchKey", "NoSuchBucket", "404"}:
            return []
        raise SummaryUpstreamError(str(e)) from e

    indexed: list[tuple[int, str]] = []
    for key in keys:
        basename = key.rsplit("/", 1)[-1]
        m = _CHAPTER_FILE_RE.match(basename)
        if m is None:
            continue
        indexed.append((int(m.group(1)), key))
    indexed.sort(key=lambda pair: pair[0])

    async def fetch(index: int, key: str) -> ChapterSummary | None:
        try:
            content = await asyncio.to_thread(_fetch_text, client, settings.s3_bucket, key)
        except ClientError as e:
            logger.warning("chapter summary fetch failed for %s: %s", key, e)
            return None
        except UnicodeDecodeError as e:
            logger.warning("chapter summary not utf-8 for %s: %s", key, e)
            return None
        return ChapterSummary(index=index, content=content)

    results = await asyncio.gather(*(fetch(i, k) for i, k in indexed))
    return [r for r in results if r is not None]
