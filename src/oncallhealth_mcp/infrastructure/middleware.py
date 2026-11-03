"""Starlette middleware applying per-API-key rate limits to MCP tool calls.

The protocol is stateless, so the middleware keys limits on the API key
presented with each request (``Authorization: Bearer`` or ``X-API-Key``) and
identifies the tool from the JSON-RPC body, which is what gets executed for
every protocol revision (routing headers alone are not trusted).
"""

from __future__ import annotations

import hashlib
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging import log_rate_limit_hit
from .rate_limiter import MCP_RATE_LIMITS, check_rate_limit, extract_tool_name

logger = logging.getLogger(__name__)


def _hash_api_key(api_key: str) -> int:
    """Hash API key to a stable integer for rate limiting and logs.

    Uses the first 8 bytes of SHA-256 as a stable numeric ID.
    """
    digest = hashlib.sha256(api_key.encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big")


def _request_api_key(request: Request) -> str | None:
    """API key from the Authorization bearer token or the X-API-Key header."""
    authorization = request.headers.get("authorization") or ""
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        return parts[1].strip()
    api_key = request.headers.get("x-api-key")
    return api_key.strip() if api_key and api_key.strip() else None


class MCPInfrastructureMiddleware(BaseHTTPMiddleware):
    """Rate-limit MCP tool invocations per API key.

    Requests without an API key pass through: FastMCP's auth layer rejects
    them. The health check endpoint is exempt.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.endswith("/health"):
            return await call_next(request)

        api_key = _request_api_key(request)
        if not api_key:
            return await call_next(request)

        # Starlette replays the cached body to the downstream app.
        request.state._cached_body = await request.body()

        tool_name = extract_tool_name(request)
        if tool_name:
            api_key_id = _hash_api_key(api_key)
            rate_limit_response = await check_rate_limit(request, api_key_id, tool_name)
            if rate_limit_response is not None:
                limit = MCP_RATE_LIMITS.get(tool_name, MCP_RATE_LIMITS["default"])
                log_rate_limit_hit(api_key_id, tool_name, limit)
                return rate_limit_response

        return await call_next(request)
