"""Tests for MCP structured logging utilities."""

import logging

from oncallhealth_mcp.infrastructure.logging import (
    MCPEvent,
    log_mcp_event,
    log_rate_limit_hit,
    truncate_api_key,
)


class TestTruncateApiKey:
    def test_normal_key(self):
        assert truncate_api_key("och_live_abc123xyz") == "och_***3xyz"

    def test_none_returns_na(self):
        assert truncate_api_key(None) == "N/A"

    def test_empty_string_returns_na(self):
        assert truncate_api_key("") == "N/A"

    def test_short_key_returns_masked(self):
        assert truncate_api_key("abc") == "och_***"

    def test_exactly_four_chars(self):
        assert truncate_api_key("abcd") == "och_***abcd"


class TestLogMcpEvent:
    def test_rate_limit_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="oncallhealth_mcp.infrastructure"):
            log_mcp_event(MCPEvent.RATE_LIMIT_HIT, api_key_id=1)
        assert "rate_limit_hit" in caplog.text

    def test_unknown_event_defaults_to_debug(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="oncallhealth_mcp.infrastructure"):
            log_mcp_event("unknown_event_type", api_key_id=1)
        assert "unknown_event_type" in caplog.text
        assert caplog.records[-1].levelno == logging.DEBUG

    def test_log_rate_limit_hit(self, caplog):
        with caplog.at_level(logging.WARNING, logger="oncallhealth_mcp.infrastructure"):
            log_rate_limit_hit(
                api_key_id=1, tool_name="analysis_start", limit="5/minute"
            )
        assert "rate_limit_hit" in caplog.text
