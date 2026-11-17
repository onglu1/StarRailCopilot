"""A changed build gets one settlement-only opportunity, never a restart budget."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

import tasks.divergent_universe.divergent_universe as du


class PostPatchSettlementTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/'evidence/du-post-patch-tests'
        base.mkdir(parents=True,exist_ok=True)
        self.temp=TemporaryDirectory(dir=base)
        self.events=Path(self.temp.name)/'events.jsonl'
        self.proof=dict(event='recovery_exhausted',run_id='old',node=None,build='build-old',
                        pid=111,action='settle',attempts=3)
        self.events.write_text(json.dumps(self.proof)+'\n',encoding='utf-8')

    def tearDown(self):self.temp.cleanup()

    def task(self):
        main=object.__new__(du.DivergentUniverse)
        data=dict(phase='error',error='equation confirmation failed',pid=111,history=[{'id':'preserved'}],
                  active=dict(id='old',node=None,stop_requested=True),
                  recovery=dict(run_id='old',node=None,action='settle',attempts=3,faults=3,
                                deadline=900,run_deadline=2000))
        main.config=NS(DivergentUniverse_RecoveryRetries=3)
        main.progress=NS(data=data,build='build-new',events_path=self.events,save=Mock(),record=Mock())
        return main

    def test_changed_build_archives_old_checkpoint_without_resetting_counts(self):
        task=self.task();original=deepcopy(task.progress.data)
        with patch.object(du.time,'time',return_value=1000):
            self.assertTrue(task.retry_exhausted_settlement_after_update())
        data=task.progress.data;archive=data['active']['post_patch_settlement_retry']
        self.assertEqual(archive['previous_recovery'],original['recovery'])
        self.assertEqual((archive['previous_error'],archive['previous_pid'],archive['from_build']),
                         (original['error'],111,'build-old'))
        self.assertEqual(data['recovery']['deadline'],1600)
        self.assertEqual((data['recovery']['faults'],data['recovery']['attempts']),(3,3))
        self.assertEqual(data['history'],original['history'])
        self.assertEqual(data['active']['id'],'old')
        self.assertTrue(data['active']['stop_requested'])
        task.progress.build='build-even-newer'
        with patch.object(du.time,'time',return_value=3000):
            self.assertFalse(task.retry_exhausted_settlement_after_update())
        self.assertEqual(data['recovery']['deadline'],1600)

    def test_same_build_user_stop_or_nonsettlement_never_grants_window(self):
        for change in ('same_build','stopped','resume','not_requested','already_settled'):
            task=self.task();data=task.progress.data
            if change=='same_build':task.progress.build='build-old'
            elif change=='stopped':data['phase']='stopped'
            elif change=='resume':data['recovery']['action']='resume'
            elif change=='not_requested':data['active']['stop_requested']=False
            else:data['active']['settlement_observed']=True
            before=deepcopy(data)
            self.assertFalse(task.retry_exhausted_settlement_after_update(),change)
            self.assertEqual(data,before)

    def test_terminal_evidence_must_match_profile_checkpoint(self):
        for field,value in (('run_id','different'),('node',5),('pid',222),('attempts',2),('action','resume')):
            self.events.write_text(json.dumps(dict(self.proof,**{field:value}))+'\n',encoding='utf-8')
            task=self.task()
            self.assertFalse(task.retry_exhausted_settlement_after_update(),field)

    def test_bounded_tail_ignores_partial_leading_line_and_finds_latest_proof(self):
        self.events.write_text('x'*600000+'\n'+json.dumps(self.proof)+'\n'+
                               json.dumps(dict(event='session_started',build='build-new'))+'\n',encoding='utf-8')
        with patch.object(du.time,'time',return_value=1000):
            self.assertTrue(self.task().retry_exhausted_settlement_after_update())

    def test_preparation_to_first_node_cannot_renew_settlement_or_restart_budget(self):
        task=self.task()
        with patch.object(du.time,'time',return_value=1000):
            self.assertTrue(task.retry_exhausted_settlement_after_update())
        task.active=task.progress.data['active'];task.active.update(mode='star',node=1)
        task.op=NS(deadline=0);task._run_deadline=1800
        retained=task.progress.data['recovery'];before=deepcopy(retained)
        with patch.object(du.time,'time',return_value=1010),patch.object(du.time,'monotonic',return_value=110):
            after=task.prepare_recovery()
        self.assertIs(after,retained)
        self.assertEqual(after['deadline'],before['deadline'])
        self.assertEqual(after['attempts'],3)
        self.assertEqual(after['faults'],before['faults']+1)
        self.assertEqual(after['node'],None)
        self.assertEqual(task.active['post_patch_settlement_retry']['previous_recovery']['attempts'],3)
        task.device=NS();task.login_from_current=Mock()
        with patch.object(du,'save_error_log'),patch.object(du,'logger'),self.assertRaises(du.RequestHumanTakeover):
            task.recover_checkpoint(RuntimeError('exit failed after entering node 1'))
        task.login_from_current.assert_not_called()

    def test_normal_resume_new_node_keeps_its_existing_fresh_budget_behavior(self):
        task=self.task();task.active=task.progress.data['active']
        task.active.update(mode='star',node=1,stop_requested=False)
        previous=task.progress.data['recovery'];previous.update(action='resume',faults=1,attempts=2)
        task._run_deadline=1800;task.op=NS(deadline=0)
        with patch.object(du.time,'time',return_value=1000),patch.object(du.time,'monotonic',return_value=100):
            after=task.prepare_recovery()
        self.assertIsNot(after,previous)
        self.assertEqual((after['node'],after['attempts'],after['faults'],after['action']),(1,0,1,'resume'))

    def test_settlement_inventory_panels_close_without_reading_bad_counts(self):
        for title in ('拥有祝福','祝福/虚无','方程'):
            task=self.task();task.active=task.progress.data['active']
            task.star_loadout=NS(revision='star-workshop-v8')
            task.appear=Mock(return_value=False)
            def text(names,*args,**kwargs):
                names=(names,) if isinstance(names,str) else names
                return NS(source=title) if title in names else None
            task.op=NS(text=text)
            with patch('tasks.divergent_universe.star_inventory.StarInventory') as cls:
                worker=cls.return_value
                worker.blessing_page.return_value=title.startswith('祝福/')
                worker.read.side_effect=AssertionError('Settlement must not read inventory counts')
                self.assertTrue(task.handle_misc())
                worker.close.assert_called_once()
                worker.read.assert_not_called()

    def test_normal_inventory_read_remains_strict(self):
        task=self.task();task.active=task.progress.data['active'];task.active['stop_requested']=False
        task.star_loadout=NS(revision='star-workshop-v8');task.appear=Mock(return_value=False)
        task.op=NS(text=lambda names,*a,**k:NS(source='拥有祝福') if isinstance(names,tuple) and '拥有祝福' in names else None)
        with patch('tasks.divergent_universe.star_inventory.StarInventory') as inventory,\
             patch('tasks.divergent_universe.star_shop.StarShop') as shop,\
             patch('tasks.divergent_universe.star.StarPreparation') as preparation:
            shop.return_value.can_handle_page.return_value=False
            preparation.return_value.revival_page_visible.return_value=False
            inventory.return_value.read.side_effect=RuntimeError('invalid actual count')
            with self.assertRaisesRegex(RuntimeError,'invalid actual count'):task.handle_misc()
            inventory.return_value.close.assert_not_called()


if __name__=='__main__':unittest.main()
