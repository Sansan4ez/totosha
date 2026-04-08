import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from documents.cache import cache_version_key, current_sidecar_dir, load_parse_cache, write_parse_cache
from documents.normalize import rebuild_parsed_sidecars
from documents.promotion import export_document_for_corp_db
from documents.search import search_documents
from documents.storage import (
    ensure_document_layout,
    find_document_by_sha256,
    get_document_paths,
    get_repo_paths,
    ingest_document,
    sync_repo_inbox,
)
from documents.usage import append_usage_stat, write_promotion_candidates_report


def _write_zip_xml(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def _env(tmpdir: str) -> dict[str, str]:
    return {"CORP_DOCS_ROOT": str(Path(tmpdir) / "corp_docs")}


class DocSearchStackTests(unittest.TestCase):
    def test_ingest_uses_cas_and_deduplicates_identical_uploads(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            source_a = Path(tmpdir) / "a.md"
            source_b = Path(tmpdir) / "b.md"
            source_a.write_text("одинаковый документ", encoding="utf-8")
            source_b.write_text("одинаковый документ", encoding="utf-8")

            first = ingest_document(source_a, source="upload_a")
            second = ingest_document(source_b, source="upload_b")
            paths = ensure_document_layout(get_document_paths())
            blobs = [path for path in (paths.cas / "sha256").rglob("*") if path.is_file()]

            self.assertEqual(first["document_id"], second["document_id"])
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(len(blobs), 1)
            manifest = find_document_by_sha256(first["sha256"])
            self.assertEqual(len(manifest["aliases"]), 2)

    def test_parse_cache_reuses_same_sha(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            source = Path(tmpdir) / "one.md"
            source.write_text("сертификат CE на серию R500", encoding="utf-8")
            manifest = ingest_document(source, source="upload")
            write_parse_cache(
                manifest["sha256"],
                text="cached text",
                structured={"pages": [{"page": 1, "text": "cached text"}]},
                meta={"backend": "test"},
            )
            cached = load_parse_cache(manifest["sha256"])

            self.assertIsNotNone(cached)
            self.assertEqual(cached["text"], "cached text")
            self.assertEqual(cached["meta"]["backend"], "test")

    def test_ingest_creates_normalized_sidecars_under_parsed_sha_version_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            source = Path(tmpdir) / "policy.md"
            source.write_text("Политика обработки данных вступает в силу немедленно.", encoding="utf-8")

            manifest = ingest_document(source, source="upload")
            sidecar_dir = current_sidecar_dir(manifest["sha256"])
            cached = load_parse_cache(manifest["sha256"])

            self.assertIsNotNone(sidecar_dir)
            self.assertTrue((sidecar_dir / "text.txt").exists())
            self.assertTrue((sidecar_dir / "pages.jsonl").exists())
            self.assertTrue((sidecar_dir / "meta.json").exists())
            self.assertIn(cache_version_key(), str(sidecar_dir))
            self.assertEqual(cached["meta"]["status"], "success")
            self.assertEqual(manifest["normalization"]["status"], "success")

    def test_search_discovers_live_documents(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            company_source = Path(tmpdir) / "company.md"
            cert_source = Path(tmpdir) / "cert.md"
            company_source.write_text("Компания основана в 2006 году", encoding="utf-8")
            cert_source.write_text("Сертификат CE для LAD LED R500", encoding="utf-8")
            ingest_document(company_source, source="upload")
            ingest_document(cert_source, source="upload")

            company_hits = search_documents(query="2006", top=3)
            cert_hits = search_documents(query="сертификат CE R500", top=3)

            self.assertEqual(company_hits["status"], "success")
            self.assertEqual(company_hits["results"][0]["source"], "corp_docs_live")
            self.assertEqual(cert_hits["status"], "success")
            self.assertEqual(cert_hits["results"][0]["source"], "corp_docs_live")

    def test_office_xml_formats_are_searchable(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            docx = Path(tmpdir) / "sheet.docx"
            pptx = Path(tmpdir) / "slides.pptx"
            xlsx = Path(tmpdir) / "table.xlsx"
            _write_zip_xml(
                docx,
                {
                    "[Content_Types].xml": "<Types/>",
                    "word/document.xml": '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>гарантия 5 лет</w:t></w:r></w:p></w:body></w:document>',
                },
            )
            _write_zip_xml(
                pptx,
                {
                    "[Content_Types].xml": "<Types/>",
                    "ppt/slides/slide1.xml": '<p:sld xmlns:p="p" xmlns:a="a"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>серия R700</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>',
                },
            )
            _write_zip_xml(
                xlsx,
                {
                    "[Content_Types].xml": "<Types/>",
                    "xl/sharedStrings.xml": '<sst xmlns="x"><si><t>телефон 239-18-11</t></si></sst>',
                    "xl/worksheets/sheet1.xml": '<worksheet xmlns="x"><sheetData><row><c t="s"><v>0</v></c></row></sheetData></worksheet>',
                },
            )
            ingest_document(docx, source="upload")
            ingest_document(pptx, source="upload")
            ingest_document(xlsx, source="upload")

            self.assertEqual(search_documents(query="гарантия 5 лет", top=2)["status"], "success")
            self.assertEqual(search_documents(query="серия R700", top=2)["status"], "success")
            self.assertEqual(search_documents(query="239-18-11", top=2)["status"], "success")

    def test_pdf_heuristic_and_cached_image_search(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            pdf = Path(tmpdir) / "fire.pdf"
            pdf.write_bytes(b"%PDF-1.4\nBT (fire certificate R700) Tj ET\n")
            ingest_document(pdf, source="upload")

            image = Path(tmpdir) / "diagram.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            image_manifest = ingest_document(image, source="upload")
            write_parse_cache(image_manifest["sha256"], text="схема подключения линии", meta={"backend": "cache_test"})

            pdf_hits = search_documents(query="certificate R700", top=2)
            image_hits = search_documents(query="схема подключения", top=2)

            self.assertEqual(pdf_hits["results"][0]["file_type"], "pdf")
            self.assertEqual(pdf_hits["results"][0]["match_mode"], "pdf_heuristic")
            self.assertEqual(image_hits["results"][0]["document_id"], image_manifest["document_id"])
            self.assertTrue(image_hits["results"][0]["cache_hit"])

    def test_search_read_path_does_not_require_layout_initialization(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(tmpdir) / "root_is_file")},
            clear=False,
        ):
            (Path(tmpdir) / "root_is_file").write_text("not a directory", encoding="utf-8")

            payload = search_documents(query="2006", top=2)

            self.assertEqual(payload["status"], "empty")
            self.assertEqual(payload["scanned_documents"], 0)

    def test_missing_sidecar_does_not_break_other_results(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            broken_source = Path(tmpdir) / "broken.md"
            healthy_source = Path(tmpdir) / "healthy.md"
            broken_source.write_text("Компания основана в 2006 году", encoding="utf-8")
            healthy_source.write_text("Пожарный сертификат LINE действует до 2026 года", encoding="utf-8")
            broken_manifest = ingest_document(broken_source, source="upload")
            ingest_document(healthy_source, source="upload")

            sidecar_dir = current_sidecar_dir(broken_manifest["sha256"])
            assert sidecar_dir is not None
            for path in sidecar_dir.iterdir():
                path.unlink()
            sidecar_dir.rmdir()

            payload = search_documents(query="сертификат line", top=3)

            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["results"][0]["source"], "corp_docs_live")
            self.assertEqual(payload["normalization_missing_count"], 1)
            self.assertEqual(payload["backend_counts"]["normalization_missing"], 1)

    def test_live_markdown_prefers_matching_lines_and_snippets(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            company = Path(tmpdir) / "common_information_about_company.md"
            norms = Path(tmpdir) / "normy_osveschennosty.md"
            company.write_text(
                "# О компании\n"
                "ЛАДзавод светотехники основан в 2006 году.\n"
                "Серия LAD LED R500 - эффективный светодиодный светильник.\n"
                "Серия LAD LED R700 - используется закаленное стекло.\n"
                "Серия LAD LED LINE - используется закаленное стекло, кроме OZ.\n"
                "Сертификат CE LAD LED R500: https://example.test/sertif-CE-LAD-LED-R500-2027.pdf\n"
                "Сертификат РОСС LAD LED LINE пожарный: https://example.test/sertif-ROSS-LAD-LED-LINE-fire-2026.pdf\n"
                "Сертификат РОСС LAD LED R700 пожарный: https://example.test/sertif-ROSS-LAD-LED-R700-fire-2026.pdf\n",
                encoding="utf-8",
            )
            norms.write_text(("LED освещение для дорог и тоннелей. " * 60), encoding="utf-8")
            ingest_document(company, source="upload")
            ingest_document(norms, source="upload")

            certs = search_documents(query="сертификат CE LAD LED R500 пожарный сертификат LAD LED LINE LAD LED R700", top=3)
            compare = search_documents(query="чем отличается серия LAD LED R500 от LAD LED R700", top=3)

            self.assertEqual(certs["status"], "success")
            self.assertEqual(certs["results"][0]["relative_path"], "common_information_about_company.md")
            self.assertIn("sertif-CE-LAD-LED-R500-2027.pdf", certs["results"][0]["snippet"])
            self.assertIn("sertif-ROSS-LAD-LED-LINE-fire-2026.pdf", certs["results"][0]["snippet"])
            self.assertIn("sertif-ROSS-LAD-LED-R700-fire-2026.pdf", certs["results"][0]["snippet"])

            self.assertEqual(compare["status"], "success")
            self.assertEqual(compare["results"][0]["relative_path"], "common_information_about_company.md")
            self.assertIn("LAD LED R500", compare["results"][0]["snippet"])
            self.assertIn("LAD LED R700", compare["results"][0]["snippet"])
            self.assertIn("закал", compare["results"][0]["snippet"].lower())

    def test_binary_office_formats_are_rejected_on_ingest(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            for suffix in (".doc", ".xls", ".ppt"):
                source = Path(tmpdir) / f"legacy{suffix}"
                source.write_bytes(b"legacy office binary")
                with self.assertRaisesRegex(ValueError, "legacy_office_binary_requires_doc_worker_runtime"):
                    ingest_document(source, source="upload")

    def test_usage_stats_drive_promotion_report_and_export(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            source = Path(tmpdir) / "promo.md"
            source.write_text("Пожарный сертификат LAD LED LINE действует до 2026 года.", encoding="utf-8")
            manifest = ingest_document(source, source="upload")
            payload = search_documents(query="пожарный сертификат line", top=3)
            append_usage_stat(
                query="пожарный сертификат line",
                payload=payload,
                intent_class="document_lookup",
                answer_success=True,
                selected_result_rank=1,
            )
            report = write_promotion_candidates_report(min_hits=1)
            exported = export_document_for_corp_db(manifest["document_id"])

            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["candidates"][0]["document_id"], manifest["document_id"])
            self.assertEqual(exported["status"], "success")
            self.assertEqual(exported["document_id"], manifest["document_id"])
            self.assertGreater(exported["chunk_count"], 0)
            self.assertTrue(Path(exported["jsonl_path"]).exists())
            self.assertEqual(exported["chunk_source"], "normalized_sidecar")

    def test_promotion_export_requires_normalized_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            source = Path(tmpdir) / "manual.md"
            source.write_text("Инструкция по монтажу LINE.", encoding="utf-8")
            manifest = ingest_document(source, source="upload")
            sidecar_dir = current_sidecar_dir(manifest["sha256"])
            assert sidecar_dir is not None
            for path in sidecar_dir.iterdir():
                path.unlink()
            sidecar_dir.rmdir()

            exported = export_document_for_corp_db(manifest["document_id"])

            self.assertEqual(exported["status"], "normalization_missing")
            self.assertEqual(exported["error"], "normalized_sidecar_required")

    def test_binary_office_is_allowed_only_with_doc_worker_runtime_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {**_env(tmpdir), "DOC_SEARCH_ENABLE_LEGACY_OFFICE": "1"},
            clear=False,
        ):
            source = Path(tmpdir) / "legacy.doc"
            source.write_bytes(b"legacy office binary")

            from documents import normalize as normalize_module
            from documents import storage as storage_module

            with patch.object(storage_module.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"), patch.object(
                normalize_module, "_liteparse_available", return_value=True
            ), patch.object(
                normalize_module,
                "_parse_with_liteparse",
                return_value=("Legacy office contract", {"pages": [{"page": 1, "text": "Legacy office contract"}]}),
            ):
                manifest = ingest_document(source, source="upload")
                cached = load_parse_cache(manifest["sha256"])

            self.assertEqual(manifest["file_type"], "doc")
            self.assertEqual(manifest["normalization"]["backend"], "liteparse")
            self.assertIsNotNone(cached)
            self.assertIn("Legacy office contract", cached["text"])

    def test_usage_stats_persistence_is_best_effort(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(tmpdir) / "root_is_file")},
            clear=False,
        ):
            (Path(tmpdir) / "root_is_file").write_text("not a directory", encoding="utf-8")
            record = append_usage_stat(
                query="контакты",
                payload={"status": "success", "result_count": 0, "results": [], "tool_name": "doc_search"},
            )

            self.assertFalse(record["persisted"])
            self.assertEqual(record["persist_error"], "NotADirectoryError")

    def test_sync_repo_ingests_inbox_and_reports_duplicates_and_rejections(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"DOC_REPO_ROOT": str(Path(tmpdir) / "repo"), **_env(tmpdir)},
            clear=False,
        ):
            repo_paths = get_repo_paths()
            repo_paths.inbox.mkdir(parents=True, exist_ok=True)
            first = repo_paths.inbox / "certs" / "fire.md"
            duplicate = repo_paths.inbox / "duplicates" / "fire-copy.md"
            invalid = repo_paths.inbox / "bad.exe"
            first.parent.mkdir(parents=True, exist_ok=True)
            duplicate.parent.mkdir(parents=True, exist_ok=True)
            first.write_text("Пожарный сертификат LINE действует до 2027 года.", encoding="utf-8")
            duplicate.write_text("Пожарный сертификат LINE действует до 2027 года.", encoding="utf-8")
            invalid.write_text("bad", encoding="utf-8")
            Path(f"{first}.meta.json").write_text(
                json.dumps({"tags": ["certificate"], "title": "Fire cert"}, ensure_ascii=False),
                encoding="utf-8",
            )

            report = sync_repo_inbox()
            ingested = next(item for item in report["results"] if item["status"] == "ingested")
            manifest = find_document_by_sha256(ingested["sha256"])

            self.assertEqual(report["counts"]["ingested"], 1)
            self.assertEqual(report["counts"]["duplicate"], 1)
            self.assertEqual(report["counts"]["rejected"], 1)
            self.assertTrue(Path(report["report_path"]).exists())
            self.assertEqual(manifest["aliases"][0]["relative_path"], "certs/fire.md")
            self.assertEqual(manifest["aliases"][0]["metadata"]["tags"], ["certificate"])

    def test_sync_repo_rejects_invalid_metadata_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"DOC_REPO_ROOT": str(Path(tmpdir) / "repo"), **_env(tmpdir)},
            clear=False,
        ):
            repo_paths = get_repo_paths()
            repo_paths.inbox.mkdir(parents=True, exist_ok=True)
            path = repo_paths.inbox / "policy.md"
            path.write_text("Политика обработки данных", encoding="utf-8")
            Path(f"{path}.meta.json").write_text('["wrong"]', encoding="utf-8")

            report = sync_repo_inbox()

            self.assertEqual(report["counts"]["rejected"], 1)
            self.assertEqual(report["results"][0]["reason"], "invalid_metadata_type")

    def test_rebuild_parsed_recreates_missing_current_version_sidecars(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            source = Path(tmpdir) / "manual.md"
            source.write_text("Руководство по эксплуатации светильника R700.", encoding="utf-8")
            manifest = ingest_document(source, source="upload")
            sidecar_dir = current_sidecar_dir(manifest["sha256"])
            assert sidecar_dir is not None
            for path in sidecar_dir.iterdir():
                path.unlink()
            sidecar_dir.rmdir()

            report = rebuild_parsed_sidecars(force=False)
            cached = load_parse_cache(manifest["sha256"])

            self.assertEqual(report["counts"]["success"], 1)
            self.assertIsNotNone(cached)
            self.assertIn("R700", cached["text"])

    def test_sidecar_version_key_invalidates_on_ocr_config_change(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            source = Path(tmpdir) / "passport.md"
            source.write_text("Паспорт изделия LAD LINE.", encoding="utf-8")
            manifest = ingest_document(source, source="upload")
            original_dir = current_sidecar_dir(manifest["sha256"])
            self.assertIsNotNone(load_parse_cache(manifest["sha256"]))

            with patch.dict(os.environ, {"DOC_SEARCH_OCR_LANGUAGE": "rus"}, clear=False):
                rotated_dir = current_sidecar_dir(manifest["sha256"])
                self.assertNotEqual(str(original_dir), str(rotated_dir))
                self.assertIsNone(load_parse_cache(manifest["sha256"]))
                rebuild_parsed_sidecars(force=False)
                self.assertIsNotNone(load_parse_cache(manifest["sha256"]))

    def test_live_doc_search_degrades_when_current_sidecar_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, _env(tmpdir), clear=False):
            source = Path(tmpdir) / "guide.md"
            source.write_text("Руководство по монтажу серии LINE.", encoding="utf-8")
            manifest = ingest_document(source, source="upload")
            sidecar_dir = current_sidecar_dir(manifest["sha256"])
            assert sidecar_dir is not None
            for path in sidecar_dir.iterdir():
                path.unlink()
            sidecar_dir.rmdir()

            payload = search_documents(query="монтаж line", top=3)

            self.assertEqual(payload["status"], "normalization_missing")
            self.assertEqual(payload["result_count"], 0)
            self.assertEqual(payload["backend_counts"]["normalization_missing"], 1)


if __name__ == "__main__":
    unittest.main()
