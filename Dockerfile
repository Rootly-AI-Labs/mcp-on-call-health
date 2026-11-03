# Multi-stage Dockerfile for the On-Call Health MCP server (Streamable HTTP)
# Dependencies are installed from uv.lock so the image is reproducible.

# =============================================================================
# Stage 1: Builder - resolve the locked dependency set into a virtualenv
# =============================================================================
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Install third-party dependencies first so this layer is cached across code changes
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project --extra server

# Install the project itself (non-editable so src/ is not needed at runtime)
COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable --extra server

# =============================================================================
# Stage 2: Runtime - minimal image for production
# =============================================================================
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Create non-root user for security
RUN groupadd -r mcpuser && useradd -r -g mcpuser mcpuser

# Copy the populated virtualenv from the builder stage
COPY --from=builder --chown=mcpuser:mcpuser /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Set Python to run unbuffered (important for Docker logging)
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER mcpuser

# Expose MCP server port
EXPOSE 8080

# Health check for container orchestrators
# Uses Python urllib to avoid adding curl/wget to minimal image
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run the Streamable HTTP app with uvicorn
CMD ["uvicorn", "oncallhealth_mcp.transport:mcp_http_app", "--host", "0.0.0.0", "--port", "8080"]
