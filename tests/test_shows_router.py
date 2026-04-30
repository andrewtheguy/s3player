from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient


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
        {"id": 1, "name": "我得你都得", "episode_count": 5},
        {"id": 2, "name": "音樂說", "episode_count": 0},
    ]

    response = client.get("/api/shows/stations/rthk-radio1/shows")

    assert response.status_code == 200
    assert response.json() == {
        "shows": [
            {"id": 1, "name": "我得你都得", "episode_count": 5},
            {"id": 2, "name": "音樂說", "episode_count": 0},
        ]
    }
    args, _ = mock_conn.fetch.call_args
    assert args[1] == "rthk-radio1"


def test_list_shows_empty_station(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = []

    response = client.get("/api/shows/stations/rthk-radio1/shows")

    assert response.status_code == 200
    assert response.json() == {"shows": []}


def test_list_months_404_when_show_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = None

    response = client.get("/api/shows/stations/rthk-radio1/shows/nope/months")

    assert response.status_code == 404
    assert response.json()["detail"] == "show not found"
    mock_conn.fetch.assert_not_awaited()


def test_list_months_returns_buckets(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = 7
    mock_conn.fetch.return_value = [
        {"year": 2026, "month": 4, "episode_count": 12},
        {"year": 2026, "month": 3, "episode_count": 9},
    ]

    response = client.get("/api/shows/stations/rthk-radio1/shows/我得你都得/months")

    assert response.status_code == 200
    assert response.json() == {
        "months": [
            {"year": 2026, "month": 4, "episode_count": 12},
            {"year": 2026, "month": 3, "episode_count": 9},
        ]
    }
    fetch_args, _ = mock_conn.fetch.call_args
    assert fetch_args[1] == 7


def test_list_episodes_returns_rows(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = [
        {
            "id": 11,
            "aired_on": date(2026, 3, 22),
            "time_slot": "0000_0200",
            "s3_key": "shows/rthk/radio1/2026/03/22/20260322_0000_0200_我得你都得.m4a",
        },
    ]

    response = client.get("/api/shows/stations/rthk-radio1/shows/我得你都得/months/2026/3/episodes")

    assert response.status_code == 200
    body = response.json()
    assert body["episodes"][0]["id"] == 11
    assert body["episodes"][0]["aired_on"] == "2026-03-22"
    assert body["episodes"][0]["time_slot"] == "0000_0200"

    args, _ = mock_conn.fetch.call_args
    assert args[1] == "rthk-radio1"
    assert args[2] == "我得你都得"
    assert args[3] == date(2026, 3, 1)
    assert args[4] == date(2026, 4, 1)


def test_list_episodes_december_wraps_year(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetch.return_value = []

    response = client.get("/api/shows/stations/rthk-radio1/shows/x/months/2026/12/episodes")

    assert response.status_code == 200
    args, _ = mock_conn.fetch.call_args
    assert args[3] == date(2026, 12, 1)
    assert args[4] == date(2027, 1, 1)


def test_list_episodes_invalid_month_422(client: TestClient, mock_conn: AsyncMock) -> None:
    del mock_conn
    response = client.get("/api/shows/stations/rthk-radio1/shows/x/months/2026/13/episodes")
    assert response.status_code == 422


def test_episode_url_404_when_missing(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = None

    response = client.get("/api/shows/episodes/999/url")

    assert response.status_code == 404
    assert response.json()["detail"] == "episode not found"


def test_episode_url_returns_presigned(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "shows/rthk/radio1/2026/03/22/20260322_0000_0200_x.m4a"
    s3_mock = MagicMock()
    s3_mock.generate_presigned_url.return_value = "https://signed.example/file?sig=abc"

    with patch("app.routers.shows.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/url")

    assert response.status_code == 200
    body = response.json()
    assert body == {"url": "https://signed.example/file?sig=abc", "expires_in": 86400}

    s3_mock.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": "test-bucket",
            "Key": "shows/rthk/radio1/2026/03/22/20260322_0000_0200_x.m4a",
        },
        ExpiresIn=86400,
    )


def test_episode_url_502_on_client_error(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = "some/key.m4a"
    s3_mock = MagicMock()
    s3_mock.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "boom"}},
        "GetObject",
    )

    with patch("app.routers.shows.get_s3_client", return_value=s3_mock):
        response = client.get("/api/shows/episodes/11/url")

    assert response.status_code == 502
    assert "AccessDenied" in response.json()["detail"]
