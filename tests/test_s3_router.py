from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient


def test_directories_have_no_trailing_slash(client: TestClient) -> None:
    s3_mock = MagicMock()
    s3_mock.list_objects_v2.return_value = {
        "CommonPrefixes": [
            {"Prefix": "shows/"},
            {"Prefix": "metadata/"},
            {"Prefix": "transcripts/"},
        ],
        "Contents": [],
    }
    with patch("app.routers.s3.get_s3_client", return_value=s3_mock):
        response = client.get("/api/s3/list")

    assert response.status_code == 200
    body = response.json()
    assert body["directories"] == ["shows", "metadata", "transcripts"]
    assert body["files"] == []


def test_files_use_name_size_last_modified(client: TestClient) -> None:
    s3_mock = MagicMock()
    s3_mock.list_objects_v2.return_value = {
        "CommonPrefixes": [],
        "Contents": [
            {
                "Key": "intro.mp3",
                "Size": 4096,
                "LastModified": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            },
            {
                "Key": "outro.mp3",
                "Size": 8192,
                "LastModified": datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC),
            },
        ],
    }
    with patch("app.routers.s3.get_s3_client", return_value=s3_mock):
        response = client.get("/api/s3/list")

    assert response.status_code == 200
    files = response.json()["files"]
    assert len(files) == 2
    assert files[0]["name"] == "intro.mp3"
    assert files[0]["size"] == 4096
    assert files[0]["last_modified"].startswith("2026-01-02T03:04:05")
    assert files[1]["name"] == "outro.mp3"


def test_empty_bucket(client: TestClient) -> None:
    s3_mock = MagicMock()
    s3_mock.list_objects_v2.return_value = {}
    with patch("app.routers.s3.get_s3_client", return_value=s3_mock):
        response = client.get("/api/s3/list")

    assert response.status_code == 200
    assert response.json() == {"directories": [], "files": []}


def test_uses_delimiter_and_configured_bucket(client: TestClient) -> None:
    s3_mock = MagicMock()
    s3_mock.list_objects_v2.return_value = {}
    with patch("app.routers.s3.get_s3_client", return_value=s3_mock):
        client.get("/api/s3/list")

    s3_mock.list_objects_v2.assert_called_once_with(
        Bucket="test-bucket",
        Delimiter="/",
    )


def test_client_error_returns_502(client: TestClient) -> None:
    s3_mock = MagicMock()
    s3_mock.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "boom"}},
        "ListObjectsV2",
    )
    with patch("app.routers.s3.get_s3_client", return_value=s3_mock):
        response = client.get("/api/s3/list")

    assert response.status_code == 502
    assert "AccessDenied" in response.json()["detail"]
