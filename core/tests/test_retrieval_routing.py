import unittest
from pathlib import Path


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "shared_skills").exists():
            return parent
    raise AssertionError("repo root with shared_skills not found")


class RetrievalRoutingPromptTests(unittest.TestCase):
    def test_system_prompt_documents_retry_policy(self):
        prompt = (_repo_root() / "core" / "src" / "agent" / "system.txt").read_text(encoding="utf-8")
        self.assertIn("ПРАВИЛА RETRY ПОСЛЕ EMPTY РЕЗУЛЬТАТА", prompt)
        self.assertIn("lamp_filters", prompt)
        self.assertIn("corp-wiki-md-search", prompt)
        self.assertIn("weight_kg_min/max", prompt)
        self.assertIn("voltage_nominal_v_*", prompt)
        self.assertIn("`kind=portfolio_examples_by_lamp`", prompt)
        self.assertIn("сначала ОБЯЗАТЕЛЬНО вызови `corp_db_search` с `kind=lamp_exact`", prompt)
        self.assertIn("Не делай после этого `hybrid_search`, `sphere_categories`, `portfolio_by_sphere`", prompt)
        self.assertIn("Не делай после этого `hybrid_search`, `lamp_suggest`", prompt)
        self.assertIn("ПРИНЦИП PROGRESSIVE DISCLOSURE", prompt)
        self.assertIn("Скорость ответа важнее максимальной полноты с первого сообщения", prompt)
        self.assertIn("Для вопросов вида «какой вес», «есть ли такая модель», «какая мощность»", prompt)

    def test_corp_pg_db_skill_documents_second_step_examples(self):
        skill = (_repo_root() / "shared_skills" / "skills" / "corp-pg-db" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Что делать после `empty`", skill)
        self.assertIn("нефтегаз", skill)
        self.assertIn("прожектор 100 ватт ip65", skill)
        self.assertIn("Как извлекать признаки в structured args", skill)
        self.assertIn("weight_kg_min", skill)
        self.assertIn("`kind=portfolio_examples_by_lamp`", skill)
        self.assertIn("Если в вопросе уже есть точное или почти точное имя модели светильника, сначала выбери правильный exact path", skill)
        self.assertIn("Только если `lamp_exact` дал `empty`", skill)


if __name__ == "__main__":
    unittest.main()
