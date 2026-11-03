"""Tests for the server factory, Code Mode opt-in and context injection."""

import inspect
import os
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode

from oncallhealth_mcp.server import (
    TOOL_SPECS,
    _validate_api_key,
    analysis_start,
    analysis_status,
    build_server,
    code_mode_from_env,
    mcp_server,
)

CODE_MODE_META_TOOLS = {"search", "get_schema", "execute"}
CATALOG_TOOL_NAMES = {fn.__name__ for fn, _ in TOOL_SPECS}


def _has_code_mode(server: FastMCP) -> bool:
    return any(isinstance(t, CodeMode) for t in (server._transforms or []))


class TestServerFactory:
    """build_server() produces the On-Call Health catalog."""

    def test_default_server_is_fastmcp_instance(self):
        assert isinstance(mcp_server, FastMCP)
        assert mcp_server.name == "On-Call Health"

    def test_code_mode_off_by_default(self, monkeypatch):
        monkeypatch.delenv("ONCALLHEALTH_CODE_MODE", raising=False)
        assert code_mode_from_env() is False
        assert not _has_code_mode(build_server())

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_code_mode_env_enables(self, monkeypatch, value):
        monkeypatch.setenv("ONCALLHEALTH_CODE_MODE", value)
        assert code_mode_from_env() is True
        assert _has_code_mode(build_server())

    @pytest.mark.parametrize("value", ["0", "false", "", "off"])
    def test_code_mode_env_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("ONCALLHEALTH_CODE_MODE", value)
        assert code_mode_from_env() is False

    def test_explicit_flag_overrides_env(self, monkeypatch):
        monkeypatch.setenv("ONCALLHEALTH_CODE_MODE", "1")
        assert not _has_code_mode(build_server(code_mode=False))
        monkeypatch.delenv("ONCALLHEALTH_CODE_MODE")
        assert _has_code_mode(build_server(code_mode=True))

    async def test_catalog_lists_every_tool_with_annotations(self):
        async with Client(build_server(code_mode=False)) as client:
            tools = {t.name: t for t in await client.list_tools()}
        assert set(tools) == CATALOG_TOOL_NAMES
        for name, tool in tools.items():
            assert tool.annotations is not None, name
            assert tool.annotations.read_only_hint is not None, name
            assert tool.description, name
        assert tools["analysis_start"].annotations.read_only_hint is False
        assert tools["analysis_run"].annotations.read_only_hint is False
        assert tools["analysis_summary"].annotations.read_only_hint is True

    async def test_tools_publish_structured_output_schemas(self):
        async with Client(build_server(code_mode=False)) as client:
            tools = {t.name: t for t in await client.list_tools()}
        summary_schema = tools["analysis_summary"].output_schema
        assert summary_schema is not None
        assert "top_at_risk" in summary_schema["properties"]
        check_schema = tools["check_users_risk"].input_schema
        assert check_schema["properties"]["rootly_user_ids"]["type"] == "array"
        assert check_schema["properties"]["rootly_user_ids"]["items"] == {
            "type": "integer"
        }

    async def test_code_mode_exposes_meta_tools_only(self):
        async with Client(build_server(code_mode=True)) as client:
            names = {t.name for t in await client.list_tools()}
        assert names == CODE_MODE_META_TOOLS

    async def test_server_metadata_and_resources(self):
        async with Client(build_server(code_mode=False)) as client:
            assert client.protocol_version == "2026-07-28"
            assert client.instructions and "analysis_run" in client.instructions
            resources = {r.uri for r in await client.list_resources()}
            templates = {t.uri_template for t in await client.list_resource_templates()}
            prompts = {p.name for p in await client.list_prompts()}
        assert str(
            next(iter(r for r in resources if "methodology" in str(r)))
        ).startswith("oncallhealth://")
        assert "oncallhealth://analyses/{analysis_id}/summary" in templates
        assert prompts == {"weekly_brief", "investigate_responder"}

    def test_cache_hints_keep_account_data_private(self):
        hints = build_server(code_mode=False)._mcp_server.cache_hints
        assert hints["resources/read"].scope == "private"
        assert all(hint.scope == "private" for hint in hints.values())

    async def test_legacy_clients_see_the_same_catalog(self):
        async with Client(build_server(code_mode=False), mode="legacy") as client:
            assert client.protocol_version != "2026-07-28"
            names = {t.name for t in await client.list_tools()}
        assert names == CATALOG_TOOL_NAMES


class TestContextInjection:
    """Tool functions accept ctx as the last keyword argument with a default."""

    @pytest.mark.parametrize("fn", [analysis_start, analysis_status])
    def test_ctx_is_last_parameter_with_default(self, fn):
        params = inspect.signature(fn).parameters
        assert list(params)[-1] == "ctx"
        assert params["ctx"].default is not inspect.Parameter.empty

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    def test_validate_api_key_with_duck_typed_context(self, mock_extract):
        mock_extract.return_value = "duck-typed-key"
        ctx = object()
        assert _validate_api_key(ctx) == "duck-typed-key"
        mock_extract.assert_called_once_with(ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    def test_validate_api_key_with_mock_context(self, mock_extract):
        mock_extract.return_value = "mock-key"
        ctx = MagicMock()
        assert _validate_api_key(ctx) == "mock-key"


class TestCliCodeMode:
    """The CLI wires --code-mode / ONCALLHEALTH_CODE_MODE into build_server()."""

    @patch("oncallhealth_mcp.cli.validate_config")
    @patch("oncallhealth_mcp.cli.setup_logging")
    def test_stdio_builds_server_without_code_mode_by_default(self, _log, _val):
        from oncallhealth_mcp.cli import main

        mock_server = MagicMock(name="mcp_server")
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("sys.argv", ["oncallhealth-mcp"]),
            patch(
                "oncallhealth_mcp.server.build_server", return_value=mock_server
            ) as b,
        ):
            os.environ.pop("ONCALLHEALTH_CODE_MODE", None)
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        b.assert_called_once_with(code_mode=False)
        mock_server.run.assert_called_once()

    @patch("oncallhealth_mcp.cli.validate_config")
    @patch("oncallhealth_mcp.cli.setup_logging")
    def test_code_mode_flag(self, _log, _val):
        from oncallhealth_mcp.cli import main

        mock_server = MagicMock(name="mcp_server")
        with (
            patch("sys.argv", ["oncallhealth-mcp", "--code-mode"]),
            patch(
                "oncallhealth_mcp.server.build_server", return_value=mock_server
            ) as b,
        ):
            with pytest.raises(SystemExit):
                main()
        b.assert_called_once_with(code_mode=True)

    @patch("oncallhealth_mcp.cli.validate_config")
    @patch("oncallhealth_mcp.cli.setup_logging")
    def test_http_transport_uses_hosted_app(self, _log, _val):
        from oncallhealth_mcp.cli import main

        mock_app = MagicMock(name="asgi_app")
        mock_uvicorn = MagicMock(name="uvicorn")
        with (
            patch.dict("sys.modules", {"uvicorn": mock_uvicorn}),
            patch(
                "sys.argv",
                ["oncallhealth-mcp", "--transport", "http", "--port", "9999"],
            ),
            patch(
                "oncallhealth_mcp.transport.create_http_app", return_value=mock_app
            ) as create,
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        create.assert_called_once_with(code_mode=False)
        mock_uvicorn.run.assert_called_once_with(mock_app, host="127.0.0.1", port=9999)
