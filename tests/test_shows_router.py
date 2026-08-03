import contextlib
import io
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from botocore.exceptions import ClientError, EndpointConnectionError, ResponseStreamingError
from fastapi.testclient import TestClient


class _AsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _install_transaction_mock(conn: AsyncMock) -> None:
    conn.transaction = MagicMock(return_value=_AsyncContext())


def test_list_stations_aggregates(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = [
        {"station": "rthk-radio1", "show_count": 3},
        {"station": "rthk-radio2", "show_count": 1},
    ]

    response = client.get("/api/shows/stations")

    assert response.status_code == 200
    assert response.json() == {
        "stations": [
            {"id": "rthk-radio1", "show_count": 3},
            {"id": "rthk-radio2", "show_count": 1},
        ]
    }


def test_list_stations_empty(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = []

    response = client.get("/api/shows/stations")

    assert response.status_code == 200
    assert response.json() == {"stations": []}


def test_list_stations_db_error_500(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.side_effect = OSError("connection refused")

    response = client.get("/api/shows/stations")

    assert response.status_code == 500
    assert "connection refused" in response.json()["detail"]


def test_list_shows_for_station(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = [
        {"id": 1, "name": "我得你都得", "episode_count": 5, "is_favorite": True},
        {"id": 2, "name": "音樂說", "episode_count": 0, "is_favorite": False},
    ]

    response = client.get("/api/shows/stations/rthk-radio1/shows")

    assert response.status_code == 200
    assert response.json() == {
        "shows": [
            {"id": 1, "name": "我得你都得", "episode_count": 5, "is_favorite": True},
            {"id": 2, "name": "音樂說", "episode_count": 0, "is_favorite": False},
        ]
    }
    args, _ = mock_conn.fetch.call_args
    assert args[1] == "rthk-radio1"


def test_list_shows_empty_station(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = []

    response = client.get("/api/shows/stations/rthk-radio1/shows")

    assert response.status_code == 200
    assert response.json() == {"shows": []}


def test_get_show_returns_detail(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = {
        "id": 7,
        "station": "rthk-radio1",
        "name": "我得你都得",
        "episode_count": 12,
    }

    response = client.get("/api/shows/7")

    assert response.status_code == 200
    assert response.json() == {
        "id": 7,
        "station": "rthk-radio1",
        "name": "我得你都得",
        "episode_count": 12,
    }


def test_get_show_404_when_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = None

    response = client.get("/api/shows/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "show not found"


def test_list_months_404_when_show_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = None

    response = client.get("/api/shows/999/months")

    assert response.status_code == 404
    assert response.json()["detail"] == "show not found"
    mock_conn.fetch.assert_not_awaited()


def test_list_months_returns_buckets(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = {
        "id": 7,
        "station": "rthk-radio1",
        "name": "我得你都得",
        "episode_count": 21,
    }
    mock_conn.fetch.return_value = [
        {"year": 2026, "month": 4, "episode_count": 12},
        {"year": 2026, "month": 3, "episode_count": 9},
    ]

    response = client.get("/api/shows/7/months")

    assert response.status_code == 200
    assert response.json() == {
        "show": {
            "id": 7,
            "station": "rthk-radio1",
            "name": "我得你都得",
            "episode_count": 21,
        },
        "months": [
            {"year": 2026, "month": 4, "episode_count": 12},
            {"year": 2026, "month": 3, "episode_count": 9},
        ],
    }
    fetch_args, _ = mock_conn.fetch.call_args
    assert fetch_args[1] == 7


def test_list_episodes_returns_rows(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = {
        "id": 7,
        "station": "rthk-radio1",
        "name": "我得你都得",
        "episode_count": 1,
    }
    mock_conn.fetch.return_value = [
        {
            "id": 11,
            "aired_on": date(2026, 3, 22),
            "time_slot": "0000_0200",
            "s3_key": "shows/rthk-radio1/2026/03/22/20260322_0000_0200_我得你都得.m4a",
            "chapters": [
                {"title": "Intro", "start": 0, "end": 60000},
                {"title": "Main", "start": 60000, "end": 7200000},
            ],
        },
    ]

    response = client.get("/api/shows/7/months/2026/3/episodes")

    assert response.status_code == 200
    body = response.json()
    assert body["show"]["id"] == 7
    assert body["show"]["station"] == "rthk-radio1"
    assert body["episodes"][0]["id"] == 11
    assert body["episodes"][0]["aired_on"] == "2026-03-22"
    assert body["episodes"][0]["time_slot"] == "0000_0200"
    assert body["episodes"][0]["chapters"] == [
        {"title": "Intro", "start": 0, "end": 60000},
        {"title": "Main", "start": 60000, "end": 7200000},
    ]

    args, _ = mock_conn.fetch.call_args
    assert args[1] == 7
    assert args[2] == date(2026, 3, 1)
    assert args[3] == date(2026, 4, 1)


def test_list_episodes_chapters_null(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = {
        "id": 1,
        "station": "rthk-radio1",
        "name": "x",
        "episode_count": 1,
    }
    mock_conn.fetch.return_value = [
        {
            "id": 12,
            "aired_on": date(2026, 3, 22),
            "time_slot": None,
            "s3_key": "k.m4a",
            "chapters": None,
        }
    ]

    response = client.get("/api/shows/1/months/2026/3/episodes")

    assert response.status_code == 200
    assert response.json()["episodes"][0]["chapters"] is None


def test_list_episodes_december_wraps_year(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = {
        "id": 1,
        "station": "rthk-radio1",
        "name": "x",
        "episode_count": 0,
    }
    mock_conn.fetch.return_value = []

    response = client.get("/api/shows/1/months/2026/12/episodes")

    assert response.status_code == 200
    args, _ = mock_conn.fetch.call_args
    assert args[2] == date(2026, 12, 1)
    assert args[3] == date(2027, 1, 1)


def test_list_episodes_invalid_month_422(client: TestClient, mock_conn: AsyncMock) -> None:
    del mock_conn
    response = client.get("/api/shows/1/months/2026/13/episodes")
    assert response.status_code == 422


def test_get_episode_returns_detail(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.side_effect = [
        {
            "id": 11,
            "aired_on": date(2026, 3, 22),
            "time_slot": "0000_0200",
            "s3_key": "shows/rthk-radio1/k.m4a",
            "chapters": [{"title": "Intro", "start": 0, "end": 60000}],
            "show_id": 7,
        },
        {
            "id": 7,
            "station": "rthk-radio1",
            "name": "我得你都得",
            "episode_count": 21,
        },
    ]

    response = client.get("/api/shows/episodes/11")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 11
    assert body["aired_on"] == "2026-03-22"
    assert body["chapters"] == [{"title": "Intro", "start": 0, "end": 60000}]
    assert body["show"] == {
        "id": 7,
        "station": "rthk-radio1",
        "name": "我得你都得",
        "episode_count": 21,
    }


def test_get_episode_404_when_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = None

    response = client.get("/api/shows/episodes/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "episode not found"


def test_audio_404_when_episode_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = None

    response = client.get("/api/shows/episodes/999/audio")

    assert response.status_code == 404
    assert response.json()["detail"] == "episode not found"


def test_audio_streams_full_object(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "shows/rthk-radio1/x.m4a"
    body = io.BytesIO(b"AUDIODATA" * 100)
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {
        "Body": body,
        "ContentLength": 900,
        "ContentType": "audio/mp4",
    }

    with patch("app.audio.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/audio")

    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "900"
    assert response.headers["content-type"] == "audio/mp4"
    assert response.content == b"AUDIODATA" * 100
    s3_mock.get_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="shows/rthk-radio1/x.m4a",
    )


def test_audio_ogg_returns_audio_ogg_content_type(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "shows/rthk-radio5/y.ogg"
    body = io.BytesIO(b"OGGDATA")
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {"Body": body, "ContentLength": 7}

    with patch("app.audio.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/12/audio")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/ogg"


def test_audio_passes_range_and_returns_206(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    body = io.BytesIO(b"PARTIAL")
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {
        "Body": body,
        "ContentLength": 7,
        "ContentRange": "bytes 0-6/900",
    }

    with patch("app.audio.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/audio", headers={"Range": "bytes=0-6"})

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-6/900"
    assert response.headers["content-length"] == "7"
    assert response.content == b"PARTIAL"

    _, kwargs = s3_mock.get_object.call_args
    assert kwargs["Range"] == "bytes=0-6"


def test_audio_range_header_without_content_range_returns_200(
    client: TestClient, mock_conn: AsyncMock
) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    body = io.BytesIO(b"FULL")
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {
        "Body": body,
        "ContentLength": 4,
    }

    with patch("app.audio.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/audio", headers={"Range": "bytes=0-6"})

    assert response.status_code == 200
    assert "content-range" not in response.headers
    assert response.content == b"FULL"


def test_audio_invalid_range_returns_416(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    s3_mock = MagicMock()
    s3_mock.get_object.side_effect = ClientError(
        {"Error": {"Code": "InvalidRange", "Message": "out of bounds"}},
        "GetObject",
    )

    with patch("app.audio.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/audio", headers={"Range": "bytes=99999-"})

    assert response.status_code == 416


def test_audio_other_client_error_502(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    s3_mock = MagicMock()
    s3_mock.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "boom"}},
        "GetObject",
    )

    with patch("app.audio.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/audio")

    assert response.status_code == 502
    assert "AccessDenied" in response.json()["detail"]


def test_audio_full_stream_keeps_cached_client(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {"Body": io.BytesIO(b"COMPLETE"), "ContentLength": 8}

    with (
        patch("app.audio.get_s3_client", return_value=s3_mock),
        patch("app.audio.reset_s3_client") as reset_mock,
    ):
        response = client.get("/api/shows/episodes/11/audio")

    assert response.status_code == 200
    assert response.content == b"COMPLETE"
    reset_mock.assert_not_called()


def test_audio_short_stream_resets_cached_client(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    s3_mock = MagicMock()
    # Upstream advertises 900 bytes but delivers 5: the pooled connection is dead.
    s3_mock.get_object.return_value = {"Body": io.BytesIO(b"SHORT"), "ContentLength": 900}

    with (
        patch("app.audio.get_s3_client", return_value=s3_mock),
        patch("app.audio.reset_s3_client") as reset_mock,
    ):
        client.get("/api/shows/episodes/11/audio")

    reset_mock.assert_called_once()


def test_audio_stream_error_resets_cached_client(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    body = MagicMock()
    body.read.side_effect = ResponseStreamingError(error="connection broken")
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {"Body": body, "ContentLength": 900}

    with (
        patch("app.audio.get_s3_client", return_value=s3_mock),
        patch("app.audio.reset_s3_client") as reset_mock,
        contextlib.suppress(ResponseStreamingError),
    ):
        client.get("/api/shows/episodes/11/audio")

    reset_mock.assert_called_once()
    body.close.assert_called_once()


def test_audio_connection_error_resets_cached_client(
    client: TestClient, mock_conn: AsyncMock
) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    s3_mock = MagicMock()
    s3_mock.get_object.side_effect = EndpointConnectionError(endpoint_url="https://s3.invalid")

    with (
        patch("app.audio.get_s3_client", return_value=s3_mock),
        patch("app.audio.reset_s3_client") as reset_mock,
    ):
        response = client.get("/api/shows/episodes/11/audio")

    assert response.status_code == 502
    reset_mock.assert_called_once()


def test_audio_url_returns_presigned_url(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "shows/rthk-radio1/x.m4a"
    s3_mock = MagicMock()
    s3_mock.generate_presigned_url.return_value = "https://s3.example/x.m4a?sig=abc"

    with patch("app.audio.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/audio_url")

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://s3.example/x.m4a?sig=abc",
        "expires_in": 3600,
    }
    s3_mock.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "test-bucket", "Key": "shows/rthk-radio1/x.m4a"},
        ExpiresIn=3600,
    )


def test_audio_url_404_when_episode_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = None

    response = client.get("/api/shows/episodes/999/audio_url")

    assert response.status_code == 404
    assert response.json()["detail"] == "episode not found"


def test_audio_url_presign_error_502(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "k.m4a"
    s3_mock = MagicMock()
    s3_mock.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "boom"}},
        "GetObject",
    )

    with patch("app.audio.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/audio_url")

    assert response.status_code == 502
    assert "AccessDenied" in response.json()["detail"]


def _summary_paginator(s3_mock: MagicMock, keys: list[str]) -> None:
    pager = MagicMock()
    pager.paginate.return_value = [{"Contents": [{"Key": k} for k in keys]}]
    s3_mock.get_paginator.return_value = pager


def test_chapter_summaries_returns_sorted_summaries(
    client: TestClient, mock_conn: AsyncMock
) -> None:
    mock_conn.fetchval.return_value = "shows/rthk-radio1/2026/03/22/abc.m4a"
    expected_prefix = "summaries/rthk-radio1/2026/03/22/abc_summary/"
    keys = [
        f"{expected_prefix}chapter_02.md",
        f"{expected_prefix}chapter_10.md",
        f"{expected_prefix}chapter_01.md",
    ]
    bodies = {
        f"{expected_prefix}chapter_01.md": b"first",
        f"{expected_prefix}chapter_02.md": b"second",
        f"{expected_prefix}chapter_10.md": b"tenth",
    }
    s3_mock = MagicMock()
    _summary_paginator(s3_mock, keys)
    s3_mock.get_object.side_effect = lambda *, Bucket, Key: {  # noqa: N803
        "Body": io.BytesIO(bodies[Key])
    }

    with patch("app.summaries.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/chapter_summaries")

    assert response.status_code == 200
    assert response.json() == {
        "summaries": [
            {"index": 1, "content": "first"},
            {"index": 2, "content": "second"},
            {"index": 10, "content": "tenth"},
        ]
    }
    pager_paginate = s3_mock.get_paginator.return_value.paginate
    _, kwargs = pager_paginate.call_args
    assert kwargs["Bucket"] == "test-bucket"
    assert kwargs["Prefix"] == expected_prefix


def test_chapter_summaries_empty_when_no_files(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "shows/rthk-radio1/x.m4a"
    s3_mock = MagicMock()
    _summary_paginator(s3_mock, [])

    with patch("app.summaries.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/chapter_summaries")

    assert response.status_code == 200
    assert response.json() == {"summaries": []}


def test_chapter_summaries_ignores_non_chapter_files(
    client: TestClient, mock_conn: AsyncMock
) -> None:
    mock_conn.fetchval.return_value = "shows/rthk-radio1/x.m4a"
    prefix = "summaries/rthk-radio1/x_summary/"
    keys = [
        f"{prefix}index.md",
        f"{prefix}chapter_aa.md",
        f"{prefix}README",
        f"{prefix}chapter_03.md",
    ]
    s3_mock = MagicMock()
    _summary_paginator(s3_mock, keys)
    s3_mock.get_object.return_value = {"Body": io.BytesIO(b"three")}

    with patch("app.summaries.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/chapter_summaries")

    assert response.status_code == 200
    assert response.json() == {"summaries": [{"index": 3, "content": "three"}]}


def test_chapter_summaries_404_when_episode_missing(
    client: TestClient, mock_conn: AsyncMock
) -> None:
    mock_conn.fetchval.return_value = None

    response = client.get("/api/shows/episodes/999/chapter_summaries")

    assert response.status_code == 404
    assert response.json()["detail"] == "episode not found"


def test_chapter_summaries_listing_error_502(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "shows/rthk-radio1/x.m4a"
    pager = MagicMock()
    pager.paginate.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "boom"}},
        "ListObjectsV2",
    )
    s3_mock = MagicMock()
    s3_mock.get_paginator.return_value = pager

    with patch("app.summaries.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/chapter_summaries")

    assert response.status_code == 502
    assert "AccessDenied" in response.json()["detail"]


def test_list_favorites_returns_rows(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = [
        {
            "id": 7,
            "station": "rthk-radio1",
            "name": "我得你都得",
            "episode_count": 21,
            "favorited_at": datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
            "latest_aired_on": date(2026, 5, 8),
        },
        {
            "id": 4,
            "station": "rthk-radio2",
            "name": "音樂說",
            "episode_count": 3,
            "favorited_at": datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
            "latest_aired_on": None,
        },
    ]

    response = client.get("/api/shows/favorites")

    assert response.status_code == 200
    body = response.json()
    assert [f["id"] for f in body["favorites"]] == [7, 4]
    assert body["favorites"][0]["station"] == "rthk-radio1"
    assert body["favorites"][0]["episode_count"] == 21
    assert body["favorites"][0]["favorited_at"].startswith("2026-05-09")
    assert body["favorites"][0]["latest_aired_on"] == "2026-05-08"
    assert body["favorites"][1]["latest_aired_on"] is None


def test_list_favorites_empty(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = []

    response = client.get("/api/shows/favorites")

    assert response.status_code == 200
    assert response.json() == {"favorites": []}


def test_add_favorite_inserts_when_show_exists(client: TestClient, mock_conn: AsyncMock) -> None:
    _install_transaction_mock(mock_conn)
    mock_conn.fetchval.return_value = 1

    response = client.post("/api/shows/7/favorite")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_conn.execute.assert_awaited_once()
    execute_args, _ = mock_conn.execute.await_args
    assert "INSERT INTO favorite_shows" in execute_args[0]
    assert execute_args[1] == 7


def test_add_favorite_404_when_show_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    _install_transaction_mock(mock_conn)
    mock_conn.fetchval.return_value = None

    response = client.post("/api/shows/999/favorite")

    assert response.status_code == 404
    assert response.json()["detail"] == "show not found"
    mock_conn.execute.assert_not_awaited()


def test_add_favorite_idempotent_second_call(client: TestClient, mock_conn: AsyncMock) -> None:
    _install_transaction_mock(mock_conn)
    mock_conn.fetchval.return_value = 1

    first = client.post("/api/shows/7/favorite")
    second = client.post("/api/shows/7/favorite")

    assert first.status_code == 200
    assert second.status_code == 200
    assert mock_conn.execute.await_count == 2


def test_remove_favorite_deletes(client: TestClient, mock_conn: AsyncMock) -> None:
    response = client.delete("/api/shows/7/favorite")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    execute_args, _ = mock_conn.execute.await_args
    assert "DELETE FROM favorite_shows" in execute_args[0]
    assert execute_args[1] == 7


def test_remove_favorite_idempotent_when_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    response = client.delete("/api/shows/999/favorite")

    assert response.status_code == 200


def test_recent_episodes_returns_rows_with_progress(
    client: TestClient, mock_conn: AsyncMock
) -> None:
    mock_conn.fetchrow.return_value = {
        "id": 7,
        "station": "rthk-radio1",
        "name": "我得你都得",
        "episode_count": 30,
    }
    mock_conn.fetch.return_value = [
        {
            "id": 12,
            "aired_on": date(2026, 5, 8),
            "time_slot": "0000_0200",
            "show_id": 7,
            "show_name": "我得你都得",
            "station": "rthk-radio1",
            "position_ms": 600_000,
            "duration_ms": 7_200_000,
            "completed": False,
            "last_played_at": datetime(2026, 5, 8, 9, 0, tzinfo=UTC),
        },
        {
            "id": 11,
            "aired_on": date(2026, 5, 7),
            "time_slot": "0000_0200",
            "show_id": 7,
            "show_name": "我得你都得",
            "station": "rthk-radio1",
            "position_ms": 0,
            "duration_ms": None,
            "completed": False,
            "last_played_at": None,
        },
    ]

    response = client.get("/api/shows/7/recent-episodes")

    assert response.status_code == 200
    body = response.json()
    assert body["show"]["id"] == 7
    assert [e["id"] for e in body["episodes"]] == [12, 11]
    assert body["episodes"][0]["position_ms"] == 600_000
    assert body["episodes"][0]["duration_ms"] == 7_200_000
    assert body["episodes"][0]["completed"] is False
    assert body["episodes"][1]["duration_ms"] is None
    assert body["episodes"][1]["last_played_at"] is None
    fetch_args, _ = mock_conn.fetch.call_args
    assert fetch_args[1] == 7
    assert fetch_args[2] == 20


def test_recent_episodes_404_when_show_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = None

    response = client.get("/api/shows/999/recent-episodes")

    assert response.status_code == 404
    assert response.json()["detail"] == "show not found"
    mock_conn.fetch.assert_not_awaited()


def test_recent_episodes_honours_custom_limit(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = {
        "id": 7,
        "station": "rthk-radio1",
        "name": "x",
        "episode_count": 0,
    }
    mock_conn.fetch.return_value = []

    response = client.get("/api/shows/7/recent-episodes?limit=5")

    assert response.status_code == 200
    fetch_args, _ = mock_conn.fetch.call_args
    assert fetch_args[2] == 5


def test_recent_episodes_rejects_oversized_limit(client: TestClient, mock_conn: AsyncMock) -> None:
    del mock_conn
    response = client.get("/api/shows/7/recent-episodes?limit=51")
    assert response.status_code == 422


def test_recent_episodes_db_error_500(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchrow.return_value = {
        "id": 7,
        "station": "rthk-radio1",
        "name": "x",
        "episode_count": 0,
    }
    mock_conn.fetch.side_effect = OSError("connection refused")

    response = client.get("/api/shows/7/recent-episodes")

    assert response.status_code == 500
    assert "connection refused" in response.json()["detail"]
