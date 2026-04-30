import hashlib
import hmac
import secrets

from fastapi import Request

COOKIE_NAME = "s3player_auth"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7


def expected_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"authenticated", hashlib.sha256).hexdigest()


def is_authenticated(request: Request, password: str) -> bool:
    if not password:
        return True
    cookie = request.cookies.get(COOKIE_NAME, "")
    if not cookie:
        return False
    return secrets.compare_digest(cookie, expected_token(password))


def safe_next(next_value: str) -> str:
    if next_value.startswith("/") and not next_value.startswith("//"):
        return next_value
    return "/"
