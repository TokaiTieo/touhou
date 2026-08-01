import json
import unittest
from pathlib import Path

from backend.version import APP_VERSION, CONTENT_SCHEMA_VERSION, SAVE_SCHEMA_VERSION, VERSION_MANIFEST


class VersionConsistencyTests(unittest.TestCase):
    def test_manifest_drives_backend_and_package_metadata(self):
        root = Path(__file__).parent
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        package_lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(APP_VERSION, VERSION_MANIFEST["version"])
        self.assertEqual(package["version"], APP_VERSION)
        self.assertEqual(package_lock["version"], APP_VERSION)
        self.assertEqual(VERSION_MANIFEST["save_schema"], SAVE_SCHEMA_VERSION)
        self.assertEqual(VERSION_MANIFEST["content_schema"], CONTENT_SCHEMA_VERSION)
        self.assertGreaterEqual(SAVE_SCHEMA_VERSION, 7)
        self.assertNotIn("v0.9.0", (root / "js/main.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
