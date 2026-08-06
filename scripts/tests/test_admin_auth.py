import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from admin_auth import AdminTokenNotFound, admin_headers, load_admin_token


class AdminAuthTests(unittest.TestCase):
    def test_prefers_admin_token_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            token_path = root / "operator-token"
            password_path = root / "legacy-token"
            token_path.write_text("current-token\n", encoding="utf-8")
            password_path.write_text("legacy-token\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ADMIN_TOKEN_FILE": str(token_path),
                    "ADMIN_PASSWORD_FILE": str(password_path),
                },
                clear=False,
            ):
                self.assertEqual(load_admin_token(repo_root=root), "current-token")
                self.assertEqual(admin_headers(repo_root=root), {"X-Admin-Token": "current-token"})

    def test_falls_back_to_repo_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            secret_path = root / "secrets" / "admin_password.txt"
            secret_path.parent.mkdir()
            secret_path.write_text("repo-token\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(load_admin_token(repo_root=root), "repo-token")

    def test_missing_token_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {}, clear=True), patch(
            "admin_auth.Path.read_text", side_effect=FileNotFoundError
        ):
            with self.assertRaisesRegex(AdminTokenNotFound, "admin token not found"):
                load_admin_token(repo_root=Path(tmpdir))


if __name__ == "__main__":
    unittest.main()
