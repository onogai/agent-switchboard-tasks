"""Agent-facing rule contract: real MCP requests against disposable storage."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastmcp import Client
from jsonschema import Draft202012Validator

from task_queue import admin, mcp_server, proposals
from task_queue.models import RULE_CREATE_DEFAULTS


class RuleMcpContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"QUEUE_DB_PATH": str(Path(tmp.name) / "queue.sqlite3")})
        env.start()
        self.addCleanup(env.stop)

    async def test_schema_contains_fields_defaults_and_constraints(self):
        async with Client(mcp_server.mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        for name, argument in (("propose_create_task_rule", "rule"),
                               ("propose_update_task_rule", "changes")):
            schema = tools[name].inputSchema
            Draft202012Validator.check_schema(schema)
            nested = schema["properties"][argument]
            if "$ref" in nested:
                nested = schema["$defs"][nested["$ref"].rsplit("/", 1)[-1]]
            fields = nested["properties"]
            self.assertFalse(nested["additionalProperties"])
            self.assertEqual(fields["priority"]["maximum"], 9)
            self.assertEqual(fields["max_lateness_minutes"]["minimum"], 0)
            self.assertIn("daily", fields["schedule_kind"]["enum"])
            self.assertIn("timezone", fields)
            self.assertTrue(fields["timezone_name"]["deprecated"])
            self.assertTrue(fields["window_after_minutes"]["deprecated"])
            validator = Draft202012Validator(schema)
            if argument == "rule":
                self.assertEqual(set(nested["required"]), {"title", "instructions"})
                self.assertNotIn("is_active", fields)
                for key, value in RULE_CREATE_DEFAULTS.items():
                    self.assertEqual(fields["timezone" if key == "timezone_name" else key]["default"], value)
                base = {"title": "Task", "instructions": "Run"}
                self.assertTrue(validator.is_valid({"rule": base, "idempotency_key": "key"}))
                self.assertFalse(validator.is_valid({"rule": {**base, "window_after_minutes": None},
                                                     "idempotency_key": "key"}))
            else:
                self.assertIn("is_active", fields)
                self.assertFalse(nested.get("required"))
                self.assertEqual(nested["minProperties"], 1)
                self.assertFalse(any("default" in field for field in fields.values()))
                base = {"rule_id": "id", "expected_version": 1, "idempotency_key": "key"}
                self.assertFalse(validator.is_valid({**base, "changes": {}}))
                for key in ("title", "instructions", "is_active", "priority", "window_after_minutes"):
                    self.assertFalse(validator.is_valid({**base, "changes": {key: None}}))
                self.assertTrue(validator.is_valid({**base, "changes": {"timezone": None}}))

    async def test_daily_create_and_partial_update(self):
        async with Client(mcp_server.mcp) as client:
            rule = dict(title="Daily", instructions="Send a summary", schedule_kind="daily",
                        daily_time_local="08:00", timezone="Europe/Madrid", priority=8)
            result = await client.call_tool("propose_create_task_rule",
                                            {"rule": rule, "idempotency_key": "daily"})
            proposal = result.structured_content
            self.assertEqual(proposal["status"], "pending")
            approved = proposals.decide_proposal(proposal["id"], True, "reviewer")
            self.assertEqual(approved["status"], "approved")
            rule_id = approved["result"]["id"]

            async def read():
                result = await client.call_tool("get_task_rule", {"rule_id": rule_id})
                return result.structured_content["definition"]

            async def edit(before, changes, key):
                result = await client.call_tool("propose_update_task_rule", {
                    "rule_id": rule_id, "changes": changes,
                    "expected_version": before["version"], "idempotency_key": key})
                proposal = result.structured_content
                self.assertEqual(proposal["status"], "pending")
                self.assertEqual(proposals.decide_proposal(proposal["id"], True, "reviewer")["status"],
                                 "approved")
                return proposal

            before = await read()
            self.assertEqual(before["timezone"], "Europe/Madrid")
            self.assertIs(before["is_active"], True)
            self.assertEqual(before["max_lateness_minutes"], 30)
            await edit(before, {"is_active": False}, "pause")
            paused = await read()
            edit_proposal = await edit(paused, {"daily_time_local": "09:00"}, "edit")
            self.assertEqual(edit_proposal["payload"], {"daily_time_local": "09:00"})
            after = await read()
            self.assertEqual(after["daily_time_local"], "09:00")
            self.assertEqual(after["timezone"], before["timezone"])
            self.assertEqual(after["instructions"], before["instructions"])
            self.assertEqual(after["priority"], 8)
            self.assertEqual(after["schedule_kind"], "daily")
            self.assertIs(after["is_active"], False)
            await edit(after, {"schedule_kind": "interval", "interval_minutes": 60,
                               "daily_time_local": None, "timezone": None}, "switch")
            switched = await read()
            self.assertEqual(switched["interval_minutes"], 60)
            self.assertIsNone(switched["timezone"])
            self.assertIs(switched["is_active"], False)

    async def test_group_and_archive_catalog_contract(self):
        async with Client(mcp_server.mcp) as client:
            result = await client.call_tool("propose_create_task_rule", {
                "rule": {"title": "Grouped", "instructions": "Run", "group": " News "},
                "idempotency_key": "group-create"})
            created = proposals.decide_proposal(result.structured_content["id"], True, "reviewer")
            self.assertEqual(created["status"], "approved")
            rule_id = created["result"]["id"]
            before = admin.get_definition(rule_id)["definition"]
            self.assertEqual(before["group"], "News")
            edit = await client.call_tool("propose_update_task_rule", {
                "rule_id": rule_id, "changes": {"group": None},
                "expected_version": before["version"], "idempotency_key": "group-clear"})
            self.assertTrue(edit.structured_content["impact"]["metadata_only"])
            self.assertEqual(proposals.decide_proposal(edit.structured_content["id"], True,
                "reviewer")["status"], "approved")
            after = admin.get_definition(rule_id)["definition"]
            self.assertIsNone(after["group"])
            self.assertEqual(after["execution_version"], before["execution_version"])
            archived = admin.create_definition("AAA", "Run", priority=9)
            admin.archive_definition(archived)
            paused = admin.create_definition("Paused", "Run")
            admin.update_definition(paused, {"is_active": False})
            async def listed(**kwargs):
                response = await client.call_tool("list_task_rules", kwargs)
                return response.structured_content["rules"]
            self.assertEqual({row["id"] for row in await listed()}, {rule_id, paused})
            self.assertNotEqual((await listed(limit=1))[0]["id"], archived)
            self.assertEqual({row["id"] for row in await listed(is_active=False)}, {paused})
            self.assertEqual({row["id"] for row in await listed(is_active=False, include_archived=True)},
                             {paused, archived})
            self.assertEqual((await listed(include_archived=True, limit=1))[0]["id"], archived)
            self.assertIn("group", (await listed())[0])
            self.assertIsNotNone(admin.get_definition(archived)["definition"]["archived_at"])

    async def test_legacy_aliases_same_proposal_and_conflicts(self):
        async with Client(mcp_server.mcp) as client:
            common = dict(title="Daily", instructions="Run", schedule_kind="daily",
                          daily_time_local="08:00")
            legacy = dict(common, timezone_name="Europe/Madrid", window_after_minutes=45)
            canonical = dict(common, timezone="Europe/Madrid", max_lateness_minutes=45)
            first = await client.call_tool("propose_create_task_rule",
                                           {"rule": legacy, "idempotency_key": "same"})
            second = await client.call_tool("propose_create_task_rule",
                                            {"rule": canonical, "idempotency_key": "same"})
            self.assertEqual(first.structured_content["id"], second.structured_content["id"])
            for conflict, message in (
                (dict(canonical, timezone_name="UTC"), "timezone"),
                (dict(canonical, window_after_minutes=10), "max_lateness_minutes"),
            ):
                result = await client.call_tool("propose_create_task_rule",
                    {"rule": conflict, "idempotency_key": "bad"}, raise_on_error=False)
                self.assertTrue(result.is_error)
                self.assertIn(message, str(result.content))
                self.assertIn("disagree", str(result.content))

    async def test_validation_names_offending_fields(self):
        async with Client(mcp_server.mcp) as client:
            common = {"title": "Task", "instructions": "Run"}
            for rule, expected in (
                ({**common, "is_active": False}, "is_active"),
                ({**common, "priority": 10}, "priority"),
                ({**common, "window_after_minutes": None}, "window_after_minutes"),
                ({"instructions": "Run"}, "title"),
                ({**common, "schedule_kind": "daily", "daily_time_local": "08:00",
                  "timezone": "Not/AZone"}, "IANA timezone"),
                ({**common, "schedule_kind": "interval"}, "positive number of minutes"),
            ):
                result = await client.call_tool("propose_create_task_rule",
                    {"rule": rule, "idempotency_key": "bad"}, raise_on_error=False)
                self.assertTrue(result.is_error)
                self.assertIn(expected, str(result.content))
            for changes, expected in (({}, "at least one field"), ({"title": None}, "title"),
                                      ({"is_active": None}, "is_active")):
                result = await client.call_tool("propose_update_task_rule", {
                    "rule_id": "unused", "expected_version": 1, "changes": changes,
                    "idempotency_key": "bad"}, raise_on_error=False)
                self.assertTrue(result.is_error)
                self.assertIn(expected, str(result.content))
            self.assertEqual(proposals.list_proposals(), [])

    def test_direct_proposal_unknown_fields(self):
        with self.assertRaisesRegex(admin.QueueAdminError, "Unknown fields: typo"):
            proposals.submit_proposal("create_rule", {"title": "Task", "instructions": "Run",
                "typo": True}, None, None, "agent", "bad")
