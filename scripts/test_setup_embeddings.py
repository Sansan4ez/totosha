"""Regression checks for required Compose embeddings secret placeholders."""
import pathlib
import subprocess
import tempfile
import unittest


SETUP = pathlib.Path(__file__).resolve().parents[1] / "setup.sh"


class SetupEmbeddingsTests(unittest.TestCase):
    def run_setup(self, root):
        subprocess.run(["bash", str(SETUP)], cwd=root, check=True, capture_output=True)

    def test_fresh_setup_and_rerun_preserve_embeddings_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.run_setup(root)
            values = {
                "embeddings_base_url.txt": "local\n",
                "embeddings_api_key.txt": "test-embedding-key\n",
            }
            for name, value in values.items():
                path = root / "secrets" / name
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_bytes(), b"")
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)
                path.write_text(value)
            self.run_setup(root)
            for name, value in values.items():
                self.assertEqual((root / "secrets" / name).read_text(), value)

    def test_existing_install_gets_missing_embeddings_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.run_setup(root)
            for name in ("embeddings_base_url.txt", "embeddings_api_key.txt"):
                (root / "secrets" / name).unlink()
            self.run_setup(root)
            for name in ("embeddings_base_url.txt", "embeddings_api_key.txt"):
                self.assertEqual((root / "secrets" / name).read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
