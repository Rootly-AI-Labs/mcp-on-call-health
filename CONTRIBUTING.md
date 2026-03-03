# Contributing to On-Call Health MCP Server

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/on-call-health/oncallhealth-mcp.git
   cd oncallhealth-mcp
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install in development mode**

   ```bash
   make install
   ```

   Or manually:

   ```bash
   pip install -e ".[test,server]"
   pip install pre-commit ruff mypy
   pre-commit install
   ```

## Running Tests

```bash
make test
```

Run a specific test file:

```bash
pytest tests/test_auth.py -v
```

Run with coverage report:

```bash
pytest tests/ --cov=oncallhealth_mcp --cov-report=html
open htmlcov/index.html
```

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
make lint      # Check for issues
make format    # Auto-fix formatting
```

Pre-commit hooks will run these checks automatically before each commit.

## Making Changes

1. **Create a branch** from `main`:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Write tests first** - we follow test-driven development where practical.

3. **Keep changes focused** - one feature or fix per PR.

4. **Run the full test suite** before submitting:

   ```bash
   make check
   ```

## Pull Request Process

1. Update the `CHANGELOG.md` with your changes under the "Unreleased" section.
2. Ensure all tests pass and linting is clean.
3. Fill out the PR template with a description and test plan.
4. Request review from a maintainer.

## Adding New MCP Tools

When adding a new tool to `server.py`:

1. Add the tool function with `@mcp_server.tool()` decorator.
2. Add input validation at the top of the function.
3. Add a normalizer in `normalizers.py` if the REST response needs transformation.
4. Add rate limits in `infrastructure/rate_limiter.py`.
5. Write tests covering: happy path, validation errors, not found, and missing API key.

## Reporting Issues

- Use the [bug report template](https://github.com/on-call-health/oncallhealth-mcp/issues/new?template=bug_report.yml) for bugs.
- Use the [feature request template](https://github.com/on-call-health/oncallhealth-mcp/issues/new?template=feature_request.yml) for new ideas.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
