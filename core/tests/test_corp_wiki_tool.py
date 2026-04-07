import asyncio
import os
import sys
import tempfile
import unittest
import importlib.util
import json
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import ToolContext
from documents.usage import load_usage_stats

_DOC_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "doc_search.py"
_DOC_SPEC = importlib.util.spec_from_file_location("doc_search_tool_module", _DOC_MODULE_PATH)
assert _DOC_SPEC and _DOC_SPEC.loader
_DOC_MODULE = importlib.util.module_from_spec(_DOC_SPEC)
sys.modules[_DOC_SPEC.name] = _DOC_MODULE
_DOC_SPEC.loader.exec_module(_DOC_MODULE)
tool_doc_search = _DOC_MODULE.tool_doc_search

_tools_package = sys.modules.get("tools")
if _tools_package is None:
    _tools_package = types.ModuleType("tools")
    sys.modules["tools"] = _tools_package
setattr(_tools_package, "doc_search", _DOC_MODULE)
sys.modules["tools.doc_search"] = _DOC_MODULE

_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "corp_wiki.py"
_SPEC = importlib.util.spec_from_file_location("corp_wiki_tool_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
tool_corp_wiki_search = _MODULE.tool_corp_wiki_search


class CorpWikiToolTests(unittest.TestCase):
    def test_alias_tool_returns_structured_matches_without_shell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            wiki_dir = root / "legacy"
            docs_root = root / "corp_docs"
            wiki_dir.mkdir(parents=True)
            (wiki_dir / "common_information_about_company.md").write_text(
                "# О компании\n\n"
                "Компания ЛАДзавод светотехники основана в 2006 году.\n\n"
                "Контакты: +7 (351) 239-18-11, lad@ladled.ru\n",
                encoding="utf-8",
            )
            ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")

            with patch.dict(
                os.environ,
                {"CORP_WIKI_PATH": str(wiki_dir), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                result = asyncio.run(tool_corp_wiki_search({"query": "контакты", "top": 3}, ctx))

        self.assertTrue(result.success)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tool_name"], "corp_wiki_search")
        self.assertEqual(payload["alias_for"], "doc_search")
        self.assertEqual(payload["search_substrate"], "parsed_sidecars")
        self.assertIn("common_information_about_company.md", payload["results"][0]["relative_path"])
        self.assertIn("lad@ladled.ru", payload["results"][0]["snippet"])
        artifact = result.metadata.get("bench_artifact")
        self.assertEqual(artifact["tool"], "corp_wiki_search")
        self.assertEqual(artifact["kind"], "doc_search")
        self.assertEqual(artifact["payload"]["search_substrate"], "parsed_sidecars")
        self.assertIn("common_information_about_company.md", artifact["payload"]["results"][0]["relative_path"])
        self.assertIn("lad@ladled.ru", artifact["payload"]["results"][0]["preview"])

    def test_alias_and_canonical_tools_share_usage_stats_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            wiki_dir = root / "legacy"
            docs_root = root / "corp_docs"
            wiki_dir.mkdir(parents=True)
            (wiki_dir / "faq.md").write_text("Гарантия на светильник составляет 5 лет.", encoding="utf-8")
            ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")

            with patch.dict(
                os.environ,
                {"CORP_WIKI_PATH": str(wiki_dir), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                canonical = asyncio.run(tool_doc_search({"query": "гарантия", "top": 3}, ctx))
                alias = asyncio.run(tool_corp_wiki_search({"query": "гарантия", "top": 3}, ctx))
                usage = load_usage_stats()

        self.assertTrue(canonical.success)
        self.assertTrue(alias.success)
        self.assertEqual(len(usage), 2)
        self.assertEqual(usage[0]["tool_name"], "doc_search")
        self.assertIsNone(usage[0]["alias_for"])
        self.assertEqual(usage[1]["tool_name"], "corp_wiki_search")
        self.assertEqual(usage[1]["alias_for"], "doc_search")


if __name__ == "__main__":
    unittest.main()
