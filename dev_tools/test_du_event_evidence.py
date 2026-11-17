"""Native decisions retain their own frames; evidence never sends game input."""
from types import SimpleNamespace as NS
import hashlib
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.base.button import ClickButton
from module.config.config import TaskEnd
from tasks.divergent_universe.events import DivergentEvent
from tasks.rogue.event import event as native
from dev_tools.test_du_event_confirmation import EventConfirmationTests


class EventEvidenceTests(unittest.TestCase):
    def handler(self, count=2):
        handler=object.__new__(DivergentEvent)
        handler.config=NS(RogueWorld_DomainStrategy='event-evidence-fixture')
        image=np.zeros((720,1280,3),dtype=np.uint8)
        handler.device=NS(image=image,click=Mock(),screenshot=Mock(side_effect=AssertionError('extra capture')))
        handler.interval_is_reached=Mock(return_value=True)
        handler.interval_reset=Mock()
        handler.event_title=None
        handler._du_main=NS(active={'id':'retained','mode':'star','node':9,'star':{'candidate':'dot'}},
            config=NS(config_name='fixture'),progress=NS(record=Mock()))
        options=[native.OptionButton(ClickButton((620,200+i*90,640,220+i*90),name=f'option{i}'),
                                     is_bottom_page=i==1) for i in range(count)]
        def match():
            handler.options=options
            return len(options)
        handler._event_option_match=match
        scroll=NS(appear=Mock(return_value=True),set_bottom=Mock(),set_top=Mock())
        return handler,options,scroll

    def run_native(self,handler,options,scroll,save_error=None):
        with patch.object(native,'SCROLL_OPTION',scroll),\
             patch.object(native.RogueEvent,'_event_option_filter',return_value=options[-1]) as selected,\
             patch('tasks.divergent_universe.events.save_image',side_effect=save_error) as saved,\
             patch('pathlib.Path.mkdir'):
            result=handler.handle_event_option()
        return result,selected,saved

    def test_multi_option_records_native_post_scroll_frame_and_exact_selected_target(self):
        handler,options,scroll=self.handler()
        after=np.ones_like(handler.device.image)
        scroll.set_bottom.side_effect=lambda **kwargs:setattr(handler.device,'image',after)
        result,selected,saved=self.run_native(handler,options,scroll)
        self.assertTrue(result);selected.assert_called_once()
        handler.device.click.assert_called_once_with(options[1].prefix_icon)
        handler.device.screenshot.assert_not_called()
        scroll.set_bottom.assert_called_once_with(main=handler)
        self.assertIs(saved.call_args.args[0],after)
        record=handler._du_main.progress.record.call_args
        self.assertEqual(record.args,('star_event_decision_observed',))
        self.assertEqual(record.kwargs['selected_index'],1)
        self.assertEqual(record.kwargs['target_area'],list(options[1].prefix_icon.button))
        self.assertEqual(record.kwargs['pixel_sha256'],hashlib.sha256(after.tobytes()).hexdigest())
        self.assertIsNone(record.kwargs['options'][1]['raw_text'])
        self.assertFalse(record.kwargs['extra_ocr']);self.assertFalse(record.kwargs['result_verified'])

    def test_native_raw_text_and_unbound_confirmation_are_not_invented(self):
        handler,options,_=self.handler();handler.options=options
        options[0].button=NS(text='失去祝福',button=(650,200,850,220),
                             matched_keyword=NS(name='Observed',cn='已识别'))
        with patch('tasks.divergent_universe.events.save_image'),patch('pathlib.Path.mkdir'):
            handler._record_decision('option',options[0],options[0].prefix_icon)
            self.assertEqual(handler._du_main.progress.record.call_args.kwargs['options'][0]['raw_text'],'失去祝福')
            handler._du_confirm_context=('retained',8,None)
            handler._du_confirm_at=time.monotonic()
            handler._record_decision('confirm',options[0],options[0].prefix_icon)
        proof=handler._du_main.progress.record.call_args.kwargs
        self.assertIsNone(proof['selected_index'])
        self.assertEqual(proof['options'],[])
        self.assertFalse(proof['selected_option_bound'])

    def test_single_option_and_interval_keep_native_behavior(self):
        handler,options,scroll=self.handler(count=1)
        result,selected,saved=self.run_native(handler,options,scroll)
        self.assertTrue(result);selected.assert_not_called()
        handler.device.click.assert_called_once_with(options[0].prefix_icon)
        self.assertEqual(handler._du_main.progress.record.call_args.kwargs['selected_index'],0)
        handler,options,scroll=self.handler()
        handler.interval_is_reached.return_value=False
        result,selected,saved=self.run_native(handler,options,scroll)
        self.assertFalse(result);selected.assert_not_called();saved.assert_not_called()
        handler.device.click.assert_not_called()

    def test_recording_failure_does_not_block_input_and_native_failures_propagate(self):
        handler,options,scroll=self.handler()
        result,_,_=self.run_native(handler,options,scroll,OSError('disk full'))
        self.assertTrue(result);handler.device.click.assert_called_once()
        self.assertEqual(handler._du_main.progress.record.call_args.args,('star_event_evidence_unavailable',))
        for error in (TaskEnd(),RuntimeError('native input failed')):
            handler,options,scroll=self.handler()
            handler.device.click.side_effect=error
            with self.assertRaises(type(error)):
                self.run_native(handler,options,scroll)
            handler._du_main.progress.record.assert_not_called()

    def test_frames_are_bounded_but_every_native_action_keeps_metadata(self):
        handler,options,_=self.handler();handler.options=options
        with patch('tasks.divergent_universe.events.save_image') as saved,patch('pathlib.Path.mkdir'):
            handler._record_decision('option',options[0],options[0].prefix_icon)
            handler._record_decision('option',options[0],options[0].prefix_icon)
            self.assertEqual(saved.call_count,1)
            for value in range(1,11):
                handler.device.image[0,0,0]=value
                handler._record_decision('option',options[0],options[0].prefix_icon)
            self.assertEqual(saved.call_count,8)
            self.assertEqual(handler._du_main.progress.record.call_count,12)
            self.assertTrue(handler._du_main.progress.record.call_args.kwargs['screenshot_limit_reached'])
            handler._du_main.active['node']=10
            handler._record_decision('option',options[0],options[0].prefix_icon)
            self.assertEqual(saved.call_count,9)

    def test_confirm_uses_only_the_two_existing_stable_frames(self):
        fixture=EventConfirmationTests()
        EventConfirmationTests.setUpClass()
        handler,clicks=fixture.handler(fixture.frames['bottom'],[fixture.frames['top']]*2)
        owner,options,_=self.handler()
        handler._du_main=owner._du_main;handler.options=options
        handler._du_confirm_option=options[1];handler.event_title=None
        handler._du_confirm_context=('retained',9,None);handler._du_confirm_at=time.monotonic()
        with patch('tasks.divergent_universe.events.save_image') as saved,patch('pathlib.Path.mkdir'):
            self.assertTrue(handler.appear_then_click(native.CHOOSE_OPTION_CONFIRM,interval=2))
        self.assertEqual(handler.device.screenshot.call_count,2)
        self.assertEqual(len(clicks),1)
        self.assertIs(saved.call_args.args[0],fixture.frames['top'])
        proof=handler._du_main.progress.record.call_args.kwargs
        self.assertEqual(proof['stage'],'confirm');self.assertIsNone(proof['selected_index'])
        self.assertFalse(proof['selected_option_bound'])
        self.assertEqual(proof['target_area'],list(clicks[0][0]))


if __name__=='__main__':unittest.main()
