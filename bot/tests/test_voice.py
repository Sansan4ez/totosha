import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


_MODULE_PATH = Path(__file__).resolve().parents[1] / "voice.py"
_SPEC = importlib.util.spec_from_file_location("bot_voice_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)

_stub_modules = {
    "aiohttp": types.SimpleNamespace(
        ClientTimeout=lambda **kwargs: None,
        ClientSession=None,
        FormData=lambda: None,
    ),
    "config": types.SimpleNamespace(
        ASR_URL="http://proxy:3200",
        ASR_TIMEOUT=60,
        ASR_LANGUAGE="ru",
    ),
}
_saved_modules = {name: sys.modules.get(name) for name in _stub_modules}
try:
    sys.modules.update(_stub_modules)
    _SPEC.loader.exec_module(_MODULE)
finally:
    for name, original in _saved_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class VoiceTests(unittest.TestCase):
    def test_raise_asr_http_error_classifies_upstream_challenge(self):
        with self.assertRaises(_MODULE.ASRTranscriptionError) as ctx:
            _MODULE._raise_asr_http_error(
                403,
                "<html><body>Enable JavaScript and cookies to continue __cf_chl challenge-platform</body></html>",
            )

        self.assertEqual(ctx.exception.code, "upstream_challenge")
        self.assertIn("ASR error: 403", ctx.exception.detail)

    def test_raise_asr_http_error_classifies_generic_auth(self):
        with self.assertRaises(_MODULE.ASRTranscriptionError) as ctx:
            _MODULE._raise_asr_http_error(403, '{"error":"forbidden"}')

        self.assertEqual(ctx.exception.code, "upstream_auth")

    def test_chatgpt_retry_retries_only_on_upstream_challenge(self):
        calls = {"count": 0}

        async def fake_transcribe(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise _MODULE.ASRTranscriptionError(
                    "upstream_challenge",
                    "ASR error: 403 <html>challenge-platform</html>",
                )
            return "ok"

        sleep_mock = AsyncMock()

        with patch.object(_MODULE, "_transcribe_chatgpt_api", side_effect=fake_transcribe), patch.object(
            _MODULE.asyncio, "sleep", sleep_mock
        ):
            result = asyncio.run(
                _MODULE._transcribe_chatgpt_api_with_retry(
                    session=object(),
                    asr_url="http://proxy:3200",
                    audio_data=b"abc",
                    language="ru",
                    api_key="",
                )
            )

        self.assertEqual(result, "ok")
        self.assertEqual(calls["count"], 2)
        sleep_mock.assert_awaited_once_with(_MODULE._CHATGPT_CHALLENGE_RETRY_DELAYS[0])


if __name__ == "__main__":
    unittest.main()
