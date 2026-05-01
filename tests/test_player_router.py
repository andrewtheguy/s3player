from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


class AsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def install_transaction_mock(conn: AsyncMock) -> None:
    conn.transaction = MagicMock(return_value=AsyncContext())


def test_claim_is_the_displacement_operation(
    client: TestClient,
    mock_conn: AsyncMock,
) -> None:
    mock_conn.fetchval.return_value = 1

    with patch("app.routers.player.secrets.token_urlsafe", return_value="new-token"):
        response = client.post("/api/player/session/claim", json={"episode_id": 1})

    assert response.status_code == 200
    assert response.json() == {"session_token": "new-token", "episode_id": 1}
    execute_args, _ = mock_conn.execute.await_args
    assert execute_args[1:] == ("new-token", 1)


def test_validate_requires_session_token(client: TestClient, mock_conn: AsyncMock) -> None:
    response = client.post("/api/player/session/validate", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "missing session token"
    mock_conn.fetchval.assert_not_awaited()


def test_validate_rejects_displaced_session(client: TestClient, mock_conn: AsyncMock) -> None:
    mock_conn.fetchval.return_value = None

    response = client.post(
        "/api/player/session/validate",
        json={},
        headers={"X-Player-Session": "old-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "session displaced"


def test_progress_requires_session_token(client: TestClient, mock_conn: AsyncMock) -> None:
    response = client.post(
        "/api/player/episodes/1/progress",
        json={"position_ms": 1000, "duration_ms": 2000},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "missing session token"
    mock_conn.fetchval.assert_not_awaited()
    mock_conn.execute.assert_not_awaited()


def test_progress_rejects_displaced_session_before_state_write(
    client: TestClient,
    mock_conn: AsyncMock,
) -> None:
    install_transaction_mock(mock_conn)
    mock_conn.fetchval.return_value = None

    response = client.post(
        "/api/player/episodes/1/progress",
        json={"position_ms": 1000, "duration_ms": 2000},
        headers={"X-Player-Session": "old-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "session displaced"
    assert mock_conn.fetchval.await_count == 1
    mock_conn.execute.assert_not_awaited()


def test_progress_saves_only_after_active_session_guard(
    client: TestClient,
    mock_conn: AsyncMock,
) -> None:
    install_transaction_mock(mock_conn)
    mock_conn.fetchval.side_effect = [1, 1, 1]

    response = client.post(
        "/api/player/episodes/1/progress",
        json={"position_ms": 1000, "duration_ms": 2000},
        headers={"X-Player-Session": "active-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert mock_conn.fetchval.await_count == 3
    mock_conn.execute.assert_awaited_once()


def test_complete_requires_session_token(client: TestClient, mock_conn: AsyncMock) -> None:
    response = client.post("/api/player/episodes/1/complete")

    assert response.status_code == 401
    assert response.json()["detail"] == "missing session token"
    mock_conn.fetchval.assert_not_awaited()
    mock_conn.execute.assert_not_awaited()


def test_complete_rejects_displaced_session_before_state_write(
    client: TestClient,
    mock_conn: AsyncMock,
) -> None:
    install_transaction_mock(mock_conn)
    mock_conn.fetchval.return_value = None

    response = client.post(
        "/api/player/episodes/1/complete",
        headers={"X-Player-Session": "old-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "session displaced"
    assert mock_conn.fetchval.await_count == 1
    mock_conn.execute.assert_not_awaited()


def test_complete_writes_only_after_active_session_guard(
    client: TestClient,
    mock_conn: AsyncMock,
) -> None:
    install_transaction_mock(mock_conn)
    mock_conn.fetchval.side_effect = [1, 1, 1, 2000]

    response = client.post(
        "/api/player/episodes/1/complete",
        headers={"X-Player-Session": "active-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert mock_conn.fetchval.await_count == 4
    mock_conn.execute.assert_awaited_once()
