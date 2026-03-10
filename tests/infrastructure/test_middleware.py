"""Tests for MCP infrastructure middleware."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oncallhealth_mcp.infrastructure.middleware import (
    MCPInfrastructureMiddleware,
    _hash_api_key,
)


class TestHashApiKey:
    """Test _hash_api_key()."""

    def test_returns_int(self):
        result = _hash_api_key("test-key")
        assert isinstance(result, int)

    def test_deterministic(self):
        """Same input should always produce same hash."""
        assert _hash_api_key("my-key") == _hash_api_key("my-key")

    def test_different_keys_different_hashes(self):
        h1 = _hash_api_key("key-1")
        h2 = _hash_api_key("key-2")
        assert h1 != h2

    def test_positive_int(self):
        result = _hash_api_key("some-key")
        assert result >= 0


def _make_request(path="/mcp", api_key=None, body=b""):
    """Create a mock Starlette request."""
    request = MagicMock()
    request.url.path = path

    # Build headers dict, then wrap in MagicMock for .get()
    _headers = {}
    if api_key:
        _headers["X-API-Key"] = api_key
    request.headers = MagicMock()
    request.headers.get = lambda k, default=None: _headers.get(k, default)

    # Async body
    async def _body():
        return body

    request.body = _body
    request.state = MagicMock()
    return request


class TestMiddlewareHealthCheck:
    """Test health check bypass."""

    @pytest.mark.asyncio
    async def test_health_passes_through(self):
        """Health check should bypass all limits."""
        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        request = _make_request(path="/health")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        await middleware.dispatch(request, call_next)
        call_next.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_mcp_health_passes_through(self):
        """Nested health path should also bypass."""
        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        request = _make_request(path="/mcp/health")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        await middleware.dispatch(request, call_next)
        call_next.assert_called_once_with(request)


class TestMiddlewareNoApiKey:
    """Test behavior without API key."""

    @pytest.mark.asyncio
    async def test_no_api_key_passes_through(self):
        """Requests without API key pass through to auth handler."""
        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        request = _make_request(api_key=None)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        await middleware.dispatch(request, call_next)
        call_next.assert_called_once_with(request)


class TestMiddlewareConnectionLimit:
    """Test connection limiting."""

    @pytest.mark.asyncio
    async def test_connection_added_and_removed(self):
        """Middleware should track connection lifecycle."""
        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        request = _make_request(api_key="test-key")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with patch(
            "oncallhealth_mcp.infrastructure.middleware.connection_tracker"
        ) as mock_tracker:
            mock_tracker.add_connection = AsyncMock(return_value=True)
            mock_tracker.remove_connection = AsyncMock()
            mock_tracker.update_activity = AsyncMock()

            await middleware.dispatch(request, call_next)

            mock_tracker.add_connection.assert_called_once()
            mock_tracker.remove_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_limit_returns_429(self):
        """Should return 429 when connection limit exceeded."""
        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        request = _make_request(api_key="test-key")
        call_next = AsyncMock()

        with patch(
            "oncallhealth_mcp.infrastructure.middleware.connection_tracker"
        ) as mock_tracker:
            mock_tracker.add_connection = AsyncMock(return_value=False)

            response = await middleware.dispatch(request, call_next)

            assert response.status_code == 429
            call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_cleaned_on_error(self):
        """Connection should be removed even if handler raises."""
        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        request = _make_request(api_key="test-key")
        call_next = AsyncMock(side_effect=RuntimeError("boom"))

        with patch(
            "oncallhealth_mcp.infrastructure.middleware.connection_tracker"
        ) as mock_tracker:
            mock_tracker.add_connection = AsyncMock(return_value=True)
            mock_tracker.remove_connection = AsyncMock()
            mock_tracker.update_activity = AsyncMock()

            with pytest.raises(RuntimeError, match="boom"):
                await middleware.dispatch(request, call_next)

            # Connection should still be cleaned up
            mock_tracker.remove_connection.assert_called_once()


class TestMiddlewareRateLimit:
    """Test rate limiting integration."""

    @pytest.mark.asyncio
    async def test_rate_limit_checked_for_tool_calls(self):
        """Rate limit should be checked when tool name is extracted."""
        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        body = json.dumps(
            {
                "method": "tools/call",
                "params": {"name": "analysis_start"},
            }
        ).encode()
        request = _make_request(api_key="test-key", body=body)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with (
            patch(
                "oncallhealth_mcp.infrastructure.middleware.connection_tracker"
            ) as mock_tracker,
            patch(
                "oncallhealth_mcp.infrastructure.middleware.check_rate_limit"
            ) as mock_rl,
            patch(
                "oncallhealth_mcp.infrastructure.middleware.extract_tool_name",
                return_value="analysis_start",
            ),
        ):
            mock_tracker.add_connection = AsyncMock(return_value=True)
            mock_tracker.remove_connection = AsyncMock()
            mock_tracker.update_activity = AsyncMock()
            mock_rl.return_value = None  # Within limit

            await middleware.dispatch(request, call_next)

            mock_rl.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_429(self):
        """Should return rate limit response when exceeded."""
        from starlette.responses import JSONResponse

        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        body = json.dumps(
            {
                "method": "tools/call",
                "params": {"name": "analysis_start"},
            }
        ).encode()
        request = _make_request(api_key="test-key", body=body)
        call_next = AsyncMock()
        rate_limit_resp = JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded"},
        )

        with (
            patch(
                "oncallhealth_mcp.infrastructure.middleware.connection_tracker"
            ) as mock_tracker,
            patch(
                "oncallhealth_mcp.infrastructure.middleware.check_rate_limit"
            ) as mock_rl,
            patch(
                "oncallhealth_mcp.infrastructure.middleware.extract_tool_name",
                return_value="analysis_start",
            ),
        ):
            mock_tracker.add_connection = AsyncMock(return_value=True)
            mock_tracker.remove_connection = AsyncMock()
            mock_tracker.update_activity = AsyncMock()
            mock_rl.return_value = rate_limit_resp

            response = await middleware.dispatch(request, call_next)

            assert response.status_code == 429
            call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_tool_requests_skip_rate_limit(self):
        """Non-tool requests should not be rate limited."""
        app = MagicMock()
        middleware = MCPInfrastructureMiddleware(app)

        request = _make_request(api_key="test-key", body=b'{"method":"resources/read"}')
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        with (
            patch(
                "oncallhealth_mcp.infrastructure.middleware.connection_tracker"
            ) as mock_tracker,
            patch(
                "oncallhealth_mcp.infrastructure.middleware.check_rate_limit"
            ) as mock_rl,
            patch(
                "oncallhealth_mcp.infrastructure.middleware.extract_tool_name",
                return_value=None,
            ),
        ):
            mock_tracker.add_connection = AsyncMock(return_value=True)
            mock_tracker.remove_connection = AsyncMock()
            mock_tracker.update_activity = AsyncMock()

            await middleware.dispatch(request, call_next)

            mock_rl.assert_not_called()
            call_next.assert_called_once()
