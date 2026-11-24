"""Regression: MCP catalogs must not leak large execution bodies."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_queue import admin, mcp_server, service


class CompactMcpListsTest(unittest.TestCase):
    def test_catalogs_are_metadata_only_and_paginated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "queue.sqlite3"
            prompt = "x" * 100_000
            result = "y" * 1_000_000
            with patch.dict(os.environ, {"QUEUE_DB_PATH": str(db)}):
                rule = admin.create_definition("Large task", prompt, db_path=db)
                task_id = admin.trigger_definition(rule, db_path=db)
                claimed = service.claim_next_task(db_path=db)["task"]
                self.assertEqual(claimed["task_id"], task_id)
                self.assertEqual(claimed["instructions"], prompt)
                service.report_task_result(task_id, claimed["lease_token"],
                                           "succeeded", result=result, db_path=db)
                second = admin.create_definition("Second", "small", db_path=db)
                admin.trigger_definition(second, db_path=db)

                rules = asyncio.run(mcp_server.list_task_rules(limit=1))
                self.assertEqual(len(rules["rules"]), 1)
                self.assertNotIn("instructions", rules["rules"][0])
                next_rules = asyncio.run(mcp_server.list_task_rules(limit=1, offset=1))
                self.assertNotEqual(rules["rules"][0]["id"], next_rules["rules"][0]["id"])

                rows = asyncio.run(mcp_server.list_task_instances(status="succeeded"))
                self.assertEqual(len(rows["instances"]), 1)
                row = rows["instances"][0]
                self.assertEqual(row["id"], task_id)
                self.assertEqual(row["definition_id"], rule)
                self.assertNotIn("instructions_snapshot", row)
                self.assertNotIn("result_json", row)
                self.assertNotIn("last_error", row)
                self.assertNotIn("lease_token", row)
                self.assertLess(len(json.dumps(rows).encode("utf-8")), 2048)
                self.assertEqual(asyncio.run(mcp_server.list_task_instances(
                    status="succeeded", limit=1, offset=1)), {"instances": []})

                detail = asyncio.run(mcp_server.get_task_instance(task_id))
                self.assertEqual(detail["instance"]["instructions_snapshot"], prompt)
                self.assertEqual(json.loads(detail["instance"]["result_json"]), result)
                self.assertNotIn("lease_token", detail["instance"])
                self.assertEqual(admin.get_definition(rule, db_path=db)["definition"]["instructions"], prompt)
                self.assertEqual(len(admin.list_instances(db_path=db)), 2)
                self.assertEqual(len(admin.list_definitions(db_path=db)), 2)


if __name__ == "__main__":
    unittest.main()
