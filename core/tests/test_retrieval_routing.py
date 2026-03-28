import unittest
from pathlib import Path


class RetrievalRoutingPromptTests(unittest.TestCase):
    def test_system_prompt_documents_retry_policy(self):
        prompt = (Path(__file__).resolve().parents[1] / "src" / "agent" / "system.txt").read_text(encoding="utf-8")
        self.assertIn("ПРАВИЛА RETRY ПОСЛЕ EMPTY РЕЗУЛЬТАТА", prompt)
        self.assertIn("lamp_filters", prompt)
        self.assertIn("corp-wiki-md-search", prompt)

    def test_corp_pg_db_skill_documents_second_step_examples(self):
        skill = (
            Path(__file__).resolve().parents[2]
            / "shared_skills"
            / "skills"
            / "corp-pg-db"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Что делать после `empty`", skill)
        self.assertIn("нефтегаз", skill)
        self.assertIn("прожектор 100 ватт ip65", skill)


if __name__ == "__main__":
    unittest.main()
