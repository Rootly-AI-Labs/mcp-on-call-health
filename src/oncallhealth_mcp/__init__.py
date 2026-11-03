"""
oncallhealth-mcp: MCP server for On-Call Health analysis.

This package provides an MCP (Model Context Protocol) server that enables
AI assistants to access On-Call Health analysis features.

Usage:
    # Run via uvx (recommended)
    uvx oncallhealth-mcp

    # Or as a module
    python -m oncallhealth_mcp

    # Or via console script after pip install
    oncallhealth-mcp

Configuration:
    ONCALLHEALTH_API_KEY: Your On-Call Health API key (required)
    ONCALLHEALTH_API_URL: API base URL (default: https://api.oncallhealth.ai)
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("oncallhealth-mcp")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0+unknown"

# Convenience exports
from oncallhealth_mcp.client import ClientConfig, OnCallHealthClient
from oncallhealth_mcp.server import mcp_server

__all__ = [
    "__version__",
    "mcp_server",
    "OnCallHealthClient",
    "ClientConfig",
]
