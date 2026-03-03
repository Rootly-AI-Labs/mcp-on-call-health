"""Tests for connection state tracking."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from oncallhealth_mcp.infrastructure.connection_tracker import (
    MAX_CONNECTIONS_PER_KEY,
    ConnectionState,
)


@pytest.fixture
def tracker():
    """Fresh ConnectionState for each test."""
    return ConnectionState()


class TestAddConnection:
    """Test ConnectionState.add_connection()."""

    @pytest.mark.asyncio
    async def test_add_returns_true(self, tracker):
        result = await tracker.add_connection(1, "conn-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_tracks_connection(self, tracker):
        await tracker.add_connection(1, "conn-1")
        count = await tracker.get_connection_count(1)
        assert count == 1

    @pytest.mark.asyncio
    async def test_sets_last_activity(self, tracker):
        await tracker.add_connection(1, "conn-1")
        assert "conn-1" in tracker.last_activity

    @pytest.mark.asyncio
    async def test_multiple_connections(self, tracker):
        for i in range(3):
            await tracker.add_connection(1, f"conn-{i}")
        count = await tracker.get_connection_count(1)
        assert count == 3

    @pytest.mark.asyncio
    async def test_rejects_at_limit(self, tracker):
        for i in range(MAX_CONNECTIONS_PER_KEY):
            result = await tracker.add_connection(1, f"conn-{i}")
            assert result is True

        # One more should be rejected
        result = await tracker.add_connection(1, f"conn-{MAX_CONNECTIONS_PER_KEY}")
        assert result is False

    @pytest.mark.asyncio
    async def test_different_keys_independent(self, tracker):
        """Each API key has its own connection limit."""
        for i in range(MAX_CONNECTIONS_PER_KEY):
            await tracker.add_connection(1, f"key1-conn-{i}")

        # Different key should still be allowed
        result = await tracker.add_connection(2, "key2-conn-0")
        assert result is True


class TestRemoveConnection:
    """Test ConnectionState.remove_connection()."""

    @pytest.mark.asyncio
    async def test_decrements_count(self, tracker):
        await tracker.add_connection(1, "conn-1")
        await tracker.add_connection(1, "conn-2")
        await tracker.remove_connection(1, "conn-1")
        count = await tracker.get_connection_count(1)
        assert count == 1

    @pytest.mark.asyncio
    async def test_cleans_activity(self, tracker):
        await tracker.add_connection(1, "conn-1")
        await tracker.remove_connection(1, "conn-1")
        assert "conn-1" not in tracker.last_activity

    @pytest.mark.asyncio
    async def test_cleans_empty_key(self, tracker):
        """Empty key sets should be removed to prevent memory growth."""
        await tracker.add_connection(1, "conn-1")
        await tracker.remove_connection(1, "conn-1")
        assert 1 not in tracker.connections

    @pytest.mark.asyncio
    async def test_remove_nonexistent_no_error(self, tracker):
        """Removing a connection that doesn't exist should not raise."""
        await tracker.remove_connection(99, "no-such-conn")

    @pytest.mark.asyncio
    async def test_frees_slot(self, tracker):
        """After removal, a new connection should be allowed."""
        for i in range(MAX_CONNECTIONS_PER_KEY):
            await tracker.add_connection(1, f"conn-{i}")

        # At limit
        assert await tracker.add_connection(1, "extra") is False

        # Remove one
        await tracker.remove_connection(1, "conn-0")

        # Now should be allowed
        assert await tracker.add_connection(1, "extra") is True


class TestUpdateActivity:
    """Test ConnectionState.update_activity()."""

    @pytest.mark.asyncio
    async def test_updates_timestamp(self, tracker):
        await tracker.add_connection(1, "conn-1")
        old_ts = tracker.last_activity["conn-1"]

        await asyncio.sleep(0.01)
        await tracker.update_activity("conn-1")

        new_ts = tracker.last_activity["conn-1"]
        assert new_ts > old_ts

    @pytest.mark.asyncio
    async def test_unknown_connection_no_error(self, tracker):
        """Updating activity for unknown connection should not raise."""
        await tracker.update_activity("no-such-conn")


class TestGetStaleConnections:
    """Test ConnectionState.get_stale_connections()."""

    @pytest.mark.asyncio
    async def test_returns_stale(self, tracker):
        await tracker.add_connection(1, "old-conn")
        # Manually set old activity
        tracker.last_activity["old-conn"] = datetime(2020, 1, 1, tzinfo=timezone.utc)

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        stale = await tracker.get_stale_connections(cutoff)
        assert len(stale) == 1
        assert stale[0] == (1, "old-conn")

    @pytest.mark.asyncio
    async def test_excludes_fresh(self, tracker):
        await tracker.add_connection(1, "fresh-conn")
        # Activity was just set by add_connection

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        stale = await tracker.get_stale_connections(cutoff)
        assert len(stale) == 0

    @pytest.mark.asyncio
    async def test_empty_tracker(self, tracker):
        cutoff = datetime.now(timezone.utc)
        stale = await tracker.get_stale_connections(cutoff)
        assert stale == []


class TestGetConnectionCount:
    """Test ConnectionState.get_connection_count()."""

    @pytest.mark.asyncio
    async def test_zero_for_unknown_key(self, tracker):
        count = await tracker.get_connection_count(999)
        assert count == 0

    @pytest.mark.asyncio
    async def test_accurate_count(self, tracker):
        await tracker.add_connection(1, "a")
        await tracker.add_connection(1, "b")
        assert await tracker.get_connection_count(1) == 2


class TestConcurrency:
    """Test thread-safety with concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_add_respects_limit(self, tracker):
        """Concurrent adds should not exceed MAX_CONNECTIONS_PER_KEY."""
        results = await asyncio.gather(
            *[tracker.add_connection(1, f"conn-{i}") for i in range(MAX_CONNECTIONS_PER_KEY + 5)]
        )
        accepted = sum(1 for r in results if r is True)
        assert accepted == MAX_CONNECTIONS_PER_KEY

    @pytest.mark.asyncio
    async def test_concurrent_add_remove(self, tracker):
        """Concurrent add and remove should not corrupt state."""
        # Add some connections first
        for i in range(3):
            await tracker.add_connection(1, f"conn-{i}")

        # Concurrently remove and add
        await asyncio.gather(
            tracker.remove_connection(1, "conn-0"),
            tracker.remove_connection(1, "conn-1"),
            tracker.add_connection(1, "conn-new"),
        )

        count = await tracker.get_connection_count(1)
        # conn-2 + conn-new = 2 (conn-0 and conn-1 removed)
        assert count == 2
