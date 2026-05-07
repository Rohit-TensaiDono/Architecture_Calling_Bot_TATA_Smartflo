import asyncio
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class BatchManagerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="batch-manager-")
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)

        import batch_manager
        import db

        self.batch_manager_module = batch_manager
        self.db_module = db
        if getattr(db._local, "conn", None) is not None:
            db._local.conn.close()
            db._local.conn = None
        db.init_db()
        sys.modules.setdefault(
            "requests",
            types.SimpleNamespace(
                post=lambda *args, **kwargs: types.SimpleNamespace(status_code=200, text="ok")
            ),
        )
        self.dialed = []

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _manager(self):
        def fake_dialer(number, agent):
            self.dialed.append((number, agent))
            return {
                "success": True,
                "status_code": 200,
                "data": {"call_id": f"call-{number}-{agent}"},
            }

        manager = self.batch_manager_module.BatchCallManager(fake_dialer)
        manager.set_loop(asyncio.get_running_loop())
        return manager

    async def _drain(self):
        await asyncio.sleep(0.1)

    async def test_next_batch_waits_for_all_current_calls(self):
        manager = self._manager()
        result = manager.create_job("job-wait", ["1001", "1002", "1003", "1004"], ["agent-a", "agent-b"])
        self.assertTrue(result["success"])

        await self._drain()
        self.assertEqual(self.dialed, [("1001", "agent-a"), ("1002", "agent-b")])

        manager.register_session("1001", "agent-a", "session-1", "sid-1")
        manager.register_session("1002", "agent-b", "session-2", "sid-2")
        manager.on_call_completed("session-1", "completed", {"session_id": "session-1"})
        await self._drain()
        self.assertEqual(len(self.dialed), 2)

        manager.on_provider_status({"call_id": "sid-2", "call_status": "missed"})
        await self._drain()
        self.assertEqual(
            self.dialed,
            [("1001", "agent-a"), ("1002", "agent-b"), ("1003", "agent-a"), ("1004", "agent-b")],
        )

    async def test_duplicate_completion_does_not_advance_twice(self):
        manager = self._manager()
        manager.create_job("job-dupe", ["2001", "2002", "2003"], ["agent-a"])
        await self._drain()
        self.assertEqual(self.dialed, [("2001", "agent-a")])

        manager.register_session("2001", "agent-a", "session-1", "sid-1")
        manager.on_call_completed("session-1", "completed", {})
        manager.on_call_completed("session-1", "completed", {})
        manager.on_provider_status({"call_id": "sid-1", "call_status": "completed"})
        await self._drain()

        self.assertEqual(self.dialed, [("2001", "agent-a"), ("2002", "agent-a")])

    async def test_job_completes_after_final_batch(self):
        manager = self._manager()
        manager.create_job("job-done", ["3001", "3002"], ["agent-a", "agent-b"])
        await self._drain()

        manager.register_session("3001", "agent-a", "session-1", "sid-1")
        manager.register_session("3002", "agent-b", "session-2", "sid-2")
        manager.on_call_completed("session-1", "completed", {})
        manager.on_call_completed("session-2", "failed", {})
        await self._drain()

        status = manager.status("job-done")
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["counts"], {"completed": 1, "failed": 1})

    async def test_db_completion_listener_fires_once(self):
        events = []
        self.db_module.register_call_completion_listener(
            lambda session_id, status, call_info: events.append((session_id, status, call_info["call_status"]))
        )
        self.db_module.db.create_call("session-once", mobile_number="agent-a", customer_number="4001")

        first = self.db_module.db.complete_call("session-once", status="completed")
        second = self.db_module.db.complete_call("session-once", status="dropped")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(events, [("session-once", "completed", "completed")])


if __name__ == "__main__":
    unittest.main()
