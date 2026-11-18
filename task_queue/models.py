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
