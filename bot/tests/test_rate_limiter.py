import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rate_limiter as rl_module
from rate_limiter import RateLimiter


class RateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.limiter = RateLimiter()
        self.orig_max_retries = rl_module.CONFIG.max_retries
        self.orig_send_timeout = rl_module.CONFIG.send_timeout
        self.orig_global_min_interval = rl_module.CONFIG.global_min_interval
        self.orig_group_min_interval = rl_module.CONFIG.group_min_interval
        rl_module.CONFIG.max_retries = 2
        rl_module.CONFIG.send_timeout = 0.05
        rl_module.CONFIG.global_min_interval = 0.0
        rl_module.CONFIG.group_min_interval = 0.0

    async def asyncTearDown(self):
        rl_module.CONFIG.max_retries = self.orig_max_retries
        rl_module.CONFIG.send_timeout = self.orig_send_timeout
        rl_module.CONFIG.global_min_interval = self.orig_global_min_interval
        rl_module.CONFIG.group_min_interval = self.orig_group_min_interval

    async def test_safe_send_retries_with_factory(self):
        attempts = 0

        async def op():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise Exception("429 retry_after")
            return "ok"

        async def no_sleep(_seconds):
            return None

        with mock.patch.object(rl_module.asyncio, "sleep", new=no_sleep):
            result = await self.limiter.safe_send(123, lambda: op())

        self.assertEqual(result, "ok")
        self.assertEqual(attempts, 2)

    async def test_safe_send_times_out(self):
        async def op():
            await asyncio.Future()

        result = await self.limiter.safe_send(123, lambda: op())
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
