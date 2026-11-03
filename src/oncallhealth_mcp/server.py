"""MCP server for On-Call Health.

Tools are plain async functions registered on a ``FastMCP`` instance by
``build_server()`` so the same catalog can be served over stdio (env-var API
key) or Streamable HTTP (verified bearer token), with Code Mode as an opt-in
transform.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.dependencies import CurrentContext, Progress
from fastmcp.exceptions import ToolError
from fastmcp.experimental.transforms.code_mode import CodeMode
from fastmcp.server.auth import AuthProvider
from fastmcp_tasks import TasksExtension
from mcp.types import ToolAnnotations
from pydantic import Field

from oncallhealth_mcp.auth import extract_api_key_header
from oncallhealth_mcp.client import ClientConfig, NotFoundError, OnCallHealthClient
from oncallhealth_mcp.normalizers import (
    normalize_analysis_response,
    normalize_analysis_start_response,
    normalize_github_status,
    normalize_jira_status,
    normalize_linear_status,
    normalize_member_daily_health,
    normalize_oncall_users,
    normalize_rootly_integration,
    normalize_slack_status,
    normalize_validation_response,
)
from oncallhealth_mcp.schemas import (
    AnalysisStartResult,
    AnalysisStatus,
    AnalysisSummary,
    AtRiskUser,
    AtRiskUsers,
    CheckedUser,
    IntegrationsList,
    MemberDailyHealth,
    MemberScore,
    OncallUsers,
    RiskLevel,
    SafeResponder,
    SafeResponders,
    UsersRiskCheck,
    ValidationResult,
)

logger = logging.getLogger(__name__)

SERVER_NAME = "On-Call Health"
WEBSITE_URL = "https://oncallhealth.ai"
CODE_MODE_ENV = "ONCALLHEALTH_CODE_MODE"

# Statuses reported by the backend for an analysis that will never complete.
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "error", "cancelled"})
_MAX_INT64 = 9223372036854775807

SERVER_INSTRUCTIONS = """\
On-Call Health scores on-call responders for overwork risk. The OCH score runs
0-100; higher means more at risk. Scores inform staffing decisions and are not a
medical diagnosis.

Typical workflow:
1. validate_integrations - confirm connected tools have valid credentials.
2. analysis_current to reuse the latest analysis, or analysis_run to start a new
   one and wait for it. analysis_start + analysis_status are the manual-polling
   alternative (an analysis usually takes 2-3 minutes).
3. analysis_summary for the team overview, then get_at_risk_users,
   check_users_risk, get_safe_responders or member_daily_health for details.

analysis_results returns the full raw payload (80+ members x ~40 fields) and
can overwhelm a context window; prefer the focused tools above.
"""

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
STARTS_ANALYSIS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)


class _AnalysisCache:
    """In-memory TTL cache for completed analysis responses.

    Only completed analyses are cached since they are immutable.
    Uses time.monotonic() for reliable TTL (not affected by clock adjustments).
    No locks needed — asyncio is single-threaded.
    """

    def __init__(self, ttl_seconds: float = 300, max_entries: int = 50) -> None:
        self._store: dict[int, tuple[dict[str, Any], float]] = {}
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries

    def get(self, analysis_id: int) -> dict[str, Any] | None:
        entry = self._store.get(analysis_id)
        if entry is None:
            return None
        data, timestamp = entry
        if time.monotonic() - timestamp > self._ttl_seconds:
            del self._store[analysis_id]
            return None
        return data

    def put(self, analysis_id: int, data: dict[str, Any]) -> None:
        if len(self._store) >= self._max_entries and analysis_id not in self._store:
            oldest_key = min(self._store, key=lambda k: self._store[k][1])
            del self._store[oldest_key]
        self._store[analysis_id] = (data, time.monotonic())

    def clear(self) -> None:
        self._store.clear()


_analysis_cache = _AnalysisCache()


async def _fetch_analysis(api_key: str, analysis_id: int) -> dict[str, Any]:
    """Fetch analysis data, using cache for completed analyses.

    Returns the full API response dict. Completed analyses are cached;
    pending/running analyses are always fetched fresh.
    """
    cached = _analysis_cache.get(analysis_id)
    if cached is not None:
        return cached

    async with OnCallHealthClient(api_key=api_key) as client:
        response = await client.get(f"/analyses/{analysis_id}")
        data = response.json()

    if data.get("status") == "completed":
        _analysis_cache.put(analysis_id, data)

    return data


async def _fetch_completed_analysis(api_key: str, analysis_id: int) -> dict[str, Any]:
    """Fetch an analysis and fail unless it has completed."""
    data = await _fetch_analysis(api_key, analysis_id)
    if data.get("status") != "completed":
        raise ValueError(f"Analysis not completed yet (status={data['status']})")
    return data


def _members(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the member list from a raw analysis payload."""
    analysis_data = data.get("analysis_data") or {}
    return analysis_data.get("team_analysis", {}).get("members", [])


def _validate_analysis_id(analysis_id: int) -> None:
    """Validate that analysis_id is positive.

    Raises:
        ValueError: If analysis_id is not positive
    """
    if analysis_id <= 0:
        raise ValueError(f"analysis_id must be positive, got {analysis_id}")


def _validate_api_key(ctx: Any) -> str:
    """Resolve and validate the API key for the current request.

    Raises:
        PermissionError: If no API key is available
    """
    api_key = extract_api_key_header(ctx)
    if not api_key:
        raise PermissionError(
            "Missing API key. Set ONCALLHEALTH_API_KEY or provide X-API-Key header."
        )
    return api_key


async def _start_analysis(
    api_key: str,
    days_back: int,
    include_weekends: bool,
    integration_id: int | None,
) -> AnalysisStartResult:
    """POST /analyses/run and normalize the response."""
    if days_back <= 0:
        raise ValueError(f"days_back must be positive, got {days_back}")
    if days_back > 365:
        raise ValueError(f"days_back cannot exceed 365 days, got {days_back}")
    if integration_id is not None and integration_id <= 0:
        raise ValueError(f"integration_id must be positive, got {integration_id}")

    request_body: dict[str, Any] = {
        "time_range": days_back,
        "include_weekends": include_weekends,
    }
    if integration_id is not None:
        request_body["integration_id"] = integration_id

    async with OnCallHealthClient(api_key=api_key) as client:
        try:
            response = await client.post("/analyses/run", json=request_body)
        except NotFoundError:
            raise LookupError("Integration not found") from None
        data = response.json()
        integration_name = data.get("integration_name") or data.get("config", {}).get(
            "integration_name", "integration"
        )
        return normalize_analysis_start_response(data, integration_name, days_back)  # type: ignore[return-value]


def _build_summary(analysis_id: int, data: dict[str, Any]) -> AnalysisSummary:
    """Condense a completed analysis payload into the team summary shape."""
    members = _members(data)
    total_members = len(members)

    # Sort by OCH score (higher = more at risk)
    sorted_by_score = sorted(members, key=lambda m: m.get("och_score", 0), reverse=True)

    def _score(member: dict[str, Any]) -> MemberScore:
        return {
            "user_name": member.get("user_name", "Unknown"),
            "och_score": member.get("och_score", 0),
            "risk_level": member.get("risk_level", "unknown"),
        }

    top_at_risk = [_score(m) for m in sorted_by_score[:5]]
    top_healthy = [_score(m) for m in sorted_by_score[-5:][::-1]]

    risk_distribution: dict[str, int] = {}
    for member in members:
        risk_level = member.get("risk_level", "unknown")
        risk_distribution[risk_level] = risk_distribution.get(risk_level, 0) + 1

    if total_members > 0:
        avg_och_score = sum(m.get("och_score", 0) for m in members) / total_members
        avg_workload = sum(m.get("workload_score", 0) for m in members) / total_members
        avg_exhaustion = (
            sum(m.get("exhaustion_score", 0) for m in members) / total_members
        )
    else:
        avg_och_score = avg_workload = avg_exhaustion = 0

    return {
        "analysis_id": analysis_id,
        "total_members": total_members,
        "team_averages": {
            "och_score": round(avg_och_score, 2),
            "workload_score": round(avg_workload, 2),
            "exhaustion_score": round(avg_exhaustion, 2),
        },
        "risk_distribution": risk_distribution,
        "top_at_risk": top_at_risk,
        "top_healthy": top_healthy,
        "note": "This is a condensed summary. Use analysis_results() for complete member data.",
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

DaysBack = Annotated[
    int,
    Field(description="Number of days of on-call data to analyze (1-365)."),
]
IntegrationId = Annotated[
    int | None,
    Field(
        description="Rootly integration ID from integrations_list; omit for default."
    ),
]
AnalysisId = Annotated[int, Field(description="Analysis ID (see analysis_current).")]


async def analysis_start(
    days_back: DaysBack = 30,
    include_weekends: Annotated[
        bool, Field(description="Include weekend activity in the analysis.")
    ] = True,
    integration_id: IntegrationId = None,
    ctx: Context = CurrentContext(),
) -> AnalysisStartResult:
    """Start a new health analysis without waiting for it.

    Poll analysis_status until status is "completed", then use analysis_summary.
    Prefer analysis_run when you want a single call that waits for the result.
    """
    api_key = _validate_api_key(ctx)
    return await _start_analysis(api_key, days_back, include_weekends, integration_id)


async def analysis_run(
    days_back: DaysBack = 30,
    include_weekends: Annotated[
        bool, Field(description="Include weekend activity in the analysis.")
    ] = True,
    integration_id: IntegrationId = None,
    wait_timeout_seconds: Annotated[
        int,
        Field(
            ge=30,
            le=1800,
            description="How long to wait for completion before giving up.",
        ),
    ] = 600,
    progress: Progress = Progress(),
    ctx: Context = CurrentContext(),
) -> AnalysisSummary:
    """Start a new health analysis, wait for it to finish, and return the summary.

    Runs as a background task for clients that support the MCP Tasks extension
    and inline otherwise. Progress messages report the analysis status while
    waiting. On timeout the analysis keeps running on the backend; use
    analysis_status with the reported analysis_id to pick it up later.
    """
    api_key = _validate_api_key(ctx)
    started = await _start_analysis(
        api_key, days_back, include_weekends, integration_id
    )
    analysis_id = started["analysis_id"]
    await progress.set_message(f"Analysis {analysis_id} started")

    config = ClientConfig.from_env()
    interval = config.analysis_poll_interval
    deadline = time.monotonic() + wait_timeout_seconds

    while True:
        data = await _fetch_analysis(api_key, analysis_id)
        status = data.get("status", "unknown")
        if status == "completed":
            await progress.set_message(f"Analysis {analysis_id} completed")
            return _build_summary(analysis_id, data)
        if status in _TERMINAL_FAILURE_STATUSES:
            error = data.get("error") or (data.get("config") or {}).get("error")
            detail = f": {error}" if error else ""
            raise ToolError(f"Analysis {analysis_id} {status}{detail}")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ToolError(
                f"Analysis {analysis_id} is still {status} after "
                f"{wait_timeout_seconds}s. Call analysis_status with "
                f"analysis_id={analysis_id} to check on it later."
            )
        await progress.set_message(f"Analysis {analysis_id} is {status}")
        await asyncio.sleep(min(interval, remaining))
        interval = min(interval * 1.5, config.analysis_poll_max_interval)


async def analysis_status(
    analysis_id: AnalysisId, ctx: Context = CurrentContext()
) -> AnalysisStatus:
    """Get the status and metadata of an analysis."""
    api_key = _validate_api_key(ctx)
    _validate_analysis_id(analysis_id)

    try:
        data = await _fetch_analysis(api_key, analysis_id)
    except NotFoundError:
        raise LookupError("Analysis not found") from None
    return normalize_analysis_response(data)  # type: ignore[return-value]


async def analysis_results(
    analysis_id: AnalysisId, ctx: Context = CurrentContext()
) -> dict[str, Any]:
    """Get the full raw results for a completed analysis.

    WARNING: Returns complete data for 80+ members with ~40 fields each and
    may overwhelm a context window. Prefer analysis_summary, get_at_risk_users
    or member_daily_health unless you need every field.
    """
    api_key = _validate_api_key(ctx)
    _validate_analysis_id(analysis_id)

    try:
        data = await _fetch_completed_analysis(api_key, analysis_id)
    except NotFoundError:
        raise LookupError("Analysis not found") from None
    return data.get("analysis_data") or {}


async def analysis_summary(
    analysis_id: AnalysisId, ctx: Context = CurrentContext()
) -> AnalysisSummary:
    """Get a condensed team summary of a completed analysis.

    Returns team averages, the risk-level distribution and the five most and
    least at-risk members. Use analysis_results only when you need every field.
    """
    api_key = _validate_api_key(ctx)
    _validate_analysis_id(analysis_id)

    try:
        data = await _fetch_completed_analysis(api_key, analysis_id)
    except NotFoundError:
        raise LookupError("Analysis not found") from None
    return _build_summary(analysis_id, data)


async def analysis_current(ctx: Context = CurrentContext()) -> AnalysisStatus:
    """Get the most recent analysis for the current account.

    Returns metadata only (status, timestamps, configuration). Use
    analysis_summary with the returned id for the team overview.
    """
    api_key = _validate_api_key(ctx)

    async with OnCallHealthClient(api_key=api_key) as client:
        response = await client.get("/analyses", params={"limit": 1})
        data = response.json()
        analyses = data.get("analyses", [])
        if not analyses:
            raise LookupError("No analyses found")
        return normalize_analysis_response(analyses[0])  # type: ignore[return-value]


async def integrations_list(ctx: Context = CurrentContext()) -> IntegrationsList:
    """List connected integrations (Rootly, GitHub, Slack, Jira, Linear)."""
    api_key = _validate_api_key(ctx)

    async with OnCallHealthClient(api_key=api_key) as client:
        # Parallel fetch all integration types
        results = await asyncio.gather(
            client.get("/rootly/integrations"),
            client.get("/integrations/github/status"),
            client.get("/integrations/slack/status"),
            client.get("/integrations/jira/status"),
            client.get("/integrations/linear/status"),
            return_exceptions=True,
        )

        integrations: dict[str, Any] = {
            "rootly": [],
            "github": [],
            "slack": [],
            "jira": [],
            "linear": [],
        }

        # Process results, handling partial failures gracefully
        endpoint_names = ["rootly", "github", "slack", "jira", "linear"]

        for name, result in zip(endpoint_names, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(f"Failed to fetch {name} integrations: {result}")
                integrations[name] = []
                continue
            try:
                data = result.json()
                if name == "rootly":
                    # Rootly returns a list directly
                    integrations[name] = [
                        normalize_rootly_integration(item) for item in data
                    ]
                elif name == "github":
                    integrations[name] = normalize_github_status(data)
                elif name == "slack":
                    integrations[name] = normalize_slack_status(data)
                elif name == "jira":
                    integrations[name] = normalize_jira_status(data)
                elif name == "linear":
                    integrations[name] = normalize_linear_status(data)
            except Exception as e:
                logger.warning(f"Failed to normalize {name} response: {e}")
                integrations[name] = []

        return integrations  # type: ignore[return-value]


async def get_at_risk_users(
    analysis_id: AnalysisId,
    min_och_score: Annotated[
        float, Field(description="Minimum OCH score to include (0-100).")
    ] = 50.0,
    include_risk_levels: Annotated[
        list[RiskLevel], Field(description="Risk levels to include.")
    ] = ["medium", "high"],  # noqa: B006
    ctx: Context = CurrentContext(),
) -> AtRiskUsers:
    """Get users at or above a health-risk threshold with their external IDs.

    Use this to identify at-risk responders and correlate them with Rootly,
    PagerDuty, Slack or GitHub using the returned platform IDs. Results are
    sorted by OCH score, highest risk first.
    """
    api_key = _validate_api_key(ctx)
    _validate_analysis_id(analysis_id)
    if min_och_score < 0:
        raise ValueError(f"min_och_score must be non-negative, got {min_och_score}")

    try:
        data = await _fetch_completed_analysis(api_key, analysis_id)
    except NotFoundError:
        raise LookupError("Analysis not found") from None

    risk_levels = {level.strip().lower() for level in include_risk_levels}

    at_risk_users: list[AtRiskUser] = []
    for member in _members(data):
        och_score = member.get("och_score", 0)
        risk_level = member.get("risk_level", "").lower()

        if och_score < min_och_score:
            continue
        if risk_levels and risk_level not in risk_levels:
            continue

        health_score = member.get("health_score")
        if health_score is None:
            logger.warning(
                f"Member {member.get('user_name', 'Unknown')} missing health_score, "
                "defaulting to 0"
            )
            health_score = 0

        at_risk_users.append(
            {
                "user_name": member.get("user_name", "Unknown"),
                "och_score": och_score,
                "risk_level": member.get("risk_level", "unknown"),
                "health_score": health_score,
                "incident_count": member.get("incident_count", 0),
                "rootly_user_id": member.get("rootly_user_id"),
                "pagerduty_user_id": member.get("pagerduty_user_id"),
                "slack_user_id": member.get("slack_user_id"),
                "github_username": member.get("github_username"),
            }
        )

    at_risk_users.sort(key=lambda u: u["och_score"], reverse=True)

    return {"total_at_risk": len(at_risk_users), "users": at_risk_users}


async def get_safe_responders(
    analysis_id: AnalysisId,
    max_och_score: Annotated[
        float, Field(description="Maximum OCH score to include (0-100).")
    ] = 30.0,
    limit: Annotated[int, Field(description="Maximum users to return.")] = 10,
    ctx: Context = CurrentContext(),
) -> SafeResponders:
    """Get users with low health risk who could take additional on-call shifts.

    Use this to find replacement responders when removing at-risk users from
    schedules. Results are sorted by OCH score, healthiest first.
    """
    api_key = _validate_api_key(ctx)
    _validate_analysis_id(analysis_id)
    if max_och_score < 0:
        raise ValueError(f"max_och_score must be non-negative, got {max_och_score}")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    try:
        data = await _fetch_completed_analysis(api_key, analysis_id)
    except NotFoundError:
        raise LookupError("Analysis not found") from None

    safe_users: list[SafeResponder] = []
    for member in _members(data):
        och_score = member.get("och_score", 0)
        if och_score > max_och_score:
            continue
        safe_users.append(
            {
                "user_name": member.get("user_name", "Unknown"),
                "och_score": och_score,
                "risk_level": member.get("risk_level", "unknown"),
                "rootly_user_id": member.get("rootly_user_id"),
                "slack_user_id": member.get("slack_user_id"),
            }
        )

    safe_users.sort(key=lambda u: u["och_score"])

    return {"total_safe": len(safe_users), "users": safe_users[:limit]}


async def check_users_risk(
    analysis_id: AnalysisId,
    rootly_user_ids: Annotated[
        list[int], Field(description="Rootly user IDs to check.")
    ],
    min_och_score: Annotated[
        float, Field(description="OCH score at or above which a user is at risk.")
    ] = 50.0,
    ctx: Context = CurrentContext(),
) -> UsersRiskCheck:
    """Check health risk for specific users by their Rootly user IDs.

    Use this after fetching a schedule from Rootly to see whether any scheduled
    responders are at risk. A user is at risk when their OCH score is at or
    above min_och_score or their risk level is medium or high.
    """
    api_key = _validate_api_key(ctx)
    _validate_analysis_id(analysis_id)
    if min_och_score < 0:
        raise ValueError(f"min_och_score must be non-negative, got {min_och_score}")
    if not rootly_user_ids:
        raise ValueError("rootly_user_ids cannot be empty")

    requested_ids: set[int] = set()
    for user_id in rootly_user_ids:
        if not isinstance(user_id, int) or user_id <= 0 or user_id > _MAX_INT64:
            raise ValueError(f"Invalid rootly_user_id: {user_id}")
        requested_ids.add(user_id)

    try:
        data = await _fetch_completed_analysis(api_key, analysis_id)
    except NotFoundError:
        raise LookupError("Analysis not found") from None

    members_by_rootly_id = {
        member["rootly_user_id"]: member
        for member in _members(data)
        if member.get("rootly_user_id") is not None
    }

    at_risk: list[CheckedUser] = []
    healthy: list[CheckedUser] = []
    not_found: list[int] = []

    for rootly_id in sorted(requested_ids):
        member = members_by_rootly_id.get(rootly_id)
        if member is None:
            not_found.append(rootly_id)
            continue

        och_score = member.get("och_score", 0)
        risk_level = member.get("risk_level", "").lower()
        user_info: CheckedUser = {
            "rootly_user_id": rootly_id,
            "user_name": member.get("user_name", "Unknown"),
            "och_score": och_score,
            "risk_level": member.get("risk_level", "unknown"),
        }
        if och_score >= min_och_score or risk_level in ("medium", "high"):
            at_risk.append(user_info)
        else:
            healthy.append(user_info)

    return {
        "checked": len(requested_ids),
        "found": len(at_risk) + len(healthy),
        "at_risk": at_risk,
        "healthy": healthy,
        "not_found": not_found,
    }


async def validate_integrations(
    force_refresh: Annotated[
        bool, Field(description="Bypass the backend cache and re-check every token.")
    ] = False,
    ctx: Context = CurrentContext(),
) -> ValidationResult:
    """Check that every connected integration has valid credentials.

    Call this before starting an analysis. Returns per-integration validation
    status (GitHub, Slack, Jira, Linear) and an all_valid flag.
    """
    api_key = _validate_api_key(ctx)

    async with OnCallHealthClient(api_key=api_key) as client:
        params = {}
        if force_refresh:
            params["force_refresh"] = "true"
        response = await client.get("/analyses/validate-integrations", params=params)
        return normalize_validation_response(response.json())  # type: ignore[return-value]


async def oncall_users(
    integration_id: Annotated[
        int, Field(description="Rootly integration ID from integrations_list.")
    ],
    ctx: Context = CurrentContext(),
) -> OncallUsers:
    """Get the users currently on call for a Rootly integration.

    Cross-reference the returned emails with analysis data (for example
    get_at_risk_users) to see whether anyone currently on call is at risk.
    """
    api_key = _validate_api_key(ctx)
    if integration_id <= 0:
        raise ValueError(f"integration_id must be positive, got {integration_id}")

    async with OnCallHealthClient(api_key=api_key) as client:
        try:
            response = await client.get(
                f"/rootly/integrations/{integration_id}/oncall-users"
            )
        except NotFoundError:
            raise LookupError("Integration not found") from None
        return normalize_oncall_users(response.json())  # type: ignore[return-value]


async def member_daily_health(
    analysis_id: AnalysisId,
    member_email: Annotated[str, Field(description="Email address of the member.")],
    ctx: Context = CurrentContext(),
) -> MemberDailyHealth:
    """Get the day-by-day health breakdown for one team member.

    Shows per-day health scores, incident counts and after-hours activity over
    the analysis period (only days with data are included).
    """
    api_key = _validate_api_key(ctx)
    _validate_analysis_id(analysis_id)
    if not member_email or not member_email.strip():
        raise ValueError("member_email cannot be empty")

    async with OnCallHealthClient(api_key=api_key) as client:
        try:
            response = await client.get(
                f"/analyses/{analysis_id}/members/{member_email}/daily-health"
            )
        except NotFoundError:
            raise LookupError("Analysis or member not found") from None
        data = response.json()
        if data.get("status") == "error":
            raise LookupError(data.get("message", "Member not found"))
        return normalize_member_daily_health(data)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Resources and prompts
# ---------------------------------------------------------------------------


def methodology_resource() -> str:
    """Short description of how On-Call Health measures overwork risk."""
    return (
        "On-Call Health measures overwork risk using a scientifically informed "
        "two-dimensional model. It combines objective workload signals (incidents, "
        "communications, commits) with self-reported data to surface risk patterns "
        "without providing medical diagnosis."
    )


async def latest_analysis_resource(ctx: Context = CurrentContext()) -> AnalysisStatus:
    """Metadata of the most recent analysis for the current account."""
    return await analysis_current(ctx=ctx)


async def analysis_summary_resource(
    analysis_id: int, ctx: Context = CurrentContext()
) -> AnalysisSummary:
    """Condensed team summary for a completed analysis."""
    return await analysis_summary(analysis_id, ctx=ctx)


def weekly_brief(team_name: str) -> str:
    """Prompt template for a weekly on-call health brief."""
    return (
        f"Create a weekly on-call health brief for the team named '{team_name}'. "
        "Start from analysis_current (or analysis_run if it is older than a week), "
        "then use analysis_summary and get_at_risk_users. Summarize overall risk "
        "trends, identify any high-risk responders, and suggest two concrete "
        "follow-up actions for managers."
    )


def investigate_responder(member_email: str, analysis_id: int) -> str:
    """Prompt template for investigating one responder's health trend."""
    return (
        f"Investigate the on-call health of {member_email} in analysis "
        f"{analysis_id}. Use member_daily_health for the daily trend and "
        "get_at_risk_users to see how they compare with the team. Explain what "
        "drove the risk (incidents, after-hours load), whether it is improving, "
        "and recommend whether to adjust their upcoming on-call shifts."
    )


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

# (function, registration options) for every tool, in catalog order.
TOOL_SPECS: list[tuple[Any, dict[str, Any]]] = [
    (validate_integrations, {"annotations": READ_ONLY, "tags": {"integrations"}}),
    (integrations_list, {"annotations": READ_ONLY, "tags": {"integrations"}}),
    (oncall_users, {"annotations": READ_ONLY, "tags": {"integrations"}}),
    (analysis_current, {"annotations": READ_ONLY, "tags": {"analysis"}}),
    (
        analysis_run,
        {"annotations": STARTS_ANALYSIS, "tags": {"analysis"}, "task": True},
    ),
    (analysis_start, {"annotations": STARTS_ANALYSIS, "tags": {"analysis"}}),
    (analysis_status, {"annotations": READ_ONLY, "tags": {"analysis"}}),
    (analysis_summary, {"annotations": READ_ONLY, "tags": {"analysis"}}),
    (analysis_results, {"annotations": READ_ONLY, "tags": {"analysis"}}),
    (get_at_risk_users, {"annotations": READ_ONLY, "tags": {"members"}}),
    (get_safe_responders, {"annotations": READ_ONLY, "tags": {"members"}}),
    (check_users_risk, {"annotations": READ_ONLY, "tags": {"members"}}),
    (member_daily_health, {"annotations": READ_ONLY, "tags": {"members"}}),
]


def code_mode_from_env() -> bool:
    """Return True when ONCALLHEALTH_CODE_MODE enables Code Mode."""
    return os.getenv(CODE_MODE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def build_server(
    *,
    code_mode: bool | None = None,
    auth: AuthProvider | None = None,
) -> FastMCP:
    """Create a FastMCP server with the On-Call Health catalog.

    Args:
        code_mode: Wrap the catalog in FastMCP Code Mode (search/get_schema/
            execute meta-tools). Defaults to the ONCALLHEALTH_CODE_MODE env var.
        auth: Optional auth provider for HTTP deployments. stdio servers
            authenticate with the ONCALLHEALTH_API_KEY environment variable.
    """
    from oncallhealth_mcp import __version__

    if code_mode is None:
        code_mode = code_mode_from_env()

    server = FastMCP(
        SERVER_NAME,
        version=__version__,
        website_url=WEBSITE_URL,
        instructions=SERVER_INSTRUCTIONS,
        auth=auth,
        transforms=[CodeMode()] if code_mode else [],
        # Applies to every cacheable method, including resources/read, whose
        # contents are account-specific: keep cached results per authorization.
        cache_ttl=300,
        cache_scope="private",
    )
    server.add_extension(TasksExtension())

    for fn, options in TOOL_SPECS:
        server.tool(fn, **options)

    server.resource(
        "oncallhealth://methodology",
        mime_type="text/plain",
        tags={"reference"},
    )(methodology_resource)
    server.resource(
        "oncallhealth://analyses/latest",
        mime_type="application/json",
        tags={"analysis"},
    )(latest_analysis_resource)
    server.resource(
        "oncallhealth://analyses/{analysis_id}/summary",
        mime_type="application/json",
        tags={"analysis"},
    )(analysis_summary_resource)

    server.prompt(weekly_brief)
    server.prompt(investigate_responder)

    return server


# Default server instance (stdio-style, Code Mode from env). HTTP deployments
# build their own instance via transport.create_http_app().
mcp_server = build_server()
