"""Bound the one environment attempt without deleting failed preparation proof."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from module.config.config import TaskEnd
from module.exception import RequestHumanTakeover
from tasks.divergent_universe import preparation_recovery as recovery


class PreparationEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.data = dict(active=None, phase='error', error=recovery.LOGIN_TIMEOUT, pid=123,
                         recovery=dict(run_id=None, node=None, action='resume', attempts=2,
                                       faults=2, deadline=100, run_deadline=2000), history=[{'id': 'real-win'}])
        shared = dict(pid=123, session='previous', run_id=None, node=None)
        self.events = [dict(shared, event='login_begin', time=10),
                       dict(shared, event='fault', time=20, error=recovery.LOGIN_TIMEOUT),
                       dict(shared, event='recovery_exhausted', time=30, attempts=2, action='resume')]

    def qualify(self, data=None, events=None):
        return recovery.qualifying_login_failure(self.data if data is None else data,
            self.events if events is None else events, now=200, retries=3)

    def test_current_login_exhaustion_is_required(self):
        self.assertEqual(self.qualify()['exhausted'], self.events[-1])
        cases = [dict(active={'id': 'unfinished'}), dict(phase='stopped'), dict(error='other fault'),
                 dict(pid=456), {recovery.MARKER: {'status': 'failed'}}]
        for changes in cases:
            data = copy.deepcopy(self.data); data.update(changes)
            self.assertIsNone(self.qualify(data))
        data = copy.deepcopy(self.data); data['recovery']['deadline'] = 999
        self.assertIsNone(self.qualify(data))

    def test_unrelated_old_event_or_missing_login_never_authorizes_restart(self):
        for changes in (dict(pid=456), dict(session='other'), dict(run_id='a-run'), dict(attempts=1)):
            events = copy.deepcopy(self.events); events[-1].update(changes)
            self.assertIsNone(self.qualify(events=events))
        self.assertIsNone(self.qualify(events=self.events[1:]))
        self.assertIsNone(self.qualify(events=self.events + [dict(event='phase', phase='stopped')]))

    def fixture(self, path):
        path.write_text('\n'.join(json.dumps(row) for row in self.events), encoding='utf-8')
        data = copy.deepcopy(self.data)
        saved, recorded = [], []
        def save(phase=None):
            if phase:
                data['phase'] = phase
            saved.append(copy.deepcopy(data))
        progress = NS(data=data, events_path=path, build='patched', save=save,
                      record=lambda event, **fields: recorded.append((event, fields)))
        config = NS(DivergentUniverse_Mode='star', DivergentUniverse_RecoveryRetries=3,
                    stop_event=NS(is_set=lambda: False), Emulator_Serial='127.0.0.1:16384',
                    EmulatorInfo_name='MuMuPlayer-12.0-0')
        return NS(active=None, config=config, progress=progress, device=object()), saved, recorded

    def test_marker_is_persisted_before_action_and_failure_does_not_refund_it(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3] / 'evidence') as tmp:
            main, saved, _ = self.fixture(Path(tmp) / 'events.jsonl')
            def fail(*args):
                self.assertEqual(saved[-1][recovery.MARKER]['status'], 'attempted')
                raise ConnectionError('native emulator start failed')
            with patch('tasks.divergent_universe.environment_recovery.restart_mumu_instance', side_effect=fail) as action:
                with self.assertRaises(RequestHumanTakeover):
                    recovery.retry_preparation_environment(main)
                self.assertFalse(recovery.retry_preparation_environment(main))
            self.assertEqual(action.call_count, 1)
            self.assertEqual(main.progress.data['recovery'], self.data['recovery'])
            self.assertEqual(main.progress.data['history'], self.data['history'])

    def test_user_stop_remains_stopped_with_consumed_marker(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3] / 'evidence') as tmp:
            main, _, _ = self.fixture(Path(tmp) / 'events.jsonl')
            with patch('tasks.divergent_universe.environment_recovery.restart_mumu_instance', side_effect=TaskEnd):
                with self.assertRaises(TaskEnd):
                    recovery.retry_preparation_environment(main)
            self.assertEqual(main.progress.data['phase'], 'stopped')
            self.assertEqual(main.progress.data[recovery.MARKER]['status'], 'stopped')
            self.assertEqual(main.progress.data['recovery']['attempts'], 2)

    def test_emulator_online_is_not_entry_verification(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3] / 'evidence') as tmp:
            main, _, _ = self.fixture(Path(tmp) / 'events.jsonl')
            with patch('tasks.divergent_universe.environment_recovery.restart_mumu_instance',
                       return_value={'before_boot_id': 'old', 'after_boot_id': 'new'}):
                self.assertTrue(recovery.retry_preparation_environment(main))
            marker = main.progress.data[recovery.MARKER]
            deadline = marker['deadline']
            recovery.finish_preparation_environment(main)
            self.assertEqual(marker['status'], 'emulator_restarted')
            self.assertEqual(recovery.preparation_environment_deadline(main.progress.data), deadline)
            main.progress.data['active'] = dict(id='actual-new-run', star={'members_verified': True})
            recovery.finish_preparation_environment(main)
            self.assertEqual(marker['status'], 'entry_verified')
            self.assertIsNone(recovery.preparation_environment_deadline(main.progress.data))
            self.assertEqual(main.progress.data['history'], self.data['history'])

    def test_expired_environment_deadline_does_not_turn_into_an_unbounded_window(self):
        self.data[recovery.MARKER] = dict(status='emulator_restarted', deadline=1)
        self.assertEqual(recovery.preparation_environment_deadline(self.data), 1)
        self.data['active'] = {'id': 'retained'}
        self.assertIsNone(recovery.preparation_environment_deadline(self.data))

    def test_stop_before_action_does_not_create_a_marker(self):
        main = NS(active=None, config=NS(DivergentUniverse_Mode='star',
                  stop_event=NS(is_set=lambda: True)), progress=NS(data=self.data))
        with self.assertRaises(TaskEnd):
            recovery.retry_preparation_environment(main)
        self.assertNotIn(recovery.MARKER, self.data)

    def test_preparation_login_and_menu_share_the_same_window(self):
        from tasks.divergent_universe.divergent_universe import DivergentUniverse
        main = NS(progress=NS(data=self.data), op=NS(deadline=1))
        with patch('tasks.divergent_universe.divergent_universe.time.monotonic', return_value=100):
            DivergentUniverse.apply_star_preparation_deadline(main)
        self.assertEqual(main.op.deadline, 460)
        with patch('tasks.divergent_universe.divergent_universe.time.monotonic', return_value=300):
            DivergentUniverse.apply_star_preparation_deadline(main)
        self.assertEqual(main.op.deadline, 460)
        self.assertEqual(self.data['recovery']['deadline'], 100)

    def test_preparation_window_never_extends_persisted_environment_deadline(self):
        from tasks.divergent_universe.divergent_universe import DivergentUniverse
        self.data[recovery.MARKER] = dict(status='emulator_restarted', deadline=1050)
        main = NS(progress=NS(data=self.data), op=NS())
        with patch('tasks.divergent_universe.divergent_universe.time.monotonic', return_value=100), \
                patch('tasks.divergent_universe.divergent_universe.time.time', return_value=1000):
            DivergentUniverse.apply_star_preparation_deadline(main)
        self.assertEqual(main.op.deadline, 150)
        with patch('tasks.divergent_universe.divergent_universe.time.monotonic', return_value=151), \
                patch('tasks.divergent_universe.divergent_universe.time.time', return_value=1051):
            DivergentUniverse.apply_star_preparation_deadline(main)
        self.assertLessEqual(main.op.deadline, 151)


if __name__ == '__main__':
    unittest.main()
