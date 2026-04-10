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
    def __init__(self):
        self.last_exact_args = None

    async def fetch(self, query, *args):
        sql = str(query)
        if "FROM corp.v_catalog_lamps_agent" in sql:
            self.last_exact_args = args
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


class PortfolioExamplesConn:
    def __init__(self, *, include_portfolio: bool = True, include_spheres: bool = True, include_category: bool = True):
        self.include_portfolio = include_portfolio
        self.include_spheres = include_spheres
        self.include_category = include_category

    @staticmethod
    def _lamp_row() -> dict:
        return {
            "lamp_id": 2014,
            "name": "LAD LED R500-9-30-6-650LZD",
            "category_id": 68,
            "category_name": "LAD LED R500-9 LZD",
            "url": "https://ladzavod.ru/catalog/r500-9-lzd/ladled-r500-9-30-6-650lzd",
            "image_url": None,
            "preview": "LAD LED R500-9 LZD | 557 Вт | 78537 лм | 30° | IP65 | 18.3 кг",
            "agent_summary": "Светильник LAD LED R500-9-30-6-650LZD. Мощность 557 Вт. Световой поток 78537 лм. Светораспределение 30°.",
            "agent_facts": {
                "power_w": {"label": "Мощность", "text": "557 Вт", "value": 557, "unit": "Вт"},
                "beam_pattern": {"label": "Светораспределение", "text": "30°", "value": "30°"},
            },
        }

    async def fetch(self, query, *args):
        sql = str(query)
        if "FROM corp.v_catalog_lamps_agent l" in sql:
            row = self._lamp_row()
            if not self.include_category:
                row["category_id"] = None
                row["category_name"] = None
            return [row]
        if "FROM corp.sphere_categories sc" in sql:
            if not self.include_spheres:
                return []
            return [
                {"sphere_id": 4, "sphere_name": "Нефтегазовый комплекс"},
                {"sphere_id": 7, "sphere_name": "Промышленность и склады"},
            ]
        if "FROM corp.portfolio p" in sql:
            if not self.include_portfolio:
                return []
            return [
                {
                    "portfolio_id": 102,
                    "name": "Освещение резервуарного парка",
                    "url": "https://ladzavod.ru/portfolio/reservoir",
                    "group_name": "Нефтегаз",
                    "image_url": "https://ladzavod.ru/images/reservoir.jpg",
                    "sphere_id": 4,
                    "sphere_name": "Нефтегазовый комплекс",
                },
                {
                    "portfolio_id": 205,
                    "name": "Освещение логистического комплекса",
                    "url": "https://ladzavod.ru/portfolio/logistics",
                    "group_name": "Логистика",
                    "image_url": "https://ladzavod.ru/images/logistics.jpg",
                    "sphere_id": 7,
                    "sphere_name": "Промышленность и склады",
                },
            ]
        return []


class EmptyLampPortfolioConn:
    async def fetch(self, query, *args):
        return []


class ApplicationRecommendationConn:
    def __init__(self):
        self.last_leaf_terms: list[str] = []

    @staticmethod
    def _sphere_rows():
        return [
            {"sphere_id": 2, "name": "Тяжелые условия эксплуатации", "url": "https://ladzavod.ru/catalog/tyazhelye-usloviya-ekspluatacii"},
            {"sphere_id": 3, "name": "Складские помещения", "url": "https://ladzavod.ru/catalog/skladskie-pomeshcheniya"},
            {"sphere_id": 6, "name": "Спортивное и освещение высокой мощности", "url": "https://ladzavod.ru/catalog/sportivnoe-osveshchenie"},
            {"sphere_id": 7, "name": "Наружное, уличное и дорожное освещение", "url": "https://ladzavod.ru/catalog/ulichnoe-i-dorozhnoe"},
            {"sphere_id": 8, "name": "Офисное, торговое, ЖКХ и АБК освещение", "url": "https://ladzavod.ru/catalog/ofisnoe-torgovoe-i-zhkh"},
            {"sphere_id": 11, "name": "Светильники специального назначения", "url": "https://ladzavod.ru/catalog/svetilniki-specialnogo-naznacheniya"},
        ]

    @staticmethod
    def _reference_categories():
        return [
            {"sphere_id": 6, "sphere_name": "Спортивное и освещение высокой мощности", "category_id": 169, "category_name": "LAD LED R500 SPORT", "url": "https://ladzavod.ru/catalog/sport", "image_url": "https://ladzavod.ru/img/r500-sport.png"},
            {"sphere_id": 6, "sphere_name": "Спортивное и освещение высокой мощности", "category_id": 37, "category_name": "LAD LED R500", "url": "https://ladzavod.ru/catalog/r500", "image_url": "https://ladzavod.ru/img/r500-parent.png"},
            {"sphere_id": 3, "sphere_name": "Складские помещения", "category_id": 39, "category_name": "LAD LED LINE-OZ", "url": "https://ladzavod.ru/catalog/line-oz", "image_url": "https://ladzavod.ru/img/line-oz.png"},
            {"sphere_id": 3, "sphere_name": "Складские помещения", "category_id": 37, "category_name": "LAD LED R500", "url": "https://ladzavod.ru/catalog/r500", "image_url": "https://ladzavod.ru/img/r500-parent.png"},
            {"sphere_id": 8, "sphere_name": "Офисное, торговое, ЖКХ и АБК освещение", "category_id": 14, "category_name": "NL Nova", "url": "https://ladzavod.ru/catalog/nl-nova", "image_url": "https://ladzavod.ru/img/nova.png"},
            {"sphere_id": 8, "sphere_name": "Офисное, торговое, ЖКХ и АБК освещение", "category_id": 170, "category_name": "NL VEGA", "url": "https://ladzavod.ru/catalog/nl-vega", "image_url": "https://ladzavod.ru/img/vega.png"},
            {"sphere_id": 7, "sphere_name": "Наружное, уличное и дорожное освещение", "category_id": 79, "category_name": "LAD LED R500 G", "url": "https://ladzavod.ru/catalog/r500-g", "image_url": "https://ladzavod.ru/img/r500-g.png"},
            {"sphere_id": 7, "sphere_name": "Наружное, уличное и дорожное освещение", "category_id": 161, "category_name": "Консольные светильники", "url": "https://ladzavod.ru/catalog/konsolnye-svetilniki", "image_url": "https://ladzavod.ru/img/console.png"},
            {"sphere_id": 11, "sphere_name": "Светильники специального назначения", "category_id": 166, "category_name": "Специальное освещение", "url": "https://ladzavod.ru/catalog/specialnoe-osveshchenie", "image_url": "https://ladzavod.ru/img/special.png"},
            {"sphere_id": 11, "sphere_name": "Светильники специального назначения", "category_id": 164, "category_name": "АЗС", "url": "https://ladzavod.ru/catalog/azs", "image_url": "https://ladzavod.ru/img/azs.png"},
        ]

    @staticmethod
    def _portfolio_rows():
        return [
            {"portfolio_id": 501, "sphere_id": 6, "sphere_name": "Спортивное и освещение высокой мощности", "name": "Освещение стадиона", "group_name": "Спорт", "url": "https://ladzavod.ru/portfolio/stadium", "image_url": "https://ladzavod.ru/img/stadium.png"},
            {"portfolio_id": 502, "sphere_id": 3, "sphere_name": "Складские помещения", "name": "Освещение логистического комплекса", "group_name": "Логистика", "url": "https://ladzavod.ru/portfolio/logistics", "image_url": "https://ladzavod.ru/img/logistics.png"},
            {"portfolio_id": 503, "sphere_id": 7, "sphere_name": "Наружное, уличное и дорожное освещение", "name": "Освещение аэропортового перрона", "group_name": "Транспорт", "url": "https://ladzavod.ru/portfolio/apron", "image_url": "https://ladzavod.ru/img/apron.png"},
            {"portfolio_id": 504, "sphere_id": 8, "sphere_name": "Офисное, торговое, ЖКХ и АБК освещение", "name": "Освещение административного корпуса", "group_name": "АБК", "url": "https://ladzavod.ru/portfolio/office", "image_url": "https://ladzavod.ru/img/office.png"},
            {"portfolio_id": 505, "sphere_id": 11, "sphere_name": "Светильники специального назначения", "name": "Освещение АЗС", "group_name": "АЗС", "url": "https://ladzavod.ru/portfolio/azs", "image_url": "https://ladzavod.ru/img/azs-portfolio.png"},
        ]

    @staticmethod
    def _leaf_categories(term: str):
        mapping = {
            "LAD LED R500": [
                {"category_id": 68, "category_name": "LAD LED R500-9 LZD", "lamp_count": 4, "url": "https://ladzavod.ru/catalog/r500-9-lzd", "image_url": "https://ladzavod.ru/img/r500-9.png"},
                {"category_id": 69, "category_name": "LAD LED R500-12 LZD", "lamp_count": 3, "url": "https://ladzavod.ru/catalog/r500-12-lzd", "image_url": "https://ladzavod.ru/img/r500-12.png"},
            ],
            "LAD LED R700": [
                {"category_id": 87, "category_name": "LAD LED R700-10 ST", "lamp_count": 2, "url": "https://ladzavod.ru/catalog/r700-10-st", "image_url": "https://ladzavod.ru/img/r700-10.png"},
            ],
            "LAD LED LINE-OZ": [
                {"category_id": 39, "category_name": "LAD LED LINE-OZ", "lamp_count": 5, "url": "https://ladzavod.ru/catalog/lad-led-line-oz", "image_url": "https://ladzavod.ru/img/line-oz.png"},
            ],
            "NL Nova": [
                {"category_id": 14, "category_name": "NL Nova120", "lamp_count": 3, "url": "https://ladzavod.ru/catalog/nl-nova120", "image_url": "https://ladzavod.ru/img/nova120.png"},
            ],
            "NL VEGA": [
                {"category_id": 170, "category_name": "NL VEGA", "lamp_count": 2, "url": "https://ladzavod.ru/catalog/nl-vega", "image_url": "https://ladzavod.ru/img/vega.png"},
            ],
            "LAD LED R500 G": [
                {"category_id": 79, "category_name": "LAD LED R500 G", "lamp_count": 2, "url": "https://ladzavod.ru/catalog/lad-led-r500-g", "image_url": "https://ladzavod.ru/img/r500-g.png"},
            ],
            "Специальное освещение": [
                {"category_id": 166, "category_name": "Специальное освещение", "lamp_count": 2, "url": "https://ladzavod.ru/catalog/specialnoe-osveshchenie", "image_url": "https://ladzavod.ru/img/special.png"},
            ],
            "АЗС": [
                {"category_id": 164, "category_name": "АЗС", "lamp_count": 1, "url": "https://ladzavod.ru/catalog/azs", "image_url": "https://ladzavod.ru/img/azs.png"},
            ],
            "LAD LED R320 Ex": [
                {"category_id": 18, "category_name": "LAD LED R320 Ex", "lamp_count": 1, "url": "https://ladzavod.ru/catalog/r320-ex", "image_url": "https://ladzavod.ru/img/r320-ex.png"},
            ],
            "LAD LED R500 2Ex": [
                {"category_id": 119, "category_name": "LAD LED R500 2Ex", "lamp_count": 1, "url": "https://ladzavod.ru/catalog/lad-led-r500-2ex", "image_url": "https://ladzavod.ru/img/r500-2ex.png"},
            ],
        }
        return mapping.get(term, [])

    @staticmethod
    def _lamp_row(
        lamp_id: int,
        *,
        name: str,
        category_id: int,
        category_name: str,
        power_w: int,
        luminous_flux_lm: int,
        ip: str,
        mounting_type: str,
        beam_pattern: str,
        image_url: str,
        url: str,
        is_explosion_protected: bool = False,
        climate_execution: str = "УХЛ1",
        cri_ra: int = 70,
        temp_min_c: int = -60,
        preview: str | None = None,
    ) -> dict:
        return {
            "lamp_id": lamp_id,
            "name": name,
            "category_id": category_id,
            "category_name": category_name,
            "url": url,
            "image_url": image_url,
            "power_w": power_w,
            "luminous_flux_lm": luminous_flux_lm,
            "beam_pattern": beam_pattern,
            "mounting_type": mounting_type,
            "explosion_protection_marking": "1Ex mb IIC T6 Gb X" if is_explosion_protected else None,
            "is_explosion_protected": is_explosion_protected,
            "color_temperature_k": 5000,
            "color_rendering_index_ra": cri_ra,
            "power_factor_operator": ">=",
            "power_factor_min": 0.95,
            "climate_execution": climate_execution,
            "operating_temperature_range_raw": f"{temp_min_c}...+50",
            "operating_temperature_min_c": temp_min_c,
            "operating_temperature_max_c": 50,
            "ingress_protection": ip,
            "electrical_protection_class": "I",
            "supply_voltage_raw": "AC230",
            "supply_voltage_kind": "AC",
            "supply_voltage_nominal_v": 230,
            "supply_voltage_min_v": 180,
            "supply_voltage_max_v": 260,
            "supply_voltage_tolerance_minus_pct": 20.0,
            "supply_voltage_tolerance_plus_pct": 15.0,
            "dimensions_raw": "500 x 300 x 200",
            "length_mm": 500.0,
            "width_mm": 300.0,
            "height_mm": 200.0,
            "warranty_years": 5,
            "weight_kg": 8.4,
            "preview": preview or f"{name} | {power_w} Вт | {luminous_flux_lm} лм | {ip}",
            "agent_summary": f"Светильник {name}. Мощность {power_w} Вт. Световой поток {luminous_flux_lm} лм.",
            "agent_facts": {
                "power_w": {"label": "Мощность", "text": f"{power_w} Вт", "value": power_w, "unit": "Вт"},
                "beam_pattern": {"label": "Светораспределение", "text": beam_pattern, "value": beam_pattern},
                "ingress_protection": {"label": "IP", "text": ip, "value": ip},
            },
        }

    async def fetch(self, query, *args):
        sql = str(query)
        if "application_reference_spheres" in sql:
            return self._sphere_rows()
        if "application_reference_categories" in sql:
            return self._reference_categories()
        if "application_reference_portfolio" in sql:
            return self._portfolio_rows()
        if "application_parent_categories" in sql:
            sphere_id = args[0]
            return [row for row in self._reference_categories() if row["sphere_id"] == sphere_id]
        if "application_leaf_categories" in sql:
            term = args[0]
            self.last_leaf_terms.append(term)
            return self._leaf_categories(term)
        if "application_lamps" in sql:
            category_ids = set(args[0])
            rows = []
            if 68 in category_ids:
                rows.append(self._lamp_row(2014, name="LAD LED R500-9-30-6-650LZD", category_id=68, category_name="LAD LED R500-9 LZD", power_w=557, luminous_flux_lm=78537, ip="IP65", mounting_type="Лира", beam_pattern="30°", image_url="https://ladzavod.ru/img/r500-9-30.png", url="https://ladzavod.ru/catalog/r500-9-lzd/ladled-r500-9-30-6-650lzd"))
            if 69 in category_ids:
                rows.append(self._lamp_row(2016, name="LAD LED R500-12-30-6-850LZD", category_id=69, category_name="LAD LED R500-12 LZD", power_w=709, luminous_flux_lm=97842, ip="IP65", mounting_type="Лира", beam_pattern="30°", image_url="https://ladzavod.ru/img/r500-12-30.png", url="https://ladzavod.ru/catalog/r500-12-lzd/ladled-r500-12-30-6-850lzd"))
            if 87 in category_ids:
                rows.append(self._lamp_row(2998, name="LAD LED R700-10 ST", category_id=87, category_name="LAD LED R700-10 ST", power_w=180, luminous_flux_lm=24579, ip="IP67", mounting_type="Лира", beam_pattern="Ш", image_url="https://ladzavod.ru/img/r700-10.png", url="https://ladzavod.ru/catalog/r700-10-st"))
            if 39 in category_ids:
                rows.append(self._lamp_row(1302, name="LAD LED LINE-OZ-80", category_id=39, category_name="LAD LED LINE-OZ", power_w=80, luminous_flux_lm=9200, ip="IP65", mounting_type="Подвес", beam_pattern="Опал", image_url="https://ladzavod.ru/img/line-oz-80.png", url="https://ladzavod.ru/catalog/lad-led-line-oz/lad-led-line-oz-80", cri_ra=80, temp_min_c=-65))
            if 14 in category_ids:
                rows.append(self._lamp_row(4101, name="NL Nova120", category_id=14, category_name="NL Nova120", power_w=36, luminous_flux_lm=4100, ip="IP40", mounting_type="Потолочное", beam_pattern="Опал", image_url="https://ladzavod.ru/img/nova120.png", url="https://ladzavod.ru/catalog/nl-nova120", cri_ra=80, temp_min_c=-20))
            if 170 in category_ids:
                rows.append(self._lamp_row(4102, name="NL VEGA-40", category_id=170, category_name="NL VEGA", power_w=40, luminous_flux_lm=4300, ip="IP40", mounting_type="Потолочное", beam_pattern="Опал", image_url="https://ladzavod.ru/img/vega40.png", url="https://ladzavod.ru/catalog/nl-vega/nl-vega-40", cri_ra=80, temp_min_c=-20))
            if 79 in category_ids:
                rows.append(self._lamp_row(5101, name="LAD LED R500 G-120", category_id=79, category_name="LAD LED R500 G", power_w=120, luminous_flux_lm=16500, ip="IP67", mounting_type="Консоль", beam_pattern="Ш", image_url="https://ladzavod.ru/img/r500-g-120.png", url="https://ladzavod.ru/catalog/lad-led-r500-g/r500-g-120"))
            if 166 in category_ids:
                rows.append(self._lamp_row(6101, name="LAD LED SPECIAL-80", category_id=166, category_name="Специальное освещение", power_w=80, luminous_flux_lm=10000, ip="IP67", mounting_type="Лира", beam_pattern="Ш", image_url="https://ladzavod.ru/img/special-80.png", url="https://ladzavod.ru/catalog/specialnoe-osveshchenie/special-80", temp_min_c=-40))
            if 18 in category_ids:
                rows.append(self._lamp_row(6102, name="LAD LED R320 Ex-50", category_id=18, category_name="LAD LED R320 Ex", power_w=50, luminous_flux_lm=6200, ip="IP67", mounting_type="Кронштейн", beam_pattern="Ш", image_url="https://ladzavod.ru/img/r320-ex-50.png", url="https://ladzavod.ru/catalog/r320-ex/r320-ex-50", is_explosion_protected=True))
            if 119 in category_ids:
                rows.append(self._lamp_row(6103, name="LAD LED R500 2Ex-120", category_id=119, category_name="LAD LED R500 2Ex", power_w=120, luminous_flux_lm=15800, ip="IP67", mounting_type="Лира", beam_pattern="60°", image_url="https://ladzavod.ru/img/r500-2ex-120.png", url="https://ladzavod.ru/catalog/lad-led-r500-2ex/r500-2ex-120", is_explosion_protected=True))
            return rows
        if "application_portfolio" in sql:
            sphere_id = args[0]
            return [row for row in self._portfolio_rows() if row["sphere_id"] == sphere_id]
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
        conn = LampExactConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
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

    def test_lamp_exact_matches_name_without_lad_prefix(self):
        conn = LampExactConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "lamp_exact", "name": "LED R500-9-30-6-650LZD"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["results"][0]["name"], "LAD LED R500-9-30-6-650LZD")
        self.assertIsNotNone(conn.last_exact_args)
        variants, core_name, _, _ = conn.last_exact_args
        self.assertIn("led r500-9-30-6-650lzd", variants)
        self.assertIn("r500-9-30-6-650lzd", variants)
        self.assertEqual(core_name, "r500-9-30-6-650lzd")

    def test_portfolio_examples_by_lamp_returns_compact_grouped_payload(self):
        conn = PortfolioExamplesConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "portfolio_examples_by_lamp", "name": "R500-9-30-6-650LZD", "limit": 10},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["kind"], "portfolio_examples_by_lamp")
        self.assertEqual(payload["lamp"]["name"], "LAD LED R500-9-30-6-650LZD")
        self.assertEqual(payload["lamp"]["category_id"], 68)
        self.assertEqual(len(payload["spheres"]), 2)
        self.assertEqual(len(payload["portfolio_examples"]), 2)
        self.assertEqual(payload["results"], payload["portfolio_examples"])
        self.assertEqual(payload["filters"]["lamp_match"], "exact")
        self.assertEqual(payload["filters"]["portfolio_count"], 2)
        self.assertEqual(payload["portfolio_examples"][0]["sphere_name"], "Нефтегазовый комплекс")

    def test_portfolio_examples_by_lamp_reports_portfolio_not_found(self):
        conn = PortfolioExamplesConn(include_portfolio=False)
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "portfolio_examples_by_lamp", "name": "R500-9-30-6-650LZD"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(payload["filters"]["reason"], "portfolio_not_found")
        self.assertEqual(payload["filters"]["category_id"], 68)
        self.assertEqual(payload["filters"]["sphere_count"], 2)
        self.assertEqual(payload["lamp"]["name"], "LAD LED R500-9-30-6-650LZD")
        self.assertEqual(payload["spheres"][0]["sphere_name"], "Нефтегазовый комплекс")

    def test_portfolio_examples_by_lamp_reports_lamp_not_found(self):
        conn = EmptyLampPortfolioConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "portfolio_examples_by_lamp", "name": "UNKNOWN-MODEL"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(payload["filters"]["reason"], "lamp_not_found")
        self.assertEqual(payload["results"], [])

    def test_application_recommendation_resolves_stadium_and_returns_payload(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери освещение для спортивного стадиона"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["kind"], "application_recommendation")
        self.assertEqual(payload["resolved_application"]["application_key"], "sports_high_power")
        self.assertEqual(payload["resolved_application"]["resolution_strategy"], "synonym_map")
        self.assertEqual(payload["categories"][0]["image_url"], "https://ladzavod.ru/img/r500-9.png")
        self.assertEqual(payload["recommended_lamps"][0]["name"], "LAD LED R500-12-30-6-850LZD")
        self.assertIn("стадионного света", payload["recommended_lamps"][0]["recommendation_reason"])
        self.assertEqual(payload["portfolio_examples"][0]["url"], "https://ladzavod.ru/portfolio/stadium")
        self.assertIn("Уточните высоту установки", payload["follow_up_question"])

    def test_application_recommendation_normalizes_quarry_typo(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери мощный светильник для карьерна"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["resolved_application"]["application_key"], "quarry_heavy_duty")
        self.assertIn(payload["recommended_lamps"][0]["category_name"], {"LAD LED R700-10 ST", "LAD LED R500-12 LZD", "LAD LED R500-9 LZD"})

    def test_application_recommendation_resolves_airport(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери освещение для аэропортового перрона"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved_application"]["application_key"], "airport_apron")
        self.assertEqual(payload["portfolio_examples"][0]["name"], "Освещение аэропортового перрона")

    def test_application_recommendation_prefers_warehouse_lamps_for_warehouse(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери освещение для склада"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved_application"]["application_key"], "warehouse")
        self.assertEqual(payload["recommended_lamps"][0]["category_name"], "LAD LED LINE-OZ")

    def test_application_recommendation_prefers_office_lamps_for_office(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери светильник для офисного кабинета"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved_application"]["application_key"], "office")
        self.assertIn(payload["recommended_lamps"][0]["category_name"], {"NL Nova120", "NL VEGA"})

    def test_application_recommendation_resolves_high_bay(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери освещение для высоких пролетов склада"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved_application"]["application_key"], "high_bay")
        self.assertNotIn(payload["recommended_lamps"][0]["category_name"], {"NL Nova120", "NL VEGA"})

    def test_application_recommendation_resolves_aggressive_environment(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери светильник для агрессивной среды"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved_application"]["application_key"], "aggressive_environment")
        self.assertTrue(payload["recommended_lamps"][0]["url"].startswith("https://ladzavod.ru/catalog/"))

    def test_application_recommendation_returns_ambiguity_payload(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери освещение для склада или офиса"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "needs_clarification")
        self.assertEqual(payload["resolved_application"]["resolution_strategy"], "ambiguity")
        self.assertGreaterEqual(len(payload["resolved_application"]["candidates"]), 2)
        self.assertEqual(payload["recommended_lamps"], [])

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

    def test_sanitize_filter_defaults_strips_lamp_filters_for_kb_route(self):
        from src.routes.corp_db import CorpDbSearchRequest, _sanitize_filter_defaults

        req = CorpDbSearchRequest(
            kind="hybrid_search",
            profile="kb_route_lookup",
            knowledge_route_id="corp_kb.company_common",
            source_files=["ignored.md"],
            topic_facets=["contacts"],
            beam_pattern="Ш",
            power_w_min=100,
            voltage_kind="AC",
        )
        sanitized = _sanitize_filter_defaults(req)

        self.assertEqual(sanitized.knowledge_route_id, "corp_kb.company_common")
        self.assertEqual(sanitized.source_files, ["common_information_about_company.md"])
        self.assertEqual(sanitized.topic_facets, ["contacts"])
        self.assertIsNone(sanitized.beam_pattern)
        self.assertIsNone(sanitized.power_w_min)
        self.assertIsNone(sanitized.voltage_kind)

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

    def test_hybrid_search_exposes_route_scope_and_uses_authoritative_source_files(self):
        conn = QueryCaptureConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={
                    "kind": "hybrid_search",
                    "query": "что такое luxnet",
                    "profile": "kb_route_lookup",
                    "knowledge_route_id": "corp_kb.luxnet",
                    "source_files": ["ignored.md"],
                    "topic_facets": ["definition"],
                    "beam_pattern": "Ш",
                    "power_w_min": 100,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["filters"]["knowledge_route_id"], "corp_kb.luxnet")
        self.assertEqual(payload["filters"]["source_file_scope"], ["about_Luxnet.md"])
        self.assertEqual(payload["filters"]["topic_facets"], ["definition"])
        self.assertEqual(len(conn.queries), 1)
        _, args = conn.queries[0]
        self.assertEqual(args[8], ["about_Luxnet.md"])

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

    def test_metrics_expose_portfolio_examples_phases(self):
        conn = PortfolioExamplesConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "portfolio_examples_by_lamp", "name": "R500-9-30-6-650LZD"},
            )
            self.assertEqual(response.status_code, 200)

            metrics = client.get("/metrics")

        self.assertEqual(metrics.status_code, 200)
        text = metrics.text
        self.assertIn('kind="portfolio_examples_by_lamp"', text)
        self.assertIn('phase="lamp_exact"', text)
        self.assertIn('phase="sphere_lookup"', text)
        self.assertIn('phase="portfolio_lookup"', text)
        self.assertIn('phase="response_build"', text)

    def test_metrics_expose_application_recommendation_phases(self):
        conn = ApplicationRecommendationConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))):
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "application_recommendation", "query": "подбери освещение для спортивного стадиона"},
            )
            self.assertEqual(response.status_code, 200)

            metrics = client.get("/metrics")

        self.assertEqual(metrics.status_code, 200)
        text = metrics.text
        self.assertIn('kind="application_recommendation"', text)
        self.assertIn('phase="application_resolution"', text)
        self.assertIn('phase="category_resolution"', text)
        self.assertIn('phase="lamp_ranking"', text)
        self.assertIn('phase="portfolio_lookup"', text)
        self.assertIn('phase="response_build"', text)

    def test_route_ingests_tool_call_headers_into_correlation_context(self):
        conn = QueryCaptureConn()
        with patch("src.routes.corp_db._get_pool", new=AsyncMock(return_value=DummyPool(conn))), patch(
            "src.routes.corp_db.update_correlation_context"
        ) as update_mock:
            from app import app

            client = TestClient(app)
            response = client.post(
                "/corp-db/search",
                json={"kind": "lamp_filters"},
                headers={"X-Tool-Call-Id": "call-9", "X-Tool-Call-Seq": "2"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(update_mock.call_count, 1)
        first_call = update_mock.call_args_list[0]
        self.assertEqual(first_call.kwargs["tool_call_id"], "call-9")
        self.assertEqual(first_call.kwargs["tool_call_seq"], "2")
        self.assertEqual(first_call.kwargs["tool_name"], "corp_db_search")
