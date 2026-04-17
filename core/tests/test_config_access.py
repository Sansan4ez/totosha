import os
import sys
import unittest
import importlib.util
from pathlib import Path
from unittest import mock


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODULE_PATH = Path(__file__).resolve().parents[1] / "config.py"


def _load_config_module():
    spec = importlib.util.spec_from_file_location("core_config_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigAccessTests(unittest.TestCase):
    def test_web_enabled_follows_environment_flag(self):
        with mock.patch.dict(os.environ, {"WEB_ENABLED": "true"}, clear=False):
            reloaded = _load_config_module()
            self.assertTrue(reloaded.CONFIG.web_enabled)

    def test_get_access_mode_maps_admin_alias(self):
        with mock.patch.dict(os.environ, {"ACCESS_MODE": "admin"}, clear=False):
            self.assertEqual(_load_config_module().get_access_mode(), "admin_only")


if __name__ == "__main__":
    unittest.main()
