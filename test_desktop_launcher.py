import os
import unittest
from unittest.mock import patch

from backend.desktop_launcher import DEFAULT_STARTUP_TIMEOUT, _startup_timeout, _wait_for_server


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


if __name__ == "__main__":
    unittest.main()
