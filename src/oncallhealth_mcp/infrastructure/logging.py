"""Structured logging for MCP infrastructure events.

- WARNING: limit violations (rate limit hit)
- DEBUG: anything else
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("oncallhealth_mcp.infrastructure")


class MCPEvent:
    """MCP infrastructure event types for structured logging."""

    RATE_LIMIT_HIT = "rate_limit_hit"


# Events that should log at WARNING level (limit violations)
_WARNING_EVENTS = {
    MCPEvent.RATE_LIMIT_HIT,
}


def truncate_api_key(api_key: str | None) -> str:
    """Truncate API key for safe logging.

    Shows only the last 4 characters with prefix "och_***" to allow
    identification without exposing the full key.

    Returns:
        Truncated key string, e.g., "och_***abcd" or "N/A" if None/empty
    """
    if not api_key:
        return "N/A"
    if len(api_key) < 4:
        return "och_***"
    return f"och_***{api_key[-4:]}"


def log_mcp_event(
    event: str,
    api_key_id: int | None = None,
    **kwargs,
) -> None:
    """Log an MCP infrastructure event with structured data.

    Args:
        event: Event type from MCPEvent constants
        api_key_id: Stable numeric ID derived from the API key (optional)
        **kwargs: Additional structured fields to include in the log
    """
    extra = {
        "mcp_event": event,
        "api_key_id": api_key_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }

    message = f"MCP: {event}"

    if event in _WARNING_EVENTS:
        logger.warning(message, extra=extra)
    else:
        logger.debug(message, extra=extra)


def log_rate_limit_hit(api_key_id: int, tool_name: str, limit: str) -> None:
    """Log when rate limit is exceeded for a tool."""
    log_mcp_event(
        MCPEvent.RATE_LIMIT_HIT,
        api_key_id=api_key_id,
        tool_name=tool_name,
        limit=limit,
    )
