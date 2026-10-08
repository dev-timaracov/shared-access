import hmac
from contextvars import ContextVar

from starlette.responses import JSONResponse

from app.config import Identity
from app.errors import ServiceError

identity_context: ContextVar[Identity | None] = ContextVar("identity", default=None)


def current_identity() -> Identity:
    identity = identity_context.get()
    if identity is None:
        raise ServiceError(401, "Authentication required")
    return identity


class AuthMiddleware:
    """Authenticate REST and MCP in one ASGI boundary; propagate identity to tool tasks."""

    def __init__(self, app, tokens: dict[str, Identity], auth_disabled: bool = False):
        self.app = app
        self.tokens = tokens
        self.local_identity = (
            Identity(developer_id="local-admin", role="admin", projects=["*"])
            if auth_disabled
            else None
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in {
            "/health/live",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/docs/oauth2-redirect",
        }:
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        scheme, _, token = headers.get(b"authorization", b"").decode("latin1").partition(" ")
        identity = self.local_identity
        if identity is None and scheme.lower() == "bearer" and token:
            for known, candidate in self.tokens.items():
                if hmac.compare_digest(token.encode(), known.encode()):
                    identity = candidate
                    break
        if identity is None:
            response = JSONResponse(
                {"detail": "Invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        reset = identity_context.set(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            identity_context.reset(reset)
