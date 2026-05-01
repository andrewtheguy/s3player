from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME


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
