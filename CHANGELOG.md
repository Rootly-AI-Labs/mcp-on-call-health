# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.1] - 2026-11-04

### Fixed
- MCP Registry name uses the GitHub organization's capitalization,
  `io.github.Rootly-AI-Labs/oncallhealth-mcp`, which is the namespace the
  registry grants to this repository. No code changes.

## [0.4.0] - 2026-11-04

Alignment with MCP revision 2026-07-28 and FastMCP 4.

### Added
- `analysis_run`: starts an analysis, waits for completion with progress
  messages, and returns the team summary. Task-enabled through the MCP Tasks
  extension (`io.modelcontextprotocol/tasks`); runs inline for clients without
  task support.
- Tool annotations (read-only / idempotent / open-world hints), structured
  output schemas and parameter descriptions on every tool; server
  `instructions`, version, website and cache hints (`ttlMs`, `cacheScope`).
- Resource templates `oncallhealth://analyses/latest` and
  `oncallhealth://analyses/{analysis_id}/summary`; prompt `investigate_responder`.
- `--code-mode` flag and `ONCALLHEALTH_CODE_MODE` environment variable.
- Hosted HTTP mode: bearer-token verification of On-Call Health API keys
  through FastMCP's auth layer (`OnCallHealthKeyVerifier`), `X-API-Key`
  compatibility shim, `Mcp-Name` header-based rate limiting, optional
  Host/Origin guard (`ONCALLHEALTH_MCP_ALLOWED_HOSTS`).
- `server.json` for the MCP Registry; `uv.lock` as the single pinned
  dependency source; manual publish workflow.

### Changed
- **Breaking:** `check_users_risk.rootly_user_ids` is a list of integers and
  `get_at_risk_users.include_risk_levels` is a list of `low|medium|high`
  (previously comma-separated strings).
- **Breaking:** Code Mode is off by default (it hid the 13 tools behind
  `search`/`get_schema`/`execute` meta-tools).
- Requires `fastmcp>=4.1.5` (MCP Python SDK 2.x, protocol 2026-07-28 with
  per-connection negotiation for older clients) and `pydantic>=2.12`.
- `--transport http` now serves the full hosted app (`/mcp`, `/health`,
  auth, rate limiting) instead of a bare FastMCP app.
- Dependabot watches `uv.lock`; the Docker image installs from the lock file
  on Python 3.12.
- Version is read from package metadata (`oncallhealth-mcp --version`).

### Removed
- Legacy HTTP+SSE endpoint and `mcp-session-id` CORS headers (the protocol is
  stateless).
- Connection tracking and stale-connection cleanup modules (they modelled
  protocol sessions that no longer exist).
- `requirements.txt` (superseded by `pyproject.toml` + `uv.lock`).

## [0.3.0] - 2026-03
- In-memory TTL cache for completed analysis results.

## [0.2.0] - 2026-03-10
- FastMCP Code Mode.

## [0.1.0]
- Initial release.
