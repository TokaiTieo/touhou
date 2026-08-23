import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.desktop_launcher import (
    DEFAULT_STARTUP_TIMEOUT,
    _startup_timeout,
    _wait_for_server,
    _write_startup_diagnostic,
)


class _StoppedThread:
    @staticmethod
    def is_alive():
        return False


class DesktopLauncherTests(unittest.TestCase):
    def test_startup_timeout_is_longer_and_bounded(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOUHOU_STARTUP_TIMEOUT", None)
            self.assertEqual(_startup_timeout(), DEFAULT_STARTUP_TIMEOUT)
        with patch.dict(os.environ, {"TOUHOU_STARTUP_TIMEOUT": "2"}):
            self.assertEqual(_startup_timeout(), 10.0)
        with patch.dict(os.environ, {"TOUHOU_STARTUP_TIMEOUT": "999"}):
            self.assertEqual(_startup_timeout(), 180.0)

    def test_wait_stops_immediately_when_server_thread_exits(self):
        self.assertFalse(
            _wait_for_server("127.0.0.1", 1, timeout=60, server_thread=_StoppedThread())
        )

    def test_preflight_diagnostic_does_not_shadow_data_dir_argument(self):
        source = (Path(__file__).resolve().parent / "backend/desktop_launcher.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('data_dir=str(data_dir)', source)
        self.assertIn('data_path=str(data_dir)', source)

    def test_startup_diagnostic_records_current_phase_without_secrets(self):
        with tempfile.TemporaryDirectory() as root:
            payload = _write_startup_diagnostic(Path(root), "health_wait", "failed", reason="timeout")
            path = Path(root) / "logs/startup-diagnostics.json"
            self.assertTrue(path.exists())
            self.assertEqual(payload["phase"], "health_wait")
            self.assertNotIn("api_key", path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
