# Contributing to On-Call Health MCP Server

Thank you for your interest in contributing! This guide will help you get started.

## Development setup

The project uses [uv](https://docs.astral.sh/uv/) and a committed `uv.lock`.

```bash
git clone https://github.com/Rootly-AI-Labs/mcp-on-call-health.git
cd mcp-on-call-health
uv sync --frozen --extra test --extra server   # also installs the dev group (ruff, mypy)
```

## Running tests

```bash
uv run pytest                     # full suite with coverage (see pyproject addopts)
uv run pytest tests/test_auth.py -v
uv run pytest -o addopts="" -q    # fast run without coverage
```

## Code style

```bash
uv run ruff check src/ tests/          # lint (add --fix to apply safe fixes)
uv run ruff format src/ tests/         # format
uv run mypy                            # type check src/oncallhealth_mcp
```

CI runs the same three commands plus the test matrix (Python 3.10-3.13).

## Trying the server

```bash
ONCALLHEALTH_API_KEY=och_live_... uv run oncallhealth-mcp            # stdio
ONCALLHEALTH_API_KEY=och_live_... uv run oncallhealth-mcp --code-mode
uv run oncallhealth-mcp --transport http --port 8000                  # hosted app on /mcp + /health
```

Point an MCP client at the stdio command or at `http://127.0.0.1:8000/mcp` with
`Authorization: Bearer och_live_...`.

## Making changes

1. Create a branch from `main`.
2. Write tests first where practical.
3. Keep changes focused: one feature or fix per PR.
4. Run `uv run ruff check`, `uv run ruff format --check`, `uv run mypy` and `uv run pytest` before opening the PR.
5. Add an entry under "Unreleased" in `CHANGELOG.md`.

## Adding a tool

Tools are plain async functions in `src/oncallhealth_mcp/server.py`, registered through `TOOL_SPECS` by `build_server()`:

1. Write the function with `Annotated[..., Field(description=...)]` parameters, a `TypedDict` return type from `schemas.py`, and `ctx: Context = CurrentContext()` as the last parameter.
2. Validate inputs at the top and resolve the key with `_validate_api_key(ctx)`.
3. Add a normalizer in `normalizers.py` if the REST response needs transformation.
4. Append `(fn, {"annotations": READ_ONLY | STARTS_ANALYSIS, "tags": {...}})` to `TOOL_SPECS`.
5. Add a rate limit in `infrastructure/rate_limiter.py` and document the tool in `README.md`.
6. Cover: happy path, validation errors, not found, and missing API key.

## Releasing

Releases are manual. Bump `version` in `pyproject.toml` and `server.json`, update `CHANGELOG.md`, tag, then run the "Publish" workflow (PyPI via trusted publishing, then the MCP Registry via `mcp-publisher`).

## Reporting issues

Open an issue at https://github.com/Rootly-AI-Labs/mcp-on-call-health/issues.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
