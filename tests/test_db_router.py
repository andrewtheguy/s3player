from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.db import get_conn


@pytest.fixture
def mock_conn() -> AsyncIterator[AsyncMock]:
    conn = AsyncMock()

    async def fake_get_conn() -> AsyncIterator[AsyncMock]:
        yield conn

    app.dependency_overrides[get_conn] = fake_get_conn
    yield conn
    app.dependency_overrides.pop(get_conn, None)


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
