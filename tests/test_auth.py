"""Tests for API key resolution and the bearer-token verifier."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oncallhealth_mcp.auth import (
    API_KEY_CLIENT_ID,
    OnCallHealthKeyVerifier,
    _normalize_header_value,
    _parse_bearer_token,
    extract_api_key_header,
)
from oncallhealth_mcp.client import AuthenticationError, ServiceUnavailableError


class TestNormalizeHeaderValue:
    def test_none_returns_none(self):
        assert _normalize_header_value(None) is None

    def test_empty_string_returns_none(self):
        assert _normalize_header_value("") is None

    def test_whitespace_only_returns_none(self):
        assert _normalize_header_value("   ") is None

    def test_strips_whitespace(self):
        assert _normalize_header_value("  abc  ") == "abc"


class TestParseBearerToken:
    def test_valid_bearer(self):
        assert _parse_bearer_token("Bearer och_123") == "och_123"

    def test_bearer_case_insensitive(self):
        assert _parse_bearer_token("bearer och_123") == "och_123"
        assert _parse_bearer_token("BEARER och_123") == "och_123"

    @pytest.mark.parametrize("value", [None, "", "och_123", "Bearer", "Bearer a b"])
    def test_invalid_values(self, value):
        assert _parse_bearer_token(value) is None


def _access_token(token="och_verified", client_id=API_KEY_CLIENT_ID):
    return MagicMock(token=token, client_id=client_id)


class TestExtractApiKeyHeader:
    """Priority: verified bearer token, then request headers, then env var."""

    def test_verified_token_wins(self):
        with (
            patch(
                "oncallhealth_mcp.auth.get_access_token", return_value=_access_token()
            ),
            patch(
                "oncallhealth_mcp.auth.get_http_headers",
                return_value={"x-api-key": "och_hdr"},
            ),
            patch.dict(os.environ, {"ONCALLHEALTH_API_KEY": "och_env"}),
        ):
            assert extract_api_key_header() == "och_verified"

    def test_token_from_other_provider_is_ignored(self):
        with (
            patch(
                "oncallhealth_mcp.auth.get_access_token",
                return_value=_access_token(client_id="some-oauth-client"),
            ),
            patch("oncallhealth_mcp.auth.get_http_headers", return_value={}),
            patch.dict(os.environ, {"ONCALLHEALTH_API_KEY": "och_env"}),
        ):
            assert extract_api_key_header() == "och_env"

    def test_x_api_key_header_fallback(self):
        with (
            patch("oncallhealth_mcp.auth.get_access_token", return_value=None),
            patch(
                "oncallhealth_mcp.auth.get_http_headers",
                return_value={"x-api-key": " och_hdr "},
            ),
            patch.dict(os.environ, {"ONCALLHEALTH_API_KEY": "och_env"}),
        ):
            assert extract_api_key_header() == "och_hdr"

    def test_authorization_header_fallback(self):
        with (
            patch("oncallhealth_mcp.auth.get_access_token", return_value=None),
            patch(
                "oncallhealth_mcp.auth.get_http_headers",
                return_value={"authorization": "Bearer och_bearer"},
            ),
            patch.dict(os.environ, {}, clear=True),
        ):
            assert extract_api_key_header() == "och_bearer"

    def test_env_var_fallback(self):
        with (
            patch("oncallhealth_mcp.auth.get_access_token", return_value=None),
            patch("oncallhealth_mcp.auth.get_http_headers", return_value={}),
            patch.dict(os.environ, {"ONCALLHEALTH_API_KEY": " och_env "}),
        ):
            assert extract_api_key_header(MagicMock()) == "och_env"

    def test_no_key_anywhere(self):
        with (
            patch("oncallhealth_mcp.auth.get_access_token", return_value=None),
            patch("oncallhealth_mcp.auth.get_http_headers", return_value={}),
            patch.dict(os.environ, {}, clear=True),
        ):
            assert extract_api_key_header() is None

    def test_get_access_token_errors_are_swallowed(self):
        with (
            patch(
                "oncallhealth_mcp.auth.get_access_token",
                side_effect=RuntimeError("no ctx"),
            ),
            patch("oncallhealth_mcp.auth.get_http_headers", return_value={}),
            patch.dict(os.environ, {"ONCALLHEALTH_API_KEY": "och_env"}),
        ):
            assert extract_api_key_header() == "och_env"


def _mock_backend(mock_client_class, side_effect=None):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    if side_effect is not None:
        client.get.side_effect = side_effect
    mock_client_class.return_value = client
    return client


class TestOnCallHealthKeyVerifier:
    async def test_rejects_keys_without_prefix(self):
        verifier = OnCallHealthKeyVerifier()
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client_class:
            assert await verifier.verify_token("sk-not-ours") is None
            assert await verifier.verify_token("   ") is None
        mock_client_class.assert_not_called()

    async def test_valid_key_is_checked_against_backend(self):
        verifier = OnCallHealthKeyVerifier()
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client_class:
            client = _mock_backend(mock_client_class)
            token = await verifier.verify_token("och_live_abcd")

        assert token is not None
        assert token.token == "och_live_abcd"
        assert token.client_id == API_KEY_CLIENT_ID
        assert token.subject and "och_" not in token.subject
        mock_client_class.assert_called_once_with(api_key="och_live_abcd")
        client.get.assert_awaited_once_with("/analyses", params={"limit": 1})

    async def test_each_key_gets_its_own_task_scope(self):
        """fastmcp_tasks scopes task ownership on client_id|claims["sub"]."""
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client:
            _mock_backend(mock_client)
            verifier = OnCallHealthKeyVerifier()
            first = await verifier.verify_token("och_live_first")
            second = await verifier.verify_token("och_live_second")
        assert first is not None and second is not None
        assert first.claims["sub"] and second.claims["sub"]
        assert first.claims["sub"] != second.claims["sub"]
        assert "och_" not in first.claims["sub"]

    async def test_successful_check_is_cached(self):
        verifier = OnCallHealthKeyVerifier(cache_ttl_seconds=60)
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client_class:
            _mock_backend(mock_client_class)
            await verifier.verify_token("och_live_abcd")
            await verifier.verify_token("och_live_abcd")
        assert mock_client_class.call_count == 1

    async def test_cache_expires(self):
        verifier = OnCallHealthKeyVerifier(cache_ttl_seconds=0)
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client_class:
            _mock_backend(mock_client_class)
            await verifier.verify_token("och_live_abcd")
            await verifier.verify_token("och_live_abcd")
        assert mock_client_class.call_count == 2

    async def test_cache_is_bounded(self):
        verifier = OnCallHealthKeyVerifier(max_cache_entries=2)
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client_class:
            _mock_backend(mock_client_class)
            for suffix in ("a", "b", "c"):
                await verifier.verify_token(f"och_{suffix}")
        assert len(verifier._valid_until) == 2

    async def test_rejected_key_is_not_cached(self):
        verifier = OnCallHealthKeyVerifier()
        error = AuthenticationError("bad key")
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client_class:
            _mock_backend(mock_client_class, side_effect=error)
            assert await verifier.verify_token("och_bad") is None
            assert await verifier.verify_token("och_bad") is None
        assert mock_client_class.call_count == 2
        assert verifier._valid_until == {}

    async def test_backend_outage_fails_closed(self, caplog):
        verifier = OnCallHealthKeyVerifier()
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client_class:
            _mock_backend(
                mock_client_class, side_effect=ServiceUnavailableError("down")
            )
            assert await verifier.verify_token("och_live_abcd") is None
        assert "rejecting request" in caplog.text

    async def test_clear_cache(self):
        verifier = OnCallHealthKeyVerifier()
        with patch("oncallhealth_mcp.auth.OnCallHealthClient") as mock_client_class:
            _mock_backend(mock_client_class)
            await verifier.verify_token("och_live_abcd")
            verifier.clear_cache()
            await verifier.verify_token("och_live_abcd")
        assert mock_client_class.call_count == 2
