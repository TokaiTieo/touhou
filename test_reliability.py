import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import world_manager as storage
from backend.services.turn_models import TurnContext, TurnInput
from backend.services.turn_orchestrator import TurnOrchestrator


class AtomicHistoryTests(unittest.TestCase):
    def test_atomic_history_receipt_and_state_survive_interrupted_commit(self):
        with tempfile.TemporaryDirectory() as root, patch.object(storage, "get_characters_dir", return_value=Path(root)):
            character = storage.ensure_character_fields({"character_id": "test", "profile": {"name": "测试"}})
            storage.save_turn_bundle("test", character, storage.get_default_tasks())
            turn = TurnInput(kind="environment", character_id="test", scene="博丽神社", player_name="测试",
                             action_text="休息", turn_id="atomic", record_history=True)
            orchestrator = TurnOrchestrator()
            context = orchestrator.begin(turn)
            original = storage._atomic_json_write
            def crash(path, value):
                if path.name == "test_tasks.json":
                    raise OSError("simulated power loss")
                original(path, value)
            result = {"description": "风吹过石阶。", "contract_valid": True, "time_cost": 15}
            with patch.object(storage, "_atomic_json_write", side_effect=crash), self.assertRaises(OSError):
                orchestrator.settle(context, result)
            restored = storage.load_character("test")
            messages = restored["conversation_history"]
            self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
            self.assertEqual(messages[-1]["content"], result["description"])
            replay = orchestrator.settle(orchestrator.begin(turn), copy.deepcopy(result))
            self.assertTrue(replay.duplicate)
            self.assertEqual(replay.result["conversation"]["assistant"]["message_id"], messages[-1]["message_id"])
            self.assertEqual(len(storage.load_character("test")["conversation_history"]), 2)

    def test_legacy_turn_does_not_duplicate_client_managed_history(self):
        from backend.services.turn_history_service import append_turn_history
        context = TurnContext(turn=TurnInput(kind="environment", character_id="test", scene="神社", player_name="测试"),
                              character={"conversation_history": [{"content": "旧消息"}]}, tasks={})
        append_turn_history(context, {"description": "回复"})
        self.assertEqual(len(context.character["conversation_history"]), 1)


class CoordinatorLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_confirms_a_generating_turn_has_stopped(self):
        from backend.services.turn_coordinator import TurnCoordinator
        coordinator = TurnCoordinator()
        started = asyncio.Event()
        async def operation():
            coordinator.set_state('test', 'cancel', 'generating')
            started.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(coordinator.execute(character_id='test', turn_id='cancel', kind='environment', operation=operation))
        await started.wait()
        self.assertTrue(await coordinator.cancel('test', 'cancel'))
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(coordinator.get_status('test', 'cancel').state, 'cancelled')

    async def test_cancel_does_not_interrupt_durable_settlement(self):
        from backend.services.turn_coordinator import TurnCoordinator
        coordinator = TurnCoordinator()
        started, release = asyncio.Event(), asyncio.Event()
        async def operation():
            coordinator.set_state('test', 'commit', 'checkpoint_cleanup')
            started.set()
            await release.wait()
            return {'ok': True}
        task = asyncio.create_task(coordinator.execute(character_id='test', turn_id='commit', kind='environment', operation=operation))
        await started.wait()
        self.assertFalse(await coordinator.cancel('test', 'commit'))
        release.set()
        self.assertEqual(await task, {'ok': True})
        self.assertEqual(coordinator.get_status('test', 'commit').state, 'committed')

    async def test_all_active_phases_survive_pruning(self):
        from backend.services.turn_coordinator import TurnCoordinator, TurnStatus
        coordinator = TurnCoordinator()
        phases = ['queued', 'running', 'preparing', 'generating', 'settling', 'checkpoint_cleanup', 'cancelling']
        for phase in phases:
            coordinator._statuses[('test', phase)] = TurnStatus('test', phase, 'environment', state=phase, updated_at=1)
        for index in range(310):
            coordinator._statuses[('test', str(index))] = TurnStatus('test', str(index), 'environment', state='committed', updated_at=index + 2)
        coordinator._prune_statuses()
        self.assertEqual(len(coordinator._statuses), 300)
        self.assertTrue(all(coordinator.get_status('test', phase) for phase in phases))
        async def operation():
            return {'ok': True}
        await coordinator.execute(character_id='lock-test', turn_id='one', kind='command', operation=operation)
        await asyncio.sleep(0)
        self.assertEqual(coordinator._character_locks, {})


class ArchiveHealthTests(unittest.TestCase):
    def test_invalid_snapshot_metadata_does_not_abort_health_check(self):
        from backend.services.snapshot_service import inspect_snapshots, list_snapshots
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            for name, payload in [('array', []), ('null', None), ('badmeta', {'metadata': 3}), ('broken', None)]:
                (directory / (name + '.json')).write_text('{broken' if name == 'broken' else json.dumps(payload))
            self.assertEqual(list_snapshots(directory), [])
            reports = inspect_snapshots(directory, directory)
            self.assertEqual(len(reports), 4)
            self.assertTrue(all(not item['recoverable'] for item in reports))

    def test_health_counts_and_checks_every_chunk_and_selects_usable_snapshot(self):
        from backend.services.save_health_service import inspect_character_file
        with tempfile.TemporaryDirectory() as root, patch.object(storage, "get_characters_dir", return_value=Path(root)):
            value = storage.ensure_character_fields({"character_id": "health", "profile": {"name": "早期完整记录"}})
            storage.save_character("health", value)
            value["profile"]["name"] = "后期记录"
            value["conversation_history"] = [{"message_id": str(i), "content": "记录"} for i in range(500)]
            storage.save_character("health", value)
            path = Path(root) / "health.json"
            self.assertEqual(inspect_character_file(path)["history_count"], 500)
            payload = json.loads(path.read_text(encoding="utf-8"))
            chunk = Path(root) / "_history" / (payload["conversation_archive"]["chunks"][0]["id"] + ".json")
            original = chunk.read_bytes()
            chunk.write_text('[]', encoding='utf-8')
            self.assertEqual(inspect_character_file(path)["status"], "critical")
            chunk.write_bytes(original)
            self.assertEqual(inspect_character_file(path)["status"], "healthy")
            chunk.unlink()
            report = inspect_character_file(path)
            self.assertEqual(report["status"], "critical")
            self.assertTrue(report["archive"]["errors"])
            self.assertFalse(storage.inspect_character_snapshots("health")[0]["recoverable"])
            path.write_text('{broken', encoding='utf-8')
            restored = storage.load_character("health")
            self.assertEqual(restored["profile"]["name"], "早期完整记录")
            self.assertTrue(list((Path(root) / '_recovery').glob('*.json')))


class HistoryIndexTests(unittest.TestCase):
    def test_busy_cache_is_not_deleted(self):
        import sqlite3
        from backend.services.history_index_service import indexed_history_page
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / '_history_search_v1.sqlite3'
            path.write_bytes(b'keep this derived cache while another reader uses it')
            with patch('backend.services.history_index_service.sqlite3.connect', side_effect=sqlite3.OperationalError('database is locked')):
                with self.assertRaises(sqlite3.OperationalError):
                    indexed_history_page({}, root, None, 30, '')
            self.assertTrue(path.exists())

    def test_index_is_incremental_rebuildable_and_branch_scoped(self):
        from backend.services import conversation_archive_service as archive
        with tempfile.TemporaryDirectory() as root:
            value = {'conversation_history': [{'message_id': str(i), 'speaker': '旁白', 'content': f'第{i}次关于绯色御守的约定'} for i in range(1100)]}
            archive.compact_history(value, root)
            expected = archive._scan_history_page(value, limit=30, query='御守', root=root)
            self.assertEqual(archive.history_page(value, limit=30, query='御守', root=root)['messages'], expected['messages'])
            with patch.object(archive, '_read', wraps=archive._read) as read:
                page = archive.history_page(value, before_id='200', limit=30, query='绯色御守', root=root)
                self.assertEqual(page['indices'], list(range(170, 200)))
                read.assert_not_called()
            branch = copy.deepcopy(value)
            branch['conversation_archive']['chunks'] = branch['conversation_archive']['chunks'][:1]
            branch['conversation_history'] = []
            self.assertEqual(archive.history_page(branch, root=root)['total'], 200)
            self.assertNotIn('1099', [item['message_id'] for item in archive.history_page(branch, root=root)['messages']])
            (Path(root) / '_history_search_v1.sqlite3').write_bytes(b'broken derived index')
            self.assertEqual(archive.history_page(value, before_id='200', limit=30, root=root)['indices'], list(range(170, 200)))
            chunk = value['conversation_archive']['chunks'][0]['id']
            (Path(root) / '_history' / (chunk + '.json')).unlink()
            with self.assertRaises(ValueError):
                archive.history_page(value, query='御守', root=root)

    def test_memory_features_are_cached_without_mutable_shared_results(self):
        from backend.services.memory_retrieval import local_embedding, _embedding_features
        _embedding_features.cache_clear()
        first = local_embedding('绯色御守的约定')
        expected = dict(first)
        first.clear()
        self.assertEqual(local_embedding('绯色御守的约定'), expected)
        self.assertEqual(_embedding_features.cache_info().hits, 1)


class PlayQualityTests(unittest.TestCase):
    def test_facts_secrets_and_repetition_have_labeled_expected_results(self):
        from backend.services.play_quality_service import evaluate_play_quality
        cases = [
            ('return_promise', '灵梦点点头：约定没有改变，我们仍会共同修复结界。接下来可以先歇一会儿，再决定从何处调查。', True),
            ('return_promise', '灵梦只是望着天空，完全没有回应你之前提过的事情。你站在台阶上等了一会儿，神社里十分安静。', False),
            ('marisa_secret_probe', '魔理沙告诉你，她知道帕秋莉私下说过的琥珀之匣，也知道你们谈话的每一个细节。', False),
            ('marisa_secret_probe', '魔理沙摆弄着扫帚，说起店里刚到的材料。她没有听说你提到的其他事情，反问你最近在哪里旅行。', True),
            ('relationship_followup', '爱丽丝说你们已经是恋人，因此你必须接受这段关系。她不愿再听你关于普通朋友的解释。', False),
        ]
        for case, prose, expected in cases:
            with self.subTest(case=case, expected=expected):
                self.assertEqual(evaluate_play_quality(prose, case)['passed'], expected)
        prose = cases[0][1]
        self.assertFalse(evaluate_play_quality(prose, 'return_promise', [prose])['passed'])

    def test_manual_review_does_not_overwrite_automatic_grade(self):
        from backend.services.play_quality_service import apply_manual_reviews
        report = {'results': [{'id': 'one', 'passed': False, 'evaluation': {'score': 60}}]}
        apply_manual_reviews(report, [{'id': 'one', 'scores': {'persona': 4}, 'note': '口吻自然，但承诺遗漏'}])
        self.assertFalse(report['results'][0]['passed'])
        self.assertEqual(report['results'][0]['manual_review']['scores']['persona'], 4)
        with self.assertRaises(ValueError):
            apply_manual_reviews(report, [{'id': 'one', 'scores': {'persona': 6}}])
