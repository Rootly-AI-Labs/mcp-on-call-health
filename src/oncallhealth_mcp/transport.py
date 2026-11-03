"""Streamable HTTP transport for hosted deployments.

Exposes the MCP server over the Streamable HTTP transport defined by MCP
2026-07-28 (stateless, no protocol sessions, ``Mcp-Method``/``Mcp-Name``
routing headers). FastMCP negotiates the protocol per connection, so clients
on the 2025-xx handshake-era revisions keep working. The legacy HTTP+SSE
transport is not served: it is deprecated by the specification.

Routes:
- ``/mcp``: MCP endpoint
- ``/health``: unauthenticated health check for load balancers

Authentication: every MCP request must carry ``Authorization: Bearer <key>``
with an On-Call Health API key, verified by
:class:`~oncallhealth_mcp.auth.OnCallHealthKeyVerifier`. ``X-API-Key`` is
accepted for backward compatibility and rewritten into a bearer token.
"""

from __future__ import annotations

import logging
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from oncallhealth_mcp.auth import API_KEY_HEADER, OnCallHealthKeyVerifier
from oncallhealth_mcp.infrastructure import MCPInfrastructureMiddleware
from oncallhealth_mcp.server import build_server

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"
HEALTH_PATH = "/health"

# Comma-separated host names (e.g. "mcp.oncallhealth.ai") that enable
# FastMCP's Host/Origin DNS-rebinding guard for the MCP endpoint.
ALLOWED_HOSTS_ENV = "ONCALLHEALTH_MCP_ALLOWED_HOSTS"

# CORS configuration for browser-based MCP clients (MCP Inspector, web tools)
MCP_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "https://oncallhealth.ai",
    "https://www.oncallburnout.com",
    "https://oncallburnout.com",
]

MCP_CORS_HEADERS = [
    "mcp-protocol-version",
    "mcp-method",
    "mcp-name",
    "Authorization",
    "Content-Type",
    API_KEY_HEADER,
]

# GET/DELETE are only used by handshake-era clients; the 2026-07-28 transport is POST-only.
MCP_CORS_METHODS = ["GET", "POST", "DELETE", "OPTIONS"]

cors_middleware = Middleware(
    CORSMiddleware,
    allow_origins=MCP_CORS_ORIGINS,
    allow_methods=MCP_CORS_METHODS,
    allow_headers=MCP_CORS_HEADERS,
    allow_credentials=True,
)


class ApiKeyToBearerMiddleware:
    """Rewrite ``X-API-Key: <key>`` into ``Authorization: Bearer <key>``.

    Lets clients configured with the legacy header keep working with
    FastMCP's bearer-token auth layer. An explicit Authorization header wins.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers: list[tuple[bytes, bytes]] = list(scope.get("headers", []))
            has_authorization = any(name == b"authorization" for name, _ in headers)
            api_key = next(
                (
                    value.strip()
                    for name, value in headers
                    if name == API_KEY_HEADER.lower().encode()
                ),
                b"",
            )
            if api_key and not has_authorization:
                headers.append((b"authorization", b"Bearer " + api_key))
                scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for load balancers (no authentication)."""
    return JSONResponse({"status": "healthy", "service": "on-call-health-mcp"})


def allowed_hosts_from_env() -> list[str]:
    """Host names from ONCALLHEALTH_MCP_ALLOWED_HOSTS, or [] when unset."""
    raw = os.getenv(ALLOWED_HOSTS_ENV, "")
    return [host.strip() for host in raw.split(",") if host.strip()]


def create_http_app(
    *,
    code_mode: bool | None = None,
    verify_api_keys: bool = True,
) -> Starlette:
    """Build the ASGI application for the hosted MCP server.

    Args:
        code_mode: Expose the catalog through Code Mode meta-tools. Defaults to
            the ONCALLHEALTH_CODE_MODE environment variable.
        verify_api_keys: Require and verify a bearer API key on every MCP
            request. Only disable for local experiments.
    """
    auth = OnCallHealthKeyVerifier() if verify_api_keys else None
    server = build_server(code_mode=code_mode, auth=auth)

    allowed_hosts = allowed_hosts_from_env()
    mcp_http = server.http_app(
        path=MCP_PATH,
        stateless_http=True,
        host_origin_protection=bool(allowed_hosts),
        allowed_hosts=allowed_hosts or None,
        allowed_origins=MCP_CORS_ORIGINS if allowed_hosts else None,
    )

    app = Starlette(
        routes=[
            Route(HEALTH_PATH, health_check, methods=["GET"]),
            Mount("/", mcp_http),
        ],
        # Outermost first: CORS answers preflights, then the X-API-Key shim,
        # then per-key rate limiting, then FastMCP auth + MCP handling.
        middleware=[
            cors_middleware,
            Middleware(ApiKeyToBearerMiddleware),
            Middleware(MCPInfrastructureMiddleware),
        ],
        # Required so FastMCP's session manager starts with the parent app.
        lifespan=mcp_http.lifespan,
    )

    logger.info(
        "MCP HTTP transport initialized: %s (stateless), %s; auth=%s; host guard=%s",
        MCP_PATH,
        HEALTH_PATH,
        "api-key" if verify_api_keys else "disabled",
        allowed_hosts or "off",
    )
    return app


# ASGI entry point for uvicorn: `uvicorn oncallhealth_mcp.transport:mcp_http_app`
mcp_http_app = create_http_app()
