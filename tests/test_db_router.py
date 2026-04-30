from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def test_db_health_ok(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = 1

    response = client.get("/api/db/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "result": 1}
    mock_conn.fetchval.assert_awaited_once_with("SELECT 1")


def test_db_health_503_on_connection_error(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.side_effect = OSError("connection refused")

    response = client.get("/api/db/health")

    assert response.status_code == 503
    assert "connection refused" in response.json()["detail"]


def test_db_health_503_when_query_returns_unexpected(
    client: TestClient, mock_conn: AsyncMock
) -> None:
    mock_conn.fetchval.return_value = None

    response = client.get("/api/db/health")

    assert response.status_code == 503
    assert "sanity check failed" in response.json()["detail"]
