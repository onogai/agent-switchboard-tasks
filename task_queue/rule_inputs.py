"""Public MCP rule inputs. Omission is different from explicit null."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field
from typing_extensions import TypedDict

from .models import RULE_CREATE_DEFAULTS


IdempotencyKey = Annotated[str, Field(min_length=1, max_length=128,
    description="Unique key for this proposal; reuse only when retrying the same request.")]
RuleVersion = Annotated[int, Field(gt=0, description="Current definition.version from get_task_rule.")]
Title = Annotated[str, Field(min_length=1, max_length=200,
    description="Short human-readable task name.")]
Instructions = Annotated[str, Field(min_length=1, max_length=100_000,
    description="Complete instructions the worker will execute.")]


class RuleFields(TypedDict, total=False):
    """Common optional settings. No values are inserted by input validation."""

    schedule_kind: Annotated[Literal["manual", "interval", "daily", "one_shot"], Field(
        description="daily: daily_time_local and timezone; interval: interval_minutes; "
        "one_shot: one_shot_at (stored as manual); manual: no recurring timing.")]
    daily_time_local: Annotated[str | None, Field(
        description="Local HH:MM (24-hour) for daily schedules only.")]
    timezone: Annotated[str | None, Field(
        description="IANA timezone for daily schedules, e.g. Europe/Madrid.")]
    interval_minutes: Annotated[int | None, Field(
        gt=0, description="Positive interval in minutes, for interval schedules only.")]
    interval_anchor_at: Annotated[str | None, Field(
        description="Optional timezone-aware ISO timestamp for interval alignment; defaults to creation time.")]
    one_shot_at: Annotated[str | None, Field(
        description="Timezone-aware ISO timestamp for a single scheduled run; use manual or one_shot.")]
    priority: Annotated[int, Field(ge=0, le=9, description="Higher values run first.")]
    miss_policy: Annotated[Literal["skip", "merge_next", "run_late"], Field(
        description="After the late window: skip, merge into the next recurring run, "
        "or run late. Manual-only rules require run_late; one-shot cannot merge_next.")]
    max_lateness_minutes: Annotated[int, Field(
        ge=0, description="Minutes after scheduled time before the execution window closes. "
        "run_late can execute beyond this window.")]
    window_before_minutes: Annotated[int, Field(
        ge=0, description="Minutes before scheduled time when execution becomes eligible. "
        "For intervals, (1440 + early window) // interval_minutes + 2 must be at most 2000.")]
    lease_seconds: Annotated[int, Field(gt=0, description="Worker lease duration in seconds.")]
    max_attempts: Annotated[int, Field(gt=0, description="Maximum execution attempts including the first.")]
    timezone_name: Annotated[str | None, Field(
        description="Legacy alias for timezone; prefer timezone. If both are supplied they must agree.",
        json_schema_extra={"deprecated": True})]
    window_after_minutes: Annotated[int, Field(
        ge=0, description="Legacy alias for max_lateness_minutes; prefer max_lateness_minutes. "
        "If both are supplied they must agree.",
        json_schema_extra={"deprecated": True})]


def _describe_create_defaults(schema: dict) -> None:
    # JSON Schema defaults are documentation only. The proposal service inserts
    # them after resolving legacy aliases, so omitted values cannot conflict.
    for name, value in RULE_CREATE_DEFAULTS.items():
        public_name = "timezone" if name == "timezone_name" else name
        schema["properties"][public_name]["default"] = value


class CreateRule(RuleFields):
    """Create an active rule. Pause or resume an existing rule with RuleChanges."""

    __pydantic_config__ = ConfigDict(extra="forbid", strict=True,
                                     json_schema_extra=_describe_create_defaults)
    title: Title
    instructions: Instructions


class RuleChanges(RuleFields, total=False):
    """Partial edit: omitted fields stay unchanged; null clears nullable timing fields only."""

    __pydantic_config__ = ConfigDict(extra="forbid", strict=True,
                                     json_schema_extra={"minProperties": 1})
    title: Title
    instructions: Instructions
    is_active: Annotated[bool, Field(description="false pauses; true resumes; omit to keep current state.")]
