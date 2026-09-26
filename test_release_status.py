import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_identity import digest
from release_status import release_status


class ReleaseStatusTests(unittest.TestCase):
    def test_exe_and_zip_are_independently_verified_against_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / 'release'
            release.mkdir()
            exe = root / 'touhou.exe'
            package = release / 'touhou-test-package.zip'
            exe.write_bytes(b'new executable')
            package.write_bytes(b'old package')
            (release / 'verified-exe.json').write_text(json.dumps({'sha256': digest(exe), 'build_id': 'new', 'version': '2'}))
            manifest = {'build_id': 'old', 'version': '1', 'files': [{'path': package.name, 'sha256': digest(package)}]}
            (release / 'touhou-test-package.zip.manifest.json').write_text(json.dumps(manifest))
            with patch('release_status.build_identity', return_value={'build_id': 'new', 'version': '2'}):
                report = release_status(root)
                self.assertEqual(report['exe']['status'], 'current')
                self.assertEqual(report['zip']['status'], 'outdated')
                self.assertFalse(report['zip']['verified'])
                exe.write_bytes(b'unsigned modification')
                self.assertEqual(release_status(root)['exe']['status'], 'unverified')
                package.unlink()
                self.assertEqual(release_status(root)['zip']['status'], 'missing')

    def test_missing_or_corrupt_receipts_do_not_certify_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'release').mkdir()
            (root / 'touhou.exe').write_bytes(b'executable')
            (root / 'release' / 'verified-exe.json').write_text('{broken')
            with patch('release_status.build_identity', return_value={'build_id': 'new', 'version': '2'}):
                self.assertEqual(release_status(root)['exe']['status'], 'unverified')
