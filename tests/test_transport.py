"""Tests for the Streamable HTTP transport (MCP 2026-07-28)."""

import socket
import threading
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from oncallhealth_mcp import server as server_module
from oncallhealth_mcp import transport
from oncallhealth_mcp.infrastructure.rate_limiter import (
    _rate_limit_store,
    _rate_limit_timestamps,
)
from oncallhealth_mcp.transport import (
    MCP_CORS_HEADERS,
    MCP_CORS_ORIGINS,
    ApiKeyToBearerMiddleware,
    allowed_hosts_from_env,
    create_http_app,
    health_check,
    mcp_http_app,
)


class TestHealthCheck:
    async def test_health_check_payload(self):
        result = await health_check(None)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200
        assert b'"status":"healthy"' in result.body


class TestAppStructure:
    def test_routes(self):
        paths = {r.path for r in mcp_http_app.routes if isinstance(r, Route)}
        assert paths == {"/health"}
        mounts = [r for r in mcp_http_app.routes if isinstance(r, Mount)]
        assert len(mounts) == 1
        inner_paths = {getattr(r, "path", None) for r in mounts[0].app.routes}
        assert "/mcp" in inner_paths
        assert not any(p and "sse" in p for p in inner_paths)

    def test_cors_headers_cover_mcp_routing_headers(self):
        lowered = {h.lower() for h in MCP_CORS_HEADERS}
        assert {
            "mcp-protocol-version",
            "mcp-method",
            "mcp-name",
            "x-api-key",
        } <= lowered
        assert "mcp-session-id" not in lowered

    def test_health_route_with_cors(self):
        client = TestClient(mcp_http_app)
        resp = client.get("/health", headers={"Origin": MCP_CORS_ORIGINS[0]})
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
        assert resp.headers["access-control-allow-origin"] == MCP_CORS_ORIGINS[0]
        assert "mcp-session-id" not in resp.headers.get(
            "access-control-expose-headers", ""
        )

    def test_mcp_requires_bearer_token(self):
        client = TestClient(mcp_http_app)
        resp = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert resp.status_code == 401

    def test_allowed_hosts_env(self, monkeypatch):
        monkeypatch.delenv(transport.ALLOWED_HOSTS_ENV, raising=False)
        assert allowed_hosts_from_env() == []
        monkeypatch.setenv(transport.ALLOWED_HOSTS_ENV, " mcp.example.com, localhost ,")
        assert allowed_hosts_from_env() == ["mcp.example.com", "localhost"]

    def test_create_http_app_without_verification(self):
        app = create_http_app(verify_api_keys=False, code_mode=False)
        assert TestClient(app).get("/health").status_code == 200


class TestApiKeyToBearerMiddleware:
    @staticmethod
    def _run(headers):
        captured = {}

        async def inner(scope, receive, send):
            captured["headers"] = dict(scope["headers"])

        import asyncio

        scope = {"type": "http", "headers": headers}
        asyncio.run(ApiKeyToBearerMiddleware(inner)(scope, None, None))
        return captured["headers"]

    def test_rewrites_x_api_key(self):
        headers = self._run([(b"x-api-key", b" och_abc ")])
        assert headers[b"authorization"] == b"Bearer och_abc"

    def test_keeps_explicit_authorization(self):
        headers = self._run(
            [(b"x-api-key", b"och_abc"), (b"authorization", b"Bearer och_other")]
        )
        assert headers[b"authorization"] == b"Bearer och_other"

    def test_no_key_no_change(self):
        headers = self._run([(b"content-type", b"application/json")])
        assert b"authorization" not in headers


@pytest.fixture
def running_server():
    """Serve create_http_app() with uvicorn in a thread on a free port."""
    uvicorn = pytest.importorskip("uvicorn")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    with patch.object(
        transport.OnCallHealthKeyVerifier,
        "_check_with_backend",
        staticmethod(lambda api_key: _truthy(api_key == "och_good")),
    ):
        app = create_http_app(code_mode=False)
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            server.should_exit = True
            thread.join(timeout=5)


async def _truthy(value):
    return value


class TestEndToEndHttp:
    async def test_bearer_key_lists_catalog_on_modern_protocol(self, running_server):
        headers = {"Authorization": "Bearer och_good"}
        async with Client(
            StreamableHttpTransport(running_server, headers=headers)
        ) as c:
            assert c.protocol_version == "2026-07-28"
            names = {t.name for t in await c.list_tools()}
        assert "analysis_run" in names and "analysis_summary" in names

    async def test_x_api_key_header_still_works(self, running_server):
        headers = {"X-API-Key": "och_good"}
        async with Client(
            StreamableHttpTransport(running_server, headers=headers)
        ) as c:
            assert len(await c.list_tools()) == 13

    @pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer och_bad"}])
    async def test_missing_or_invalid_key_is_rejected(self, running_server, headers):
        with pytest.raises(Exception):
            async with Client(
                StreamableHttpTransport(running_server, headers=headers)
            ) as c:
                await c.list_tools()


class TestEndToEndRawRequests:
    """Wire-level checks that need the real HTTP stack rather than fastmcp.Client."""

    @staticmethod
    def _headers(**extra):
        return {
            "Authorization": "Bearer och_good",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **extra,
        }

    async def test_legacy_tool_call_with_misleading_method_header_is_limited(
        self, running_server
    ):
        """A handshake-era tools/call body executes as a tool call whatever the
        Mcp-Method header claims, so it must count against the tool's limit."""
        _rate_limit_store.clear()
        _rate_limit_timestamps.clear()
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "analysis_start", "arguments": {}},
        }
        started = AsyncMock(
            return_value={"analysis_id": 1, "status": "pending", "message": "ok"}
        )
        with patch.object(server_module, "_start_analysis", started):
            async with httpx.AsyncClient(timeout=10) as http:
                codes = [
                    (
                        await http.post(
                            running_server,
                            headers=self._headers(**{"Mcp-Method": "tools/list"}),
                            json=body,
                        )
                    ).status_code
                    for _ in range(6)
                ]
        assert codes[:5] == [200] * 5
        assert codes[5] == 429

    async def test_resource_read_is_cached_privately(self, running_server):
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {
                "uri": "oncallhealth://methodology",
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        }
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.post(
                running_server,
                headers=self._headers(
                    **{
                        "MCP-Protocol-Version": "2026-07-28",
                        "Mcp-Method": "resources/read",
                        "Mcp-Name": "oncallhealth://methodology",
                    }
                ),
                json=body,
            )
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["cacheScope"] == "private"
        assert result["ttlMs"] == 300_000
