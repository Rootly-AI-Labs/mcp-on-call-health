"""Unit tests for MCP transport layer.

Tests verify that the transport module correctly:
1. Exposes health check endpoint at /health
2. Provides a valid ASGI application structure
3. Has CORS headers configured for web-based MCP clients
"""
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient


class TestHealthCheckFunction:
    """Tests for the health_check function directly."""

    @pytest.mark.asyncio
    async def test_health_check_returns_json_response(self):
        """health_check returns a JSONResponse."""
        from oncallhealth_mcp.transport import health_check

        # Create a minimal mock request
        class MockRequest:
            pass

        result = await health_check(MockRequest())
        assert isinstance(result, JSONResponse)

    @pytest.mark.asyncio
    async def test_health_check_response_content(self):
        """health_check returns expected JSON structure."""
        from oncallhealth_mcp.transport import health_check

        class MockRequest:
            pass

        result = await health_check(MockRequest())
        # JSONResponse body is bytes, decode it
        import json

        data = json.loads(result.body.decode())
        assert data["status"] == "healthy"
        assert data["service"] == "on-call-health-mcp"

    @pytest.mark.asyncio
    async def test_health_check_status_code(self):
        """health_check returns 200 status code."""
        from oncallhealth_mcp.transport import health_check

        class MockRequest:
            pass

        result = await health_check(MockRequest())
        assert result.status_code == 200


class TestTransportModuleStructure:
    """Tests for the transport module structure."""

    def test_create_mcp_http_app_function_exists(self):
        """_create_mcp_http_app function exists in transport module."""
        from oncallhealth_mcp.transport import _create_mcp_http_app

        assert callable(_create_mcp_http_app)

    def test_health_check_function_exists(self):
        """health_check function exists in transport module."""
        from oncallhealth_mcp.transport import health_check

        assert callable(health_check)


class TestCORSConfiguration:
    """Tests for CORS configuration constants."""

    def test_sse_heartbeat_interval_exists(self):
        """SSE_HEARTBEAT_INTERVAL is configured."""
        from oncallhealth_mcp.transport import SSE_HEARTBEAT_INTERVAL

        assert SSE_HEARTBEAT_INTERVAL == 30

    def test_cors_origins_configured(self):
        """MCP_CORS_ORIGINS includes expected origins."""
        from oncallhealth_mcp.transport import MCP_CORS_ORIGINS

        assert "http://localhost:3000" in MCP_CORS_ORIGINS
        assert "https://oncallburnout.com" in MCP_CORS_ORIGINS

    def test_cors_headers_include_api_key(self):
        """MCP_CORS_HEADERS includes X-API-Key."""
        from oncallhealth_mcp.transport import MCP_CORS_HEADERS

        assert "X-API-Key" in MCP_CORS_HEADERS

    def test_cors_expose_headers_include_session_id(self):
        """MCP_CORS_EXPOSE_HEADERS includes mcp-session-id."""
        from oncallhealth_mcp.transport import MCP_CORS_EXPOSE_HEADERS

        assert "mcp-session-id" in MCP_CORS_EXPOSE_HEADERS


class TestTransportApp:
    """Tests for the transport ASGI app."""

    def test_cors_allows_x_api_key_header(self):
        """CORS allows X-API-Key header in preflight."""
        from oncallhealth_mcp.transport import mcp_http_app

        client = TestClient(mcp_http_app)
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        assert resp.status_code == 200
        allowed_headers = resp.headers.get("access-control-allow-headers", "").lower()
        assert "x-api-key" in allowed_headers

    def test_cors_exposes_mcp_session_id_header(self):
        """CORS exposes mcp-session-id header for browser clients."""
        from oncallhealth_mcp.transport import mcp_http_app

        client = TestClient(mcp_http_app)
        resp = client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert resp.status_code == 200
        exposed_headers = resp.headers.get("access-control-expose-headers", "")
        assert "mcp-session-id" in exposed_headers
