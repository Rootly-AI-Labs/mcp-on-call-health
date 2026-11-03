"""MCP infrastructure safeguards for the hosted HTTP endpoint.

Provides per-API-key, per-tool rate limiting and structured logging. The
protocol is stateless (MCP 2026-07-28), so there is no connection tracking.
"""

from .logging import (
    MCPEvent,
    log_mcp_event,
    log_rate_limit_hit,
    truncate_api_key,
)
from .middleware import MCPInfrastructureMiddleware
from .rate_limiter import MCP_RATE_LIMITS

__all__ = [
    "MCPEvent",
    "MCPInfrastructureMiddleware",
    "MCP_RATE_LIMITS",
    "log_mcp_event",
    "log_rate_limit_hit",
    "truncate_api_key",
]
