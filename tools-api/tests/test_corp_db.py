"""corp_db_search route tests."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class DummyAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyPool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return DummyAcquire(self.conn)


class DummyConn:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, query, *args):
        return self.rows


class RoutingConn:
    async def fetch(self, query, *args):
        sql = str(query)
        if "corp.corp_hybrid_search" in sql:
            search_query = args[0]
            if search_query == "нефтегаз проекты портфолио":
                return []
            if search_query == "нефтегаз":
                return [
                    {
                        "doc_id": 7,
                        "entity_type": "portfolio",
                        "entity_id": "portfolio:1",
                        "title": "Освещение установки комплексной подготовки газа",
                        "content": "Нефтегазовый комплекс и взрывозащищенное оборудование",
                        "metadata": {"portfolio_id": "portfolio:1", "sphere_name": "Нефтегазовый комплекс"},
                        "score": 0.81,
                        "debug_info": None,
                    }
                ]
            return []
        if "FROM corp.catalog_lamps l" in sql:
            return [
                {
                    "lamp_id": 1998,
                    "name": "LAD LED R700-1 ST",
                    "category_id": 87,
                    "category_name": "LAD LED R700-1 ST",
                    "power_w": 100,
                    "luminous_flux_lm": 14579,
                    "color_temperature_k": 5000,
                    "ingress_protection": "IP67",
                    "mounting_type": "лира",
                    "supply_voltage_kind": "AC",
                    "operating_temperature_range_raw": "-60...+50",
                    "url": "https://ladzavod.ru/catalog/r700-1-st",
                }
            ]
        return []


class CorpDbRouteTests(unittest.TestCase):
    def test_hybrid_search_route_returns_allowlisted_result(self):
        rows = [
            {
                "doc_id": 1,
                "entity_type": "lamp",
                "entity_id": "1301",
                "title": "LAD LED LINE-OZ-25",
                "content": "LAD LED LINE-OZ | 25 Вт | 3030 лм | 5000 K | IP65",
                "metadata": {"lamp_id": 1301, "category_id": 39},
                "score": 0.91,
                "debug_info": None,
            }
        ]
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(DummyConn(rows)))), patch(
            "src.routes.corp_db._get_query_embedding", new=AsyncMock(return_value=[0.0] * 1536)
        ):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "hybrid_search", "query": "LINE OZ 25", "profile": "entity_resolver"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["kind"], "hybrid_search")
        self.assertEqual(payload["results"][0]["entity_type"], "lamp")
        self.assertEqual(payload["results"][0]["title"], "LAD LED LINE-OZ-25")

    def test_normalize_query_text_normalizes_units(self):
        from src.routes.corp_db import _normalize_query_text

        normalized = _normalize_query_text("IP65 5000K 25Вт")
        self.assertIn("ip65", normalized)
        self.assertIn("5000k", normalized)
        self.assertIn("25w", normalized)

    def test_extract_filter_retry_parses_power_and_ip(self):
        from src.routes.corp_db import _extract_filter_retry

        filters = _extract_filter_retry("прожектор 100 ватт ip65")
        self.assertEqual(filters["ip"], "IP65")
        self.assertLessEqual(filters["power_w_min"], 100)
        self.assertGreaterEqual(filters["power_w_max"], 100)

    def test_hybrid_search_uses_token_fallback_after_empty(self):
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(RoutingConn()))), patch(
            "src.routes.corp_db._get_query_embedding", new=AsyncMock(return_value=None)
        ):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "hybrid_search", "query": "нефтегаз проекты портфолио", "profile": "related_evidence"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["filters"]["search_strategy"], "fallback")
        self.assertEqual(payload["results"][0]["entity_type"], "portfolio")

    def test_candidate_generation_uses_filter_fallback_after_empty(self):
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(RoutingConn()))), patch(
            "src.routes.corp_db._get_query_embedding", new=AsyncMock(return_value=None)
        ):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "hybrid_search", "query": "прожектор 100 ватт ip65", "profile": "candidate_generation"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["filters"]["search_strategy"], "fallback")
        self.assertEqual(payload["results"][0]["entity_type"], "lamp")
