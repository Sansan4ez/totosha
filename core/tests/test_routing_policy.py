import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from documents.routing_policy import (  # noqa: E402
    company_common_topic_facets,
    company_fact_intent_type,
    is_document_lookup_intent,
    is_portfolio_lookup_intent,
    rewrite_company_fact_search_args,
    routing_query_text,
)


class RoutingPolicyTests(unittest.TestCase):
    def test_company_common_facets_classify_certification_and_quality(self):
        self.assertFalse(is_document_lookup_intent("какие есть сертификаты?"))
        self.assertEqual(company_fact_intent_type("какие есть сертификаты?"), "certification")
        self.assertEqual(company_common_topic_facets("какие есть сертификаты?"), ["certification"])

        self.assertEqual(company_fact_intent_type("Какие используются комплектующие?"), "quality")
        self.assertEqual(company_common_topic_facets("Какие используются комплектующие?"), ["quality"])

    def test_rewrite_company_fact_search_args_keeps_existing_contract(self):
        rewritten = rewrite_company_fact_search_args(
            {"power_w_min": 0, "voltage_kind": "AC", "explosion_protected": False, "limit": 5},
            "Подскажи контакты компании.",
        )

        self.assertEqual(rewritten["kind"], "hybrid_search")
        self.assertEqual(rewritten["profile"], "kb_route_lookup")
        self.assertEqual(rewritten["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(rewritten["source_files"], ["common_information_about_company.md"])
        self.assertEqual(rewritten["topic_facets"], ["contacts"])
        self.assertEqual(rewritten["limit"], 5)
        self.assertNotIn("power_w_min", rewritten)
        self.assertNotIn("voltage_kind", rewritten)
        self.assertNotIn("explosion_protected", rewritten)

    def test_transport_wrappers_are_ignored_for_policy_intents(self):
        message = "[От: @bench (42)]\n[Голосовое сообщение, распознанный текст:]\nРасскажи про Белый Раст"

        self.assertEqual(routing_query_text(message), "Расскажи про Белый Раст")
        self.assertTrue(is_portfolio_lookup_intent(message))


if __name__ == "__main__":
    unittest.main()
