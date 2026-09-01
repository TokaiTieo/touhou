import json
import re
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class VueArchitectureTests(unittest.TestCase):
    def test_legacy_renderer_is_not_imported_by_runtime_modules(self):
        offenders = []
        for path in (ROOT / "js").rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            if "ui/render.js" in text or "ghost/ui/render" in text:
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_legacy_renderer_has_been_removed(self):
        self.assertFalse((ROOT / "js/ghost/ui/render.js").exists())

    def test_vue_controller_owns_game_data_refresh(self):
        controller = (ROOT / "js/vue/game-controller.js").read_text(encoding="utf-8")
        for function_name in (
            "renderChatHistory",
            "renderSidebarLocations",
            "refreshNPCList",
            "refreshTasksPanel",
            "showGameInterface",
        ):
            self.assertIn(f"function {function_name}", controller)

    def test_sensitive_settings_and_producer_console_are_vue_owned(self):
        settings = (ROOT / "js/vue/settings-dialog.js").read_text(encoding="utf-8")
        producer = (ROOT / "js/vue/producer-console.js").read_text(encoding="utf-8")
        compatibility = (ROOT / "js/ghost/modules/producer-console.js").read_text(encoding="utf-8")
        self.assertIn("defineComponent", settings)
        self.assertNotIn("localStorage.setItem('touhou_api_key'", settings)
        self.assertIn("defineComponent", producer)
        self.assertIn("openProducerConsoleVue", compatibility)

    def test_runtime_modules_are_split_and_single_world_ui_has_no_switch_control(self):
        for path in (
            "backend/services/turn_resolution_service.py",
            "backend/services/turn_prompt_service.py",
            "backend/services/turn_context_service.py",
            "backend/services/snapshot_service.py",
            "backend/services/npc_memory_service.py",
            "backend/routes/producer.py",
        ):
            self.assertTrue((ROOT / path).exists(), path)
        character_ui = (ROOT / "js/vue/character-selection.js").read_text(encoding="utf-8")
        self.assertNotIn("switchWorldBtn", character_ui)
        settings = (ROOT / "js/vue/settings-dialog.js").read_text(encoding="utf-8")
        self.assertIn("/api/ghost/diagnostics", settings)

    def test_frontend_has_one_vue_root_and_no_legacy_dom_mount_chain(self):
        legacy_paths = (
            "js/vue/game-bridge.js",
            "js/vue/game-host.js",
            "js/ghost/ui/dom.js",
            "js/ghost/ui/character-render.js",
            "js/ghost/modules/character.js",
            "js/ghost/modules/details.js",
            "js/ghost/modules/helper.js",
            "js/ghost/modules/npc.js",
            "js/ghost/modules/relationships.js",
        )
        for path in legacy_paths:
            self.assertFalse((ROOT / path).exists(), path)

        create_app_files = []
        for path in (ROOT / "js").rglob("*.js"):
            if path.name == "vue.esm-browser.prod.js":
                continue
            if "createApp(" in path.read_text(encoding="utf-8"):
                create_app_files.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(create_app_files, ["js/main.js"])

        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("css/app.css", index)
        self.assertNotIn("css/style.css", index)

    def test_every_base_location_has_a_valid_widescreen_scene(self):
        location_data = json.loads(
            (ROOT / "worlds/world_touhou/locations/location_base.json").read_text(encoding="utf-8-sig")
        )
        scene_source = (ROOT / "js/ghost/ui/scene-art.js").read_text(encoding="utf-8")
        for location in location_data["locations"]:
            self.assertIn(f"'{location['name']}'", scene_source, location["name"])

        asset_names = set(re.findall(r"/static/static/([^']+\.png)", scene_source))
        self.assertEqual(len(asset_names), len(location_data["locations"]))
        for asset_name in asset_names:
            asset_path = ROOT / "static" / asset_name
            self.assertTrue(asset_path.exists(), asset_name)
            header = asset_path.read_bytes()[:24]
            self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n", asset_name)
            self.assertEqual(struct.unpack(">II", header[16:24]), (1672, 941), asset_name)

    def test_theme_overrides_have_one_canonical_owner(self):
        app_css = (ROOT / "css/app.css").read_text(encoding="utf-8")
        game_css = (ROOT / "css/vue-game.css").read_text(encoding="utf-8")
        self.assertNotIn("唯美主题覆写层", app_css)
        self.assertEqual(game_css.count("东方异变录 · 统一主题层"), 1)
        self.assertGreater(game_css.find("东方异变录 · 统一主题层"), len(game_css) // 4)
        self.assertNotRegex(game_css, r"(?m)^\+")

    def test_accessibility_settings_and_local_tts_are_vue_owned(self):
        main = (ROOT / "js/main.js").read_text(encoding="utf-8")
        settings = (ROOT / "js/vue/settings-dialog.js").read_text(encoding="utf-8")
        game = (ROOT / "js/vue/game-screen.js").read_text(encoding="utf-8")
        accessibility = (ROOT / "js/vue/accessibility.js").read_text(encoding="utf-8")
        self.assertIn("applyAccessibilitySettings", main)
        self.assertIn('type="range"', settings)
        self.assertIn("本地朗读", settings)
        self.assertIn("speechSynthesis", accessibility)
        self.assertIn("SpeechSynthesisUtterance", accessibility)
        self.assertIn("event.isComposing", game)
        self.assertIn("ctrl-enter", game)
        self.assertIn("highContrast", settings)
        self.assertIn("reduceMotion", settings)
        self.assertIn("ttsVoice", settings)
        self.assertNotIn('class="th-chat-scroll" aria-live=', game)
        self.assertIn('role="status" aria-live="polite"', game)

    def test_v8_player_and_producer_tools_are_vue_owned(self):
        producer = (ROOT / "js/vue/producer-console.js").read_text(encoding="utf-8")
        dialogs = (ROOT / "js/vue/game-dialogs.js").read_text(encoding="utf-8")
        game = (ROOT / "js/vue/game-screen.js").read_text(encoding="utf-8")
        for token in (
            "runProducerEvaluation", "restoreProducerContentBackup",
            "runMemoryMaintenance", "downloadDiagnostics", "producer-field-grid",
        ):
            self.assertIn(token, producer)
        self.assertIn("performInventoryAction", dialogs)
        self.assertIn("th-onboarding", game)


if __name__ == "__main__":
    unittest.main()
