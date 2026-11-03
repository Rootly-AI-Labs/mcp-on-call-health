"""Tests for the task-enabled analysis_run tool."""

from itertools import count
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from oncallhealth_mcp.server import analysis_run, build_server

START_RESPONSE = {"id": 1226, "status": "pending", "integration_name": "Rootly Prod"}


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def _mock_client(mock_client_class, statuses, completed_payload):
    """Configure OnCallHealthClient so GET /analyses/{id} walks through statuses."""
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.post.return_value = _response(START_RESPONSE)
    client.get.side_effect = [
        _response(
            completed_payload
            if status == "completed"
            else {"id": 1226, "status": status, "error": "boom"}
        )
        for status in statuses
    ]
    mock_client_class.return_value = client
    return client


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch):
    monkeypatch.setenv("ONCALLHEALTH_POLL_INTERVAL", "0.001")
    monkeypatch.setenv("ONCALLHEALTH_POLL_MAX_INTERVAL", "0.002")
    monkeypatch.setenv("ONCALLHEALTH_API_KEY", "test-api-key")


@patch("oncallhealth_mcp.server.OnCallHealthClient")
async def test_run_polls_until_completed(mock_client_class, sample_analysis_response):
    client = _mock_client(
        mock_client_class, ["pending", "running", "completed"], sample_analysis_response
    )

    async with Client(build_server(code_mode=False)) as mcp:
        result = await mcp.call_tool("analysis_run", {"days_back": 7})

    summary = result.structured_content
    assert summary["analysis_id"] == 1226
    assert summary["total_members"] == 5
    assert summary["top_at_risk"][0]["user_name"] == "Quentin Rousseau"
    client.post.assert_awaited_once_with(
        "/analyses/run", json={"time_range": 7, "include_weekends": True}
    )
    assert client.get.await_count == 3


@patch("oncallhealth_mcp.server.OnCallHealthClient")
async def test_run_works_for_legacy_protocol_clients(
    mock_client_class, sample_analysis_response
):
    _mock_client(mock_client_class, ["completed"], sample_analysis_response)

    async with Client(build_server(code_mode=False), mode="legacy") as mcp:
        result = await mcp.call_tool("analysis_run", {})

    assert result.structured_content["total_members"] == 5


@patch("oncallhealth_mcp.server.OnCallHealthClient")
async def test_run_raises_when_backend_reports_failure(
    mock_client_class, sample_analysis_response
):
    _mock_client(mock_client_class, ["pending", "failed"], sample_analysis_response)

    with pytest.raises(ToolError, match="Analysis 1226 failed: boom"):
        await analysis_run(progress=AsyncMock(), ctx=MagicMock())


@patch("oncallhealth_mcp.server.OnCallHealthClient")
async def test_run_times_out_and_points_to_analysis_status(
    mock_client_class, sample_analysis_response
):
    _mock_client(mock_client_class, ["pending"] * 10, sample_analysis_response)
    # Each monotonic() call advances 100s, so the 600s budget is exhausted quickly.
    clock = count(0, 100)

    with (
        patch(
            "oncallhealth_mcp.server.time.monotonic", side_effect=lambda: next(clock)
        ),
        pytest.raises(ToolError, match="analysis_id=1226"),
    ):
        await analysis_run(progress=AsyncMock(), ctx=MagicMock())


@patch("oncallhealth_mcp.server.OnCallHealthClient")
async def test_run_validates_inputs_before_calling_backend(mock_client_class):
    with pytest.raises(ValueError, match="days_back cannot exceed 365"):
        await analysis_run(days_back=400, progress=AsyncMock(), ctx=MagicMock())
    mock_client_class.assert_not_called()
