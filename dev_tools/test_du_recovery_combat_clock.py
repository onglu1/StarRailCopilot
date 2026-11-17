"""Recovery clock accounting with persisted state and no game I/O."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import tasks.divergent_universe.divergent_universe as du

BASE = 1700000000

class RecoveryCombatClockTests(unittest.TestCase):
    def setUp(self):
        self.wall=BASE+1000.0
        self.mono=100.0
        self.patches=[patch.object(du.time,'time',lambda:self.wall),
                      patch.object(du.time,'monotonic',lambda:self.mono),
                      patch('module.base.timer.time',lambda:self.wall)]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()

    def advance(self,seconds):
        self.wall+=seconds;self.mono+=seconds

    def task(self,data=None):
        task=object.__new__(du.DivergentUniverse)
        task.config=SimpleNamespace(DivergentUniverse_MaxMinutes=30,DivergentUniverse_RecoveryRetries=3,
                                    stop_event=None)
        if data is None:
            data={'active':dict(id='retained',node=3,mode='star',battles=2,
                                started=datetime.fromtimestamp(BASE+900).isoformat()),
                  'recovery':dict(run_id='retained',node=3,faults=1,attempts=1,
                                  action='resume',deadline=BASE+1060)}
        task.progress=SimpleNamespace(data=deepcopy(data),save=Mock(),record=Mock())
        task.active=task.progress.data['active']
        task.device=SimpleNamespace()
        task.op=SimpleNamespace(deadline=0)
        def check():
            if self.mono>task.op.deadline:raise TimeoutError('deadline')
        task.op.check=check
        task.is_combat_executing=Mock(return_value=True)
        task.world_visible=Mock(return_value=False)
        task.selection_kind=Mock(return_value=None)
        task.lobby_visible=Mock(return_value=False)
        task.settlement_title=Mock(return_value=None)
        task.appear=Mock(return_value=False)
        # The first fault occurs with 1700 seconds left in this worker's
        # original MaxMinutes allowance; persisted recovery freezes it.
        task._run_deadline=self.mono+1700
        task.apply_recovery_deadline()
        return task

    def test_live_combat_can_cross_stage_deadline_and_restores_exact_remaining(self):
        task=self.task();recovery=task.progress.data['recovery']
        with task.recovery_combat_window():
            self.assertEqual(recovery['combat_pause']['remaining'],60)
            self.advance(200)
            task.op.check()
            self.assertEqual((recovery['faults'],recovery['attempts']),(1,1))
        self.assertEqual(recovery['deadline'],BASE+1260)
        self.assertNotIn('combat_pause',recovery)
        self.assertEqual(recovery['run_deadline'],BASE+2700)
        self.assertNotIn('run_deadline_at',task.active)

    def test_reload_reuses_pause_and_fixed_whole_run_ceiling(self):
        task=self.task()
        with task.recovery_combat_window():
            saved=deepcopy(task.progress.data)
        self.advance(200)
        loaded=self.task(saved)
        self.assertEqual(loaded.progress.data['recovery']['run_deadline'],BASE+2700)
        with loaded.recovery_combat_window():
            self.assertEqual(loaded.progress.data['recovery']['combat_pause'],saved['recovery']['combat_pause'])
            self.advance(100)
        self.assertEqual(loaded.progress.data['recovery']['deadline'],BASE+1360)
        self.assertEqual(loaded.progress.data['recovery']['attempts'],1)

    def test_reload_known_reward_world_or_login_resumes_clock_but_animation_does_not(self):
        task=self.task()
        with task.recovery_combat_window():saved=deepcopy(task.progress.data)
        self.advance(100)
        for page in ('world','reward','login'):
            loaded=self.task(saved);loaded.is_combat_executing.return_value=False
            self.assertFalse(loaded.reconcile_recovery_combat_pause())
            self.assertIn('combat_pause',loaded.progress.data['recovery'])
            if page=='world':loaded.world_visible.return_value=True
            elif page=='reward':loaded.selection_kind.return_value='blessing'
            else:loaded.appear.return_value=True
            self.assertTrue(loaded.reconcile_recovery_combat_pause())
            self.assertEqual(loaded.progress.data['recovery']['deadline'],BASE+1160)
            self.assertEqual(loaded.progress.data['recovery']['faults'],1)

    def test_hard_run_limit_still_expires_in_combat_and_settlement_gets_short_window(self):
        task=self.task()
        with self.assertRaises(TimeoutError):
            with task.recovery_combat_window():
                self.advance(1800)
                task.op.check()
        self.assertEqual(task.progress.data['recovery']['run_deadline'],BASE+2700)
        recovery=task.prepare_recovery()
        self.assertEqual((recovery['faults'],recovery['attempts']),(2,1))
        self.assertEqual(recovery['action'],'settle')
        self.assertEqual(recovery['deadline'],self.wall+600)
        self.assertEqual(task.op.deadline,self.mono+600)

    def test_larger_maxminutes_never_extends_saved_run_budget(self):
        task=self.task();task.config.DivergentUniverse_MaxMinutes=120
        self.advance(10)
        task._run_deadline=self.mono+7200
        task.apply_recovery_deadline()
        with task.recovery_combat_window():
            self.assertEqual(task.progress.data['recovery']['run_deadline'],BASE+2700)
            self.assertEqual(task.op.deadline,self.mono+(BASE+2700-self.wall))

    def test_normal_user_paused_run_keeps_original_resume_behavior(self):
        task=self.task({'active':dict(id='paused',node=3,mode='star',battles=2,
                                     started=datetime.fromtimestamp(BASE-36000).isoformat())})
        self.assertNotIn('recovery',task.progress.data)
        self.assertNotIn('run_deadline_at',task.active)
        self.assertEqual(task.op.deadline,self.mono+1700)
        with task.recovery_combat_window():task.op.check()
        self.assertNotIn('recovery',task.progress.data)

    def test_first_fault_captures_whole_run_budget_before_short_recovery_clock(self):
        task=self.task({'active':dict(id='original',node=3,mode='star',battles=2)})
        recovery=task.prepare_recovery()
        self.assertEqual(recovery['run_deadline'],BASE+2700)
        self.assertEqual(recovery['deadline'],BASE+1600)
        self.assertEqual(task._run_deadline,self.mono+600)
        self.advance(10)
        task._run_deadline=self.mono+7200
        task.apply_recovery_deadline()
        self.assertEqual(recovery['run_deadline'],BASE+2700)

    def test_run_allowance_expiring_inside_login_transitions_to_bounded_settlement(self):
        for limit in (1,3):
            with self.subTest(retry_limit=limit):
                task=self.task();recovery=task.progress.data['recovery']
                task.config.DivergentUniverse_RecoveryRetries=limit
                recovery.update(attempts=0,deadline=self.wall+600,run_deadline=self.wall+30)
                hard_deadline=recovery['run_deadline'];actions=[]
                def login(restart=False):
                    actions.append(recovery['action'])
                    if len(actions)==1:
                        self.advance(40)
                        raise TimeoutError('whole-run ceiling expired during login')
                    task.op.check()
                task.login_from_current=login
                with patch.object(du,'save_error_log'),patch.object(du,'logger'):
                    if limit==1:
                        with self.assertRaises(du.RequestHumanTakeover):task.recover_checkpoint(RuntimeError('first fault'))
                    else:
                        task.recover_checkpoint(RuntimeError('first fault'))
                self.assertEqual(recovery['action'],'settle')
                self.assertEqual(recovery['run_deadline'],hard_deadline)
                self.assertEqual(recovery['faults'],2)
                self.assertEqual(actions,['resume'] if limit==1 else ['resume','settle'])
                self.assertEqual(recovery['attempts'],len(actions))
                self.assertEqual(recovery['deadline'],self.wall+600)

    def test_reload_animation_does_not_use_unknown_page_back_or_restart(self):
        task=self.task()
        with task.recovery_combat_window():saved=deepcopy(task.progress.data)
        task=self.task(saved)
        task.is_combat_executing.return_value=False
        task.adventure_intro_visible=Mock(return_value=False)
        task.forge_panel_visible=Mock(return_value=False)
        task.adventure_result_button=Mock(return_value=False)
        task.discard_confirmation_visible=Mock(return_value=False)
        task.login_from_current=Mock(side_effect=AssertionError('Animation must not trigger login'))
        task.return_to_main=Mock(side_effect=AssertionError('Animation must not send back'))
        task.op.image=SimpleNamespace(mean=lambda:20)
        task.op.save=Mock()
        def snapshot():
            self.advance(20)
            task.op.check()
        task.op.snapshot=snapshot
        with self.assertRaisesRegex(RuntimeError,'未能从当前页面回到差分宇宙入口'):
            task.go_to_lobby()
        self.assertGreaterEqual(self.wall,BASE+1150)
        self.assertLess(self.wall,BASE+1200)
        self.assertIn('combat_pause',task.progress.data['recovery'])
        task.login_from_current.assert_not_called()
        task.return_to_main.assert_not_called()

    def test_native_error_and_user_stop_restore_clock_without_erasing_fault_history(self):
        for error in (RuntimeError('native watchdog'),du.TaskEnd()):
            task=self.task();recovery=task.progress.data['recovery']
            with self.assertRaises(type(error)):
                with task.recovery_combat_window():
                    self.advance(10)
                    raise error
            self.assertNotIn('combat_pause',recovery)
            self.assertEqual((recovery['faults'],recovery['attempts']),(1,1))
            self.assertEqual(recovery['deadline']-self.wall,BASE+1060-(self.wall-10))

    def test_unconfirmed_combat_or_expired_action_budget_cannot_start_pause(self):
        task=self.task();task.is_combat_executing.return_value=False
        with task.recovery_combat_window():
            self.assertNotIn('combat_pause',task.progress.data['recovery'])
        task.is_combat_executing.return_value=True
        self.advance(61)
        with self.assertRaises(TimeoutError):
            with task.recovery_combat_window():self.fail('Expired recovery must not get a combat lease')
        self.assertNotIn('combat_pause',task.progress.data['recovery'])


if __name__=='__main__':unittest.main()
