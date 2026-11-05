import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.api import app
from backend.security import SESSION_TOKEN, TOKEN_HEADER


class AgentPersistenceTests(unittest.TestCase):
    def test_export_import_and_snapshot_branch_preserve_mode_events_and_private_fields(self):
        from backend import world_manager as wm
        with tempfile.TemporaryDirectory() as directory, patch.object(wm, 'get_characters_dir', return_value=Path(directory)), \
                patch('backend.routes.records.get_characters_dir', return_value=Path(directory)), TestClient(app) as client:
            headers = {TOKEN_HEADER: SESSION_TOKEN}
            created = client.post('/api/ghost/create_character', headers=headers, json={'profile': {'name': '协作存储测试', 'age': 25}})
            self.assertEqual(created.status_code, 200, created.text)
            identity = created.json()['character_id']
            response = client.post('/api/ghost/agent_mode', headers=headers, json={'character_id': identity, 'mode': 'collaborative'})
            self.assertEqual(response.status_code, 200, response.text)
            owner = wm.load_character(identity)
            owner['agent_state']['events'].append({'id': 'pending-event', 'kind': 'invite', 'status': 'pending',
                'actor_id': 'npc_reimu', 'target_id': '@player', 'hour': 50, 'scene': '博丽神社'})
            owner['profile']['body_data'] = {'unchanged': True}
            wm.save_character(identity, owner)
            snapshot = wm.create_character_snapshot(identity, owner, force=True)
            exported = client.get('/api/ghost/export_character/' + identity, headers=headers)
            self.assertEqual(exported.status_code, 200, exported.text)
            original = copy.deepcopy(exported.json()['agent_state'])
            imported = client.post('/api/ghost/import_character', headers=headers, json={'character_data': exported.json()})
            self.assertEqual(imported.status_code, 200, imported.text)
            imported_owner = wm.load_character(imported.json()['character_id'])
            self.assertNotEqual(imported_owner['character_id'], identity)
            self.assertEqual(imported_owner['agent_state'], original)
            self.assertEqual(imported_owner['profile']['body_data'], {'unchanged': True})
            restored = client.post('/api/ghost/snapshots/restore', headers=headers,
                json={'character_id': identity, 'snapshot_id': snapshot['snapshot_id'], 'branch': True})
            self.assertEqual(restored.status_code, 200, restored.text)
            branch = wm.load_character(restored.json()['character_id'])
            self.assertEqual(branch['agent_state']['mode'], 'collaborative')
            self.assertEqual(branch['agent_state']['events'], original['events'])
            self.assertNotEqual(branch['timeline_epoch'], owner.get('timeline_epoch', ''))


if __name__ == '__main__':
    unittest.main()
