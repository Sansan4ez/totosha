import os
import sys
import unittest
import types
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import ToolContext


def _load_bash_module():
    sandbox_module = types.ModuleType("tools.sandbox")

    async def execute_in_sandbox(user_id, command, cwd):
        return False, "sandbox unavailable", False

    def mark_user_active(user_id):
        return None

    sandbox_module.execute_in_sandbox = execute_in_sandbox
    sandbox_module.mark_user_active = mark_user_active

    tools_package = types.ModuleType("tools")
    tools_package.sandbox = sandbox_module

    sys.modules["tools"] = tools_package
    sys.modules["tools.sandbox"] = sandbox_module

    bash_path = Path(__file__).resolve().parents[1] / "tools" / "bash.py"
    spec = importlib.util.spec_from_file_location("core_bash_module", bash_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


bash = _load_bash_module()


TEST_CTX = ToolContext(
    cwd="/tmp",
    session_id="test-session",
    user_id=12345,
    chat_id=12345,
    chat_type="private",
    source="bot",
)


class BashPublicModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_mode_blocks_local_shell_when_sandbox_disabled(self):
        previous_mode = os.environ.get("ACCESS_MODE")
        previous_enabled = bash.SANDBOX_ENABLED
        os.environ["ACCESS_MODE"] = "public"
        bash.SANDBOX_ENABLED = False
        try:
            result = await bash.tool_run_command({"command": "echo hello"}, TEST_CTX)
        finally:
            bash.SANDBOX_ENABLED = previous_enabled
            if previous_mode is None:
                os.environ.pop("ACCESS_MODE", None)
            else:
                os.environ["ACCESS_MODE"] = previous_mode

        self.assertFalse(result.success)
        self.assertIn("sandbox", result.error.lower())

    async def test_public_mode_blocks_fallback_after_sandbox_failure(self):
        previous_mode = os.environ.get("ACCESS_MODE")
        previous_enabled = bash.SANDBOX_ENABLED
        previous_execute = bash.execute_in_sandbox
        previous_mark = bash.mark_user_active
        os.environ["ACCESS_MODE"] = "public"
        bash.SANDBOX_ENABLED = True

        async def fake_execute_in_sandbox(user_id, command, cwd):
            return False, "sandbox unavailable", False

        def fake_mark_user_active(user_id):
            return None

        bash.execute_in_sandbox = fake_execute_in_sandbox
        bash.mark_user_active = fake_mark_user_active
        try:
            result = await bash.tool_run_command({"command": "echo hello"}, TEST_CTX)
        finally:
            bash.SANDBOX_ENABLED = previous_enabled
            bash.execute_in_sandbox = previous_execute
            bash.mark_user_active = previous_mark
            if previous_mode is None:
                os.environ.pop("ACCESS_MODE", None)
            else:
                os.environ["ACCESS_MODE"] = previous_mode

        self.assertFalse(result.success)
        self.assertIn("sandbox", result.error.lower())


if __name__ == "__main__":
    unittest.main()
