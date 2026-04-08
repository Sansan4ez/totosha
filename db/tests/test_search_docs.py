import asyncio
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search_docs import _category_doc, _kb_chunk_doc, _lamp_doc, _portfolio_doc


class SearchDocsTests(unittest.TestCase):
    def test_lamp_doc_includes_related_codes_in_aliases(self):
        lamp = {
            "lamp_id": 1301,
            "name": "LAD LED LINE-OZ-25",
            "category_name": "LAD LED LINE-OZ",
            "power_w": 25,
            "luminous_flux_lm": 3030,
            "beam_pattern": "10°",
            "color_temperature_k": 5000,
            "color_rendering_index_ra": 80,
            "ingress_protection": "IP65",
            "mounting_type": "Потолочное",
            "electrical_protection_class": "I",
            "operating_temperature_range_raw": "−65...+50",
            "supply_voltage_raw": "AC230",
            "url": "https://ladzavod.ru/catalog/lad-led-line-oz/lad-led-line-oz-25",
            "category_id": 39,
            "weight_kg": Decimal("0.87"),
            "dimensions_raw": "200 x 100 x 50",
            "warranty_years": 5,
            "preview": "LAD LED LINE-OZ | 25 Вт | 3030 лм | 10° | IP65 | 0.87 кг",
            "agent_summary": "Светильник LAD LED LINE-OZ-25. Мощность 25 Вт. Вес 0.87 кг.",
            "agent_facts": {
                "power_w": {"label": "Мощность", "text": "25 Вт", "value": 25, "unit": "Вт"},
                "weight_kg": {"label": "Вес", "text": "0.87 кг", "value": 0.87, "unit": "кг"},
            },
            "search_text": "LAD LED LINE-OZ. Светильник LAD LED LINE-OZ-25. Мощность 25 Вт. Вес 0.87 кг.",
            "search_aliases": "lad led line oz 25 25w 25 вт 0.87kg 0.87 кг вес cri ra 80 ip65",
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
        doc = _lamp_doc(lamp, skus)
        self.assertEqual(doc["entity_type"], "lamp")
        self.assertIn("LINE1132", doc["aliases"])
        self.assertIn("1669705", doc["aliases"])
        self.assertEqual(doc["metadata"]["lamp_id"], 1301)
        self.assertIn("25w", doc["aliases"])
        self.assertEqual(doc["content"], lamp["search_text"])
        self.assertIn("0.87kg", doc["aliases"])
        self.assertEqual(doc["metadata"]["etm_codes"], ["LINE1132"])
        self.assertEqual(doc["metadata"]["weight_kg"], 0.87)
        self.assertEqual(doc["metadata"]["agent_summary"], lamp["agent_summary"])
        self.assertEqual(doc["metadata"]["facts"]["weight_kg"]["text"], "0.87 кг")
        self.assertEqual(doc["metadata"]["beam_pattern"], "10°")

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

    def test_kb_chunk_doc_adds_targeted_company_aliases(self):
        chunk = {
            "source_file": "common_information_about_company.md",
            "document_title": "Общая информация о компании ЛАДзавод светотехники",
            "chunk_index": 1,
            "heading": "Контактная информация",
            "content": "Телефон +7 (351) 239-18-11, email lad@ladled.ru.",
            "metadata": {"source_file": "common_information_about_company.md"},
        }
        doc = _kb_chunk_doc(chunk)
        self.assertIn("контакты компании", doc["aliases"].lower())
        self.assertIn("телефон", doc["aliases"].lower())
        self.assertIn("ladzavod", doc["aliases"].lower())

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

    def test_build_search_docs_uses_stage_swap_instead_of_truncate(self):
        from search_docs import build_search_docs

        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeConn:
            def __init__(self):
                self.executed = []

            async def fetch(self, query):
                sql = str(query)
                if "FROM corp.categories" in sql:
                    return [{"category_id": 1, "name": "Series"}]
                return []

            async def execute(self, query):
                self.executed.append(str(query))
                return "OK"

            async def executemany(self, query, args):
                self.executed.append(str(query))
                return None

            def transaction(self):
                return _Tx()

        conn = FakeConn()
        asyncio.run(build_search_docs(conn, embeddings_enabled=False))

        joined_sql = "\n".join(conn.executed)
        self.assertIn("CREATE TABLE corp.corp_search_docs_stage", joined_sql)
        self.assertIn("GRANT SELECT ON TABLE corp.corp_search_docs_stage TO corp_ro", joined_sql)
        self.assertIn("ALTER TABLE corp.corp_search_docs RENAME TO corp_search_docs_old", joined_sql)
        self.assertIn("ALTER TABLE corp.corp_search_docs_stage RENAME TO corp_search_docs", joined_sql)
        self.assertNotIn("TRUNCATE TABLE corp.corp_search_docs", joined_sql)


if __name__ == "__main__":
    unittest.main()
