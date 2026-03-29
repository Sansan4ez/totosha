import unittest
from pathlib import Path


class RetrievalRoutingPromptTests(unittest.TestCase):
    def test_system_prompt_documents_retry_policy(self):
        prompt = (Path(__file__).resolve().parents[1] / "src" / "agent" / "system.txt").read_text(encoding="utf-8")
        self.assertIn("ПРАВИЛА RETRY ПОСЛЕ EMPTY РЕЗУЛЬТАТА", prompt)
        self.assertIn("lamp_filters", prompt)
        self.assertIn("corp-wiki-md-search", prompt)
        self.assertIn("weight_kg_min/max", prompt)
        self.assertIn("voltage_nominal_v_*", prompt)
        self.assertIn("сначала ОБЯЗАТЕЛЬНО вызови `corp_db_search` с `kind=lamp_exact`", prompt)
        self.assertIn("Не делай после этого `hybrid_search`, `lamp_suggest`", prompt)
        self.assertIn("ПРИНЦИП PROGRESSIVE DISCLOSURE", prompt)
        self.assertIn("Скорость ответа важнее максимальной полноты с первого сообщения", prompt)
        self.assertIn("Для вопросов вида «какой вес», «есть ли такая модель», «какая мощность»", prompt)

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
        self.assertIn("Как извлекать признаки в structured args", skill)
        self.assertIn("weight_kg_min", skill)
        self.assertIn("Если в вопросе уже есть точное или почти точное имя модели светильника, сначала используй `kind=lamp_exact`", skill)
        self.assertIn("Только если `lamp_exact` дал `empty`", skill)


if __name__ == "__main__":
    unittest.main()
