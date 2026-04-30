import html
import secrets
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import COOKIE_MAX_AGE, COOKIE_NAME, expected_token, safe_next
from app.config import get_settings

router = APIRouter(tags=["auth"])

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>s3player — Sign in</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      display: grid; place-items: center; min-height: 100vh;
      margin: 0; background: #0f1115; color: #e6e6e6;
    }}
    form {{
      display: flex; flex-direction: column; gap: 0.75rem;
      min-width: 19rem; padding: 2rem; background: #181b22;
      border-radius: 0.75rem; box-shadow: 0 1px 0 #2a2f3a, 0 8px 30px #0008;
    }}
    h1 {{ margin: 0 0 0.25rem; font-size: 1.05rem; letter-spacing: 0.02em; }}
    label {{ font-size: 0.8rem; color: #a1a7b3; }}
    input[type=password] {{
      padding: 0.55rem 0.75rem; border-radius: 0.4rem;
      border: 1px solid #2a2f3a; background: #0c0f14; color: #e6e6e6;
      font-size: 0.95rem;
    }}
    input[type=password]:focus {{ outline: 2px solid #4f8cff; outline-offset: 1px; }}
    button {{
      padding: 0.55rem 0.75rem; border: 0; border-radius: 0.4rem;
      background: #4f8cff; color: white; font-weight: 600; cursor: pointer;
    }}
    button:hover {{ background: #6da0ff; }}
    .error {{ color: #ff7b7b; font-size: 0.85rem; margin: 0; }}
  </style>
</head>
<body>
  <form method="post" action="/login">
    <h1>s3player — sign in</h1>
    {error_html}
    <input type="hidden" name="next" value="{next_value}">
    <label for="password">Password</label>
    <input id="password" type="password" name="password" autofocus required>
    <button type="submit">Continue</button>
  </form>
</body>
</html>
"""


def render(next_value: str = "/", error: str = "") -> str:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return LOGIN_HTML.format(
        error_html=error_html,
        next_value=html.escape(next_value, quote=True),
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(next: str = "/") -> HTMLResponse:
    return HTMLResponse(render(next_value=safe_next(next)))


@router.post("/login", response_model=None)
def login_submit(
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> HTMLResponse | RedirectResponse:
    settings = get_settings()
    target = safe_next(next)
    if not secrets.compare_digest(password, settings.site_password):
        return HTMLResponse(
            render(next_value=target, error="Wrong password."),
            status_code=401,
        )
    response = RedirectResponse(url=target, status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        expected_token(settings.site_password),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response
