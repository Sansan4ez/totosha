"""corp_db_search route tests."""

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


def test_hybrid_search_route_returns_allowlisted_result():
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

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["kind"] == "hybrid_search"
    assert payload["results"][0]["entity_type"] == "lamp"
    assert payload["results"][0]["title"] == "LAD LED LINE-OZ-25"


def test_sku_by_code_requires_exactly_one_code():
    from app import app

    client = TestClient(app)
    response = client.post(
        "/corp-db/search",
        json={"kind": "sku_by_code", "etm": "LINE1132", "oracl": "1669705"},
    )
    assert response.status_code == 400
