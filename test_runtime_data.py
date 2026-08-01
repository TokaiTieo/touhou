import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import migrate_legacy_runtime_data
from backend.utils.secret_store import load_secret, save_secret
from backend.world_manager import ensure_worlds_available


class RuntimeDataTests(unittest.TestCase):
    def test_legacy_worlds_and_env_migrate_once(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            legacy = root / "legacy"
            target = root / "target"
            (legacy / "worlds/world_touhou/sessions/characters").mkdir(parents=True)
            (legacy / "worlds/world_touhou/sessions/characters/old.json").write_text("{}", encoding="utf-8")
            (legacy / ".env").write_text("DEEPSEEK_API_KEY=legacy-test\n", encoding="utf-8")
            self.assertTrue(migrate_legacy_runtime_data(legacy, target))
            self.assertTrue((target / "worlds/world_touhou/sessions/characters/old.json").exists())
            self.assertFalse(migrate_legacy_runtime_data(legacy, target))

    def test_dpapi_secret_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "api_key.dat"
            save_secret(path, "test-key-not-real")
            self.assertEqual(load_secret(path), "test-key-not-real")
            self.assertNotIn(b"test-key-not-real", path.read_bytes())

    def test_new_incident_content_is_added_without_overwriting_existing_world(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            bundled = root / "bundled/worlds"
            target = root / "data/worlds"
            world = target / "world_touhou"
            for relative in (
                "worlds_index.json",
                "world_touhou/locations/location_base.json",
                "world_touhou/npcs/npc_index.json",
                "world_touhou/timeline.json",
                "world_touhou/worldview.txt",
            ):
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("existing", encoding="utf-8")
            (bundled / "world_touhou").mkdir(parents=True)
            (bundled / "world_touhou/incidents.json").write_text('{"incidents": []}', encoding="utf-8")
            with patch("backend.world_manager.BASE_DIR", root / "bundled"), patch("backend.world_manager.WORLDS_DIR", target):
                ensure_worlds_available()
            self.assertEqual((world / "worldview.txt").read_text(encoding="utf-8"), "existing")
            self.assertTrue((world / "incidents.json").exists())


if __name__ == "__main__":
    unittest.main()
