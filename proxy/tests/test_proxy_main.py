import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import _hash_embedding, _local_embeddings_response, _resolve_target_url


class ProxyHelpersTests(unittest.TestCase):
    def test_resolve_target_url_handles_v1_base(self):
        url = _resolve_target_url("http://proxy.example/v1", "embeddings")
        self.assertEqual(url, "http://proxy.example/v1/embeddings")

    def test_hash_embedding_is_deterministic(self):
        first = _hash_embedding("нефтегаз ip65 100w", 16)
        second = _hash_embedding("нефтегаз ip65 100w", 16)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)

    def test_local_embeddings_response_supports_batch_input(self):
        payload = {"model": "text-embedding-3-large", "input": ["ip65", "5000k"], "dimensions": 8}
        response = _local_embeddings_response(payload)
        self.assertEqual(response["embedding_backend"], "local_hash_fallback")
        self.assertEqual(len(response["data"]), 2)
        self.assertEqual(len(response["data"][0]["embedding"]), 8)


if __name__ == "__main__":
    unittest.main()
