import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from manager import upgrade
from integration import writer_runner as writer


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.health = {'service': 'novel-helper-manager', 'pid': 1234, 'startup_id': 'old',
                       'root': str(self.root), 'mode': 'dsh_managed', 'upgrade_guard':1}
        writer.atomic_json(self.root / 'integration_data/run-description.json',
                           {**self.health, 'owner': 'plugin'})

    def responses(self, operations):
        return [io.BytesIO(json.dumps(self.health).encode()),
                io.BytesIO(json.dumps({'operations': operations}).encode()),
                io.BytesIO(json.dumps(self.health).encode()), URLError('stopped')]

    def test_idle_owned_process_stops_and_maintenance_is_restored(self):
        with patch.object(upgrade, 'command_matches', return_value=True), \
                patch.object(upgrade, '_stop') as stop, \
                patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.responses([])
            self.assertTrue(upgrade.stop_idle(self.root, 18765, 1234, 'old')['stopped'])
            stop.assert_called_once_with(1234)
        self.assertFalse((self.root / 'integration_data/maintenance.json').exists())

    def test_active_task_or_unverified_command_is_preserved(self):
        for owned, operations in ((True, [{'status': 'running'}]), (False, [])):
            with patch.object(upgrade, 'command_matches', return_value=owned), \
                    patch.object(upgrade, '_stop') as stop, \
                    patch('urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = self.responses(operations)
                self.assertFalse(upgrade.stop_idle(self.root, 18765, 1234, 'old')['stopped'])
                stop.assert_not_called()

    def test_previous_coordinator_is_marked_for_restart(self):
        writer.atomic_json(self.root / 'integration_data/serial_service/heartbeat.json',
                           {'pid':4321,'active_job':None})
        with patch.object(upgrade, 'command_matches', return_value=True), \
                patch.object(upgrade, '_stop') as stop, patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.responses([])
            self.assertTrue(upgrade.stop_idle(self.root,18765,1234,'old')['restart_serial'])
            self.assertEqual([c.args[0] for c in stop.call_args_list], [4321,1234])

    def test_dead_coordinator_heartbeat_does_not_block_upgrade(self):
        writer.atomic_json(self.root / 'integration_data/serial_service/heartbeat.json',
                           {'pid':4321,'active_job':'stale-job'})
        with patch.object(upgrade, 'command_matches', side_effect=lambda pid, entry:pid==1234), \
                patch.object(upgrade, '_stop') as stop, patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.responses([])
            self.assertTrue(upgrade.stop_idle(self.root,18765,1234,'old')['stopped'])
            stop.assert_called_once_with(1234)

    def test_legacy_instance_requires_explicit_stop(self):
        self.health.pop('upgrade_guard')
        with patch.object(upgrade, 'command_matches', return_value=True), \
                patch.object(upgrade, '_stop') as stop, patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.responses([])
            self.assertFalse(upgrade.stop_idle(self.root,18765,1234,'old')['stopped'])
            stop.assert_not_called()

    def test_aborted_upgrade_restores_stopped_coordinator(self):
        writer.atomic_json(self.root / 'integration_data/serial_service/heartbeat.json',
                           {'pid':4321,'active_job':None})
        changed = {**self.health,'startup_id':'replacement'}
        responses=self.responses([])
        responses[2]=io.BytesIO(json.dumps(changed).encode())
        with patch.object(upgrade, 'command_matches', return_value=True), \
                patch.object(upgrade, '_stop'), patch('urllib.request.build_opener') as opener, \
                patch.object(upgrade.subprocess, 'run') as restart:
            opener.return_value.open.side_effect = responses
            self.assertFalse(upgrade.stop_idle(self.root,18765,1234,'old')['stopped'])
            restart.assert_called_once()
        self.assertFalse((self.root/'integration_data/upgrade-resume.json').exists())

    def test_admission_contention_returns_immediately(self):
        from manager import app
        import time
        ops=app.Operations.__new__(app.Operations)
        with patch.object(app,'DATA',self.root/'integration_data'):
            with writer.file_lock(app.DATA/'upgrade-admission.lock'):
                started=time.monotonic()
                with self.assertRaises(app.HTTPException) as caught:
                    ops.start('daily',[], 'fixture')
                self.assertEqual(caught.exception.status_code,409)
                self.assertLess(time.monotonic()-started,1)
