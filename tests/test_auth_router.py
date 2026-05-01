from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, expected_token
from app.config import get_settings


def test_login_sets_browser_session_cookie(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"password": "test-password", "next": "/stations"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    set_cookie = response.headers["set-cookie"]
    assert f"{COOKIE_NAME}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Max-Age" not in set_cookie
    assert "expires=" not in set_cookie.lower()


def test_api_login_returns_token_for_correct_password(client: TestClient) -> None:
    client.cookies.clear()

    response = client.post("/api/auth/login", json={"password": "test-password"})

    assert response.status_code == 200
    assert response.json() == {"token": expected_token(get_settings().site_password)}
    assert "set-cookie" not in response.headers


def test_api_login_rejects_wrong_password(client: TestClient) -> None:
    client.cookies.clear()

    response = client.post("/api/auth/login", json={"password": "nope"})

    assert response.status_code == 401
    assert response.json() == {"detail": "wrong_password"}


def test_health_is_open(client: TestClient) -> None:
    client.cookies.clear()

    response = client.get("/api/health")

    assert response.status_code == 200


def test_bearer_token_authenticates_protected_endpoint(
    client: TestClient, mock_conn: AsyncMock
) -> None:
    client.cookies.clear()
    mock_conn.fetch.return_value = []
    token = expected_token(get_settings().site_password)

    response = client.get(
        "/api/shows/stations",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"stations": []}


def test_bad_bearer_token_is_rejected(client: TestClient) -> None:
    client.cookies.clear()

    response = client.get(
        "/api/shows/stations",
        headers={"Authorization": "Bearer not-the-real-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}


def test_missing_auth_returns_401_json_for_api(client: TestClient) -> None:
    client.cookies.clear()

    response = client.get("/api/shows/stations")

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}
