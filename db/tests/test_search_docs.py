import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search_docs import _category_doc, _kb_chunk_doc, _lamp_doc, _portfolio_doc


class SearchDocsTests(unittest.TestCase):
    def test_lamp_doc_includes_related_codes_in_aliases(self):
        lamp = {
            "lamp_id": 1301,
            "name": "LAD LED LINE-OZ-25",
            "power_w": 25,
            "luminous_flux_lm": 3030,
            "color_temperature_k": 5000,
            "ingress_protection": "IP65",
            "mounting_type": "Потолочное",
            "operating_temperature_range_raw": "−65...+50",
            "supply_voltage_raw": "AC230",
            "url": "https://ladzavod.ru/catalog/lad-led-line-oz/lad-led-line-oz-25",
            "category_id": 39,
        }
        skus = [
            {
                "etm_code": "LINE1132",
                "oracl_code": "1669705",
                "short_box_name_wms": "LADLEDL1015B",
                "catalog_1c": "15Лайн-10 черный",
                "box_name": "ДБП-15w IP66 1751Лм 5000К 10° BLACK",
            }
        ]
        doc = _lamp_doc(lamp, "LAD LED LINE-OZ", skus)
        self.assertEqual(doc["entity_type"], "lamp")
        self.assertIn("LINE1132", doc["aliases"])
        self.assertIn("1669705", doc["aliases"])
        self.assertEqual(doc["metadata"]["lamp_id"], 1301)
        self.assertIn("25w", doc["aliases"])
        self.assertEqual(doc["metadata"]["etm_codes"], ["LINE1132"])

    def test_kb_chunk_doc_keeps_document_title_metadata(self):
        chunk = {
            "source_file": "common_information_about_company.md",
            "document_title": "Общая информация о компании ЛАДзавод светотехники",
            "chunk_index": 0,
            "heading": "О компании",
            "content": "Компания разрабатывает и производит светодиодные светильники.",
            "metadata": {"source_file": "common_information_about_company.md"},
        }
        doc = _kb_chunk_doc(chunk)
        self.assertEqual(doc["entity_type"], "kb_chunk")
        self.assertEqual(doc["metadata"]["document_title"], chunk["document_title"])
        self.assertTrue(doc["entity_id"].startswith("common_information_about_company.md:"))

    def test_category_doc_keeps_sphere_names_in_metadata(self):
        doc = _category_doc(
            {"category_id": 164, "name": "АЗС", "url": "https://ladzavod.ru/catalog/azs"},
            ["Нефтегазовый комплекс и взрывозащищенное оборудование"],
        )
        self.assertIn("Нефтегазовый комплекс", doc["aliases"])
        self.assertEqual(doc["metadata"]["sphere_names"][0], "Нефтегазовый комплекс и взрывозащищенное оборудование")

    def test_portfolio_doc_keeps_group_and_sphere_metadata(self):
        doc = _portfolio_doc(
            {
                "portfolio_id": "portfolio:1",
                "name": "Освещение установки комплексной подготовки газа",
                "group_name": "Нефтегазовый комплекс и взрывозащищенное оборудование",
                "url": "https://ladzavod.ru/portfolio/ukpg",
                "sphere_id": 8,
            },
            "Нефтегазовый комплекс и взрывозащищенное оборудование",
        )
        self.assertIn("Нефтегазовый комплекс", doc["aliases"])
        self.assertEqual(doc["metadata"]["sphere_name"], "Нефтегазовый комплекс и взрывозащищенное оборудование")


if __name__ == "__main__":
    unittest.main()
