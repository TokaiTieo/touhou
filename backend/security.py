"""Per-process protection for the local HTTP API."""

import hmac
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse


SESSION_TOKEN = secrets.token_urlsafe(32)
TOKEN_HEADER = "X-Touhou-Token"
PUBLIC_API_PATHS = {"/api/health", "/api/version"}


def inject_session_token(html: str) -> str:
    marker = '<meta name="touhou-session-token"'
    if marker in html:
        return html
    tag = f'<meta name="touhou-session-token" content="{SESSION_TOKEN}">'
    return html.replace("</head>", f"    {tag}\n</head>")


async def require_local_session_token(request: Request, call_next):
    path = request.url.path
    if (
        request.method == "OPTIONS"
        or not path.startswith("/api")
        or path in PUBLIC_API_PATHS
    ):
        return await call_next(request)
    supplied = request.headers.get(TOKEN_HEADER, "")
    if not supplied or not hmac.compare_digest(supplied, SESSION_TOKEN):
        return JSONResponse(
            status_code=403,
            content={"detail": "本地游戏会话令牌无效，请从游戏首页重新进入。"}
        )
    return await call_next(request)
