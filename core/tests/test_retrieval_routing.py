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
        self.assertIn("Используй route cards / route selector как первый выбор retrieval path", prompt)
        self.assertIn("Если выбранный route вернул sufficient evidence", prompt)
        self.assertIn("bounded route-aware fallback", prompt)
        self.assertIn("`corp_db_search` — основной structured source", prompt)
        self.assertIn("портфолио", prompt)
        self.assertIn("`doc_search` - используется для поиска по тематике", prompt)
        self.assertIn("Generic вопросы про сертификаты, декларации, комплектующие или качество", prompt)
        self.assertIn("сервиса, гарантии, контактов, реквизитов, адреса, сайта, соцсетей, года основания", prompt)
        self.assertIn("Не используй generic `doc_search` fallback для company facts", prompt)

    def test_corp_pg_db_skill_documents_second_step_examples(self):
        skill = (_repo_root() / "shared_skills" / "skills" / "corp-pg-db" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Что делать после `empty`", skill)
        self.assertIn("нефтегаз", skill)
        self.assertIn("прожектор 100 ватт ip65", skill)
        self.assertIn("concrete `doc_domain` route", skill)
        self.assertIn("Как извлекать признаки в structured args", skill)
        self.assertIn("weight_kg_min", skill)
        self.assertIn("`kind=portfolio_examples_by_lamp`", skill)
        self.assertIn("`kind=application_recommendation`", skill)
        self.assertIn("Если в вопросе уже есть точное или почти точное имя модели светильника, сначала выбери правильный exact path", skill)
        self.assertIn("Только если `lamp_exact` дал `empty`", skill)
        self.assertIn("company facts: год основания, сайт, адрес, соцсети, контакты", skill)
        self.assertIn("Если вопрос про сайт, адрес, соцсети, контакты, реквизиты", skill)
        self.assertIn("После успешного company-fact `kb_search` не делай `doc-search`, `doc_search`, `run_command`, `list_directory`, `read_file` или `search_text`", skill)
        self.assertIn("Правило для broad-object подбора по сфере применения", skill)
        self.assertIn("Первый ответ по этому payload должен содержать", skill)
        self.assertIn("подбери мощный светильник для карьерна", skill)

    def test_doc_search_skill_is_canonical(self):
        skill = (_repo_root() / "shared_skills" / "skills" / "doc-search" / "SKILL.md").read_text(encoding="utf-8")
        skill_json = (_repo_root() / "shared_skills" / "skills" / "doc-search" / "skill.json").read_text(encoding="utf-8")
        self.assertIn("Canonical tool: `doc_search`", skill)
        self.assertIn("concrete `doc_domain` route cards", skill)
        self.assertIn("run `doc_search` with the route", skill)
        self.assertIn("/data/corp_docs/live/", skill)
        self.assertIn("document-domain", skill_json)
        self.assertNotIn("deprecated", skill_json.lower())


if __name__ == "__main__":
    unittest.main()
