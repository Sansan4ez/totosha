import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logger_stub = ModuleType("logger")
logger_stub.agent_logger = SimpleNamespace(info=lambda *args, **kwargs: None)
sys.modules.setdefault("logger", logger_stub)

import config as core_config
from session_manager import SessionManager


class WebSessionManagerTests(unittest.TestCase):
    def test_web_sessions_use_dedicated_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager()
            original_workspace = core_config.CONFIG.workspace
            manager.web_workspace_root = os.path.join(tmpdir, "_web")
            core_config.CONFIG.workspace = tmpdir
            try:
                bot_session = manager.get(11, 22, source="bot")
                web_session = manager.get(11, 22, source="web")
            finally:
                core_config.CONFIG.workspace = original_workspace

            self.assertTrue(bot_session.cwd.endswith("/11"))
            self.assertIn("/_web/11_22", web_session.cwd)
            self.assertNotEqual(bot_session.cwd, web_session.cwd)

    def test_reclaim_expired_web_sessions_removes_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager()
            original_workspace = core_config.CONFIG.workspace
            manager.web_workspace_root = os.path.join(tmpdir, "_web")
            core_config.CONFIG.workspace = tmpdir
            try:
                with mock.patch.dict(os.environ, {"AGENT_WEB_SESSION_TTL_S": "60"}, clear=False):
                    session = manager.get(91, 92, source="web")
                    with open(os.path.join(session.cwd, "touch.txt"), "w", encoding="utf-8") as handle:
                        handle.write("ok")

                    reclaimed = manager.reclaim_expired_web_sessions(
                        now=session.last_activity_at + 61,
                    )

                    self.assertEqual(reclaimed, 1)
                    self.assertFalse(os.path.exists(session.cwd))
                    self.assertFalse(manager.reclaim(91, 92, source="web"))
            finally:
                core_config.CONFIG.workspace = original_workspace


if __name__ == "__main__":
    unittest.main()
