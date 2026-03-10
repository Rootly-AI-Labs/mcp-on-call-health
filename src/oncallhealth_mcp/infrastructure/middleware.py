"""Starlette middleware combining connection tracking and rate limiting.

This middleware protects the MCP endpoint from resource exhaustion by:
1. Limiting concurrent connections per API key
2. Rate limiting tool invocations per API key

Applied to mcp_http_app before CORS middleware.
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .connection_tracker import (
    connection_tracker,
    MAX_CONNECTIONS_PER_KEY,
)
from .rate_limiter import (
    check_rate_limit,
    extract_tool_name,
    MCP_RATE_LIMITS,
)
from .logging import (
    log_connection_open,
    log_connection_close,
    log_connection_limit_hit,
    log_rate_limit_hit,
)

logger = logging.getLogger(__name__)


def _hash_api_key(api_key: str) -> int:
    """Hash API key to a stable integer for connection tracking.

    Uses first 8 bytes of SHA-256 as a stable numeric ID.

    Args:
        api_key: The full API key string

    Returns:
        Stable integer derived from API key hash
    """
    digest = hashlib.sha256(api_key.encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big")


class MCPInfrastructureMiddleware(BaseHTTPMiddleware):
    """Middleware for MCP connection limits and rate limiting.

    Applies infrastructure safeguards to MCP endpoints:
    - Connection limit: Max concurrent connections per API key
    - Rate limit: Per-tool request limits based on resource consumption

    Health check endpoint is exempt from all limits.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with infrastructure checks.

        Args:
            request: Starlette request object
            call_next: Next middleware/handler in chain

        Returns:
            Response from handler or 429 error if limits exceeded
        """
        # Skip health check - must always be available for ALB
        if request.url.path.endswith("/health"):
            return await call_next(request)

        # Extract API key from header
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            # No API key - pass through, auth middleware handles rejection
            return await call_next(request)

        # Derive stable numeric ID from API key for tracking
        api_key_id = _hash_api_key(api_key)

        # Generate unique connection ID for this request
        connection_id = f"{api_key_id}:{uuid.uuid4().hex[:8]}"

        # Check connection limit
        can_connect = await connection_tracker.add_connection(api_key_id, connection_id)
        if not can_connect:
            log_connection_limit_hit(api_key_id)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "connection_limit_exceeded",
                    "detail": f"Maximum concurrent connections reached ({MAX_CONNECTIONS_PER_KEY}). Close idle connections and retry.",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )

        # Log successful connection open
        log_connection_open(api_key_id, connection_id)

        try:
            # Cache request body for rate limit extraction
            # This allows extract_tool_name to access the body
            body = await request.body()
            request.state._cached_body = body

            # Extract tool name and check rate limit (only for tool calls)
            tool_name = extract_tool_name(request)
            if tool_name:
                rate_limit_response = await check_rate_limit(
                    request, api_key_id, tool_name
                )
                if rate_limit_response is not None:
                    # Log rate limit violation
                    limit = MCP_RATE_LIMITS.get(tool_name, MCP_RATE_LIMITS["default"])
                    log_rate_limit_hit(api_key_id, tool_name, limit)
                    return rate_limit_response

            # Update activity timestamp
            await connection_tracker.update_activity(connection_id)

            # Process the request
            response = await call_next(request)

            # Update activity timestamp on successful completion
            await connection_tracker.update_activity(connection_id)

            return response

        finally:
            # Always clean up connection on request completion
            await connection_tracker.remove_connection(api_key_id, connection_id)
            log_connection_close(api_key_id, connection_id)
