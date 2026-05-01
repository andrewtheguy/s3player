import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request

from app.config import get_settings

COOKIE_NAME = "s3player_auth"


def expected_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"authenticated", hashlib.sha256).hexdigest()


def is_authenticated(request: Request, password: str) -> bool:
    expected = expected_token(password)
    cookie = request.cookies.get(COOKIE_NAME, "")
    if cookie and secrets.compare_digest(cookie, expected):
        return True
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return scheme.lower() == "bearer" and bool(token) and secrets.compare_digest(token, expected)


def require_auth(request: Request) -> None:
    if not is_authenticated(request, get_settings().site_password):
        raise HTTPException(status_code=401, detail="unauthenticated")


def safe_next(next_value: str) -> str:
    if next_value.startswith("/") and not next_value.startswith("//"):
        return next_value
    return "/"
