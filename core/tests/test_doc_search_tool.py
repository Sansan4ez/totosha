import asyncio
import json
import os
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import ToolContext
from documents.usage import load_usage_stats

_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "doc_search.py"
_SPEC = importlib.util.spec_from_file_location("doc_search_tool_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
tool_doc_search = _MODULE.tool_doc_search


class DocSearchToolTests(unittest.TestCase):
    def test_tool_returns_structured_matches_without_shell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_root = root / "corp_docs"
            source = root / "common_information_about_company.md"
            source.write_text(
                "# О компании\n\n"
                "Компания ЛАДзавод светотехники основана в 2006 году.\n\n"
                "Контакты: +7 (351) 239-18-11, lad@ladled.ru\n",
                encoding="utf-8",
            )
            ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")

            old_env = dict(os.environ)
            os.environ.update({"CORP_DOCS_ROOT": str(docs_root)})
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from documents.storage import ingest_document

                ingest_document(source, source="upload")
                result = asyncio.run(tool_doc_search({"query": "контакты", "top": 3}, ctx))
            finally:
                os.environ.clear()
                os.environ.update(old_env)

        self.assertTrue(result.success)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["tool_name"], "doc_search")
        self.assertEqual(payload["search_substrate"], "parsed_sidecars")
        self.assertIn("common_information_about_company.md", payload["results"][0]["relative_path"])
        self.assertIn("lad@ladled.ru", payload["results"][0]["snippet"])
        artifact = result.metadata.get("bench_artifact")
        self.assertEqual(artifact["tool"], "doc_search")
        self.assertEqual(artifact["kind"], "doc_search")
        self.assertEqual(artifact["payload"]["search_substrate"], "parsed_sidecars")
        self.assertIn("common_information_about_company.md", artifact["payload"]["results"][0]["relative_path"])
        self.assertIn("lad@ladled.ru", artifact["payload"]["results"][0]["preview"])

    def test_canonical_tool_writes_usage_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_root = root / "corp_docs"
            source = root / "faq.md"
            source.write_text("Гарантия на светильник составляет 5 лет.", encoding="utf-8")
            ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")

            old_env = dict(os.environ)
            os.environ.update({"CORP_DOCS_ROOT": str(docs_root)})
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from documents.storage import ingest_document

                ingest_document(source, source="upload")
                result = asyncio.run(tool_doc_search({"query": "гарантия", "top": 3}, ctx))
                usage = load_usage_stats()
            finally:
                os.environ.clear()
                os.environ.update(old_env)

        self.assertTrue(result.success)
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["tool_name"], "doc_search")
        self.assertIsNone(usage[0]["alias_for"])

    def test_tool_passes_preferred_document_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_root = root / "corp_docs"
            first = root / "sports.md"
            second = root / "other.md"
            first.write_text("Нормы освещенности спортивных объектов.", encoding="utf-8")
            second.write_text("Нормы освещенности спортивных объектов.", encoding="utf-8")
            ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")

            old_env = dict(os.environ)
            os.environ.update({"CORP_DOCS_ROOT": str(docs_root)})
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from documents.storage import ingest_document

                manifest = ingest_document(first, source="upload")
                ingest_document(second, source="upload")
                result = asyncio.run(
                    tool_doc_search(
                        {
                            "query": "нормы освещенности спортивных объектов",
                            "top": 3,
                            "preferred_document_ids": [manifest["document_id"]],
                        },
                        ctx,
                    )
                )
            finally:
                os.environ.clear()
                os.environ.update(old_env)

        self.assertTrue(result.success)
        payload = json.loads(result.output)
        self.assertEqual(payload["results"][0]["document_id"], manifest["document_id"])


if __name__ == "__main__":
    unittest.main()
