"""Recovery control and real checkpoint persistence, with all game I/O stubbed."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import tasks.divergent_universe.divergent_universe as du
import tasks.divergent_universe.progress as progress
from dev_tools.du_recovery_probe import check_recovery_probe, probe_path, RecoveryProbeError
from tasks.currency_wars.operator import Box


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'evidence' / 'du-recovery-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix='local-check-', dir=base))
        self.patches = [patch.object(progress, 'ROOT', self.folder),
                        patch.object(du, 'FileLock', lambda *a, **k: nullcontext()),
                        patch.object(du, 'STATE_DIR', self.folder),
                        patch.object(du, 'save_error_log', lambda **k: None)]
        for p in self.patches:
            p.start()
        self.checkpoint = progress.Progress('fixture')
        active = self.checkpoint.begin('full', 'periodic')
        active.update(node=5, node_total=13, station='事件', node_done=False)
        self.original = active['id']
        self.checkpoint.save('navigating')

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def task(self, runs=1, retries=3):
        t = object.__new__(du.DivergentUniverse)
        t.config = SimpleNamespace(Emulator_GameLanguage='cn', DivergentUniverse_Runs=runs,
                                   DivergentUniverse_RecoveryRetries=retries, config_name='fixture',
                                   DivergentUniverse_Mode='full', DivergentUniverse_Calculation='periodic',
                                   DivergentUniverse_ClaimRewards=False, Error_SaveError=False,
                                   task='DivergentUniverse', stop_event=threading.Event(),
                                   load=lambda: None, bind=lambda *a: None)
        t.device = SimpleNamespace()
        t.progress = progress.Progress('fixture')
        t.active = t.progress.data['active']
        def initialize():
            t.active = t.progress.data.get('active')
            t._run_deadline = time.monotonic() + 7200
            t.op = SimpleNamespace(deadline=t._run_deadline)
            t.apply_recovery_deadline()
        t._initialize = initialize
        initialize()
        t.go_to_lobby = lambda: True
        t.world_visible = lambda: False
        t.logins = []
        def login(restart=False):
            on_disk = json.loads(t.progress.path.read_text('utf-8'))
            assert on_disk['recovery']['attempts'] == len(t.logins) + 1
            t.logins.append(on_disk['recovery'].copy())
        t.login_from_current = login
        return t

    def test_first_fault_resumes_and_retains_original(self):
        t = self.task()
        attempts = []
        def play():
            attempts.append(t.active['id'])
            if len(attempts) == 1:
                raise RuntimeError('navigation stuck')
            self.assertFalse(t.active.get('stop_requested'))
            t.active['settlement_observed'] = True
            return 'win'
        t.play_run = play
        t.run()
        self.assertEqual(attempts, [self.original, self.original])
        self.assertEqual(len(t.logins), 1)
        self.assertEqual(t.progress.data['history'][-1]['result'], 'win')
        self.assertNotIn('recovery', t.progress.data)

    def test_same_room_more_battles_abandons_then_really_starts_new_run(self):
        t = self.task(runs=2)
        calls = []
        def play():
            calls.append(t.active['id'])
            if len(calls) <= 2:
                t.active['battles'] += 1
                t.active['selections'] += 3
                raise RuntimeError('same room remains stuck')
            if len(calls) == 3:
                self.assertTrue(t.active['stop_requested'])
                self.assertEqual(t.active['id'], self.original)
                self.assertFalse(t.active.get('settlement_observed'))
                self.assertEqual(t.progress.data['history'], [])
                t.active['settlement_observed'] = True
                return 'interrupted'
            self.assertNotEqual(t.active['id'], self.original)
            self.assertNotIn('recovery', t.progress.data)
            t.active['settlement_observed'] = True
            return 'win'
        t.play_run = play
        t.run()
        self.assertEqual([x['action'] for x in t.logins], ['resume', 'settle'])
        self.assertEqual([x['result'] for x in t.progress.data['history']], ['interrupted', 'win'])

    def test_failed_settlement_stops_after_total_restart_budget(self):
        t = self.task()
        t.play_run = lambda: (_ for _ in ()).throw(RuntimeError('exit never confirmed'))
        with self.assertRaises(du.RequestHumanTakeover):
            t.run()
        self.assertEqual(len(t.logins), 3)
        self.assertEqual(t.progress.data['active']['id'], self.original)
        self.assertEqual(t.progress.data['history'], [])
        self.assertFalse(t.active.get('settlement_observed'))
        self.assertEqual(t.progress.data['recovery']['action'], 'settle')

    def test_failed_login_consumes_budget_without_sending_settlement(self):
        t = self.task()
        t.play_run = lambda: (_ for _ in ()).throw(RuntimeError('offline'))
        attempts = []
        def offline(restart):
            attempts.append(True)
            raise ConnectionError('network unavailable')
        t.login_from_current = offline
        with self.assertRaises(du.RequestHumanTakeover):
            t.run()
        self.assertEqual(len(attempts), 3)
        self.assertEqual(t.progress.data['recovery']['attempts'], 3)
        self.assertFalse(t.active.get('stop_requested'))

    def test_reload_does_not_reset_attempts_or_settlement_deadline(self):
        t = self.task()
        first = t.prepare_recovery()
        first['attempts'] = 1
        t.progress.save('error')
        loaded = self.task()
        second = loaded.prepare_recovery()
        self.assertEqual(second['attempts'], 1)
        self.assertEqual(second['action'], 'settle')
        deadline = second['deadline']
        loaded.progress.save('error')
        reloaded = self.task()
        self.assertEqual(reloaded.prepare_recovery()['deadline'], deadline)
        self.assertEqual(reloaded.progress.data['recovery']['faults'], 3)

    def test_expired_stage_is_bounded_and_next_room_restores_budget(self):
        t = self.task()
        recovery = t.prepare_recovery()
        recovery.update(action='settle', deadline=time.time() - 1)
        t.progress.save('error')
        t.apply_recovery_deadline()
        self.assertLessEqual(t.op.deadline, time.monotonic())
        with self.assertRaises(du.RequestHumanTakeover):
            t.recover_checkpoint(RuntimeError('expired'))
        self.assertEqual(t.logins, [])
        recovery['action'] = 'resume'
        t.op.read_region = lambda *a, **k: [Box(30, 0, 300, 30, '(6/13) 第三位面-休整', 1)]
        t.update_station_header()
        self.assertNotIn('recovery', t.progress.data)
        self.assertGreater(t.op.deadline, time.monotonic())

    def test_user_stop_and_disabled_recovery_never_restart(self):
        for stopped in [False, True]:
            t = self.task(retries=3 if stopped else 0)
            t.prepare_recovery()
            if stopped:
                t.config.stop_event.set()
            with self.assertRaises(du.TaskEnd if stopped else du.RequestHumanTakeover):
                t.recover_checkpoint(RuntimeError('fault'))
            self.assertEqual(t.logins, [])
            self.assertEqual(t.progress.data['history'], [])

    def test_no_confirmed_settlement_no_finished_or_replacement_run(self):
        t = self.task()
        t.active['stop_requested'] = True
        with self.assertRaises(RuntimeError):
            t.progress.finish('interrupted')
        t.op.text = lambda *a, **k: Box(900, 630, 200, 30, '启动差分宇宙', 1)
        with self.assertRaises(du.RequestHumanTakeover):
            t.start_or_resume()
        self.assertEqual(t.progress.data['active']['id'], self.original)
        self.assertEqual(t.progress.data['history'], [])

    def test_opt_in_probe_exact_identity_expiry_and_consumption(self):
        t = self.task()
        allowed = self.folder / 'state/divergent_universe/validation'
        allowed.mkdir(parents=True)
        self.assertIsNone(probe_path(self.folder, '', 'fixture'))
        with self.assertRaises(ValueError):
            probe_path(self.folder, str(self.folder), 'fixture')
        t._recovery_probe_path = probe_path(self.folder, str(allowed), 'fixture')
        request = dict(profile='fixture', run_id=self.original, node=5, remaining=2,
                       expires_at=time.time() + 600, label='unit-only')
        for key, value in [('profile', 'other'), ('run_id', 'other'), ('node', 6), ('expires_at', 0)]:
            t._recovery_probe_path.write_text(json.dumps(dict(request, **{key: value})), 'utf-8')
            check_recovery_probe(t)
        t._recovery_probe_path.write_text(json.dumps(request), 'utf-8')
        for left in [1, 0]:
            with self.assertRaises(RecoveryProbeError):
                check_recovery_probe(t)
            self.assertEqual(json.loads(t._recovery_probe_path.read_text('utf-8'))['remaining'], left)
        check_recovery_probe(t)


if __name__ == '__main__':
    unittest.main()
