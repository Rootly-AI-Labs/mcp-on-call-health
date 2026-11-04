# oncallhealth-mcp

[![PyPI version](https://badge.fury.io/py/oncallhealth-mcp.svg)](https://badge.fury.io/py/oncallhealth-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

MCP server for [On-Call Health](https://oncallhealth.ai) burnout analysis. Connects AI assistants to your on-call data for workload insights.

<!-- mcp-name: io.github.Rootly-AI-Labs/oncallhealth-mcp -->

## Prerequisites

- An On-Call Health account at [oncallhealth.ai](https://oncallhealth.ai)
- An API key from [oncallhealth.ai/settings/api-keys](https://oncallhealth.ai/settings/api-keys)

## Installation

The server runs locally over stdio with `uvx` (no install step) and reads the API key from the `ONCALLHEALTH_API_KEY` environment variable. Pick your client:

### Claude Code

```bash
claude mcp add oncallhealth --env ONCALLHEALTH_API_KEY=och_live_... -- uvx oncallhealth-mcp
```

### Claude Desktop

Add to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "oncallhealth": {
      "command": "uvx",
      "args": ["oncallhealth-mcp"],
      "env": { "ONCALLHEALTH_API_KEY": "och_live_your_api_key_here" }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project (or `~/.cursor/mcp.json` for global):

```json
{
  "mcpServers": {
    "oncallhealth": {
      "command": "uvx",
      "args": ["oncallhealth-mcp"],
      "env": { "ONCALLHEALTH_API_KEY": "och_live_your_api_key_here" }
    }
  }
}
```

### VS Code / GitHub Copilot

Add to `.vscode/mcp.json` in your project:

```json
{
  "servers": {
    "oncallhealth": {
      "command": "uvx",
      "args": ["oncallhealth-mcp"],
      "env": { "ONCALLHEALTH_API_KEY": "och_live_your_api_key_here" }
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "oncallhealth": {
      "command": "uvx",
      "args": ["oncallhealth-mcp"],
      "env": { "ONCALLHEALTH_API_KEY": "och_live_your_api_key_here" }
    }
  }
}
```

### Codex CLI

```bash
codex mcp add oncallhealth --env ONCALLHEALTH_API_KEY=och_live_... -- uvx oncallhealth-mcp
```

### Gemini CLI

```bash
gemini mcp add oncallhealth -e ONCALLHEALTH_API_KEY=och_live_... uvx oncallhealth-mcp
```

### Manual / other clients

```bash
pip install oncallhealth-mcp
export ONCALLHEALTH_API_KEY=och_live_...
oncallhealth-mcp
```

Or run without installing: `ONCALLHEALTH_API_KEY=och_live_... uvx oncallhealth-mcp`.

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ONCALLHEALTH_API_KEY` | Yes (stdio) | - | API key from oncallhealth.ai |
| `ONCALLHEALTH_API_URL` | No | `https://api.oncallhealth.ai` | API endpoint URL |
| `ONCALLHEALTH_CODE_MODE` | No | off | `1` exposes the catalog through Code Mode meta-tools (see below) |
| `ONCALLHEALTH_POLL_INTERVAL` | No | `5.0` | Seconds between status checks inside `analysis_run` (backs off to `ONCALLHEALTH_POLL_MAX_INTERVAL`, default `30.0`) |
| `ONCALLHEALTH_MCP_ALLOWED_HOSTS` | No | - | HTTP only: comma-separated host names that enable the Host/Origin DNS-rebinding guard |

Request timeouts, retries and circuit-breaker settings are also configurable; see `oncallhealth_mcp/client/config.py`.

### Security note

Avoid committing API keys to version control. Use environment variables or a secrets manager instead of hardcoding keys in config files.

## Protocol compatibility

The server implements MCP revision **2026-07-28** (stateless Streamable HTTP, `Mcp-Method`/`Mcp-Name` routing headers, cacheable list results, the Tasks extension) and negotiates older revisions per connection, so clients on the 2025 handshake-era protocol keep working. Every tool publishes annotations (read-only, idempotent, open-world) and a structured output schema. The deprecated HTTP+SSE transport is not served.

## Tools

Start with `validate_integrations`, then `analysis_current` (or `analysis_run` for a fresh analysis), then `analysis_summary` and the member-level tools.

| Tool | What it does |
|------|--------------|
| `validate_integrations` | Check that every connected integration has valid credentials. `force_refresh` bypasses the backend cache. |
| `integrations_list` | List connected Rootly, GitHub, Slack, Jira and Linear integrations. |
| `oncall_users` | Who is currently on call for a Rootly integration (`integration_id`). |
| `analysis_current` | Metadata of the most recent analysis (status, timestamps, config). |
| `analysis_run` | Start an analysis and wait for it: `days_back` (default 30), `include_weekends`, `integration_id`, `wait_timeout_seconds` (default 600). Returns the team summary. Runs as a background task for clients that support the MCP Tasks extension, inline otherwise, with progress messages while waiting. |
| `analysis_start` | Start an analysis without waiting. Poll with `analysis_status`. |
| `analysis_status` | Status and metadata of an analysis (`analysis_id`). |
| `analysis_summary` | Team averages, risk distribution, top five at-risk and healthiest members. |
| `analysis_results` | Full raw payload of a completed analysis (large; prefer the focused tools). |
| `get_at_risk_users` | Members at or above `min_och_score` (default 50) in `include_risk_levels` (default `["medium", "high"]`), with Rootly/PagerDuty/Slack/GitHub IDs. |
| `get_safe_responders` | Members at or below `max_och_score` (default 30) who could take extra shifts, up to `limit`. |
| `check_users_risk` | Risk check for specific `rootly_user_ids` (list of integers), split into at-risk, healthy and not-found. |
| `member_daily_health` | Day-by-day health, incident and after-hours breakdown for `member_email`. |

OCH scores run 0-100; higher means more at risk. Scores inform staffing decisions and are not a medical diagnosis.

## Resources

| URI | Content |
|-----|---------|
| `oncallhealth://methodology` | Short description of the scoring methodology |
| `oncallhealth://analyses/latest` | Metadata of the most recent analysis (JSON) |
| `oncallhealth://analyses/{analysis_id}/summary` | Team summary of a completed analysis (JSON) |

## Prompts

| Prompt | Arguments | Purpose |
|--------|-----------|---------|
| `weekly_brief` | `team_name` | Weekly on-call health brief with follow-up actions |
| `investigate_responder` | `member_email`, `analysis_id` | Dig into one responder's trend and recommend shift changes |

## Code Mode (optional)

With `--code-mode` or `ONCALLHEALTH_CODE_MODE=1` the catalog is exposed through FastMCP Code Mode: three meta-tools (`search`, `get_schema`, `execute`) let an agent discover tools on demand and chain calls in a sandboxed Python snippet. It saves context when an agent needs many calls per task, at the cost of hiding the tool list, annotations and output schemas from clients that read them directly. Off by default.

## CLI reference

```
usage: oncallhealth-mcp [-h] [--transport {stdio,http}] [--host HOST]
                        [--port PORT] [--code-mode] [-v] [--version]

options:
  --transport {stdio,http}  Transport to use (default: stdio)
  --host HOST               Host to bind to (http transport only, default: 127.0.0.1)
  --port PORT               Port to bind to (http transport only, default: 8000)
  --code-mode               Expose the catalog through Code Mode meta-tools
  -v, --verbose             Enable verbose logging
  --version                 show program's version number and exit
```

## Hosted deployment (Streamable HTTP)

`oncallhealth-mcp --transport http` (or the Docker image, which runs `uvicorn oncallhealth_mcp.transport:mcp_http_app`) serves:

- `POST /mcp`: stateless Streamable HTTP MCP endpoint
- `GET /health`: unauthenticated health check

Every MCP request must carry the user's API key as `Authorization: Bearer och_...`; `X-API-Key: och_...` is accepted as well. Keys are verified against the On-Call Health API (successful checks are cached for five minutes) and unauthenticated requests get `401` before any tool runs. Tool calls are rate limited per key and per tool (for example `analysis_run` and `analysis_start` at 5/minute) identified from the JSON-RPC body, with `429` and `Retry-After` on excess.

Example remote client configuration (Claude Code):

```bash
claude mcp add --transport http oncallhealth https://your-host/mcp --header "Authorization: Bearer och_live_..."
```

Because the server is stateless you can run several uvicorn workers or replicas. For `analysis_run` background tasks to be shared across workers, point FastMCP's task backend at Redis or Valkey with `FASTMCP_DOCKET_URL`; the default in-memory backend is per process.

Set `ONCALLHEALTH_MCP_ALLOWED_HOSTS=mcp.example.com` to enable FastMCP's Host/Origin DNS-rebinding guard for the public host name.

```bash
docker build -t oncallhealth-mcp .
docker run -p 8080:8080 oncallhealth-mcp
```

## Links

- [On-Call Health](https://oncallhealth.ai) - Main website
- [API Documentation](https://api.oncallhealth.ai/docs) - REST API docs
- [GitHub Issues](https://github.com/Rootly-AI-Labs/mcp-on-call-health/issues) - Report bugs

## License

Apache-2.0
