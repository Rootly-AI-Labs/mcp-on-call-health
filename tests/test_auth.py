"""Tests for auth helpers."""
import os
from unittest.mock import patch

import pytest

from oncallhealth_mcp.auth import (
    _get_header,
    _normalize_header_value,
    _parse_bearer_token,
    extract_api_key_header,
    extract_bearer_token,
)


class TestNormalizeHeaderValue:
    """Test _normalize_header_value()."""

    def test_none_returns_none(self):
        assert _normalize_header_value(None) is None

    def test_empty_string_returns_none(self):
        assert _normalize_header_value("") is None

    def test_strips_whitespace(self):
        assert _normalize_header_value("  value  ") == "value"

    def test_normal_value(self):
        assert _normalize_header_value("abc") == "abc"


class TestParseBearerToken:
    """Test _parse_bearer_token()."""

    def test_valid_bearer(self):
        assert _parse_bearer_token("Bearer my-token-123") == "my-token-123"

    def test_bearer_case_insensitive(self):
        assert _parse_bearer_token("bearer my-token") == "my-token"
        assert _parse_bearer_token("BEARER my-token") == "my-token"

    def test_none_returns_none(self):
        assert _parse_bearer_token(None) is None

    def test_empty_returns_none(self):
        assert _parse_bearer_token("") is None

    def test_no_bearer_prefix(self):
        assert _parse_bearer_token("my-token") is None

    def test_bearer_only_no_token(self):
        assert _parse_bearer_token("Bearer") is None

    def test_extra_parts(self):
        # "Bearer a b" splits into 3 parts, doesn't match len==2
        assert _parse_bearer_token("Bearer a b") is None

    def test_whitespace_stripped(self):
        assert _parse_bearer_token("  Bearer  tok  ") == "tok"


class TestGetHeader:
    """Test _get_header()."""

    def test_none_headers(self):
        assert _get_header(None, "X-API-Key") is None

    def test_dict_exact_match(self):
        headers = {"X-API-Key": "abc"}
        assert _get_header(headers, "X-API-Key") == "abc"

    def test_dict_lowercase_fallback(self):
        headers = {"x-api-key": "abc"}
        assert _get_header(headers, "X-API-Key") == "abc"

    def test_dict_uppercase_fallback(self):
        headers = {"X-API-KEY": "abc"}
        assert _get_header(headers, "X-API-Key") == "abc"

    def test_dict_case_insensitive_iteration(self):
        # When direct lookups fail, falls back to iterating items()
        headers = {"x-Api-Key": "abc"}
        assert _get_header(headers, "X-API-Key") == "abc"

    def test_dict_missing_key(self):
        headers = {"Authorization": "Bearer tok"}
        assert _get_header(headers, "X-API-Key") is None

    def test_object_with_items(self):
        """Works with any object that has .items()."""

        class HeaderLike:
            def items(self):
                return [("x-api-key", "val")]

        assert _get_header(HeaderLike(), "X-API-Key") == "val"

    def test_object_without_get_or_items(self):
        """Returns None for objects without header access."""
        assert _get_header(42, "X-API-Key") is None


class TestExtractBearerToken:
    """Test extract_bearer_token()."""

    def test_from_request_headers(self):
        class Ctx:
            request_headers = {"Authorization": "Bearer tok-1"}

        assert extract_bearer_token(Ctx()) == "tok-1"

    def test_from_headers(self):
        class Ctx:
            request_headers = None
            headers = {"Authorization": "Bearer tok-2"}

        assert extract_bearer_token(Ctx()) == "tok-2"

    def test_from_request_dot_headers(self):
        class Req:
            headers = {"Authorization": "Bearer tok-3"}

        class Ctx:
            request_headers = None
            headers = {}
            request = Req()

        assert extract_bearer_token(Ctx()) == "tok-3"

    def test_no_token_anywhere(self):
        class Ctx:
            request_headers = {}
            headers = {}
            request = None

        assert extract_bearer_token(Ctx()) is None

    def test_priority_request_headers_first(self):
        """request_headers takes priority over headers."""

        class Ctx:
            request_headers = {"Authorization": "Bearer first"}
            headers = {"Authorization": "Bearer second"}

        assert extract_bearer_token(Ctx()) == "first"


class TestExtractApiKeyHeader:
    """Test extract_api_key_header()."""

    def test_env_var_priority(self):
        """Environment variable takes priority over headers."""

        class Ctx:
            headers = {"X-API-Key": "header-key"}

        with patch.dict(os.environ, {"ONCALLHEALTH_API_KEY": "env-key"}):
            assert extract_api_key_header(Ctx()) == "env-key"

    def test_header_fallback(self):
        """Falls back to header when env var not set."""

        class Ctx:
            headers = {"X-API-Key": "header-key"}

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ONCALLHEALTH_API_KEY", None)
            assert extract_api_key_header(Ctx()) == "header-key"

    def test_request_headers_attr(self):
        class Ctx:
            request_headers = {"X-API-Key": "rh-key"}
            headers = {}

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ONCALLHEALTH_API_KEY", None)
            assert extract_api_key_header(Ctx()) == "rh-key"

    def test_request_dot_headers(self):
        class Req:
            headers = {"X-API-Key": "req-key"}

        class Ctx:
            request_headers = {}
            headers = {}
            request = Req()

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ONCALLHEALTH_API_KEY", None)
            assert extract_api_key_header(Ctx()) == "req-key"

    def test_no_key_anywhere(self):
        class Ctx:
            request_headers = {}
            headers = {}
            request = None

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ONCALLHEALTH_API_KEY", None)
            assert extract_api_key_header(Ctx()) is None

    def test_whitespace_stripped(self):
        class Ctx:
            headers = {"X-API-Key": "  my-key  "}

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ONCALLHEALTH_API_KEY", None)
            assert extract_api_key_header(Ctx()) == "my-key"
