"""Typed result shapes for MCP tools.

These TypedDicts are used as return annotations so FastMCP publishes a real
``outputSchema`` for every tool (MCP clients use it to validate and display
structured content). Tools still return plain dicts at runtime.
"""

from __future__ import annotations

from typing import Any, Literal

from typing_extensions import NotRequired, TypedDict

RiskLevel = Literal["low", "medium", "high"]


class AnalysisStartResult(TypedDict):
    analysis_id: int
    status: Literal["started"]
    message: str


class ResultsSummary(TypedDict):
    total_users: int
    high_risk_count: int
    team_average_score: float | None


class AnalysisStatus(TypedDict):
    id: int
    status: str
    created_at: str | None
    completed_at: str | None
    config: dict[str, Any] | None
    error: NotRequired[str]
    results_summary: NotRequired[ResultsSummary]


class TeamAverages(TypedDict):
    och_score: float
    workload_score: float
    exhaustion_score: float


class MemberScore(TypedDict):
    user_name: str
    och_score: float
    risk_level: str


class AnalysisSummary(TypedDict):
    analysis_id: int
    total_members: int
    team_averages: TeamAverages
    risk_distribution: dict[str, int]
    top_at_risk: list[MemberScore]
    top_healthy: list[MemberScore]
    note: str


class AtRiskUser(TypedDict):
    user_name: str
    och_score: float
    risk_level: str
    health_score: float
    incident_count: int
    rootly_user_id: int | None
    pagerduty_user_id: str | None
    slack_user_id: str | None
    github_username: str | None


class AtRiskUsers(TypedDict):
    total_at_risk: int
    users: list[AtRiskUser]


class SafeResponder(TypedDict):
    user_name: str
    och_score: float
    risk_level: str
    rootly_user_id: int | None
    slack_user_id: str | None


class SafeResponders(TypedDict):
    total_safe: int
    users: list[SafeResponder]


class CheckedUser(TypedDict):
    rootly_user_id: int
    user_name: str
    och_score: float
    risk_level: str


class UsersRiskCheck(TypedDict):
    checked: int
    found: int
    at_risk: list[CheckedUser]
    healthy: list[CheckedUser]
    not_found: list[int]


class IntegrationsList(TypedDict):
    rootly: list[dict[str, Any]]
    github: list[dict[str, Any]]
    slack: list[dict[str, Any]]
    jira: list[dict[str, Any]]
    linear: list[dict[str, Any]]


class IntegrationValidation(TypedDict):
    valid: bool
    message: str
    error_code: NotRequired[str]


class ValidationResult(TypedDict):
    all_valid: bool
    integrations: dict[str, IntegrationValidation]


class OncallUsers(TypedDict):
    integration_id: int | None
    total_oncall: int
    oncall_emails: list[str]
    checked_at: str | None


class DailyHealthEntry(TypedDict):
    date: str | None
    health_score: float
    incident_count: int
    after_hours_count: int
    severity_weighted_count: float


class DailyHealthSummary(TypedDict):
    total_days: int
    days_with_data: int
    avg_health_score: float


class MemberDailyHealth(TypedDict):
    member_email: str | None
    member_name: str | None
    daily_health: list[DailyHealthEntry]
    summary: DailyHealthSummary
