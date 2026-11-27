"""Standalone Task Queue MCP entrypoint, independent of gateway imports.

Run as: python -m task_queue.mcp_server
Do not expose this unauthenticated service publicly; bind to a private Docker network.
The gateway continues to own OAuth, public catalog and profile grants.
"""
from __future__ import annotations

import asyncio
import os

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import admin, proposals, service
from .rule_inputs import CreateRule, RuleChanges, IdempotencyKey, RuleVersion

mcp = FastMCP("Task Queue")


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("limit must be 1–100 and offset must be nonnegative.")


def _public_instance(row: dict) -> dict:
    return {key: value for key, value in row.items()
            if key not in {"lease_token", "report_hash", "report_response_json"}}


def _proposer() -> str:
    return "google:" + os.environ.get("ALLOWED_GOOGLE_EMAIL", "authenticated-mcp").strip().lower()


async def claim_next_task() -> dict:
    """Reserve the next ready task, or return task: null."""
    return await asyncio.to_thread(service.claim_next_task)


async def extend_task_lease(task_id: str, lease_token: str) -> dict:
    """Extend the current task lease."""
    return await asyncio.to_thread(service.extend_task_lease, task_id, lease_token)


async def report_task_result(task_id: str, lease_token: str, status: str,
                             result: str | None = None, error: str | None = None) -> dict:
    """Report one task attempt as succeeded or failed."""
    return await asyncio.to_thread(service.report_task_result, task_id, lease_token, status, result, error)


async def list_task_rules(is_active: bool | None = None, limit: int = 50, offset: int = 0) -> dict:
    """List task rule metadata only. Use get_task_rule for full instructions."""
    _page(limit, offset)
    rows = await asyncio.to_thread(admin.list_definition_summaries, is_active, limit, offset)
    for row in rows:
        row["is_active"] = bool(row["is_active"])
    return {"rules": rows}


async def get_task_rule(rule_id: str) -> dict:
    """Read a task rule and its events."""
    data = await asyncio.to_thread(admin.get_definition, rule_id)
    data["definition"]["is_active"] = bool(data["definition"]["is_active"])
    return data


async def list_task_instances(status: str | None = None, limit: int = 50,
                              offset: int = 0) -> dict:
    """List task instance metadata only. No instructions, results or errors.
    Use get_task_instance for an explicit diagnostic read, not as agent memory."""
    _page(limit, offset)
    rows = await asyncio.to_thread(admin.list_instance_summaries, status, limit, offset)
    return {"instances": rows}


async def get_task_instance(task_id: str) -> dict:
    """Read an instance, attempts and events."""
    data = await asyncio.to_thread(admin.get_instance, task_id)
    data["instance"] = _public_instance(data["instance"])
    data["attempts"] = [_public_instance(row) for row in data["attempts"]]
    return data


async def get_task_proposal(proposal_id: str) -> dict:
    """Read a proposal's current decision status."""
    return await asyncio.to_thread(proposals.get_proposal, proposal_id)


async def propose_create_task_rule(rule: CreateRule, idempotency_key: IdempotencyKey) -> dict:
    """Schedule a daily, interval, one-shot or manually triggered task for existing workers.
    Creates an active rule after approval (status pending until approved, unless auto-approved).
    Daily example: title, instructions, schedule_kind="daily", daily_time_local="08:00",
    timezone="Europe/Madrid". Interval: schedule_kind="interval", interval_minutes=60.
    One-shot: schedule_kind="one_shot", one_shot_at with UTC offset.
    Omit optional settings to use defaults. Use a new idempotency key per distinct proposal.
    """
    return await asyncio.to_thread(proposals.submit_proposal, "create_rule",
                                   rule.model_dump(exclude_unset=True), None,
                                   None, _proposer(), idempotency_key)


async def propose_update_task_rule(rule_id: str, changes: RuleChanges,
                                   expected_version: RuleVersion,
                                   idempotency_key: IdempotencyKey) -> dict:
    """Edit a scheduled task or pause/resume it (is_active=false/true), subject to approval.
    Read get_task_rule first; pass its definition.version as expected_version.
    Only supplied fields change; null clears nullable timing fields. When changing schedule
    kind, clear incompatible old timing fields with null and supply the new timing fields.
    Use a new idempotency key per distinct edit. Check returned proposal status.
    """
    return await asyncio.to_thread(proposals.submit_proposal, "update_rule",
                                   changes.model_dump(exclude_unset=True),
                                   rule_id, expected_version, _proposer(), idempotency_key)


async def propose_archive_task_rule(rule_id: str, expected_version: int,
                                    idempotency_key: str) -> dict:
    """Propose archiving a rule."""
    return await asyncio.to_thread(proposals.submit_proposal, "archive_rule", {},
                                   rule_id, expected_version, _proposer(), idempotency_key)


async def propose_run_task_rule(rule_id: str, expected_version: int,
                                idempotency_key: str) -> dict:
    """Propose a manual run of a rule."""
    return await asyncio.to_thread(proposals.submit_proposal, "run_rule", {},
                                   rule_id, expected_version, _proposer(), idempotency_key)


async def propose_cancel_task_instance(task_id: str, idempotency_key: str) -> dict:
    """Propose cancelling a pending or leased task."""
    return await asyncio.to_thread(proposals.submit_proposal, "cancel_instance", {},
                                   task_id, None, _proposer(), idempotency_key)


async def propose_retry_task_instance(task_id: str, idempotency_key: str) -> dict:
    """Propose retrying a failed or cancelled task."""
    return await asyncio.to_thread(proposals.submit_proposal, "retry_instance", {},
                                   task_id, None, _proposer(), idempotency_key)


_READ_ONLY = {"list_task_rules", "get_task_rule", "list_task_instances",
              "get_task_instance", "get_task_proposal"}
_DESTRUCTIVE = {"report_task_result", "propose_update_task_rule",
                "propose_archive_task_rule", "propose_cancel_task_instance"}
for _tool in (
    claim_next_task, extend_task_lease, report_task_result,
    list_task_rules, get_task_rule, list_task_instances, get_task_instance,
    get_task_proposal, propose_create_task_rule, propose_update_task_rule,
    propose_archive_task_rule, propose_run_task_rule,
    propose_cancel_task_instance, propose_retry_task_instance,
):
    mcp.tool(_tool, annotations=ToolAnnotations(
        read_only_hint=_tool.__name__ in _READ_ONLY,
        destructive_hint=_tool.__name__ in _DESTRUCTIVE,
        open_world_hint=False,
    ))


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0",
            port=int(os.environ.get("TASK_QUEUE_MCP_PORT", "8771")))
