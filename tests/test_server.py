"""Unit tests for On-Call Health MCP server."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from oncallhealth_mcp.client.exceptions import NotFoundError
from oncallhealth_mcp.server import (
    _validate_analysis_id,
    _validate_api_key,
)


class TestHelperFunctions:
    """Tests for validation helper functions."""

    def test_validate_analysis_id_positive(self):
        """Test validation passes for positive analysis ID."""
        _validate_analysis_id(1)
        _validate_analysis_id(1226)
        _validate_analysis_id(999999)

    def test_validate_analysis_id_zero(self):
        """Test validation fails for zero."""
        with pytest.raises(ValueError, match="analysis_id must be positive, got 0"):
            _validate_analysis_id(0)

    def test_validate_analysis_id_negative(self):
        """Test validation fails for negative ID."""
        with pytest.raises(ValueError, match="analysis_id must be positive, got -1"):
            _validate_analysis_id(-1)
        with pytest.raises(ValueError, match="analysis_id must be positive, got -100"):
            _validate_analysis_id(-100)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    def test_validate_api_key_present(self, mock_extract):
        """Test validation passes when API key is present."""
        mock_extract.return_value = "test-api-key"
        ctx = MagicMock()

        result = _validate_api_key(ctx)

        assert result == "test-api-key"
        mock_extract.assert_called_once_with(ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    def test_validate_api_key_missing(self, mock_extract):
        """Test validation fails when API key is missing."""
        mock_extract.return_value = None
        ctx = MagicMock()

        with pytest.raises(PermissionError, match="Missing API key"):
            _validate_api_key(ctx)


class TestAnalysisSummary:
    """Tests for analysis_summary tool (bug fix verification)."""

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_analysis_summary_reads_correct_path(
        self, mock_client_class, mock_extract, sample_analysis_summary_response
    ):
        """Test that analysis_summary reads members from team_analysis.members."""
        mock_extract.return_value = "test-api-key"

        # Mock the response object
        mock_response = MagicMock()
        mock_response.json.return_value = sample_analysis_summary_response

        # Mock the client
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        # Import and call the function
        from oncallhealth_mcp.server import analysis_summary

        ctx = MagicMock()
        result = await analysis_summary(1226, ctx=ctx)

        # Verify it correctly counts members from team_analysis.members
        assert result["total_members"] == 2
        assert "User 1" in str(result)
        assert "User 2" in str(result)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_analysis_summary_empty_members(
        self, mock_client_class, mock_extract
    ):
        """Test analysis_summary with no members."""
        mock_extract.return_value = "test-api-key"

        # Mock the response object
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 1226,
            "status": "completed",
            "analysis_data": {
                "team_analysis": {"members": []},
                "team_health": {
                    "overall_score": 0,
                    "risk_distribution": {
                        "low": 0,
                        "medium": 0,
                        "high": 0,
                        "critical": 0,
                    },
                },
            },
        }

        # Mock the client
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        from oncallhealth_mcp.server import analysis_summary

        ctx = MagicMock()
        result = await analysis_summary(1226, ctx=ctx)

        assert result["total_members"] == 0


class TestGetAtRiskUsers:
    """Tests for get_at_risk_users tool."""

    def _setup_mock_client(self, mock_client_class, mock_extract, response_data):
        """Helper to setup mock client with correct async context manager pattern."""
        mock_extract.return_value = "test-api-key"

        # Mock the response object
        mock_response = MagicMock()
        mock_response.json.return_value = response_data

        # Mock the client with async context manager support
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        return mock_client

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_default_params(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test get_at_risk_users with default parameters."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        result = await get_at_risk_users(1226, ctx=ctx)

        # Default: min_och_score=50.0, include_risk_levels="medium,high"
        # Should return Quentin (72.5, high), Diana (68.0, HIGH), Bob (55.0, medium)
        assert result["total_at_risk"] == 3
        assert len(result["users"]) == 3

        # Verify sorted by OCH score (highest first)
        assert result["users"][0]["user_name"] == "Quentin Rousseau"
        assert result["users"][0]["och_score"] == 72.5
        assert result["users"][1]["user_name"] == "Diana Prince"
        assert result["users"][1]["och_score"] == 68.0
        assert result["users"][2]["user_name"] == "Bob Smith"
        assert result["users"][2]["och_score"] == 55.0

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_custom_threshold(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test get_at_risk_users with custom min_och_score."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        result = await get_at_risk_users(1226, min_och_score=70.0, ctx=ctx)

        # Only Quentin (72.5) should be returned
        assert result["total_at_risk"] == 1
        assert result["users"][0]["user_name"] == "Quentin Rousseau"

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_high_only(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test get_at_risk_users filtering only high risk."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        result = await get_at_risk_users(1226, include_risk_levels="high", ctx=ctx)

        # Should return Quentin (high) and Diana (HIGH - case insensitive)
        assert result["total_at_risk"] == 2
        assert result["users"][0]["user_name"] == "Quentin Rousseau"
        assert result["users"][1]["user_name"] == "Diana Prince"

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_case_insensitive_risk_levels(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test that risk level comparison is case-insensitive."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        # Diana has risk_level="HIGH" (uppercase)
        result = await get_at_risk_users(
            1226, include_risk_levels="HIGH,MEDIUM", ctx=ctx
        )

        # Should include Diana (HIGH) and Bob (medium)
        assert (
            result["total_at_risk"] == 3
        )  # Quentin (high), Diana (HIGH), Bob (medium)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_no_results(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test get_at_risk_users with criteria matching no users."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        result = await get_at_risk_users(1226, min_och_score=100.0, ctx=ctx)

        assert result["total_at_risk"] == 0
        assert result["users"] == []

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_includes_external_ids(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test that result includes all external integration IDs."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        result = await get_at_risk_users(1226, min_och_score=70.0, ctx=ctx)

        user = result["users"][0]
        assert user["rootly_user_id"] == 2381
        assert user["pagerduty_user_id"] == "P123ABC"
        assert user["slack_user_id"] == "U012345"
        assert user["github_username"] == "quentinr"

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_missing_analysis_data(
        self, mock_client_class, mock_extract
    ):
        """Test get_at_risk_users handles missing analysis_data gracefully."""
        mock_extract.return_value = "test-api-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 1226,
            "status": "completed",
            # Missing analysis_data entirely
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        result = await get_at_risk_users(1226, ctx=ctx)

        assert result["total_at_risk"] == 0
        assert result["users"] == []

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_missing_team_analysis(
        self, mock_client_class, mock_extract
    ):
        """Test get_at_risk_users handles missing team_analysis gracefully."""
        mock_extract.return_value = "test-api-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 1226,
            "status": "completed",
            "analysis_data": {
                # Missing team_analysis
            },
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        result = await get_at_risk_users(1226, ctx=ctx)

        assert result["total_at_risk"] == 0
        assert result["users"] == []

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_at_risk_users_missing_members(
        self, mock_client_class, mock_extract
    ):
        """Test get_at_risk_users handles missing members list gracefully."""
        mock_extract.return_value = "test-api-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 1226,
            "status": "completed",
            "analysis_data": {
                "team_analysis": {
                    # Missing members
                }
            },
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        from oncallhealth_mcp.server import get_at_risk_users

        ctx = MagicMock()
        result = await get_at_risk_users(1226, ctx=ctx)

        assert result["total_at_risk"] == 0
        assert result["users"] == []


class TestGetSafeResponders:
    """Tests for get_safe_responders tool."""

    def _setup_mock_client(self, mock_client_class, mock_extract, response_data):
        """Helper to setup mock client with correct async context manager pattern."""
        mock_extract.return_value = "test-api-key"

        # Mock the response object
        mock_response = MagicMock()
        mock_response.json.return_value = response_data

        # Mock the client with async context manager support
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        return mock_client

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_safe_responders_default_params(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test get_safe_responders with default parameters."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_safe_responders

        ctx = MagicMock()
        result = await get_safe_responders(1226, ctx=ctx)

        # Default: max_och_score=30.0, limit=10
        # Should return Alice (12.3) and Carol (25.0)
        assert result["total_safe"] == 2
        assert len(result["users"]) == 2

        # Verify sorted by OCH score (lowest first)
        assert result["users"][0]["user_name"] == "Alice Johnson"
        assert result["users"][0]["och_score"] == 12.3
        assert result["users"][1]["user_name"] == "Carol Davis"
        assert result["users"][1]["och_score"] == 25.0

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_safe_responders_custom_threshold(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test get_safe_responders with custom max_och_score."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_safe_responders

        ctx = MagicMock()
        result = await get_safe_responders(1226, max_och_score=15.0, ctx=ctx)

        # Only Alice (12.3) should be returned
        assert result["total_safe"] == 1
        assert result["users"][0]["user_name"] == "Alice Johnson"

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_safe_responders_limit(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test get_safe_responders respects limit parameter."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_safe_responders

        ctx = MagicMock()
        result = await get_safe_responders(1226, max_och_score=30.0, limit=1, ctx=ctx)

        # Should return only 1 user even though 2 qualify
        assert result["total_safe"] == 2  # Total qualifying
        assert len(result["users"]) == 1  # Limited to 1
        assert result["users"][0]["user_name"] == "Alice Johnson"

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_safe_responders_no_results(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test get_safe_responders with criteria matching no users."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import get_safe_responders

        ctx = MagicMock()
        result = await get_safe_responders(1226, max_och_score=5.0, ctx=ctx)

        assert result["total_safe"] == 0
        assert result["users"] == []

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_get_safe_responders_missing_analysis_data(
        self, mock_client_class, mock_extract
    ):
        """Test get_safe_responders handles missing analysis_data gracefully."""
        mock_extract.return_value = "test-api-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 1226,
            "status": "completed",
            # Missing analysis_data entirely
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        from oncallhealth_mcp.server import get_safe_responders

        ctx = MagicMock()
        result = await get_safe_responders(1226, ctx=ctx)

        assert result["total_safe"] == 0
        assert result["users"] == []


class TestCheckUsersRisk:
    """Tests for check_users_risk tool."""

    def _setup_mock_client(self, mock_client_class, mock_extract, response_data):
        """Helper to setup mock client with correct async context manager pattern."""
        mock_extract.return_value = "test-api-key"

        # Mock the response object
        mock_response = MagicMock()
        mock_response.json.return_value = response_data

        # Mock the client with async context manager support
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        return mock_client

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_check_users_risk_mixed_results(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test check_users_risk with mix of at_risk, healthy, not_found."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()
        # Quentin (2381) = at risk, Alice (94178) = healthy, 27965 = not found
        result = await check_users_risk(1226, "2381,94178,27965", ctx=ctx)

        assert result["checked"] == 3
        assert result["found"] == 2

        # Verify at_risk
        assert len(result["at_risk"]) == 1
        assert result["at_risk"][0]["rootly_user_id"] == 2381
        assert result["at_risk"][0]["user_name"] == "Quentin Rousseau"

        # Verify healthy
        assert len(result["healthy"]) == 1
        assert result["healthy"][0]["rootly_user_id"] == 94178
        assert result["healthy"][0]["user_name"] == "Alice Johnson"

        # Verify not_found
        assert result["not_found"] == [27965]

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_check_users_risk_custom_threshold(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test check_users_risk with custom min_och_score."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()
        # Alice (94178) has score 12.3 and risk_level low, should be healthy
        result = await check_users_risk(1226, "94178", min_och_score=60.0, ctx=ctx)

        assert result["checked"] == 1
        assert result["found"] == 1
        assert len(result["at_risk"]) == 0
        assert len(result["healthy"]) == 1
        assert result["healthy"][0]["rootly_user_id"] == 94178

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_check_users_risk_high_risk_level_override(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test that medium/high risk_level marks user as at_risk regardless of score."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()
        # Bob has score 55.0 and risk_level medium
        # Even with high threshold (70), should be at_risk due to risk_level
        result = await check_users_risk(1226, "1234", min_och_score=70.0, ctx=ctx)

        assert result["checked"] == 1
        assert len(result["at_risk"]) == 1
        assert result["at_risk"][0]["rootly_user_id"] == 1234

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_check_users_risk_exact_threshold(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test that users with score exactly at threshold are marked as at_risk."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()
        # Bob has score 55.0, threshold exactly 55.0 should mark as at_risk (>=)
        result = await check_users_risk(1226, "1234", min_och_score=55.0, ctx=ctx)

        assert result["checked"] == 1
        assert len(result["at_risk"]) == 1
        assert result["at_risk"][0]["och_score"] == 55.0

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_check_users_risk_invalid_id_format(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test check_users_risk with invalid ID format."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()

        with pytest.raises(ValueError, match="Invalid rootly_user_id"):
            await check_users_risk(1226, "abc,123", ctx=ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    async def test_check_users_risk_empty_ids(self, mock_extract):
        """Test check_users_risk with empty ID string."""
        mock_extract.return_value = "test-api-key"

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()

        with pytest.raises(ValueError, match="rootly_user_ids cannot be empty"):
            await check_users_risk(1226, "", ctx=ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_check_users_risk_integer_overflow(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test check_users_risk rejects IDs outside valid range."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()

        # Test overflow (> max 64-bit int)
        with pytest.raises(ValueError, match="Invalid rootly_user_id"):
            await check_users_risk(1226, "99999999999999999999999999999", ctx=ctx)

        # Test negative ID
        with pytest.raises(ValueError, match="Invalid rootly_user_id"):
            await check_users_risk(1226, "-1", ctx=ctx)

        # Test zero ID
        with pytest.raises(ValueError, match="Invalid rootly_user_id"):
            await check_users_risk(1226, "0", ctx=ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_check_users_risk_all_not_found(
        self, mock_client_class, mock_extract, sample_analysis_response
    ):
        """Test check_users_risk when all IDs are not found."""
        self._setup_mock_client(
            mock_client_class, mock_extract, sample_analysis_response
        )

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()
        result = await check_users_risk(1226, "99999,88888", ctx=ctx)

        assert result["checked"] == 2
        assert result["found"] == 0
        assert len(result["at_risk"]) == 0
        assert len(result["healthy"]) == 0
        assert set(result["not_found"]) == {99999, 88888}

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_check_users_risk_missing_analysis_data(
        self, mock_client_class, mock_extract
    ):
        """Test check_users_risk handles missing analysis_data gracefully."""
        mock_extract.return_value = "test-api-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 1226,
            "status": "completed",
            # Missing analysis_data entirely
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        from oncallhealth_mcp.server import check_users_risk

        ctx = MagicMock()
        result = await check_users_risk(1226, "2381,1234", ctx=ctx)

        assert result["checked"] == 2
        assert result["found"] == 0
        assert len(result["at_risk"]) == 0
        assert len(result["healthy"]) == 0
        assert set(result["not_found"]) == {2381, 1234}


class TestValidationErrors:
    """Tests for validation error handling across all tools."""

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    async def test_tools_reject_invalid_analysis_id(self, mock_extract):
        """Test that all tools reject invalid analysis_id."""
        mock_extract.return_value = "test-api-key"
        ctx = MagicMock()

        from oncallhealth_mcp.server import (
            get_at_risk_users,
            get_safe_responders,
            check_users_risk,
        )

        # Test all tools reject zero
        with pytest.raises(ValueError, match="analysis_id must be positive"):
            await get_at_risk_users(0, ctx=ctx)

        with pytest.raises(ValueError, match="analysis_id must be positive"):
            await get_safe_responders(0, ctx=ctx)

        with pytest.raises(ValueError, match="analysis_id must be positive"):
            await check_users_risk(0, "123", ctx=ctx)

        # Test all tools reject negative
        with pytest.raises(ValueError, match="analysis_id must be positive"):
            await get_at_risk_users(-1, ctx=ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    async def test_tools_reject_missing_api_key(self, mock_extract):
        """Test that all tools reject missing API key."""
        mock_extract.return_value = None
        ctx = MagicMock()

        from oncallhealth_mcp.server import (
            get_at_risk_users,
            get_safe_responders,
            check_users_risk,
        )

        with pytest.raises(PermissionError, match="Missing API key"):
            await get_at_risk_users(1226, ctx=ctx)

        with pytest.raises(PermissionError, match="Missing API key"):
            await get_safe_responders(1226, ctx=ctx)

        with pytest.raises(PermissionError, match="Missing API key"):
            await check_users_risk(1226, "123", ctx=ctx)


class TestValidateIntegrations:
    """Tests for validate_integrations tool."""

    def _setup_mock_client(self, mock_client_class, mock_extract, response_data):
        mock_extract.return_value = "test-api-key"
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        return mock_client

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_all_valid(self, mock_client_class, mock_extract):
        self._setup_mock_client(
            mock_client_class,
            mock_extract,
            {
                "all_valid": True,
                "integrations": {
                    "github": {"valid": True, "message": "Token valid"},
                    "slack": {"valid": True, "message": "Token valid"},
                },
            },
        )

        from oncallhealth_mcp.server import validate_integrations

        ctx = MagicMock()
        result = await validate_integrations(ctx=ctx)

        assert result["all_valid"] is True
        assert result["integrations"]["github"]["valid"] is True
        assert result["integrations"]["slack"]["valid"] is True

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_some_invalid(self, mock_client_class, mock_extract):
        self._setup_mock_client(
            mock_client_class,
            mock_extract,
            {
                "all_valid": False,
                "integrations": {
                    "github": {"valid": True, "message": "Token valid"},
                    "jira": {
                        "valid": False,
                        "message": "Token expired",
                        "error_code": "token_expired",
                    },
                },
            },
        )

        from oncallhealth_mcp.server import validate_integrations

        ctx = MagicMock()
        result = await validate_integrations(ctx=ctx)

        assert result["all_valid"] is False
        assert result["integrations"]["jira"]["valid"] is False
        assert result["integrations"]["jira"]["error_code"] == "token_expired"

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_force_refresh(self, mock_client_class, mock_extract):
        mock_client = self._setup_mock_client(
            mock_client_class,
            mock_extract,
            {
                "all_valid": True,
                "integrations": {},
            },
        )

        from oncallhealth_mcp.server import validate_integrations

        ctx = MagicMock()
        await validate_integrations(force_refresh=True, ctx=ctx)

        # Verify force_refresh was passed as query param
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[1]["params"]["force_refresh"] == "true"

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    async def test_rejects_missing_api_key(self, mock_extract):
        mock_extract.return_value = None
        ctx = MagicMock()

        from oncallhealth_mcp.server import validate_integrations

        with pytest.raises(PermissionError, match="Missing API key"):
            await validate_integrations(ctx=ctx)


class TestOncallUsers:
    """Tests for oncall_users tool."""

    def _setup_mock_client(self, mock_client_class, mock_extract, response_data):
        mock_extract.return_value = "test-api-key"
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        return mock_client

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_returns_oncall_users(self, mock_client_class, mock_extract):
        self._setup_mock_client(
            mock_client_class,
            mock_extract,
            {
                "integration_id": "1",
                "total_oncall": 2,
                "oncall_emails": ["alice@example.com", "bob@example.com"],
                "checked_at": "2026-02-28T14:30:00Z",
            },
        )

        from oncallhealth_mcp.server import oncall_users

        ctx = MagicMock()
        result = await oncall_users(integration_id=1, ctx=ctx)

        assert result["total_oncall"] == 2
        assert len(result["oncall_emails"]) == 2
        assert "alice@example.com" in result["oncall_emails"]

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_empty_oncall(self, mock_client_class, mock_extract):
        self._setup_mock_client(
            mock_client_class,
            mock_extract,
            {
                "integration_id": "1",
                "total_oncall": 0,
                "oncall_emails": [],
                "checked_at": "2026-02-28T14:30:00Z",
            },
        )

        from oncallhealth_mcp.server import oncall_users

        ctx = MagicMock()
        result = await oncall_users(integration_id=1, ctx=ctx)

        assert result["total_oncall"] == 0
        assert result["oncall_emails"] == []

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_not_found(self, mock_client_class, mock_extract):
        mock_extract.return_value = "test-api-key"
        mock_client = AsyncMock()
        mock_client.get.side_effect = NotFoundError("Not found")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        from oncallhealth_mcp.server import oncall_users

        ctx = MagicMock()
        with pytest.raises(LookupError, match="Integration not found"):
            await oncall_users(integration_id=999, ctx=ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    async def test_rejects_invalid_id(self, mock_extract):
        mock_extract.return_value = "test-api-key"
        ctx = MagicMock()

        from oncallhealth_mcp.server import oncall_users

        with pytest.raises(ValueError, match="integration_id must be positive"):
            await oncall_users(integration_id=0, ctx=ctx)

        with pytest.raises(ValueError, match="integration_id must be positive"):
            await oncall_users(integration_id=-1, ctx=ctx)


class TestMemberDailyHealth:
    """Tests for member_daily_health tool."""

    def _setup_mock_client(self, mock_client_class, mock_extract, response_data):
        mock_extract.return_value = "test-api-key"
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client
        return mock_client

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_returns_daily_health(self, mock_client_class, mock_extract):
        self._setup_mock_client(
            mock_client_class,
            mock_extract,
            {
                "status": "success",
                "data": {
                    "member_email": "alice@example.com",
                    "member_name": "Alice Johnson",
                    "daily_health": [
                        {
                            "date": "2026-02-27",
                            "health_score": 75,
                            "incident_count": 2,
                            "after_hours_count": 1,
                            "severity_weighted_count": 24.0,
                            "has_data": True,
                        },
                        {
                            "date": "2026-02-26",
                            "health_score": 0,
                            "incident_count": 0,
                            "after_hours_count": 0,
                            "severity_weighted_count": 0,
                            "has_data": False,
                        },
                    ],
                    "summary": {
                        "total_days": 30,
                        "days_with_data": 8,
                        "avg_health_score": 72,
                    },
                },
            },
        )

        from oncallhealth_mcp.server import member_daily_health

        ctx = MagicMock()
        result = await member_daily_health(1226, "alice@example.com", ctx=ctx)

        assert result["member_email"] == "alice@example.com"
        assert result["member_name"] == "Alice Johnson"
        # Only days with data should be included
        assert len(result["daily_health"]) == 1
        assert result["daily_health"][0]["health_score"] == 75
        assert result["summary"]["days_with_data"] == 8

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    @patch("oncallhealth_mcp.server.OnCallHealthClient")
    async def test_member_not_found(self, mock_client_class, mock_extract):
        self._setup_mock_client(
            mock_client_class,
            mock_extract,
            {
                "status": "error",
                "message": "Member not found in analysis",
                "data": None,
            },
        )

        from oncallhealth_mcp.server import member_daily_health

        ctx = MagicMock()
        with pytest.raises(LookupError, match="Member not found"):
            await member_daily_health(1226, "nonexistent@example.com", ctx=ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    async def test_rejects_empty_email(self, mock_extract):
        mock_extract.return_value = "test-api-key"
        ctx = MagicMock()

        from oncallhealth_mcp.server import member_daily_health

        with pytest.raises(ValueError, match="member_email cannot be empty"):
            await member_daily_health(1226, "", ctx=ctx)

        with pytest.raises(ValueError, match="member_email cannot be empty"):
            await member_daily_health(1226, "   ", ctx=ctx)

    @patch("oncallhealth_mcp.server.extract_api_key_header")
    async def test_rejects_invalid_analysis_id(self, mock_extract):
        mock_extract.return_value = "test-api-key"
        ctx = MagicMock()

        from oncallhealth_mcp.server import member_daily_health

        with pytest.raises(ValueError, match="analysis_id must be positive"):
            await member_daily_health(0, "alice@example.com", ctx=ctx)
