import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from asr_compat_smoke import (
    EXPECTED_BACKEND_MODE,
    EXPECTED_BRANCH,
    build_test_wav_bytes,
    rate_for_window,
    validate_transcribe_health,
)


class AsrCompatSmokeTests(unittest.TestCase):
    def test_build_test_wav_bytes_returns_non_empty_wav(self):
        payload = build_test_wav_bytes()

        self.assertTrue(payload.startswith(b"RIFF"))
        self.assertGreater(len(payload), 128)

    def test_rate_for_window_returns_zero_without_requests(self):
        self.assertEqual(rate_for_window({"requests": 0, "challenges": 5}, "challenges"), 0.0)

    def test_validate_transcribe_health_accepts_healthy_snapshot(self):
        payload = {
            "backend_mode": EXPECTED_BACKEND_MODE,
            "compatibility_branch": EXPECTED_BRANCH,
            "degraded_credential_count": 0,
            "last_5m": {"requests": 10, "failures": 1, "challenges": 1},
            "last_30m": {"requests": 30, "failures": 3, "challenges": 2},
        }

        errors = validate_transcribe_health(
            payload,
            max_challenge_rate_5m=0.2,
            max_error_rate_5m=0.3,
            max_challenge_rate_30m=0.1,
            max_error_rate_30m=0.2,
            max_degraded_credentials=0,
        )

        self.assertEqual(errors, [])

    def test_validate_transcribe_health_reports_threshold_breaches(self):
        payload = {
            "backend_mode": "openai_compatible",
            "compatibility_branch": "wrong-branch",
            "degraded_credential_count": 2,
            "last_5m": {"requests": 4, "failures": 2, "challenges": 2},
            "last_30m": {"requests": 10, "failures": 4, "challenges": 2},
        }

        errors = validate_transcribe_health(
            payload,
            max_challenge_rate_5m=0.2,
            max_error_rate_5m=0.3,
            max_challenge_rate_30m=0.1,
            max_error_rate_30m=0.2,
            max_degraded_credentials=0,
        )

        self.assertIn("backend_mode=openai_compatible", errors)
        self.assertIn("compatibility_branch=wrong-branch", errors)
        self.assertIn("degraded_credential_count=2", errors)
        self.assertIn("last_5m.challenge_rate=0.500", errors)
        self.assertIn("last_5m.error_rate=0.500", errors)
        self.assertIn("last_30m.challenge_rate=0.200", errors)
        self.assertIn("last_30m.error_rate=0.400", errors)


if __name__ == "__main__":
    unittest.main()
