"""Response normalizers for MCP tools using REST API.

Transforms REST API responses to match existing MCP tool contracts,
ensuring backward compatibility for MCP clients.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def serialize_datetime(value: Any) -> Optional[str]:
    """Convert datetime to ISO string format.

    Handles various input types:
    - datetime objects: calls .isoformat()
    - strings (already ISO): returns as-is
    - None: returns None

    Args:
        value: Datetime value to serialize

    Returns:
        ISO formatted string or None
    """
    if value is None:
        return None
    # If already a string (from JSON response), return as-is
    if isinstance(value, str):
        return value
    # If datetime object, convert to ISO string
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def normalize_analysis_response(rest_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform REST API AnalysisResponse to MCP tool contract.

    Maps REST API response fields to match the existing MCP analysis_status
    and analysis_current tool response format.

    Args:
        rest_data: Response dict from GET /analyses/{id} or list item

    Returns:
        Normalized dict matching MCP tool contract:
        - id: int
        - status: str
        - created_at: ISO string
        - completed_at: ISO string or None
        - config: dict or None
        - error: str (optional, only if present)
        - results_summary: dict (optional, only if completed with results)
    """
    normalized: Dict[str, Any] = {
        "id": rest_data["id"],
        "status": rest_data["status"],
        "created_at": serialize_datetime(rest_data.get("created_at")),
        "completed_at": serialize_datetime(rest_data.get("completed_at")),
        "config": rest_data.get("config"),
    }

    # Map error field - check both config.error and top-level error
    error = rest_data.get("error")
    if not error:
        config = rest_data.get("config") or {}
        error = config.get("error") or config.get("error_message")
    if error:
        normalized["error"] = error

    # Extract results_summary from analysis_data if status is completed
    analysis_data = rest_data.get("analysis_data")
    if rest_data["status"] == "completed" and analysis_data:
        team_analysis = analysis_data.get("team_analysis", {})
        # team_analysis may be a dict with "members" key or a flat list
        if isinstance(team_analysis, dict):
            members = team_analysis.get("members", [])
        else:
            members = team_analysis
        team_summary = analysis_data.get("team_summary", {})

        normalized["results_summary"] = {
            "total_users": len(members),
            "high_risk_count": len(
                [u for u in members if isinstance(u, dict) and u.get("risk_level") == "high"]
            ),
            "team_average_score": team_summary.get("average_score"),
        }

    return normalized


def normalize_analysis_start_response(
    rest_data: Dict[str, Any],
    integration_name: str,
    days_back: int,
) -> Dict[str, Any]:
    """Transform POST /analyses/run response to MCP analysis_start contract.

    Args:
        rest_data: Response dict from POST /analyses/run
        integration_name: Name of the integration being used
        days_back: Number of days for the analysis

    Returns:
        Normalized dict matching MCP analysis_start response:
        - analysis_id: int
        - status: "started"
        - message: str with integration name and days_back
    """
    return {
        "analysis_id": rest_data["id"],
        "status": "started",
        "message": (
            f"Analysis started using '{integration_name}'. "
            f"This usually takes 2-3 minutes for {days_back} days of data."
        ),
    }


def normalize_rootly_integration(rest_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform /rootly/integrations response item to MCP format.

    Args:
        rest_data: Single integration dict from GET /rootly/integrations

    Returns:
        Normalized dict matching MCP integrations_list contract
    """
    return {
        "id": rest_data.get("id"),
        "name": rest_data.get("name"),
        "platform": rest_data.get("platform", "rootly"),
        "organization_name": rest_data.get("organization_name"),
        "is_default": rest_data.get("is_default", False),
        "is_active": rest_data.get("is_active", True),
        "total_users": rest_data.get("total_users", 0),
        "last_used_at": serialize_datetime(rest_data.get("last_used_at")),
        "created_at": serialize_datetime(rest_data.get("created_at")),
    }


def normalize_github_status(rest_data: Optional[Dict[str, Any]]) -> list:
    """Transform /integrations/github/status response to MCP format.

    REST returns single status object if connected, empty/null if not.
    MCP expects list of integrations.

    Args:
        rest_data: Response dict from GET /integrations/github/status

    Returns:
        List with single integration dict if connected, empty list otherwise
    """
    if not rest_data or not rest_data.get("connected"):
        return []
    integration = rest_data.get("integration", {})
    return [{
        "id": integration.get("id"),
        "username": integration.get("github_username"),
        "organizations": integration.get("organizations", []),
        "has_token": bool(integration.get("token_preview")),
        "token_source": integration.get("token_source"),
        "created_at": serialize_datetime(integration.get("connected_at")),
        "updated_at": serialize_datetime(integration.get("last_updated")),
    }]


def normalize_slack_status(rest_data: Optional[Dict[str, Any]]) -> list:
    """Transform /integrations/slack/status response to MCP format.

    Args:
        rest_data: Response dict from GET /integrations/slack/status

    Returns:
        List with single integration dict if connected, empty list otherwise
    """
    if not rest_data or not rest_data.get("connected"):
        return []
    integration = rest_data.get("integration", {})
    return [{
        "id": integration.get("id"),
        "workspace_id": integration.get("workspace_id"),
        "workspace_name": integration.get("workspace_name"),
        "slack_user_id": integration.get("slack_user_id"),
        "has_token": integration.get("token_source") == "oauth",
        "token_source": integration.get("token_source"),
        "created_at": serialize_datetime(integration.get("connected_at")),
        "updated_at": serialize_datetime(integration.get("last_updated")),
    }]


def normalize_jira_status(rest_data: Optional[Dict[str, Any]]) -> list:
    """Transform /integrations/jira/status response to MCP format.

    Args:
        rest_data: Response dict from GET /integrations/jira/status

    Returns:
        List with single integration dict if connected, empty list otherwise
    """
    if not rest_data or not rest_data.get("connected"):
        return []
    integration = rest_data.get("integration", {})
    return [{
        "id": integration.get("id"),
        "cloud_id": integration.get("jira_cloud_id"),
        "site_url": integration.get("jira_site_url"),
        "display_name": integration.get("jira_display_name"),
        "has_token": bool(integration.get("token_preview")),
        "token_source": integration.get("token_source"),
        "created_at": serialize_datetime(integration.get("updated_at")),
        "updated_at": serialize_datetime(integration.get("updated_at")),
    }]


def normalize_linear_status(rest_data: Optional[Dict[str, Any]]) -> list:
    """Transform /integrations/linear/status response to MCP format.

    Args:
        rest_data: Response dict from GET /integrations/linear/status

    Returns:
        List with single integration dict if connected, empty list otherwise
    """
    if not rest_data or not rest_data.get("connected"):
        return []
    integration = rest_data.get("integration", {})
    return [{
        "id": integration.get("id"),
        "workspace_id": integration.get("workspace_id"),
        "workspace_name": integration.get("workspace_name"),
        "workspace_url_key": integration.get("workspace_url_key"),
        "has_token": bool(integration.get("token_preview")),
        "token_source": integration.get("token_source"),
        "created_at": serialize_datetime(integration.get("updated_at")),
        "updated_at": serialize_datetime(integration.get("updated_at")),
    }]


def normalize_oncall_users(rest_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform /rootly/integrations/{id}/oncall-users response to MCP format.

    Args:
        rest_data: Response dict from GET /rootly/integrations/{id}/oncall-users

    Returns:
        Normalized dict with oncall user info
    """
    return {
        "integration_id": rest_data.get("integration_id"),
        "total_oncall": rest_data.get("total_oncall", 0),
        "oncall_emails": rest_data.get("oncall_emails", []),
        "checked_at": serialize_datetime(rest_data.get("checked_at")),
    }


def normalize_validation_response(rest_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform /analyses/validate-integrations response to MCP format.

    Args:
        rest_data: Response dict from GET /analyses/validate-integrations

    Returns:
        Normalized dict with validation results per integration
    """
    integrations = rest_data.get("integrations", {})
    normalized_integrations = {}
    for name, info in integrations.items():
        normalized_integrations[name] = {
            "valid": info.get("valid", False),
            "message": info.get("message", ""),
        }
        if info.get("error_code"):
            normalized_integrations[name]["error_code"] = info["error_code"]

    return {
        "all_valid": rest_data.get("all_valid", False),
        "integrations": normalized_integrations,
    }


def normalize_member_daily_health(rest_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform /analyses/{id}/members/{email}/daily-health response to MCP format.

    Condenses detailed daily health data to key fields to avoid context overflow.

    Args:
        rest_data: Response dict from GET /analyses/{id}/members/{email}/daily-health

    Returns:
        Normalized dict with member daily health summary
    """
    data = rest_data.get("data") or {}
    daily_health = data.get("daily_health", [])
    summary = data.get("summary", {})

    # Condense daily entries to essential fields
    condensed_days = []
    for day in daily_health:
        if not day.get("has_data", False):
            continue
        condensed_days.append({
            "date": day.get("date"),
            "health_score": day.get("health_score", 0),
            "incident_count": day.get("incident_count", 0),
            "after_hours_count": day.get("after_hours_count", 0),
            "severity_weighted_count": day.get("severity_weighted_count", 0),
        })

    return {
        "member_email": data.get("member_email"),
        "member_name": data.get("member_name"),
        "daily_health": condensed_days,
        "summary": {
            "total_days": summary.get("total_days", 0),
            "days_with_data": summary.get("days_with_data", 0),
            "avg_health_score": summary.get("avg_health_score", 0),
        },
    }
