"""Tests for MCP rate limiter."""
import json
import time
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from oncallhealth_mcp.infrastructure.rate_limiter import (
    MCP_RATE_LIMITS,
    _cleanup_old_windows,
    _rate_limit_store,
    _rate_limit_timestamps,
    check_rate_limit,
    extract_tool_name,
    get_mcp_rate_limit_key,
)


@pytest.fixture(autouse=True)
def clear_rate_limit_store():
    """Clear the global rate limit store between tests."""
    _rate_limit_store.clear()
    _rate_limit_timestamps.clear()
    yield
    _rate_limit_store.clear()
    _rate_limit_timestamps.clear()


def _make_request(body: bytes = b"", cached: bool = True) -> MagicMock:
    """Create a mock Starlette request."""
    request = MagicMock()
    request.state = MagicMock()
    if cached:
        request.state._cached_body = body
    else:
        request.state._cached_body = None
    return request


class TestMCPRateLimits:
    """Test rate limit configuration."""

    def test_analysis_start_has_low_limit(self):
        assert MCP_RATE_LIMITS["analysis_start"] == "5/minute"

    def test_analysis_status_has_high_limit(self):
        assert MCP_RATE_LIMITS["analysis_status"] == "60/minute"

    def test_default_exists(self):
        assert "default" in MCP_RATE_LIMITS


class TestGetMCPRateLimitKey:
    """Test get_mcp_rate_limit_key()."""

    def test_format(self):
        key = get_mcp_rate_limit_key(123, "analysis_start")
        assert key == "mcp:123:analysis_start"

    def test_different_keys_unique(self):
        k1 = get_mcp_rate_limit_key(1, "tool_a")
        k2 = get_mcp_rate_limit_key(2, "tool_a")
        k3 = get_mcp_rate_limit_key(1, "tool_b")
        assert k1 != k2
        assert k1 != k3


class TestExtractToolName:
    """Test extract_tool_name()."""

    def test_valid_tool_call(self):
        body = json.dumps({
            "method": "tools/call",
            "params": {"name": "analysis_start", "arguments": {}},
        }).encode()
        request = _make_request(body)
        assert extract_tool_name(request) == "analysis_start"

    def test_non_tool_method(self):
        body = json.dumps({"method": "resources/read", "params": {}}).encode()
        request = _make_request(body)
        assert extract_tool_name(request) is None

    def test_no_cached_body(self):
        request = _make_request(cached=False)
        assert extract_tool_name(request) is None

    def test_invalid_json(self):
        request = _make_request(b"not json")
        assert extract_tool_name(request) is None

    def test_missing_params(self):
        body = json.dumps({"method": "tools/call"}).encode()
        request = _make_request(body)
        assert extract_tool_name(request) is None

    def test_missing_name(self):
        body = json.dumps({"method": "tools/call", "params": {}}).encode()
        request = _make_request(body)
        assert extract_tool_name(request) is None

    def test_non_string_name(self):
        body = json.dumps({
            "method": "tools/call",
            "params": {"name": 123},
        }).encode()
        request = _make_request(body)
        assert extract_tool_name(request) is None


class TestCheckRateLimit:
    """Test check_rate_limit()."""

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        request = _make_request()
        result = await check_rate_limit(request, 1, "analysis_status")
        assert result is None  # None means allowed

    @pytest.mark.asyncio
    async def test_sets_remaining_header(self):
        request = _make_request()
        await check_rate_limit(request, 1, "analysis_status")
        # analysis_status limit is 60/minute, after 1 call remaining should be 59
        assert request.state.rate_limit_remaining == 59
        assert request.state.rate_limit_limit == 60

    @pytest.mark.asyncio
    async def test_blocks_at_limit(self):
        """Should return 429 when limit is exceeded."""
        # analysis_start has 5/minute limit
        for i in range(5):
            request = _make_request()
            result = await check_rate_limit(request, 1, "analysis_start")
            assert result is None  # All 5 should pass

        # 6th should be blocked
        request = _make_request()
        result = await check_rate_limit(request, 1, "analysis_start")
        assert result is not None
        assert result.status_code == 429

    @pytest.mark.asyncio
    async def test_429_has_retry_after(self):
        """429 response should include Retry-After header."""
        for i in range(5):
            await check_rate_limit(_make_request(), 1, "analysis_start")

        result = await check_rate_limit(_make_request(), 1, "analysis_start")
        assert result is not None
        assert "Retry-After" in result.headers

    @pytest.mark.asyncio
    async def test_different_keys_independent(self):
        """Different API keys have independent limits."""
        for i in range(5):
            await check_rate_limit(_make_request(), 1, "analysis_start")

        # Key 2 should still be allowed
        result = await check_rate_limit(_make_request(), 2, "analysis_start")
        assert result is None

    @pytest.mark.asyncio
    async def test_different_tools_independent(self):
        """Different tools have independent limits."""
        for i in range(5):
            await check_rate_limit(_make_request(), 1, "analysis_start")

        # Different tool should still be allowed
        result = await check_rate_limit(_make_request(), 1, "analysis_status")
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_tool_uses_default(self):
        """Unknown tools should use the default limit."""
        for i in range(100):
            request = _make_request()
            result = await check_rate_limit(request, 1, "unknown_tool")
            assert result is None

        # 101st should be blocked (default is 100/minute)
        result = await check_rate_limit(_make_request(), 1, "unknown_tool")
        assert result is not None
        assert result.status_code == 429


class TestCleanupOldWindows:
    """Test _cleanup_old_windows()."""

    def test_removes_expired_entries(self):
        _rate_limit_store[("key1", 100)] = 5
        _rate_limit_store[("key2", 101)] = 3
        _rate_limit_store[("key3", 200)] = 1  # current

        _cleanup_old_windows(200, 60)

        assert ("key1", 100) not in _rate_limit_store
        assert ("key2", 101) not in _rate_limit_store
        assert ("key3", 200) in _rate_limit_store

    def test_keeps_recent_window(self):
        _rate_limit_store[("key1", 199)] = 5  # previous window
        _rate_limit_store[("key2", 200)] = 1  # current window

        _cleanup_old_windows(200, 60)

        # Previous window (199) is within current_window - 1, so kept
        assert ("key1", 199) in _rate_limit_store
        assert ("key2", 200) in _rate_limit_store

    def test_empty_store_no_error(self):
        _cleanup_old_windows(200, 60)
