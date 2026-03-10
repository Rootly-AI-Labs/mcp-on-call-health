"""Tests for CodeMode integration and related migration changes.

Verifies that the FastMCP server is configured with standalone fastmcp and
CodeMode enabled, that tool functions accept ctx as a keyword argument (last
parameter with default), and that the CLI HTTP transport uses
mcp_server.http_app().
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode

from oncallhealth_mcp.server import (
    _validate_api_key,
    analysis_start,
    analysis_status,
    mcp_server,
)


class TestServerCodeModeConfiguration:
    """Verify the MCP server is configured with standalone fastmcp and CodeMode."""

    def test_server_is_fastmcp_instance(self):
        """mcp_server must be an instance of fastmcp.FastMCP."""
        assert isinstance(mcp_server, FastMCP)

    def test_server_has_code_mode_transform(self):
        """mcp_server must have a CodeMode instance in its transforms list."""
        transforms = mcp_server._transforms
        assert transforms is not None, "transforms attribute not found on mcp_server"
        assert len(transforms) >= 1, "Expected at least one transform"

        has_code_mode = any(isinstance(t, CodeMode) for t in transforms)
        assert has_code_mode, f"CodeMode not found in transforms: {transforms}"

    def test_server_name(self):
        """Server name must be 'On-Call Health'."""
        assert mcp_server.name == "On-Call Health"


def _get_underlying_fn(tool_obj):
    """Extract the underlying function from a FunctionTool or return as-is."""
    return getattr(tool_obj, "fn", tool_obj)


class TestContextInjection:
    """Verify tool functions accept ctx as a keyword argument after the migration."""

    def test_analysis_start_ctx_is_keyword_with_default(self):
        """analysis_start must accept ctx with a default value (CurrentContext())."""
        fn = _get_underlying_fn(analysis_start)
        sig = inspect.signature(fn)
        assert "ctx" in sig.parameters

        ctx_param = sig.parameters["ctx"]
        assert ctx_param.default is not inspect.Parameter.empty, (
            "ctx parameter should have a default value (CurrentContext())"
        )

    def test_analysis_status_ctx_is_keyword_with_default(self):
        """analysis_status must accept ctx with a default value (CurrentContext())."""
        fn = _get_underlying_fn(analysis_status)
        sig = inspect.signature(fn)
        assert "ctx" in sig.parameters

        ctx_param = sig.parameters["ctx"]
        assert ctx_param.default is not inspect.Parameter.empty, (
            "ctx parameter should have a default value (CurrentContext())"
        )

    def test_ctx_is_last_parameter(self):
        """ctx must be the last parameter in tool function signatures."""
        for tool_obj in (analysis_start, analysis_status):
            fn = _get_underlying_fn(tool_obj)
            params = list(inspect.signature(fn).parameters.keys())
            assert params[-1] == "ctx", (
                f"Expected ctx as last parameter in {fn.__name__}, "
                f"got parameter order: {params}"
            )

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    def test_validate_api_key_with_duck_typed_context(self, mock_extract):
        """_validate_api_key works with any object via duck-typing (getattr)."""
        mock_extract.return_value = "duck-typed-key"

        ctx = object()
        result = _validate_api_key(ctx)

        assert result == "duck-typed-key"
        mock_extract.assert_called_once_with(ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    def test_validate_api_key_with_mock_context(self, mock_extract):
        """_validate_api_key works with MagicMock standing in for Context."""
        mock_extract.return_value = "mock-key"

        ctx = MagicMock()
        result = _validate_api_key(ctx)

        assert result == "mock-key"
        mock_extract.assert_called_once_with(ctx)


class TestCliHttpApp:
    """Verify that HTTP transport calls mcp_server.http_app()."""

    @patch("oncallhealth_mcp.cli.validate_config")
    @patch("oncallhealth_mcp.cli.setup_logging")
    @patch("sys.argv", ["oncallhealth-mcp", "--transport", "http", "--port", "9999"])
    def test_http_transport_calls_http_app(self, mock_logging, mock_validate):
        """When transport is http, main() calls mcp_server.http_app() and uvicorn.run()."""
        mock_app = MagicMock(name="asgi_app")
        mock_server = MagicMock(name="mcp_server")
        mock_server.http_app.return_value = mock_app

        mock_uvicorn = MagicMock(name="uvicorn")

        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}):
            with patch("oncallhealth_mcp.server.mcp_server", mock_server):
                from oncallhealth_mcp.cli import main

                with pytest.raises(SystemExit) as exc_info:
                    main()

                assert exc_info.value.code == 0
                mock_server.http_app.assert_called_once()
                mock_uvicorn.run.assert_called_once_with(
                    mock_app, host="127.0.0.1", port=9999
                )
