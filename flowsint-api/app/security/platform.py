"""ASGI boundary: validate session and project before any API handler or SQL."""

import os
from time import monotonic

from pydantic import ValidationError
from redis.exceptions import RedisError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from flowsint_core.core.platform_auth import AccessDenied, AuthClient, SessionRejected
from flowsint_core.core.project_scope import avl4_enabled, project_scope


class Avl4AuthMiddleware:
    def __init__(self, app: ASGIApp, client: AuthClient | None = None) -> None:
        self.app = app
        self.client = client or AuthClient()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not avl4_enabled():
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = request.url.path.rstrip("/")
        if not path.startswith("/api/") or request.method == "OPTIONS":
            return await self.app(scope, receive, send)
        disabled = (
            path in {"/api/auth/token", "/api/auth/register", "/api/auth/users/search"}
            or "/collaborators" in path
            or (path == "/api/auth/me" and request.method != "GET")
        )
        if disabled:
            return await JSONResponse({"detail": "Not found"}, 404)(
                scope, receive, send
            )
        session_id = request.headers.get("h-avl-session") or request.cookies.get(
            "c-avl-session"
        )
        if not session_id:
            return await self._reject(scope, receive, send)
        project_id = request.headers.get("h-avl-project")
        if not project_id:
            return await JSONResponse({"detail": "PROJECT_REQUIRED"}, 400)(
                scope, receive, send
            )
        # Cookie-authenticated mutations must originate from a configured UI.
        if request.method not in {"GET", "HEAD"} and not request.headers.get(
            "h-avl-session"
        ):
            origins = {
                o.strip()
                for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(
                    ","
                )
            }
            if request.headers.get("origin") not in origins:
                return await JSONResponse({"detail": "Origin not allowed"}, 403)(
                    scope, receive, send
                )
        try:
            verified = await self.client.authenticate(session_id, project_id)
        except (SessionRejected, ValidationError):
            return await self._reject(scope, receive, send)
        except AccessDenied:
            return await JSONResponse({"detail": "Forbidden"}, 403)(
                scope, receive, send
            )
        except (RedisError, ImportError, OSError):
            return await JSONResponse({"detail": "AUTH_UNAVAILABLE"}, 503)(
                scope, receive, send
            )

        streaming = False
        checked_at = monotonic()

        async def guarded_send(message: Message) -> None:
            nonlocal streaming, checked_at
            if message["type"] == "http.response.start":
                streaming = any(
                    key.lower() == b"content-type" and b"text/event-stream" in value
                    for key, value in message.get("headers", [])
                )
            if (
                streaming
                and message["type"] == "http.response.body"
                and monotonic() - checked_at >= 10
            ):
                try:
                    await self.client.authenticate(session_id, project_id)
                except (
                    SessionRejected,
                    AccessDenied,
                    ValidationError,
                    RedisError,
                    OSError,
                ) as exc:
                    # ASGI servers/StreamingResponse treat OSError as disconnect;
                    # no more project content is sent after access is lost.
                    raise OSError("Project stream admission ended") from exc
                checked_at = monotonic()
            await send(message)

        with project_scope(verified):
            await self.app(scope, receive, guarded_send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse(
            {"detail": "SESSION_REQUIRED"},
            401,
            headers={"X-AVL-Auth-Guard": "session-rejected"},
        )(scope, receive, send)
