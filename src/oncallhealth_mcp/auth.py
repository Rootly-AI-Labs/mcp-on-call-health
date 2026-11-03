"""Authentication for MCP tools.

Two deployment shapes are supported:

* **stdio** (local clients such as Claude Desktop, Cursor, Claude Code): the
  API key comes from the ``ONCALLHEALTH_API_KEY`` environment variable.
* **Streamable HTTP** (hosted): FastMCP's auth layer verifies the bearer token
  on every request with :class:`OnCallHealthKeyVerifier`, so unauthenticated
  requests are rejected with 401 before any tool runs. Tools then read the
  verified key back through :func:`extract_api_key_header`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token, get_http_headers

from oncallhealth_mcp.client import AuthenticationError, OnCallHealthClient

logger = logging.getLogger(__name__)

API_KEY_ENV = "ONCALLHEALTH_API_KEY"
API_KEY_HEADER = "X-API-Key"
API_KEY_PREFIX = "och_"
API_KEY_CLIENT_ID = "oncallhealth-api-key"

# Cheap, read-only endpoint that accepts X-API-Key; used to validate a key.
_VALIDATION_PATH = "/analyses"
_VALIDATION_PARAMS = {"limit": 1}


def _normalize_header_value(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip() or None


def _parse_bearer_token(value: str | None) -> str | None:
    value = _normalize_header_value(value)
    if not value:
        return None
    parts = value.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _key_digest(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _verified_api_key() -> str | None:
    """API key from the bearer token FastMCP's auth layer already verified."""
    try:
        token = get_access_token()
    except Exception:  # no auth context (stdio, tests)
        return None
    if token is None or token.client_id != API_KEY_CLIENT_ID:
        return None
    return _normalize_header_value(token.token)


def _header_api_key() -> str | None:
    """API key from the raw HTTP request, for HTTP apps built without auth."""
    headers = get_http_headers(include_all=True)
    key = _normalize_header_value(headers.get(API_KEY_HEADER.lower()))
    if key:
        return key
    return _parse_bearer_token(headers.get("authorization"))


def extract_api_key_header(ctx: Any = None) -> str | None:
    """Resolve the API key for the current request.

    Priority:
    1. Bearer token verified by :class:`OnCallHealthKeyVerifier` (hosted HTTP)
    2. ``X-API-Key`` / ``Authorization`` headers on the current HTTP request
    3. ``ONCALLHEALTH_API_KEY`` environment variable (stdio)

    ``ctx`` is accepted for backward compatibility and is not inspected: the
    MCP ``Context`` no longer carries request headers.
    """
    return _verified_api_key() or _header_api_key() or _env_api_key()


def _env_api_key() -> str | None:
    return _normalize_header_value(os.getenv(API_KEY_ENV))


class OnCallHealthKeyVerifier(TokenVerifier):
    """Verify ``Authorization: Bearer och_...`` tokens against the backend.

    A key is accepted when it has the On-Call Health prefix and a cheap
    read-only request to the API succeeds with it. Successful checks are
    cached (by SHA-256 of the key) so steady-state requests cost no extra
    round trip; failures are never cached.
    """

    def __init__(
        self,
        *,
        cache_ttl_seconds: float = 300.0,
        max_cache_entries: int = 1000,
    ) -> None:
        super().__init__()
        self._cache_ttl_seconds = cache_ttl_seconds
        self._max_cache_entries = max_cache_entries
        self._valid_until: dict[str, float] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        api_key = _normalize_header_value(token)
        if not api_key or not api_key.startswith(API_KEY_PREFIX):
            return None

        digest = _key_digest(api_key)
        now = time.monotonic()
        if self._valid_until.get(digest, 0.0) > now:
            return self._access_token(api_key, digest)

        if not await self._check_with_backend(api_key):
            self._valid_until.pop(digest, None)
            return None

        self._remember(digest, now)
        return self._access_token(api_key, digest)

    def clear_cache(self) -> None:
        self._valid_until.clear()

    def _remember(self, digest: str, now: float) -> None:
        if (
            len(self._valid_until) >= self._max_cache_entries
            and digest not in self._valid_until
        ):
            oldest = min(self._valid_until, key=self._valid_until.__getitem__)
            del self._valid_until[oldest]
        self._valid_until[digest] = now + self._cache_ttl_seconds

    @staticmethod
    def _access_token(api_key: str, digest: str) -> AccessToken:
        # fastmcp_tasks scopes task ownership on ``client_id|claims["sub"]``;
        # every key needs its own ``sub`` or all keys would share one scope.
        return AccessToken(
            token=api_key,
            client_id=API_KEY_CLIENT_ID,
            scopes=[],
            subject=digest[:16],
            claims={"sub": digest},
        )

    @staticmethod
    async def _check_with_backend(api_key: str) -> bool:
        try:
            async with OnCallHealthClient(api_key=api_key) as client:
                await client.get(_VALIDATION_PATH, params=_VALIDATION_PARAMS)
        except AuthenticationError:
            return False
        except Exception as exc:
            # Backend unavailable or unexpected failure: fail closed but say why.
            logger.warning("API key validation failed (rejecting request): %s", exc)
            return False
        return True
