import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import expected_token
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class TokenLoginRequest(BaseModel):
    password: str


class TokenLoginResponse(BaseModel):
    token: str


@router.post(
    "/login",
    response_model=TokenLoginResponse,
    summary="Exchange the site password for a bearer token",
)
def api_login(body: TokenLoginRequest) -> TokenLoginResponse:
    """Exchange the shared site password for a bearer token.

    Used by non-browser clients (mobile, desktop, CLI). Send the returned
    token as `Authorization: Bearer <token>` on subsequent `/api/*` requests.
    The token is deterministic and only changes when the site password rotates.
    Returns 401 if the password is wrong.
    """
    settings = get_settings()
    if not secrets.compare_digest(body.password, settings.site_password):
        raise HTTPException(status_code=401, detail="wrong_password")
    return TokenLoginResponse(token=expected_token(settings.site_password))
