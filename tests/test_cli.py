"""Tests for CLI entry point."""

import logging
import os
from unittest.mock import patch

import pytest

from oncallhealth_mcp.cli import parse_args, setup_logging, validate_config


class TestParseArgs:
    """Test parse_args()."""

    def test_defaults(self):
        with patch("sys.argv", ["oncallhealth-mcp"]):
            args = parse_args()
        assert args.transport == "stdio"
        assert args.host == "127.0.0.1"
        assert args.port == 8000
        assert args.verbose is False

    def test_http_transport(self):
        with patch("sys.argv", ["oncallhealth-mcp", "--transport", "http"]):
            args = parse_args()
        assert args.transport == "http"

    def test_custom_host_port(self):
        with patch(
            "sys.argv", ["oncallhealth-mcp", "--host", "0.0.0.0", "--port", "9000"]
        ):
            args = parse_args()
        assert args.host == "0.0.0.0"
        assert args.port == 9000

    def test_verbose(self):
        with patch("sys.argv", ["oncallhealth-mcp", "-v"]):
            args = parse_args()
        assert args.verbose is True

    def test_verbose_long(self):
        with patch("sys.argv", ["oncallhealth-mcp", "--verbose"]):
            args = parse_args()
        assert args.verbose is True

    def test_invalid_transport(self):
        with patch("sys.argv", ["oncallhealth-mcp", "--transport", "grpc"]):
            with pytest.raises(SystemExit):
                parse_args()


class TestSetupLogging:
    """Test setup_logging()."""

    def test_verbose_passes_debug_level(self):
        """Verbose mode should configure with DEBUG level."""
        with patch("oncallhealth_mcp.cli.logging.basicConfig") as mock_basic:
            setup_logging(verbose=True)
            mock_basic.assert_called_once()
            assert mock_basic.call_args[1]["level"] == logging.DEBUG

    def test_default_passes_info_level(self):
        """Default mode should configure with INFO level."""
        with patch("oncallhealth_mcp.cli.logging.basicConfig") as mock_basic:
            setup_logging(verbose=False)
            mock_basic.assert_called_once()
            assert mock_basic.call_args[1]["level"] == logging.INFO


class TestValidateConfig:
    """Test validate_config()."""

    def test_exits_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ONCALLHEALTH_API_KEY", None)
            with pytest.raises(SystemExit) as exc_info:
                validate_config()
            assert exc_info.value.code == 1

    def test_passes_with_api_key(self):
        with patch.dict(os.environ, {"ONCALLHEALTH_API_KEY": "test-key"}):
            validate_config()  # Should not raise
