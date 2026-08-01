import unittest
from pathlib import Path


ROOT = Path(__file__).parent


class CheckpointPrivacyTests(unittest.TestCase):
    def test_pyinstaller_does_not_bundle_runtime_checkpoint(self):
        spec = (ROOT / "api_release.spec").read_text(encoding="utf-8-sig").lower()
        self.assertNotIn("turn_checkpoints", spec)
        self.assertNotIn("runtime\\\\", spec)

    def test_distribution_script_uses_a_clean_whitelist(self):
        script = (ROOT / "scripts/package-test.ps1").read_text(
            encoding="utf-8-sig"
        ).lower()
        self.assertIn("deepseek_api_key=", script)
        self.assertNotIn("turn_checkpoints", script)
        self.assertNotIn("sessions", script)
        self.assertNotIn("runtime", script.replace("$projectroot", ""))


if __name__ == "__main__":
    unittest.main()
