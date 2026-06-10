import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class DocWorkerFoundationTests(unittest.TestCase):
    def test_compose_declares_doc_worker_operator_service(self):
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("doc-worker:", compose)
        self.assertIn("build: ./doc-worker", compose)
        self.assertIn("profiles:\n      - operator", compose)
        self.assertIn("- .:/repo:ro", compose)
        self.assertIn("- ./workspace/_shared:/data", compose)

    def test_dockerfile_keeps_lit_dependencies_outside_core(self):
        dockerfile = (REPO_ROOT / "doc-worker" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("npm install -g @llamaindex/liteparse", dockerfile)
        self.assertIn("libreoffice", dockerfile)
        self.assertIn("imagemagick", dockerfile)

        core_dockerfile = (REPO_ROOT / "core" / "Dockerfile").read_text(encoding="utf-8").lower()
        self.assertNotIn("liteparse", core_dockerfile)
        self.assertNotIn("libreoffice", core_dockerfile)
        self.assertNotIn("imagemagick", core_dockerfile)

    def test_worker_foundation_commands_are_invokable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            env = {
                "DOC_REPO_ROOT": str(repo_root),
                "CORP_DOCS_ROOT": str(Path(tmpdir) / "data" / "corp_docs"),
            }
            worker = REPO_ROOT / "doc-worker" / "worker.py"
            for args in (
                ("doctor",),
                ("sync-repo",),
                ("rebuild-parsed",),
                ("rebuild-routes",),
            ):
                completed = subprocess.run(
                    [sys.executable, str(worker), *args],
                    cwd=str(REPO_ROOT),
                    env={**os.environ, **env},
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, msg=completed.stderr)
                payload = json.loads(completed.stdout)
                if args[0] == "doctor":
                    self.assertIn("binaries", payload)
                else:
                    self.assertEqual(payload["command"], args[0])

    def test_doctor_reports_parsed_corpus_health(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "CORP_DOCS_ROOT": str(Path(tmpdir) / "corp_docs"),
            }
            import os
            import sys

            sys.path.insert(0, str(REPO_ROOT / "core"))
            from documents.storage import ingest_document

            source = Path(tmpdir) / "manual.md"
            source.write_text("Инструкция LINE", encoding="utf-8")
            old_env = dict(os.environ)
            os.environ.update(env)
            try:
                ingest_document(source, source="upload")
                completed = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "doc-worker" / "worker.py"), "doctor"],
                    cwd=str(REPO_ROOT),
                    env={**os.environ, "DOC_REPO_ROOT": str(Path(tmpdir) / "repo")},
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                os.environ.clear()
                os.environ.update(old_env)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["corpus"]["live_documents"], 1)
            self.assertEqual(payload["corpus"]["parsed_current"], 1)


if __name__ == "__main__":
    unittest.main()
