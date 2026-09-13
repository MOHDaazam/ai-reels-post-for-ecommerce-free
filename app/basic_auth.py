"""Optional HTTP Basic Auth for public deployments."""

from __future__ import annotations

import base64
import secrets
from typing import Callable, Awaitable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings


def _credentials_ok(request: Request) -> bool:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    username, sep, password = raw.partition(":")
    if not sep:
        return False
    user_ok = secrets.compare_digest(username, settings.studio_basic_auth_user)
    pass_ok = secrets.compare_digest(password, settings.studio_basic_auth_password)
    return user_ok and pass_ok


def _challenge() -> Response:
    return JSONResponse(
        status_code=401,
        content={"detail": "Authentication required."},
        headers={"WWW-Authenticate": 'Basic realm="Kaggle Video Studio"'},
    )


async def basic_auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if not settings.studio_basic_auth_enabled:
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)
    if _credentials_ok(request):
        return await call_next(request)
    return _challenge()
