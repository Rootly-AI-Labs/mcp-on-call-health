"""MCP infrastructure safeguards module.

Provides connection tracking, rate limiting, graceful cleanup, and structured
logging for the hosted MCP endpoint to protect against resource exhaustion
and abuse.
"""

from .connection_tracker import (
    connection_tracker,
    ConnectionState,
    MAX_CONNECTIONS_PER_KEY,
)
from .middleware import MCPInfrastructureMiddleware
from .rate_limiter import MCP_RATE_LIMITS
from .logging import (
    MCPEvent,
    log_mcp_event,
    log_connection_open,
    log_connection_close,
    log_connection_limit_hit,
    log_rate_limit_hit,
    log_cleanup_completed,
    log_cleanup_failed,
    truncate_api_key,
)
from .cleanup import (
    cleanup_stale_connections,
    get_cleanup_job_config,
    STALE_CONNECTION_TIMEOUT_MINUTES,
)

__all__ = [
    # Connection tracking
    "connection_tracker",
    "ConnectionState",
    "MAX_CONNECTIONS_PER_KEY",
    # Middleware
    "MCPInfrastructureMiddleware",
    # Rate limiting
    "MCP_RATE_LIMITS",
    # Logging
    "MCPEvent",
    "log_mcp_event",
    "log_connection_open",
    "log_connection_close",
    "log_connection_limit_hit",
    "log_rate_limit_hit",
    "log_cleanup_completed",
    "log_cleanup_failed",
    "truncate_api_key",
    # Cleanup
    "cleanup_stale_connections",
    "get_cleanup_job_config",
    "STALE_CONNECTION_TIMEOUT_MINUTES",
]
