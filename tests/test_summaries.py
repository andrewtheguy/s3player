import asyncio
import io
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app import summaries


def test_derive_summary_prefix_beautiful_sunday() -> None:
    audio_key = (
        "shows/rthk-radio1/2026/03/22/20260322_0600_0700_Beautiful_Sunday_(與第二台聯播).m4a"
    )
    assert summaries.derive_summary_prefix(audio_key) == (
        "summaries/rthk-radio1/2026/03/22/"
        "20260322_0600_0700_Beautiful_Sunday_(與第二台聯播)_summary/"
    )


def test_derive_summary_prefix_simple() -> None:
    assert summaries.derive_summary_prefix("shows/x/y.m4a") == "summaries/x/y_summary/"


def test_derive_summary_prefix_rejects_non_shows_prefix() -> None:
    assert summaries.derive_summary_prefix("other/x.m4a") is None


def test_derive_summary_prefix_rejects_non_m4a_suffix() -> None:
    assert summaries.derive_summary_prefix("shows/x.mp3") is None


def _make_paginator(pages: list[list[str]]) -> MagicMock:
    pager = MagicMock()
    pager.paginate.return_value = [{"Contents": [{"Key": k} for k in page]} for page in pages]
    client = MagicMock()
    client.get_paginator.return_value = pager
    return client


def test_list_chapter_summaries_sorts_by_index_and_skips_non_chapter() -> None:
    prefix = "summaries/rthk-radio1/2026/03/22/x_summary/"
    keys = [
        f"{prefix}chapter_02.md",
        f"{prefix}chapter_10.md",
        f"{prefix}chapter_01.md",
        f"{prefix}index.md",
        f"{prefix}chapter_aa.md",
        f"{prefix}README",
    ]
    client = _make_paginator([keys])

    bodies = {
        f"{prefix}chapter_01.md": b"first",
        f"{prefix}chapter_02.md": b"second",
        f"{prefix}chapter_10.md": b"tenth",
    }

    def get_object(*, Bucket: str, Key: str) -> dict[str, object]:  # noqa: N803
        del Bucket
        return {"Body": io.BytesIO(bodies[Key])}

    client.get_object.side_effect = get_object

    with patch("app.summaries.get_s3_client", return_value=client):
        result = asyncio.run(summaries.list_chapter_summaries("shows/rthk-radio1/2026/03/22/x.m4a"))

    assert [(r.index, r.content) for r in result] == [
        (1, "first"),
        (2, "second"),
        (10, "tenth"),
    ]


def test_list_chapter_summaries_empty_when_no_keys() -> None:
    client = _make_paginator([[]])
    with patch("app.summaries.get_s3_client", return_value=client):
        result = asyncio.run(summaries.list_chapter_summaries("shows/r/y.m4a"))
    assert result == []


def test_list_chapter_summaries_returns_empty_for_unmappable_key() -> None:
    result = asyncio.run(summaries.list_chapter_summaries("notshows/x.mp3"))
    assert result == []


def test_list_chapter_summaries_listing_no_such_bucket_returns_empty() -> None:
    pager = MagicMock()
    pager.paginate.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": "missing"}},
        "ListObjectsV2",
    )
    client = MagicMock()
    client.get_paginator.return_value = pager

    with patch("app.summaries.get_s3_client", return_value=client):
        result = asyncio.run(summaries.list_chapter_summaries("shows/r/y.m4a"))
    assert result == []


def test_list_chapter_summaries_listing_other_error_raises() -> None:
    pager = MagicMock()
    pager.paginate.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "boom"}},
        "ListObjectsV2",
    )
    client = MagicMock()
    client.get_paginator.return_value = pager

    with (
        patch("app.summaries.get_s3_client", return_value=client),
        pytest.raises(summaries.SummaryUpstreamError) as excinfo,
    ):
        asyncio.run(summaries.list_chapter_summaries("shows/r/y.m4a"))

    assert "AccessDenied" in str(excinfo.value)


def test_list_chapter_summaries_skips_individual_fetch_failure() -> None:
    prefix = "summaries/r/y_summary/"
    client = _make_paginator([[f"{prefix}chapter_01.md", f"{prefix}chapter_02.md"]])

    def get_object(*, Bucket: str, Key: str) -> dict[str, object]:  # noqa: N803
        del Bucket
        if Key.endswith("chapter_01.md"):
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "boom"}},
                "GetObject",
            )
        return {"Body": io.BytesIO(b"two")}

    client.get_object.side_effect = get_object

    with patch("app.summaries.get_s3_client", return_value=client):
        result = asyncio.run(summaries.list_chapter_summaries("shows/r/y.m4a"))

    assert [(r.index, r.content) for r in result] == [(2, "two")]
