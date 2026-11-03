"""CLI entry point for oncallhealth-mcp server."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import NoReturn

from oncallhealth_mcp import __version__


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="oncallhealth-mcp",
        description="MCP server for On-Call Health analysis",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport to use (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (http transport only, default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (http transport only, default: 8000)",
    )
    parser.add_argument(
        "--code-mode",
        action="store_true",
        default=None,
        help=(
            "Expose the catalog through FastMCP Code Mode meta-tools "
            "(search/get_schema/execute) instead of the 13 tools directly. "
            "Also enabled by ONCALLHEALTH_CODE_MODE=1."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args()


# Third-party loggers that are chatty at INFO (task worker, HTTP client).
_NOISY_LOGGERS = ("docket", "httpx2", "httpcore2")


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the server.

    Logs go to stderr (stdout is the MCP stdio channel). FastMCP's startup
    banner and PyPI update check are disabled so a stdio launch stays quiet
    and offline.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    if not verbose:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    import fastmcp

    fastmcp.settings.show_server_banner = False
    fastmcp.settings.check_for_updates = "off"


def validate_config() -> None:
    """Validate required configuration is present."""
    api_key = os.environ.get("ONCALLHEALTH_API_KEY")
    if not api_key:
        print(
            "Error: ONCALLHEALTH_API_KEY environment variable is required.\n\n"
            "Set it with:\n"
            "  export ONCALLHEALTH_API_KEY=your_api_key\n\n"
            "Or pass it inline:\n"
            "  ONCALLHEALTH_API_KEY=your_api_key oncallhealth-mcp",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> NoReturn:
    """Main entry point for the CLI."""
    args = parse_args()
    setup_logging(args.verbose)
    validate_config()

    # Import server lazily to avoid import errors before validation
    from oncallhealth_mcp.server import build_server, code_mode_from_env

    code_mode = args.code_mode if args.code_mode is not None else code_mode_from_env()

    logger = logging.getLogger(__name__)
    logger.info(
        f"Starting On-Call Health MCP server "
        f"(transport={args.transport}, code_mode={code_mode})"
    )

    if args.transport == "stdio":
        # Run with stdio transport
        build_server(code_mode=code_mode).run()
    else:
        # Run with HTTP transport using uvicorn
        try:
            import uvicorn
        except ImportError:
            print(
                "Error: uvicorn is required for HTTP transport.\n"
                "Install with: pip install uvicorn",
                file=sys.stderr,
            )
            sys.exit(1)

        # Full hosted app: /mcp (stateless Streamable HTTP, bearer API keys,
        # rate limiting) plus /health
        from oncallhealth_mcp.transport import create_http_app

        app = create_http_app(code_mode=code_mode)
        uvicorn.run(app, host=args.host, port=args.port)

    sys.exit(0)


if __name__ == "__main__":
    main()
