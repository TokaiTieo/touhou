import hashlib
import json
import struct
import unittest
import zlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes.system import mount_static_files
from backend.services.npc_identity_service import resolve_npc


ROOT = Path(__file__).parent
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class AvatarResourceTests(unittest.TestCase):
    def test_shipped_npcs_have_images_at_the_resolved_urls(self):
        document = json.loads((ROOT / "worlds/world_touhou/npcs/npc_index.json").read_text(encoding="utf-8-sig"))
        for npc in document["npcs"]:
            with self.subTest(npc=npc["name"]):
                registered = resolve_npc(npc["id"])
                self.assertIsNotNone(registered)
                self.assertEqual(registered["avatar_url"], f"/avatars/{registered['id']}.png")
                path = ROOT / "avatars" / f"{registered['id']}.png"
                self.assertTrue(path.is_file(), str(path))
                with path.open("rb") as handle:
                    header = handle.read(24)
                self.assertEqual(header[:8], PNG_SIGNATURE)
                width, height = struct.unpack_from(">II", header, 16)
                self.assertEqual(width, height)
                self.assertGreaterEqual(width, 256)

    def test_new_portraits_match_their_manifest_and_are_complete_distinct_pngs(self):
        manifest = json.loads((ROOT / "docs/avatar-generation-2026-10-29.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["completed"])
        self.assertEqual(len(manifest["entries"]), 33)
        self.assertEqual(len({entry["id"] for entry in manifest["entries"]}), 33)
        self.assertEqual(sum(bool(entry["game"]) for entry in manifest["entries"]), 31)
        digests = set()
        for entry in manifest["entries"]:
            with self.subTest(npc=entry["name"]):
                self.assertEqual(entry["status"], "saved")
                self.assertTrue(entry.get("exact_prompt") or entry.get("subject_prompt"))
                if entry["game"]:
                    self.assertTrue(entry["wiki_reference_reviewed"])
                    self.assertTrue(entry["source_image"].startswith("https://thwiki.cc/文件:"))
                else:
                    self.assertEqual(entry["source"], "project-original")
                data = (ROOT / entry["output"]).read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                self.assertEqual(digest, entry["sha256"])
                self.assertNotIn(digest, digests)
                digests.add(digest)
                self.assertEqual(data[:8], PNG_SIGNATURE)
                width, height, depth, color, compression, filtering, interlace = struct.unpack_from(">IIBBBBB", data, 16)
                self.assertEqual((width, height), (entry["width"], entry["height"]))
                self.assertEqual((depth, compression, filtering, interlace), (8, 0, 0, 0))
                self.assertIn(color, (2, 6))
                offset, compressed, ended = 8, [], False
                while offset + 12 <= len(data):
                    length = struct.unpack_from(">I", data, offset)[0]
                    end = offset + 12 + length
                    self.assertLessEqual(end, len(data))
                    kind = data[offset + 4:offset + 8]
                    chunk = data[offset + 8:offset + 8 + length]
                    checksum = struct.unpack_from(">I", data, offset + 8 + length)[0]
                    self.assertEqual(zlib.crc32(kind + chunk), checksum)
                    if kind == b"IDAT":
                        compressed.append(chunk)
                    offset = end
                    if kind == b"IEND":
                        ended = True
                        break
                self.assertTrue(ended)
                self.assertEqual(offset, len(data))
                channels = 3 if color == 2 else 4
                pixels = zlib.decompress(b"".join(compressed))
                self.assertEqual(len(pixels), height * (1 + width * channels))

    def test_server_serves_all_avatar_urls_and_resolved_legacy_identities(self):
        document = json.loads((ROOT / "worlds/world_touhou/npcs/npc_index.json").read_text(encoding="utf-8-sig"))
        app = FastAPI()
        mount_static_files(app)
        with TestClient(app) as client:
            for npc in document["npcs"]:
                url = resolve_npc(npc["id"])["avatar_url"]
                with self.subTest(url=url):
                    response = client.head(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["content-type"], "image/png")
            for identity in ("npc_chiyoda", "千亦", "npc_hisami_c", "日狭美", "npc_patchouli_n"):
                response = client.get(resolve_npc(identity)["avatar_url"])
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content.startswith(PNG_SIGNATURE))


if __name__ == "__main__":
    unittest.main()
