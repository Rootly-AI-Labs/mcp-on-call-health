# oncallhealth-mcp

[![PyPI version](https://badge.fury.io/py/oncallhealth-mcp.svg)](https://badge.fury.io/py/oncallhealth-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

MCP server for [On-Call Health](https://oncallhealth.ai) burnout analysis. Connects AI assistants to your on-call data for workload insights.

## Prerequisites

- An On-Call Health account at [oncallhealth.ai](https://oncallhealth.ai)
- An API key from [oncallhealth.ai/settings/api-keys](https://oncallhealth.ai/settings/api-keys)

## Installation

Pick your editor or client below and follow the instructions.

### Claude Code

```bash
claude mcp add oncallhealth -e ONCALLHEALTH_API_KEY=och_live_... -- uvx oncallhealth-mcp
```

### Claude Desktop

Add to your `claude_desktop_config.json`:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "oncallhealth": {
      "command": "uvx",
      "args": ["oncallhealth-mcp"],
      "env": {
        "ONCALLHEALTH_API_KEY": "och_live_your_api_key_here"
      }
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
      "env": {
        "ONCALLHEALTH_API_KEY": "och_live_your_api_key_here"
      }
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
      "env": {
        "ONCALLHEALTH_API_KEY": "och_live_your_api_key_here"
      }
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
      "env": {
        "ONCALLHEALTH_API_KEY": "och_live_your_api_key_here"
      }
    }
  }
}
```

### Manual / Other Clients

Install from PyPI:

```bash
pip install oncallhealth-mcp
```

Run the server:

```bash
export ONCALLHEALTH_API_KEY=och_live_...
oncallhealth-mcp
```

Or run without installing using `uvx`:

```bash
ONCALLHEALTH_API_KEY=och_live_... uvx oncallhealth-mcp
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ONCALLHEALTH_API_KEY` | Yes | - | API key from oncallhealth.ai |
| `ONCALLHEALTH_API_URL` | No | `https://api.oncallhealth.ai` | API endpoint URL |

### Security Note

Avoid committing API keys to version control. Use environment variables or a secrets manager instead of hardcoding keys in config files.

## Available Tools

### analysis_start

Start a new burnout analysis for your on-call data.

**Parameters:**
- `days_back` (int, default: 30): Number of days to analyze
- `include_weekends` (bool, default: true): Include weekend data
- `integration_id` (int, optional): Specific integration to analyze

### analysis_status

Check the status of a running analysis.

**Parameters:**
- `analysis_id` (int): ID of the analysis to check

### analysis_results

Get full results for a completed analysis.

**Parameters:**
- `analysis_id` (int): ID of the completed analysis

### analysis_current

Get the most recent analysis for your account.

**Parameters:** None

### integrations_list

List all connected integrations (Rootly, GitHub, Slack, Jira, Linear).

**Parameters:** None

## Resources

### oncallhealth://methodology

Provides a brief description of the On-Call Health methodology for measuring workload and burnout risk.

## Prompts

### weekly_brief

Template for generating a weekly on-call health summary.

**Parameters:**
- `team_name` (str): Name of the team to summarize

## CLI Reference

```
usage: oncallhealth-mcp [-h] [--transport {stdio,http}] [--host HOST]
                        [--port PORT] [-v] [--version]

options:
  -h, --help            show this help message and exit
  --transport {stdio,http}
                        Transport to use (default: stdio)
  --host HOST           Host to bind to (http transport only, default: 127.0.0.1)
  --port PORT           Port to bind to (http transport only, default: 8000)
  -v, --verbose         Enable verbose logging
  --version             show program's version number and exit
```

### Transport Options

- **stdio** (default): Standard input/output transport. Used by Claude Desktop and most MCP clients.
- **http**: HTTP transport with Server-Sent Events. Useful for web-based clients or debugging.

## Links

- [On-Call Health](https://oncallhealth.ai) - Main website
- [API Documentation](https://api.oncallhealth.ai/docs) - REST API docs
- [GitHub Issues](https://github.com/Rootly-AI-Labs/MCP-On-Call-Health/issues) - Report bugs

## License

Apache-2.0
