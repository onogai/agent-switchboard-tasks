"""Public MCP rule inputs. Storage and proposal payloads retain their existing format."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


IdempotencyKey = Annotated[str, Field(min_length=1, max_length=128,
    description="Unique key for this proposal; reuse only when retrying the same request.")]
RuleVersion = Annotated[int, Field(gt=0, description="Current definition.version from get_task_rule.")]
Title = Annotated[str, Field(min_length=1, max_length=200)]
Instructions = Annotated[str, Field(min_length=1, max_length=100_000)]


class RuleFields(BaseModel):
    """Common writable rule settings; defaults apply only at creation."""
    model_config = ConfigDict(extra="forbid", strict=True)

    schedule_kind: Literal["manual", "interval", "daily", "one_shot"] = Field(
        "manual", description="daily: daily_time_local and timezone; interval: interval_minutes; "
        "one_shot: one_shot_at (stored as manual); manual: no recurring timing.")
    daily_time_local: str | None = Field(
        None, description="Local HH:MM (24-hour) for daily schedules only.")
    timezone: str | None = Field(
        None, description="IANA timezone for daily schedules, e.g. Europe/Madrid.")
    interval_minutes: int | None = Field(
        None, gt=0, description="Positive interval in minutes, for interval schedules only.")
    interval_anchor_at: str | None = Field(
        None, description="Optional timezone-aware ISO timestamp for interval alignment; defaults to creation time.")
    one_shot_at: str | None = Field(
        None, description="Timezone-aware ISO timestamp for a single scheduled run; use manual or one_shot.")
    priority: int = Field(5, ge=0, le=9, description="Higher values run first.")
    miss_policy: Literal["skip", "merge_next", "run_late"] = Field(
        "run_late", description="After the late window: skip, merge into the next recurring run, "
        "or run late. Manual-only rules require run_late; one-shot cannot merge_next.")
    max_lateness_minutes: int = Field(
        30, ge=0, description="Minutes after scheduled time before the execution window closes. "
        "run_late can execute beyond this window.")
    window_before_minutes: int = Field(
        0, ge=0, description="Minutes before scheduled time when execution becomes eligible. "
        "For intervals, (1440 + early window) // interval_minutes + 2 must be at most 2000.")
    lease_seconds: int = Field(1800, gt=0, description="Worker lease duration in seconds.")
    max_attempts: int = Field(3, gt=0, description="Maximum execution attempts including the first.")
    timezone_name: str | None = Field(
        None, description="Legacy alias for timezone; prefer timezone.",
        json_schema_extra={"deprecated": True})
    window_after_minutes: int | None = Field(
        None, ge=0, description="Legacy alias for max_lateness_minutes; prefer max_lateness_minutes.",
        json_schema_extra={"deprecated": True})

    @model_validator(mode="after")
    def validate_aliases(self):
        supplied = self.model_fields_set
        for canonical, alias in (("timezone", "timezone_name"),
                                 ("max_lateness_minutes", "window_after_minutes")):
            if canonical in supplied and alias in supplied and getattr(self, canonical) != getattr(self, alias):
                raise ValueError(f"{canonical} and legacy {alias} disagree; use {canonical}.")
        if "window_after_minutes" in supplied and self.window_after_minutes is None:
            raise ValueError("window_after_minutes must be a nonnegative integer; use max_lateness_minutes.")
        return self


class CreateRule(RuleFields):
    """Create an active rule. Pause or resume an existing rule with RuleChanges."""

    title: Title = Field(description="Short human-readable task name.")
    instructions: Instructions = Field(description="Complete instructions the worker will execute.")


class RuleChanges(RuleFields):
    """Partial edit: omitted fields stay unchanged, even when a default appears in the schema."""

    title: Title | None = Field(None, description="New task name; omit to keep unchanged.")
    instructions: Instructions | None = Field(None, description="New complete worker instructions; omit to keep unchanged.")
    is_active: bool = Field(True, description="false pauses; true resumes; omit to keep current state.")

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("changes must contain at least one field.")
        for name in ("title", "instructions"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null; omit it to keep unchanged.")
        return self
