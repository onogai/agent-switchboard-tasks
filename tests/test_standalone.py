"""Standalone Task Queue contract smoke tests with Gateway absent."""
import asyncio
import importlib.abc
import sys
import tempfile
import unittest
from pathlib import Path

EXPECTED = {
    "claim_next_task", "extend_task_lease", "report_task_result",
    "list_task_rules", "get_task_rule", "list_task_instances",
    "get_task_instance", "get_task_proposal", "propose_create_task_rule",
    "propose_update_task_rule", "propose_archive_task_rule",
    "propose_run_task_rule", "propose_cancel_task_instance",
    "propose_retry_task_instance",
}


class RejectGateway(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "gateway" or fullname.startswith("gateway."):
            raise ImportError("Gateway Core must not be imported by Tasks")


class IsolationTests(unittest.TestCase):
    def test_exact_mcp_catalog_without_gateway(self):
        blocker = RejectGateway()
        sys.meta_path.insert(0, blocker)
        try:
            from task_queue.mcp_server import mcp
            tools = asyncio.run(mcp.list_tools())
            self.assertEqual({tool.name for tool in tools}, EXPECTED)
            self.assertFalse(any(name == "gateway" or name.startswith("gateway.")
                                 for name in sys.modules))
        finally:
            sys.meta_path.remove(blocker)

    def test_queue_storage_on_disposable_database(self):
        from task_queue.db import open_queue_db
        with tempfile.TemporaryDirectory() as td:
            with open_queue_db(Path(td) / "test.sqlite3") as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_web_ui_assets_present(self):
        self.assertTrue(Path("/app/queue_ui/dist/index.html").is_file())
        self.assertTrue(Path("/app/queue_ui/managed-dist/index.html").is_file())
        self.assertFalse(Path("/app/queue_ui/admin-dist").exists(),
                         "Gateway Admin UI must not be shipped by Queue")


if __name__ == "__main__":
    unittest.main()
