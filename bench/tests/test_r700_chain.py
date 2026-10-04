import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "bench/golden/r700-chain-regression.jsonl"
CHAIN_IDS = [
    "r700-list-five-models-typo",
    "r700-series-description",
    "r700-prom-models",
    "r700-prom-portfolio",
    "r700-contextual-portfolio-followup",
]


class R700ChainContractTests(unittest.TestCase):
    def test_golden_has_sequential_five_turn_context_chain_and_negative_controls(self):
        cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
        by_id = {case["id"]: case for case in cases}
        self.assertEqual(len(by_id), len(cases), "case IDs must be unique")
        self.assertEqual([case["id"] for case in cases[:5]], CHAIN_IDS)
        self.assertTrue({"r7000-must-not-prefix-match-r700", "exact-r700-sku", "r700-code-lookup", "unknown-series-lookup"}.issubset(by_id))
        self.assertTrue(all(case.get("execution", {}).get("mode", "agent_chat") == "agent_chat" for case in cases))
        self.assertIn("тогда", by_id[CHAIN_IDS[-1]]["question"].lower())
        self.assertEqual(by_id[CHAIN_IDS[0]]["routing"]["route_id"], "series_models")
        self.assertEqual(by_id[CHAIN_IDS[2]]["routing"]["route_id"], "series_models")
        self.assertEqual(by_id[CHAIN_IDS[3]]["routing"]["route_id"], "portfolio_examples_by_lamp")
        self.assertEqual(by_id["exact-r700-sku"]["routing"]["route_id"], "catalog_entity_lookup")
        self.assertEqual(by_id["r700-code-lookup"]["routing"]["route_id"], "lamp_code_lookup")
        self.assertEqual(by_id["r7000-must-not-prefix-match-r700"]["routing"]["route_id"], "series_models")
        self.assertEqual(by_id["unknown-series-lookup"]["routing"]["route_id"], "series_models")
        self.assertIn("PROM", by_id[CHAIN_IDS[2]]["question"])
        self.assertIn("R7000", by_id["r7000-must-not-prefix-match-r700"]["question"])
        self.assertIn("UNKNOWN-SERIES-XYZ", by_id["unknown-series-lookup"]["question"])


if __name__ == "__main__":
    unittest.main()
