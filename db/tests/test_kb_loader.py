import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kb_loader import ManifestValidationError, load_manifest, parse_markdown_document


class KnowledgeBaseLoaderTests(unittest.TestCase):
    def test_load_manifest_from_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "knowledge_base_manifest.yaml"
            manifest_path.write_text(
                "version: 1\nfiles:\n  - about_Luxnet.md\n  - common_information_about_company.md\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_manifest(manifest_path),
                ["about_Luxnet.md", "common_information_about_company.md"],
            )

    def test_parse_markdown_document_requires_single_h1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "broken.md"
            source_path.write_text(
                "## Нет H1\n\n### Раздел\nТекст",
                encoding="utf-8",
            )
            with self.assertRaises(ManifestValidationError):
                parse_markdown_document(source_path, "broken.md")

    def test_parse_markdown_document_chunks_by_h3(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "ok.md"
            source_path.write_text(
                "# Документ\n\nВступление\n\n### Раздел 1\nПервый абзац.\n\n### Раздел 2\nВторой абзац.\n",
                encoding="utf-8",
            )
            document_title, chunks = parse_markdown_document(source_path, "ok.md")
            self.assertEqual(document_title, "Документ")
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0]["heading"], "Раздел 1")
            self.assertEqual(chunks[1]["heading"], "Раздел 2")


if __name__ == "__main__":
    unittest.main()
