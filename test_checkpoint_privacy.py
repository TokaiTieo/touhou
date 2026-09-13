import unittest
import tempfile
from pathlib import Path

from release_manifest import build_release_manifest


ROOT = Path(__file__).parent


class CheckpointPrivacyTests(unittest.TestCase):
    def test_build_identity_changes_with_source_but_excludes_runtime_secrets(self):
        from build_identity import build_identity
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("index.html", "api_release.spec", "build_identity.py", "requirements.txt"):
                (root / name).write_text("fixture", encoding="utf-8")
            (root / "version.json").write_text('{"version":"test"}', encoding="utf-8")
            (root / "release/build_worlds_clean").mkdir(parents=True)
            (root / ".env").write_text("test-secret", encoding="utf-8")
            before = build_identity(root)
            (root / ".env").write_text("different-test-secret", encoding="utf-8")
            self.assertEqual(before["build_id"], build_identity(root)["build_id"])
            self.assertNotIn(".env", before["files"])
            (root / "index.html").write_text("changed", encoding="utf-8")
            self.assertNotEqual(before["build_id"], build_identity(root)["build_id"])

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
        self.assertIn("release_manifest.py", script)
        self.assertIn("release-manifest.json", script)


    def test_release_manifest_contains_hashes_not_credentials(self):
        source = (ROOT / "release_manifest.py").read_text(encoding="utf-8-sig").lower()
        self.assertIn("sha256", source)
        self.assertNotIn("deepseek_api_key", source)

    def test_release_manifest_hashes_real_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            artifact = Path(root) / "touhou.exe"
            artifact.write_bytes(b"test-release-artifact")
            manifest = build_release_manifest(Path(root), [artifact])
        self.assertEqual(manifest["files"][0]["path"], "touhou.exe")
        self.assertEqual(len(manifest["files"][0]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
