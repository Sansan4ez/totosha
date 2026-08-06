import re
import unittest
from pathlib import Path


class EmbeddingConfigTests(unittest.TestCase):
    def test_embedding_model_has_single_source(self):
        db_dir = Path(__file__).resolve().parents[1]
        hits = [
            path.relative_to(db_dir.parent)
            for path in db_dir.glob("*.py")
            if re.search(r"^EMBEDDING_MODEL\s*=", path.read_text(encoding="utf-8"), re.MULTILINE)
        ]

        self.assertEqual(hits, [Path("db/common.py")])


if __name__ == "__main__":
    unittest.main()
