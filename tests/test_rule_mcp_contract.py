"""Agent-facing rule contract: discoverable schema and real proposal round trips."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from task_queue import admin, mcp_server, proposals
from task_queue.rule_inputs import CreateRule, RuleChanges


class RuleMcpContractTest(unittest.TestCase):
    def test_schema_contains_fields_defaults_and_constraints(self):
        tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
        for name, argument in (("propose_create_task_rule", "rule"),
                               ("propose_update_task_rule", "changes")):
            schema = tools[name].parameters
            nested = schema["properties"][argument]
            if "$ref" in nested:
                nested = schema["$defs"][nested["$ref"].rsplit("/", 1)[-1]]
            fields = nested["properties"]
            self.assertFalse(nested["additionalProperties"])
            self.assertEqual(fields["priority"]["default"], 5)
            self.assertEqual(fields["priority"]["maximum"], 9)
            self.assertEqual(fields["max_lateness_minutes"]["minimum"], 0)
            self.assertIn("daily", fields["schedule_kind"]["enum"])
            self.assertIn("timezone", fields)
            self.assertTrue(fields["timezone_name"]["deprecated"])
            self.assertTrue(fields["window_after_minutes"]["deprecated"])
            if argument == "rule":
                self.assertEqual(set(nested["required"]), {"title", "instructions"})
                self.assertNotIn("is_active", fields)
            else:
                self.assertIn("is_active", fields)
                self.assertFalse(nested.get("required"))

    def test_daily_create_and_partial_update(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "QUEUE_DB_PATH": str(Path(tmp) / "queue.sqlite3")}):
            rule = CreateRule(title="Daily", instructions="Send a summary",
                              schedule_kind="daily", daily_time_local="08:00",
                              timezone="Europe/Madrid")
            proposal = asyncio.run(mcp_server.propose_create_task_rule(rule, "daily"))
            self.assertEqual(proposal["status"], "pending")
            approved = proposals.decide_proposal(proposal["id"], True, "reviewer")
            self.assertEqual(approved["status"], "approved")
            rule_id = approved["result"]["id"]
            before = asyncio.run(mcp_server.get_task_rule(rule_id))["definition"]
            self.assertEqual(before["timezone"], "Europe/Madrid")
            self.assertIs(before["is_active"], True)
            self.assertEqual(before["max_lateness_minutes"], 30)
            changes = RuleChanges(is_active=False, daily_time_local="09:00")
            edit = asyncio.run(mcp_server.propose_update_task_rule(
                rule_id, changes, before["version"], "edit"))
            self.assertEqual(edit["payload"], {"is_active": False, "daily_time_local": "09:00"})
            self.assertEqual(proposals.decide_proposal(edit["id"], True, "reviewer")["status"], "approved")
            after = asyncio.run(mcp_server.get_task_rule(rule_id))["definition"]
            self.assertEqual(after["daily_time_local"], "09:00")
            self.assertEqual(after["timezone"], before["timezone"])
            self.assertEqual(after["instructions"], before["instructions"])
            self.assertIs(after["is_active"], False)
            switch = RuleChanges(schedule_kind="interval", interval_minutes=60,
                                 daily_time_local=None, timezone=None)
            edit = asyncio.run(mcp_server.propose_update_task_rule(
                rule_id, switch, after["version"], "switch"))
            self.assertEqual(proposals.decide_proposal(edit["id"], True, "reviewer")["status"], "approved")
            switched = asyncio.run(mcp_server.get_task_rule(rule_id))["definition"]
            self.assertEqual(switched["interval_minutes"], 60)
            self.assertIsNone(switched["timezone"])

    def test_legacy_aliases_same_proposal_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "QUEUE_DB_PATH": str(Path(tmp) / "queue.sqlite3")}):
            common = dict(title="Daily", instructions="Run", schedule_kind="daily",
                          daily_time_local="08:00")
            legacy = CreateRule(**common, timezone_name="Europe/Madrid", window_after_minutes=45)
            canonical = CreateRule(**common, timezone="Europe/Madrid", max_lateness_minutes=45)
            first = asyncio.run(mcp_server.propose_create_task_rule(legacy, "same"))
            second = asyncio.run(mcp_server.propose_create_task_rule(canonical, "same"))
            self.assertEqual(first["id"], second["id"])
            with self.assertRaisesRegex(ValidationError, "timezone.*disagree"):
                CreateRule(**common, timezone="UTC", timezone_name="Europe/Madrid")
            with self.assertRaisesRegex(ValidationError, "max_lateness_minutes.*disagree"):
                RuleChanges(max_lateness_minutes=5, window_after_minutes=10)

    def test_validation_names_offending_fields(self):
        with self.assertRaisesRegex(ValidationError, "is_active"):
            CreateRule(title="Task", instructions="Run", is_active=False)
        with self.assertRaisesRegex(ValidationError, "priority"):
            RuleChanges(priority=10)
        with self.assertRaisesRegex(ValidationError, "title"):
            RuleChanges(title=None)
        with self.assertRaisesRegex(ValidationError, "at least one field"):
            RuleChanges()
        with self.assertRaisesRegex(admin.QueueAdminError, "IANA timezone"):
            asyncio.run(mcp_server.propose_create_task_rule(
                CreateRule(title="Task", instructions="Run", schedule_kind="daily",
                           daily_time_local="08:00", timezone="Not/AZone"), "bad"))
        with self.assertRaisesRegex(admin.QueueAdminError, "Unknown fields: typo"):
            proposals.submit_proposal("create_rule", {"title": "Task", "instructions": "Run",
                "typo": True}, None, None, "agent", "bad")
