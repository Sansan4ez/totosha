import asyncio
import os
import sys
import tempfile
import unittest
import importlib.util
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import ToolContext

_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "files.py"
_SPEC = importlib.util.spec_from_file_location("doc_security_files_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_saved_modules = {name: sys.modules.get(name) for name in ("security", "logger")}
try:
    sys.modules["security"] = types.SimpleNamespace(is_sensitive_file=lambda path: False)
    sys.modules["logger"] = types.SimpleNamespace(tool_logger=types.SimpleNamespace(info=lambda *a, **k: None))
    _SPEC.loader.exec_module(_MODULE)
finally:
    for name, original in _saved_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
is_path_safe = _MODULE.is_path_safe
tool_search_files = _MODULE.tool_search_files
tool_search_text = _MODULE.tool_search_text


class DocSecurityTests(unittest.TestCase):
    def test_managed_doc_corpus_is_not_path_safe_for_generic_file_tools(self):
        safe, reason = is_path_safe("/data/corp_docs/live/doc_123.json", "/workspace/42")
        self.assertFalse(safe)
        self.assertIn("managed document corpus", reason)
        safe, reason = is_path_safe("/data/skills/corp-wiki-md-search/wiki/page.md", "/workspace/42")
        self.assertFalse(safe)
        self.assertIn("managed document corpus", reason)

    def test_search_text_uses_no_shell_and_respects_path_safety(self):
        ctx = ToolContext(cwd="/workspace/42", user_id=42, chat_id=42, chat_type="private")
        result = asyncio.run(tool_search_text({"pattern": "test", "path": "/data/corp_docs/live"}, ctx))
        self.assertFalse(result.success)
        self.assertIn("managed document corpus", result.error)

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "note.txt"
            file_path.write_text("hello grep", encoding="utf-8")
            ctx = ToolContext(cwd=tmpdir, user_id=42, chat_id=42, chat_type="private")
            with patch.object(_MODULE.subprocess, "run") as run_mock, patch.object(_MODULE.shutil, "which", return_value="/usr/bin/rg"):
                run_mock.return_value.stdout = f"{file_path}:1:hello grep\n"
                run_mock.return_value.returncode = 0
                result = asyncio.run(tool_search_text({"pattern": "grep", "path": tmpdir}, ctx))

            self.assertTrue(result.success)
            called_args = run_mock.call_args.args[0]
            self.assertIsInstance(called_args, list)
            self.assertEqual(called_args[0], "/usr/bin/rg")
            self.assertIn("grep", result.output)

    def test_search_files_respects_managed_corpus_boundary(self):
        ctx = ToolContext(cwd="/workspace/42", user_id=42, chat_id=42, chat_type="private")
        result = asyncio.run(tool_search_files({"pattern": "/data/corp_docs/live/**/*.json"}, ctx))
        self.assertFalse(result.success)
        self.assertIn("managed document corpus", result.error)

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "docs").mkdir()
            (workspace / "docs" / "note.md").write_text("hello", encoding="utf-8")
            ctx = ToolContext(cwd=tmpdir, user_id=42, chat_id=42, chat_type="private")
            result = asyncio.run(tool_search_files({"pattern": "docs/**/*.md"}, ctx))

        self.assertTrue(result.success)
        self.assertIn("note.md", result.output)


if __name__ == "__main__":
    unittest.main()
