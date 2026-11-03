"""Tests for the rate-limiting middleware."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from oncallhealth_mcp.infrastructure.middleware import (
    MCPInfrastructureMiddleware,
    _hash_api_key,
    _request_api_key,
)


class TestHashApiKey:
    def test_deterministic_positive_int(self):
        assert _hash_api_key("my-key") == _hash_api_key("my-key")
        assert _hash_api_key("key-1") != _hash_api_key("key-2")
        assert _hash_api_key("some-key") >= 0


def _make_request(path="/mcp", headers=None, body=b""):
    """Create a mock Starlette request with case-insensitive header lookup."""
    request = MagicMock()
    request.url.path = path
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    request.headers = MagicMock()
    request.headers.get = lambda k, default=None: lowered.get(k.lower(), default)

    async def _body():
        return body

    request.body = _body
    request.state = MagicMock()
    request.state._cached_body = None
    return request


class TestRequestApiKey:
    def test_bearer_token(self):
        req = _make_request(headers={"Authorization": "Bearer och_abc"})
        assert _request_api_key(req) == "och_abc"

    def test_x_api_key(self):
        req = _make_request(headers={"X-API-Key": " och_abc "})
        assert _request_api_key(req) == "och_abc"

    def test_bearer_wins_over_x_api_key(self):
        req = _make_request(
            headers={"Authorization": "Bearer och_1", "X-API-Key": "och_2"}
        )
        assert _request_api_key(req) == "och_1"

    def test_missing(self):
        assert _request_api_key(_make_request()) is None


class TestMiddlewareDispatch:
    def _middleware(self):
        return MCPInfrastructureMiddleware(MagicMock())

    async def test_health_passes_through(self):
        request = _make_request(path="/health")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        await self._middleware().dispatch(request, call_next)
        call_next.assert_called_once_with(request)

    async def test_no_api_key_passes_through_to_auth_layer(self):
        request = _make_request(headers={"Mcp-Method": "tools/call", "Mcp-Name": "x"})
        call_next = AsyncMock(return_value=MagicMock(status_code=401))
        with patch(
            "oncallhealth_mcp.infrastructure.middleware.check_rate_limit"
        ) as crl:
            await self._middleware().dispatch(request, call_next)
        crl.assert_not_called()
        call_next.assert_called_once_with(request)

    @staticmethod
    def _tool_call(name):
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            }
        ).encode()

    async def test_tool_call_with_routing_headers_is_rate_limited(self):
        request = _make_request(
            headers={
                "Authorization": "Bearer och_abc",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "analysis_start",
            },
            body=self._tool_call("analysis_start"),
        )
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        with patch(
            "oncallhealth_mcp.infrastructure.middleware.check_rate_limit",
            new=AsyncMock(return_value=None),
        ) as crl:
            await self._middleware().dispatch(request, call_next)
        crl.assert_awaited_once_with(
            request, _hash_api_key("och_abc"), "analysis_start"
        )
        call_next.assert_called_once_with(request)

    async def test_misleading_method_header_does_not_bypass_limit(self):
        request = _make_request(
            headers={"Authorization": "Bearer och_abc", "Mcp-Method": "tools/list"},
            body=self._tool_call("analysis_start"),
        )
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        with patch(
            "oncallhealth_mcp.infrastructure.middleware.check_rate_limit",
            new=AsyncMock(return_value=None),
        ) as crl:
            await self._middleware().dispatch(request, call_next)
        crl.assert_awaited_once_with(
            request, _hash_api_key("och_abc"), "analysis_start"
        )

    async def test_legacy_body_fallback(self):
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "oncall_users"},
            }
        ).encode()
        request = _make_request(headers={"X-API-Key": "och_abc"}, body=body)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        with patch(
            "oncallhealth_mcp.infrastructure.middleware.check_rate_limit",
            new=AsyncMock(return_value=None),
        ) as crl:
            await self._middleware().dispatch(request, call_next)
        assert request.state._cached_body == body
        crl.assert_awaited_once_with(request, _hash_api_key("och_abc"), "oncall_users")

    async def test_rate_limited_response_is_returned_and_logged(self):
        request = _make_request(
            headers={
                "Authorization": "Bearer och_abc",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "analysis_start",
            },
            body=self._tool_call("analysis_start"),
        )
        limited = MagicMock(status_code=429)
        call_next = AsyncMock()
        with (
            patch(
                "oncallhealth_mcp.infrastructure.middleware.check_rate_limit",
                new=AsyncMock(return_value=limited),
            ),
            patch(
                "oncallhealth_mcp.infrastructure.middleware.log_rate_limit_hit"
            ) as log,
        ):
            response = await self._middleware().dispatch(request, call_next)
        assert response is limited
        log.assert_called_once_with(
            _hash_api_key("och_abc"), "analysis_start", "5/minute"
        )
        call_next.assert_not_called()

    async def test_non_tool_methods_skip_rate_limit(self):
        request = _make_request(
            headers={"Authorization": "Bearer och_abc", "Mcp-Method": "tools/list"},
            body=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            ).encode(),
        )
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        with patch(
            "oncallhealth_mcp.infrastructure.middleware.check_rate_limit"
        ) as crl:
            await self._middleware().dispatch(request, call_next)
        crl.assert_not_called()
