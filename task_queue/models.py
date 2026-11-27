"""Shared values for the durable task queue."""

from enum import Enum


class ScheduleKind(str, Enum):
    MANUAL = "manual"
    INTERVAL = "interval"
    DAILY = "daily"


class MissPolicy(str, Enum):
    SKIP = "skip"
    MERGE_NEXT = "merge_next"
    RUN_LATE = "run_late"


class InstanceStatus(str, Enum):
    FUTURE = "future"
    READY = "ready"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    MERGED = "merged"
    CANCELLED = "cancelled"


# Proposal creation defaults, also advertised by the MCP create schema.
# Keep storage names here so existing proposal payloads and fingerprints stay stable.
RULE_CREATE_DEFAULTS = {
    "schedule_kind": "manual", "priority": 5,
    "miss_policy": "run_late", "max_lateness_minutes": 30,
    "window_before_minutes": 0, "lease_seconds": 1800,
    "max_attempts": 3, "interval_minutes": None,
    "interval_anchor_at": None, "daily_time_local": None,
    "timezone_name": None, "one_shot_at": None,
}
