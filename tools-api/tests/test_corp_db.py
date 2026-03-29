"""corp_db_search route tests."""

import unittest
from decimal import Decimal
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


class LampExactConn:
    async def fetch(self, query, *args):
        sql = str(query)
        if "FROM corp.v_catalog_lamps_agent" in sql:
            return [
                {
                    "lamp_id": 2014,
                    "name": "LAD LED R500-9-30-6-650LZD",
                    "category_id": 68,
                    "category_name": "LAD LED R500-9 LZD",
                    "url": "https://ladzavod.ru/catalog/r500-9-lzd/ladled-r500-9-30-6-650lzd",
                    "image_url": None,
                    "power_w": 557,
                    "luminous_flux_lm": 78537,
                    "beam_pattern": "30°",
                    "explosion_protection_marking": None,
                    "is_explosion_protected": False,
                    "color_temperature_k": 5000,
                    "color_rendering_index_ra": None,
                    "power_factor_operator": ">=",
                    "power_factor_min": 0.95,
                    "climate_execution": "УХЛ1",
                    "weight_kg": 18.3,
                    "ingress_protection": "IP65",
                    "mounting_type": "Лира",
                    "supply_voltage_raw": "220+40%, 220-30%",
                    "supply_voltage_kind": "AC",
                    "supply_voltage_nominal_v": 220,
                    "supply_voltage_min_v": 154,
                    "supply_voltage_max_v": 308,
                    "supply_voltage_tolerance_minus_pct": 30.0,
                    "supply_voltage_tolerance_plus_pct": 40.0,
                    "operating_temperature_range_raw": "-60...+70",
                    "operating_temperature_min_c": -60,
                    "operating_temperature_max_c": 70,
                    "electrical_protection_class": "I",
                    "dimensions_raw": "774 x 428 x 406",
                    "length_mm": 774.0,
                    "width_mm": 428.0,
                    "height_mm": 406.0,
                    "warranty_years": 5,
                    "preview": "LAD LED R500-9 LZD | 557 Вт | 78537 лм | 30° | IP65 | 18.3 кг",
                    "agent_summary": "Светильник LAD LED R500-9-30-6-650LZD. Мощность 557 Вт. Световой поток 78537 лм. Светораспределение 30°. Вес 18.3 кг.",
                    "agent_facts": {
                        "power_w": {"label": "Мощность", "text": "557 Вт", "value": 557, "unit": "Вт"},
                        "beam_pattern": {"label": "Светораспределение", "text": "30°", "value": "30°"},
                        "weight_kg": {"label": "Вес", "text": "18.3 кг", "value": 18.3, "unit": "кг"},
                    },
                }
            ]
        return []


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
        if "FROM corp.v_catalog_lamps_agent l" in sql:
            return [
                {
                    "lamp_id": 1998,
                    "name": "LAD LED R700-1 ST",
                    "category_id": 87,
                    "category_name": "LAD LED R700-1 ST",
                    "power_w": 100,
                    "luminous_flux_lm": 14579,
                    "beam_pattern": "Ш",
                    "explosion_protection_marking": None,
                    "is_explosion_protected": False,
                    "color_temperature_k": 5000,
                    "color_rendering_index_ra": 80,
                    "power_factor_operator": ">=",
                    "power_factor_min": 0.95,
                    "climate_execution": "УХЛ1",
                    "weight_kg": 8.4,
                    "ingress_protection": "IP67",
                    "mounting_type": "лира",
                    "electrical_protection_class": "I",
                    "supply_voltage_kind": "AC",
                    "supply_voltage_raw": "AC230",
                    "supply_voltage_nominal_v": 230,
                    "supply_voltage_min_v": 180,
                    "supply_voltage_max_v": 260,
                    "supply_voltage_tolerance_minus_pct": 20.0,
                    "supply_voltage_tolerance_plus_pct": 15.0,
                    "operating_temperature_range_raw": "-60...+50",
                    "operating_temperature_min_c": -60,
                    "operating_temperature_max_c": 50,
                    "dimensions_raw": "500 x 300 x 200",
                    "length_mm": 500.0,
                    "width_mm": 300.0,
                    "height_mm": 200.0,
                    "warranty_years": 5,
                    "url": "https://ladzavod.ru/catalog/r700-1-st",
                    "image_url": None,
                    "preview": "LAD LED R700-1 ST | 100 Вт | 14579 лм | IP67 | 8.4 кг",
                    "agent_summary": "Светильник LAD LED R700-1 ST. Мощность 100 Вт. Вес 8.4 кг.",
                    "agent_facts": {
                        "power_w": {"label": "Мощность", "text": "100 Вт", "value": 100, "unit": "Вт"},
                        "weight_kg": {"label": "Вес", "text": "8.4 кг", "value": 8.4, "unit": "кг"},
                        "electrical_protection_class": {"label": "Класс электрозащиты", "text": "I", "value": "I"},
                    },
                }
            ]
        return []


class HybridLampFilterConn:
    def __init__(self, *, primary_matches_filters: bool):
        self.primary_matches_filters = primary_matches_filters
        self.hybrid_queries = 0
        self.alias_queries = 0
        self.lamp_filter_queries = 0

    @staticmethod
    def _lamp_row() -> dict:
        return {
            "lamp_id": 1998,
            "name": "LAD LED R700-1 ST",
            "category_id": 87,
            "category_name": "LAD LED R700-1 ST",
            "power_w": 100,
            "luminous_flux_lm": 14579,
            "beam_pattern": "Ш",
            "explosion_protection_marking": None,
            "is_explosion_protected": False,
            "color_temperature_k": 5000,
            "color_rendering_index_ra": 80,
            "power_factor_operator": ">=",
            "power_factor_min": 0.95,
            "climate_execution": "УХЛ1",
            "weight_kg": 8.4,
            "ingress_protection": "IP67",
            "mounting_type": "лира",
            "electrical_protection_class": "I",
            "supply_voltage_kind": "AC",
            "supply_voltage_raw": "AC230",
            "supply_voltage_nominal_v": 230,
            "supply_voltage_min_v": 180,
            "supply_voltage_max_v": 260,
            "supply_voltage_tolerance_minus_pct": 20.0,
            "supply_voltage_tolerance_plus_pct": 15.0,
            "operating_temperature_range_raw": "-60...+50",
            "operating_temperature_min_c": -60,
            "operating_temperature_max_c": 50,
            "dimensions_raw": "500 x 300 x 200 мм",
            "length_mm": 500.0,
            "width_mm": 300.0,
            "height_mm": 200.0,
            "warranty_years": 5,
            "url": "https://ladzavod.ru/catalog/r700-1-st",
            "image_url": None,
            "preview": "LAD LED R700-1 ST | 100 Вт | 14579 лм | IP67 | 8.4 кг | 500 x 300 x 200 мм",
            "agent_summary": "Светильник LAD LED R700-1 ST. Мощность 100 Вт. Вес 8.4 кг.",
            "agent_facts": {
                "power_w": {"label": "Мощность", "text": "100 Вт", "value": 100, "unit": "Вт"},
                "weight_kg": {"label": "Вес", "text": "8.4 кг", "value": 8.4, "unit": "кг"},
                "electrical_protection_class": {"label": "Класс электрозащиты", "text": "I", "value": "I"},
            },
        }

    async def fetch(self, query, *args):
        sql = str(query)
        if "corp.corp_hybrid_search" in sql:
            self.hybrid_queries += 1
            entity_id = "1998" if self.primary_matches_filters else "5001"
            return [
                {
                    "doc_id": 11,
                    "entity_type": "lamp",
                    "entity_id": entity_id,
                    "title": "LAD LED R700-1 ST" if self.primary_matches_filters else "LAD LED OTHER",
                    "content": "лира ip67 до 9 кг",
                    "metadata": {"lamp_id": int(entity_id)},
                    "score": 0.91,
                    "debug_info": {"fts": {"rank_ix": 1}, "semantic": {}, "fuzzy": {}},
                }
            ]
        if "WHERE l.lamp_id = ANY($1::bigint[])" in sql:
            if self.primary_matches_filters:
                return [self._lamp_row()]
            return []
        if "similarity(lower(d.title), lower($1))" in sql:
            self.alias_queries += 1
            return []
        if "FROM corp.v_catalog_lamps_agent l" in sql:
            self.lamp_filter_queries += 1
            return [self._lamp_row()]
        return []


class QueryCaptureConn:
    def __init__(self):
        self.queries: list[tuple[str, tuple]] = []

    async def fetch(self, query, *args):
        self.queries.append((str(query), args))
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

    def test_lamp_exact_returns_weight(self):
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(LampExactConn()))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "lamp_exact", "name": "LAD LED R500-9-30-6-650LZD"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["results"][0]["weight_kg"], 18.3)
        self.assertIn("agent_summary", payload["results"][0])
        self.assertEqual(payload["results"][0]["facts"]["beam_pattern"]["text"], "30°")

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

    def test_sanitize_filter_defaults_drops_zero_ranges_and_false_boolean(self):
        from src.routes.corp_db import CorpDbSearchRequest, _sanitize_filter_defaults

        req = CorpDbSearchRequest(
            kind="hybrid_search",
            query="R320 Ex",
            power_factor_operator="",
            power_w_min=0,
            power_w_max=0,
            weight_kg_min=0.0,
            warranty_years_max=0,
            temp_c_min=0,
            temp_c_max=0,
            explosion_protected=False,
        )
        sanitized = _sanitize_filter_defaults(req)
        self.assertIsNone(sanitized.power_w_min)
        self.assertIsNone(sanitized.power_w_max)
        self.assertIsNone(sanitized.weight_kg_min)
        self.assertIsNone(sanitized.warranty_years_max)
        self.assertIsNone(sanitized.power_factor_operator)
        self.assertIsNone(sanitized.temp_c_min)
        self.assertIsNone(sanitized.temp_c_max)
        self.assertIsNone(sanitized.explosion_protected)

    def test_build_lamp_conditions_normalizes_dimensions_and_voltage_kind(self):
        from src.routes.corp_db import CorpDbSearchRequest, _build_lamp_conditions

        req = CorpDbSearchRequest(
            kind="lamp_filters",
            dimensions_raw="774 x 428 x 406 мм",
            voltage_kind="AC/DC",
        )
        conditions, args, filters = _build_lamp_conditions(req)

        self.assertIn("774x428x406", args)
        self.assertEqual(filters["dimensions_raw"], "774 x 428 x 406 мм")
        self.assertEqual(filters["voltage_kind"], "AC/DC")
        self.assertTrue(any("regexp_replace(lower(coalesce(l.dimensions_raw, '')), '[^0-9x]+'" in cond for cond in conditions))
        self.assertTrue(any("nullif(trim(coalesce(l.supply_voltage_kind, '')), '') IS NULL" in cond for cond in conditions))
        self.assertTrue(any("upper(l.supply_voltage_kind) = 'AC/DC'" in cond for cond in conditions))

    def test_build_lamp_conditions_widens_decimal_equality_ranges(self):
        from src.routes.corp_db import CorpDbSearchRequest, _build_lamp_conditions

        req = CorpDbSearchRequest(
            kind="lamp_filters",
            beam_pattern="60°",
            dimensions_raw="774 x 428 x 406 мм",
            weight_kg_min=18.3,
            weight_kg_max=18.3,
            power_factor_min_min=0.95,
            power_factor_min_max=0.95,
        )
        conditions, args, filters = _build_lamp_conditions(req)

        self.assertEqual(filters["weight_kg_min"], 18.3)
        self.assertEqual(filters["weight_kg_max"], 18.3)
        self.assertEqual(filters["power_factor_min_min"], 0.95)
        self.assertEqual(filters["power_factor_min_max"], 0.95)
        self.assertEqual(args[2], Decimal("18.2995"))
        self.assertEqual(args[3], Decimal("18.3005"))
        self.assertEqual(args[4], Decimal("0.9495"))
        self.assertEqual(args[5], Decimal("0.9505"))
        self.assertTrue(any("l.weight_kg >=" in cond for cond in conditions))
        self.assertTrue(any("l.weight_kg <=" in cond for cond in conditions))

    def test_build_lamp_conditions_preserves_non_equality_decimal_ranges(self):
        from src.routes.corp_db import CorpDbSearchRequest, _build_lamp_conditions

        req = CorpDbSearchRequest(
            kind="lamp_filters",
            weight_kg_max=18.3,
            length_mm_min=774.0,
            length_mm_max=775.0,
        )
        _, args, filters = _build_lamp_conditions(req)

        self.assertEqual(filters["weight_kg_max"], 18.3)
        self.assertEqual(args[0], Decimal("18.3"))
        self.assertEqual(args[1], Decimal("774.0"))
        self.assertEqual(args[2], Decimal("775.0"))

    def test_lamp_filters_route_sanitizes_zero_defaults_from_agent(self):
        conn = QueryCaptureConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={
                    "kind": "lamp_filters",
                    "power_w_min": 35,
                    "power_w_max": 35,
                    "cct_k_min": 5000,
                    "cct_k_max": 5000,
                    "voltage_nominal_v_min": 230,
                    "voltage_nominal_v_max": 230,
                    "flux_lm_min": 0,
                    "flux_lm_max": 0,
                    "cri_ra_min": 0,
                    "cri_ra_max": 0,
                    "temp_c_min": 0,
                    "temp_c_max": 0,
                    "explosion_protected": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(conn.queries), 1)
        _, args = conn.queries[0]
        self.assertEqual(args[:-2], (35, 35, 5000, 5000, 230, 230))

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
        self.assertEqual(payload["results"][0]["metadata"]["weight_kg"], 8.4)
        self.assertEqual(payload["results"][0]["facts"]["electrical_protection_class"]["text"], "I")

    def test_lamp_filters_supports_extended_characteristics(self):
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(RoutingConn()))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={
                    "kind": "lamp_filters",
                    "electrical_protection_class": "I",
                    "weight_kg_min": 8.0,
                    "weight_kg_max": 9.0,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["results"][0]["facts"]["weight_kg"]["text"], "8.4 кг")
        self.assertEqual(payload["results"][0]["metadata"]["electrical_protection_class"], "I")

    def test_hybrid_search_uses_authoritative_lamp_filters_when_primary_topn_misses(self):
        conn = HybridLampFilterConn(primary_matches_filters=False)
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))), patch(
            "src.routes.corp_db._get_query_embedding", new=AsyncMock(return_value=[0.0] * 1536)
        ):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={
                    "kind": "hybrid_search",
                    "query": "подбери светильник с лирой ip67 и весом до 9 кг",
                    "profile": "entity_resolver",
                    "mounting_type": "лира",
                    "ip": "IP67",
                    "weight_kg_max": 9.0,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["filters"]["lamp_filters_applied"], True)
        self.assertEqual(payload["results"][0]["entity_id"], "1998")
        self.assertEqual(payload["results"][0]["metadata"]["weight_kg"], 8.4)

    def test_hybrid_search_short_circuits_fast_path_before_hybrid_and_embedding(self):
        conn = HybridLampFilterConn(primary_matches_filters=False)
        embedding_mock = AsyncMock(return_value=[0.0] * 1536)
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))), patch(
            "src.routes.corp_db._get_query_embedding", new=embedding_mock
        ):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={
                    "kind": "hybrid_search",
                    "query": "подбери светильник с лирой ip67 и весом до 9 кг",
                    "profile": "entity_resolver",
                    "mounting_type": "лира",
                    "ip": "IP67",
                    "weight_kg_max": 9.0,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["filters"]["search_strategy"], "lamp_filters")
        self.assertEqual(conn.hybrid_queries, 0)
        self.assertEqual(conn.alias_queries, 0)
        embedding_mock.assert_not_awaited()

    def test_hybrid_search_skips_token_fallback_when_lamp_filters_already_found(self):
        conn = HybridLampFilterConn(primary_matches_filters=False)
        embedding_mock = AsyncMock(return_value=[0.0] * 1536)
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))), patch(
            "src.routes.corp_db._get_query_embedding", new=embedding_mock
        ):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={
                    "kind": "hybrid_search",
                    "query": "R700 лира ip67 до 9 кг",
                    "profile": "entity_resolver",
                    "mounting_type": "лира",
                    "ip": "IP67",
                    "weight_kg_max": 9.0,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["results"][0]["entity_id"], "1998")
        self.assertEqual(conn.hybrid_queries, 1)
        self.assertEqual(conn.alias_queries, 0)
        embedding_mock.assert_not_awaited()

    def test_hybrid_search_primary_contract_keeps_lamp_filters_flag(self):
        conn = HybridLampFilterConn(primary_matches_filters=True)
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))), patch(
            "src.routes.corp_db._get_query_embedding", new=AsyncMock(return_value=[0.0] * 1536)
        ):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={
                    "kind": "hybrid_search",
                    "query": "R700 лира ip67 8.4 кг",
                    "profile": "entity_resolver",
                    "mounting_type": "лира",
                    "ip": "IP67",
                    "weight_kg_max": 9.0,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["filters"]["search_strategy"], "primary")
        self.assertEqual(payload["filters"]["lamp_filters_applied"], True)

    def test_metrics_expose_search_phase_histogram_after_request(self):
        conn = HybridLampFilterConn(primary_matches_filters=False)
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={
                    "kind": "hybrid_search",
                    "query": "подбери светильник с лирой ip67 и весом до 9 кг",
                    "profile": "entity_resolver",
                    "mounting_type": "лира",
                    "ip": "IP67",
                    "weight_kg_max": 9.0,
                },
            )
            self.assertEqual(response.status_code, 200)

            metrics = client.get("/metrics")

        self.assertEqual(metrics.status_code, 200)
        text = metrics.text
        self.assertIn("corp_db_search_phase_duration_milliseconds_bucket", text)
        self.assertIn('phase="lamp_filters"', text)
