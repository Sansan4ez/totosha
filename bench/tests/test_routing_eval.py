import unittest

from bench.bench_lib import eval_routing


class BenchRoutingEvalTests(unittest.TestCase):
    def test_eval_routing_passes_for_expected_corp_db_path(self):
        meta = {
            "retrieval_intent": "company_fact",
            "retrieval_selected_source": "corp_db",
            "retrieval_wiki_after_corp_db_success": False,
            "routing_guardrail_hits": 0,
            "tools_used": ["corp_db_search"],
        }
        routing = {
            "intent": "company_fact",
            "selected_source": "corp_db",
            "wiki_after_corp_db_success": False,
            "guardrail_hits_max": 0,
            "forbid_tools": ["run_command", "list_directory", "read_file"],
        }

        ok, errors = eval_routing(meta, routing)

        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_eval_routing_treats_wiki_and_doc_search_as_same_document_source(self):
        meta = {
            "retrieval_intent": "document_lookup",
            "retrieval_selected_source": "wiki",
            "retrieval_wiki_after_corp_db_success": False,
            "routing_guardrail_hits": 0,
            "tools_used": ["corp_wiki_search"],
        }
        routing = {
            "intent": "document_lookup",
            "selected_source": "doc_search",
            "wiki_after_corp_db_success": False,
            "guardrail_hits_max": 0,
            "forbid_tools": ["run_command"],
        }

        ok, errors = eval_routing(meta, routing)

        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_eval_routing_fails_for_wiki_regression(self):
        meta = {
            "retrieval_intent": "company_fact",
            "retrieval_selected_source": "corp_db",
            "retrieval_wiki_after_corp_db_success": True,
            "routing_guardrail_hits": 1,
            "tools_used": ["corp_db_search", "run_command"],
        }
        routing = {
            "intent": "company_fact",
            "selected_source": "corp_db",
            "wiki_after_corp_db_success": False,
            "guardrail_hits_max": 0,
            "forbid_tools": ["run_command"],
        }

        ok, errors = eval_routing(meta, routing)

        self.assertFalse(ok)
        self.assertTrue(any("wiki_after_corp_db_success" in error for error in errors))
        self.assertTrue(any("guardrail_hits" in error for error in errors))
        self.assertTrue(any("forbid_tools_used" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
