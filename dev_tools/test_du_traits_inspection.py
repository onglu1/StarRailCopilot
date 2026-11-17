"""The diagnostic may open a known reader once, never resume/settle the run."""
from copy import deepcopy
from types import SimpleNamespace as NS
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.config.config import TaskEnd
from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_traits import KEY, inspect_traits, TraitInspectionOperator


class TraitsInspectionTests(unittest.TestCase):
    def fixture(self):
        active = dict(id='retained', mode='star', node=7, star=dict(candidate='dot',
            loadout=dict(candidate='dot', team=['a','b','c','d'], guide_code='unused')))
        recovery = dict(run_id='retained', node=7, deadline=time.time()+90,
                        run_deadline=time.time()+120, attempts=1, action='resume')
        data = dict(active=active, history=[{'id':'old','result':'loss'}], phase='stopped',
                    recovery=recovery, error='old diagnostic')
        progress = NS(data=data, save=Mock(), record=Mock())
        config = NS(config_name='fixture', stop_event=None)
        op = NS(deadline=time.monotonic()+999, image=np.zeros((720,1280,3), dtype=np.uint8),
                snapshot=Mock(), read_line=Mock(return_value=NS(source='祝福/全部')),
                read_region=Mock(return_value=[Box(976,24,50,28,'特性')]),
                click_box=Mock(return_value=True), back=Mock(side_effect=AssertionError('no back')))
        main = NS(device=object(), world_visible=Mock(return_value=False),
                  is_combat_executing=Mock(return_value=False), selection_kind=Mock(return_value='blessing'),
                  _initialize=Mock(side_effect=AssertionError('no init/login')))
        inventory = NS(blessing_page=Mock(return_value=True), read=Mock(),
                       close=Mock(side_effect=AssertionError('unknown page must not close')))
        return config, progress, main, op, inventory

    def invoke(self, fixture, expected='retained'):
        config, progress, main, op, inventory = fixture
        with patch('tasks.divergent_universe.divergent_universe.DivergentUniverse', return_value=main) as constructed, \
             patch('tasks.divergent_universe.star_traits.TraitInspectionOperator', return_value=op), \
             patch('tasks.divergent_universe.star_traits.StarInventory', return_value=inventory), \
             patch('tasks.divergent_universe.star_traits.save_image') as saved, patch('pathlib.Path.mkdir'):
            result = inspect_traits(config, progress, expected)
        return result, constructed, saved

    def test_invalid_checkpoint_is_rejected_before_constructing_device(self):
        for change in ('missing','wrong_run','node','stopped','candidate','saved_candidate'):
            fixture = self.fixture(); active=fixture[1].data['active']; expected='retained'
            if change=='missing':fixture[1].data['active']=None
            elif change=='wrong_run':expected='other'
            elif change=='node':active['node']=6
            elif change=='stopped':active['stop_requested']=True
            elif change=='candidate':active['star']['candidate']='aglaea'
            else:active['star']['loadout']['candidate']='dot_blackswan'
            with patch('tasks.divergent_universe.divergent_universe.DivergentUniverse') as constructed:
                with self.assertRaises(ValueError):inspect_traits(fixture[0],fixture[1],expected)
                constructed.assert_not_called()

    def test_expired_recovery_or_existing_profile_attempt_never_constructs_device(self):
        fixture=self.fixture();fixture[1].data['recovery']['deadline']=time.time()-1
        result,constructed,_=self.invoke(fixture)
        self.assertEqual(result['reason'],'existing_recovery_deadline_expired')
        constructed.assert_not_called()
        fixture=self.fixture();fixture[1].data['star_mechanism_pages']={KEY:{'run_id':'previous'}}
        result,constructed,_=self.invoke(fixture)
        self.assertEqual(result['status'],'already_attempted');constructed.assert_not_called()

    def test_world_combat_and_unknown_page_make_no_input_or_checkpoint(self):
        for page in ('world','combat','unknown'):
            fixture=self.fixture();_,progress,main,op,inventory=fixture
            before=deepcopy(progress.data)
            if page=='world':main.world_visible.return_value=True
            elif page=='combat':main.is_combat_executing.return_value=True
            else:inventory.blessing_page.return_value=False;main.selection_kind.return_value=None
            result,_,_=self.invoke(fixture)
            self.assertEqual(result['status'],'needs_inventory')
            op.click_box.assert_not_called();inventory.read.assert_not_called()
            self.assertEqual(progress.data,before)

    def test_one_open_two_saved_frames_and_normal_inspection_stop_preserve_run(self):
        fixture=self.fixture();_,progress,main,op,inventory=fixture
        recovery=deepcopy(progress.data['recovery']);history=deepcopy(progress.data['history'])
        def click(*args,**kwargs):
            self.assertIn(KEY,progress.data['star_mechanism_pages'])
            self.assertEqual(progress.data['phase'],'inspection_paused')
            self.assertGreater(progress.save.call_count,0)
            return True
        op.click_box.side_effect=click
        result,_,saved=self.invoke(fixture)
        self.assertEqual(result['status'],'awaiting_page_review')
        self.assertEqual(len(result['frames']),2);self.assertEqual(saved.call_count,3)
        self.assertFalse(result['trait_verified']);self.assertFalse(result['return_verified'])
        self.assertTrue(progress.data['active']['execution']['development_inspection'])
        self.assertEqual(progress.data['active']['id'],'retained')
        self.assertEqual(progress.data['history'],history);self.assertEqual(progress.data['recovery'],recovery)
        self.assertEqual(progress.data['error'],'old diagnostic')
        self.assertLess(op.deadline,time.monotonic()+46)
        op.click_box.assert_called_once();op.back.assert_not_called();inventory.close.assert_not_called()
        main._initialize.assert_not_called()
        result,constructed,_=self.invoke(fixture)
        self.assertEqual(result['status'],'already_attempted');constructed.assert_not_called()

    def test_known_reward_uses_existing_inventory_read_without_close_or_propagation(self):
        fixture=self.fixture();_,progress,_,_,inventory=fixture
        inventory.blessing_page.side_effect=[False,False,True,True]
        def read(**kwargs):
            progress.data['phase']='star_inventory_observed';progress.data.pop('error',None)
            return {'虚无':6}
        inventory.read.side_effect=read
        result,_,_=self.invoke(fixture)
        inventory.read.assert_called_once_with(close=False)
        self.assertEqual(result['status'],'awaiting_page_review')
        self.assertEqual(progress.data['phase'],'inspection_paused')
        self.assertEqual(progress.data['error'],'old diagnostic')

    def test_ambiguous_button_or_unstable_inventory_never_opens(self):
        for reason in ('ambiguous','outside','unstable'):
            fixture=self.fixture();_,progress,_,op,_=fixture
            if reason=='ambiguous':op.read_region.return_value*=2
            elif reason=='outside':op.read_region.return_value=[Box(950,24,50,28,'特性')]
            else:op.read_line.side_effect=[NS(source='祝福/全部'),NS(source='祝福/虚无')]
            result,_,_=self.invoke(fixture)
            self.assertEqual(result['status'],'needs_inventory');op.click_box.assert_not_called()
            self.assertIn(KEY,progress.data['star_mechanism_pages'])

    def test_stop_or_capture_failure_after_open_keeps_checkpoint_without_recovery(self):
        for error in (TaskEnd(),RuntimeError('capture unavailable')):
            fixture=self.fixture();_,progress,_,op,inventory=fixture
            recovery=deepcopy(progress.data['recovery'])
            op.snapshot.side_effect=[None,None,None,error]
            if isinstance(error,TaskEnd):
                with self.assertRaises(TaskEnd):self.invoke(fixture)
            else:
                result,_,_=self.invoke(fixture)
                self.assertEqual(result['status'],'inspection_incomplete')
            self.assertEqual(op.click_box.call_count,1);inventory.close.assert_not_called()
            self.assertEqual(progress.data['phase'],'inspection_paused')
            self.assertEqual(progress.data['recovery'],recovery)

    def test_diagnostic_snapshot_does_not_dismiss_popups_or_fullscreen_ocr(self):
        op=object.__new__(TraitInspectionOperator)
        op.check=Mock();op.device=NS(screenshot=Mock(return_value=np.zeros((720,1280,3),dtype=np.uint8)))
        op.popups=NS(handle_monthly_card_reward=Mock(side_effect=AssertionError('no popup input')))
        op._ocr_cache={'old':1};op.frame_cache={'old':1}
        self.assertEqual(op.snapshot(),[])
        self.assertEqual(op._ocr_cache,{});self.assertEqual(op.frame_cache,{})
        op.popups.handle_monthly_card_reward.assert_not_called()
        with self.assertRaises(ValueError):op.snapshot(ocr=True)

    def test_saved_frame_is_retained_when_optional_header_read_fails(self):
        fixture=self.fixture();op=fixture[3]
        op.read_line.side_effect=[NS(source='祝福/全部'),NS(source='祝福/全部'),RuntimeError('header OCR failed')]
        result,_,saved=self.invoke(fixture)
        self.assertEqual(result['status'],'inspection_incomplete')
        self.assertEqual(saved.call_count,2)
        self.assertEqual(len(result['frames']),1)
        self.assertIn('screenshot',result['frames'][0])
        self.assertNotIn('header',result['frames'][0])

    def test_cli_traits_branch_exits_before_common_initializer_and_deadline_override(self):
        import runpy
        fixture=self.fixture();config,progress=fixture[:2]
        with patch('sys.argv',['du_star_prepare','--profile','fixture','--page','traits-inspect','--expected-run','retained']), \
             patch('module.config.config.AzurLaneConfig',return_value=config), \
             patch('module.logger.set_file_logger'),patch('filelock.FileLock') as lock, \
             patch('tasks.divergent_universe.progress.Progress',return_value=progress), \
             patch('tasks.divergent_universe.divergent_universe.DivergentUniverse') as device_owner, \
             patch('tasks.divergent_universe.star_traits.inspect_traits',return_value={'status':'needs_inventory'}) as inspect, \
             patch('builtins.print'),self.assertRaises(SystemExit) as stopped:
            runpy.run_module('dev_tools.du_star_prepare',run_name='__main__')
        self.assertEqual(stopped.exception.code,0)
        inspect.assert_called_once_with(config,progress,'retained')
        device_owner.assert_not_called()
        self.assertEqual(lock.call_args.kwargs['timeout'],0)


if __name__=='__main__':unittest.main()
