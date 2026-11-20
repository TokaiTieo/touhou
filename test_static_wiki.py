import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from backend.services import agent_scheduler, turn_workflow, wiki_store
from backend.services.agent_context_service import EvidenceContext, HOST
from backend.services.agent_contracts import Reader
from backend.services.npc_agent_runtime import AgentDecisionError, NPCRuntime
from backend.services.turn_models import TurnContext
from backend.services.wiki_compiler import compile_world, load, markdown, validate_draft
from backend.services.wiki_contracts import FILES, checksum
from backend.services.wiki_store import Store, freeze, write_json
from test_agent_boundaries import character, records, turn


class WikiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.world = self.root / "world"
        source = Path(__file__).parent / "worlds/world_touhou"
        for file, _, _ in FILES.values():
            dest = self.world / file
            dest.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(source / file, dest)
        self.store = Store(self.world, self.root / "wiki")
        self.draft = compile_world(self.world)
        self.edition = self.store.publish(self.draft, checksum(self.draft), "fixture reviewer")
        self.path = self.root / "checkpoints.db"
        self.book = load(self.world / "world_info.json")["entries"]
        self.patch = patch.object(wiki_store, "configured_store", return_value=self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def pin(self, scope="s"):
        return freeze(NPCRuntime(scope, path=self.path).ledger)

    def second_edition(self):
        draft = copy.deepcopy(self.draft)
        draft["pages"]["npc_sanae"]["claims"].pop()
        return self.store.publish(draft, checksum(draft), "fixture reviewer")

    def view(self, snapshot, who=HOST):
        people = records()
        return EvidenceContext(Reader(save_id="s", epoch="one", npc_id=who, task_id="t"),
                               character(), {}, "人间之里", records=people, world_entries=self.book, wiki=snapshot)

    def test_extraction_citations_and_private_fields(self):
        path = self.world / FILES["npc"][0]
        data = load(path)
        data["npcs"][0]["profile"]["secret_fixture"] = "NOT_FOR_COMPILATION"
        write_json(path, data)
        compiled = compile_world(self.world)
        self.assertEqual(checksum(compiled), self.edition)
        self.assertNotIn("NOT_FOR_COMPILATION", json.dumps(compiled))
        self.assertEqual(len(compiled["pages"]), 12)
        self.assertEqual({p["type"] for p in compiled["pages"].values()}, {"person", "place", "faction", "rule"})
        for key, page in compiled["pages"].items():
            for fact in page["claims"]:
                self.assertTrue(fact["refs"])
                for ref in fact["refs"]:
                    src = compiled["sources"][ref]
                    self.assertEqual(checksum(src["value"]), src["hash"])
                    self.assertIn(src["selector"], markdown(compiled, key))

    def test_unreviewed_forged_or_interrupted_publish_does_not_replace_head(self):
        for mutation in ("refs", "readers", "links", "title", "text"):
            bad = copy.deepcopy(self.draft)
            page = bad["pages"]["npc_sanae"]
            if mutation in page:
                page[mutation] = "forged"
            else:
                page["claims"][0][mutation] = "forged"
            with self.assertRaises(ValueError):
                self.store.publish(bad, checksum(bad), "fixture")
        with self.assertRaises(ValueError):
            self.store.publish(self.draft, "wrong-review", "fixture")
        with patch.object(wiki_store, "markdown", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.second_edition()
        self.assertEqual(self.store.read()[0], self.edition)

    def test_acl_title_link_snippet_source_dedup_and_budgets(self):
        snap = self.pin()
        query = "守矢成员和早苗、红魔馆成员与符卡决斗"
        rows = self.view(snap, "test_0").search_world_info(query)
        for row in rows:
            self.assertNotIn(row["id"], ("wi_faction_moriya", "wi_faction_scarlet"))
            if row["kind"] == "wiki":
                self.assertNotIn(row["title"], ("东风谷早苗", "红魔馆成员", "守矢成员"))
                self.assertEqual(row["links"], [])
        assembled = self.view(snap).assemble(query)
        self.assertTrue(any(r["kind"] == "wiki" for r in assembled["world_info"]))
        refs = {ref.split(":")[1] for row in assembled["world_info"] for ref in row.get("refs", [])}
        self.assertFalse(refs & {r["id"] for r in assembled["world_info"]})
        size = lambda row: len(json.dumps(row, ensure_ascii=False))
        self.assertLessEqual(sum(map(size, assembled["world_info"])), 1800)
        self.assertLessEqual(sum(size(r) for section in assembled.values() for r in section), 15000)

    def test_restart_pins_version_but_source_withdrawal_overrides_all_versions(self):
        a = self.pin()
        new = self.second_edition()
        self.assertNotEqual(a.version, new)
        self.assertEqual(self.pin().version, a.version)
        self.assertEqual(self.pin("other").version, new)
        self.store.withdraw_source("book:wi_faction_moriya:content")
        with self.assertRaises(ValueError):
            self.view(a).search_world_info("守矢成员")
        fallback = self.pin()
        self.assertFalse(fallback.bundle)
        rows = self.view(fallback).search_world_info("守矢成员和符卡")
        self.assertNotIn("wi_faction_moriya", [r["id"] for r in rows])
        self.assertIn("wi_spellcard_rules", [r["id"] for r in rows])
        with self.assertRaises(ValueError):
            self.store.publish(self.draft, self.edition, "fixture")

    def test_changed_source_or_acl_invalidates_cached_views(self):
        path = self.world / FILES["npc"][0]
        original = load(path)
        for i, mutate in enumerate((lambda row: row["profile"].update(identity="新设定"),
                                    lambda row: row.update(visibility={"scope": "private"}))):
            write_json(path, original)
            snap = self.pin(str(i))
            data = copy.deepcopy(original)
            mutate(next(n for n in data["npcs"] if n["id"] == "npc_sanae"))
            write_json(path, data)
            with self.assertRaises(ValueError):
                snap.check()
            self.assertEqual(self.store.reviewed_copy()[0], self.edition)
            self.assertIsNone(self.pin(str(i)))

    def test_location_conflict_blocks_new_publication(self):
        path = self.world / FILES["npc"][0]
        data = load(path)
        next(n for n in data["npcs"] if n["id"] == "npc_sanae")["location_id"] = "loc_hakurei"
        write_json(path, data)
        draft = compile_world(self.world)
        self.assertTrue(draft["conflicts"])
        with self.assertRaises(ValueError):
            validate_draft(self.world, draft)

    def test_original_detail_and_denied_book_obey_reader_scope(self):
        snap = self.pin()
        args = {"query": "红魔馆成员", "source": "world_book"}
        self.assertIn("wi_faction_scarlet", {r["id"] for r in self.view(snap).query("search_world_info", args)})
        self.assertNotIn("wi_faction_scarlet", {r["id"] for r in self.view(snap, "test_0").query("search_world_info", args)})
        view = self.view(snap)
        for entry in view._world:
            if entry["id"] == "wi_faction_scarlet":
                entry["visibility"] = {"scope": "private", "audience": []}
        self.assertNotIn("wiki:scarlet:0", {r["id"] for r in view.search_world_info("红魔馆成员")})

    def test_export_contains_only_current_approved_json_and_reading_pages(self):
        from backend.services.wiki_store import release_files
        new = self.second_edition()
        (self.store.packages / "draft.json").write_text("not for release")
        files = release_files(self.store)
        self.assertEqual(len(files), 14)
        self.assertEqual(json.loads(files["published.json"])["approved"], {new: "fixture reviewer"})
        self.assertEqual({k for k in files if not k.startswith("versions/" + new + "/")}, {"published.json"})
        self.assertTrue(all("not for release" not in data for data in files.values()))

    def test_damaged_missing_and_disabled_fall_back(self):
        normal = self.view(None).search_world_info("符卡")
        with patch.object(wiki_store, "configured_store", return_value=None):
            self.assertIsNone(self.pin("absent"))
        self.assertIsNone(self.pin("absent"))
        (self.store.packages / "versions" / self.edition / "bundle.json").write_text("[]", encoding="utf-8")
        self.assertEqual(self.view(self.pin("corrupt")).search_world_info("符卡"), normal)
        (self.store.packages / "published.json").unlink()
        self.assertIsNone(self.pin("missing"))

    async def test_zero_one_six_and_isolation_in_actual_requests(self):
        people = records(6)
        for enabled in (False, True):
            for count in (0, 1, 6):
                calls = []

                async def generate(prompt, temperature):
                    calls.append(prompt)
                    if "独立的人物" in prompt:
                        self.assertNotIn("wiki:scarlet:", prompt)
                        return '{"commands":[{"kind":"wait"}]}'
                    return '{"description":"测试。","cited_event_ids":[]}'

                action = ("向" + "、".join(r["name"] for r in list(people.values())[:count]) + "问符卡和红魔馆成员"
                          if count else "独自研究符卡")
                ctx = TurnContext(turn=turn(action), character=character(), tasks={})
                rt = NPCRuntime(f"{enabled}-{count}", path=self.path, generate=generate, checkpoint=False)
                with patch.object(wiki_store, "configured_store", return_value=self.store if enabled else None):
                    result, _ = await agent_scheduler.run_agent_turn(ctx, runtime=rt, records=people, present_ids=list(people),
                                                                     world_entries=self.book, persist=False)
                self.assertEqual(len(calls), count + 1)
                self.assertEqual(len(result["agent_turn"]["participants"]), count)
                self.assertEqual(any("wiki:spellcard:" in p for p in calls), enabled)

    async def test_resume_frozen_candidate_then_revoke_during_host(self):
        people, calls = records(), []
        ctx = TurnContext(turn=turn("向甲问符卡"), character=character(), tasks={})
        original = copy.deepcopy(ctx.character)

        async def generate(prompt, temperature):
            npc = "独立的人物" in prompt
            calls.append(("npc" if npc else "host", self.edition in prompt))
            if npc:
                return '{"commands":[{"kind":"wait"}]}'
            if len(calls) == 2:
                self.second_edition()
                raise RuntimeError("fixture interrupted")
            if len(calls) == 3:
                self.store.withdraw(self.edition)
            return '{"description":"测试。","cited_event_ids":[]}'

        async def run():
            return await agent_scheduler.run_agent_turn(ctx, runtime=NPCRuntime("recover", path=self.path, generate=generate),
                records=people, present_ids=list(people), world_entries=self.book, persist=False)

        with patch.object(turn_workflow, "CHECKPOINT_PATH", self.path):
            try:
                with self.assertRaises(AgentDecisionError):
                    await run()
                await turn_workflow.close_workflow_runtime(self.path)
                with self.assertRaises(AgentDecisionError):
                    await run()
                self.assertEqual(ctx.character, original)
                await run()
                self.assertEqual(calls, [("npc", True), ("host", True), ("host", True), ("npc", False), ("host", False)])
            finally:
                await turn_workflow.close_workflow_runtime(self.path)
