"""Tests for stale connection cleanup."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from oncallhealth_mcp.infrastructure.cleanup import (
    STALE_CONNECTION_TIMEOUT_MINUTES,
    cleanup_stale_connections,
    get_cleanup_job_config,
)


class TestCleanupStaleConnections:
    """Test cleanup_stale_connections()."""

    @pytest.mark.asyncio
    async def test_no_stale_connections_is_noop(self):
        with patch(
            "oncallhealth_mcp.infrastructure.cleanup.connection_tracker"
        ) as mock_tracker:
            mock_tracker.get_stale_connections = AsyncMock(return_value=[])
            await cleanup_stale_connections()
            mock_tracker.remove_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_removes_stale_connections(self):
        stale = [(1, "conn-a"), (2, "conn-b")]
        with patch(
            "oncallhealth_mcp.infrastructure.cleanup.connection_tracker"
        ) as mock_tracker:
            mock_tracker.get_stale_connections = AsyncMock(return_value=stale)
            mock_tracker.remove_connection = AsyncMock()

            await cleanup_stale_connections()

            assert mock_tracker.remove_connection.call_count == 2
            mock_tracker.remove_connection.assert_any_call(1, "conn-a")
            mock_tracker.remove_connection.assert_any_call(2, "conn-b")

    @pytest.mark.asyncio
    async def test_uses_correct_cutoff_time(self):
        with patch(
            "oncallhealth_mcp.infrastructure.cleanup.connection_tracker"
        ) as mock_tracker:
            mock_tracker.get_stale_connections = AsyncMock(return_value=[])
            before = datetime.now(timezone.utc)

            await cleanup_stale_connections()

            call_args = mock_tracker.get_stale_connections.call_args[0][0]
            expected_cutoff = before - timedelta(
                minutes=STALE_CONNECTION_TIMEOUT_MINUTES
            )
            # Cutoff should be within 1 second of expected
            assert abs((call_args - expected_cutoff).total_seconds()) < 1

    @pytest.mark.asyncio
    async def test_continues_on_individual_connection_error(self):
        stale = [(1, "conn-a"), (2, "conn-b"), (3, "conn-c")]
        with patch(
            "oncallhealth_mcp.infrastructure.cleanup.connection_tracker"
        ) as mock_tracker:
            mock_tracker.get_stale_connections = AsyncMock(return_value=stale)
            mock_tracker.remove_connection = AsyncMock(
                side_effect=[None, RuntimeError("db error"), None]
            )

            # Should not raise despite error on conn-b
            await cleanup_stale_connections()
            assert mock_tracker.remove_connection.call_count == 3

    @pytest.mark.asyncio
    async def test_handles_tracker_error_gracefully(self):
        with patch(
            "oncallhealth_mcp.infrastructure.cleanup.connection_tracker"
        ) as mock_tracker:
            mock_tracker.get_stale_connections = AsyncMock(
                side_effect=RuntimeError("redis down")
            )
            # Should not raise
            await cleanup_stale_connections()


class TestGetCleanupJobConfig:
    """Test get_cleanup_job_config()."""

    def test_returns_cleanup_function(self):
        config = get_cleanup_job_config()
        assert config["func"] is cleanup_stale_connections

    def test_returns_job_id(self):
        config = get_cleanup_job_config()
        assert config["id"] == "mcp_connection_cleanup"

    def test_replace_existing_is_true(self):
        config = get_cleanup_job_config()
        assert config["replace_existing"] is True
