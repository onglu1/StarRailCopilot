"""Non-blessing evidence uses the decision's frame without observing again."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np

from tasks.currency_wars.operator import Box
from module.config.config import TaskEnd
from tasks.divergent_universe.selection import Choice
from tasks.divergent_universe.star_effects import observe_effects


class CandidateEvidenceTests(unittest.TestCase):
    def task(self):
        forbidden=Mock(side_effect=AssertionError('No new screenshot, OCR, or input'))
        image=np.zeros((720,1280,3),dtype=np.uint8)
        op=NS(image=image,snapshot=forbidden,read_region=forbidden,read_line=forbidden,
              click_box=forbidden,click_point=forbidden)
        main=NS(op=op,config=NS(config_name='fixture'),star_loadout=NS(candidate='dot'),
            active={'id':'retained','mode':'star','node':7,'selections':20,'star':{'candidate':'dot'}},
            progress=NS(record=Mock()))
        choices=[Choice(Box(156,155,280,420,'DU_CARD'),'原始OCR标题',True,True,np.int64(2),
                        ('虚无','巡猎'),(('虚无',np.int64(6)),('巡猎',np.int64(4))))]
        return main,choices,forbidden

    def test_existing_frame_and_basic_metadata_match_without_mutating_choices(self):
        for kind in ('equation','curio','miracle','discard'):
            main,choices,forbidden=self.task();before=deepcopy(choices);active=deepcopy(main.active)
            with patch('tasks.divergent_universe.star_effects.save_image') as saved, \
                 patch('pathlib.Path.mkdir'),patch('pathlib.Path.write_text') as written:
                observe_effects(main,choices,kind)
            forbidden.assert_not_called()
            self.assertIs(saved.call_args.args[0],main.op.image)
            payload=json.loads(written.call_args.args[0])
            self.assertEqual(payload['kind'],kind)
            self.assertEqual(payload['cards'][0],dict(title='原始OCR标题',rarity=2,recommended=True,
                uncollected=True,box=[156,155,436,575],paths=['虚无','巡猎'],
                requirements=[['虚无',6],['巡猎',4]],effect_text=''))
            self.assertEqual(payload['pixel_sha256'],hashlib.sha256(main.op.image.tobytes()).hexdigest())
            self.assertFalse(payload['body_ocr_performed'])
            self.assertEqual(main.progress.record.call_args.args,('star_candidate_frame_observed',))
            self.assertEqual(main.progress.record.call_args.kwargs,payload)
            self.assertEqual(choices,before);self.assertEqual(main.active,active)

    def test_deduplicates_identical_frame_but_keeps_distinct_bounded_frames(self):
        main,choices,forbidden=self.task()
        with patch('tasks.divergent_universe.star_effects.save_image') as saved, \
             patch('pathlib.Path.mkdir'),patch('pathlib.Path.write_text'), \
             patch('tasks.divergent_universe.star_effects.time.time_ns',return_value=123):
            observe_effects(main,choices,'miracle')
            observe_effects(main,choices,'miracle')
            for value in range(1,6):
                main.op.image[0,0,0]=value
                observe_effects(main,choices,'miracle')
            self.assertEqual(saved.call_count,4)
            paths=[str(call.args[1]) for call in saved.call_args_list]
            self.assertEqual(len(set(paths)),4)
            main.active['selections']+=1
            observe_effects(main,choices,'miracle')
            self.assertEqual(saved.call_count,5)
        forbidden.assert_not_called()

    def test_new_evidence_failures_do_not_block_but_old_blessing_errors_still_propagate(self):
        for failure in ('image','json','metadata'):
            main,choices,forbidden=self.task();before=deepcopy(choices)
            if failure=='metadata':choices[0].requirements=(('虚无',object()),)
            with patch('pathlib.Path.mkdir'), \
                 patch('tasks.divergent_universe.star_effects.save_image',side_effect=OSError('full disk') if failure=='image' else None), \
                 patch('pathlib.Path.write_text',side_effect=OSError('write failed') if failure=='json' else None):
                observe_effects(main,choices,'curio')
            forbidden.assert_not_called()
            self.assertEqual(main.progress.record.call_args.args,('star_candidate_frame_unavailable',))
            if failure!='metadata':self.assertEqual(choices,before)
        main,choices,_=self.task()
        main.op.read_region=Mock(side_effect=RuntimeError('old blessing OCR error'))
        with self.assertRaisesRegex(RuntimeError,'old blessing OCR error'):
            observe_effects(main,choices,'blessing')
        main,choices,_=self.task();main.op.read_region=Mock(return_value=[])
        with patch('tasks.divergent_universe.star_effects.save_image') as saved,patch('pathlib.Path.mkdir'):
            observe_effects(main,choices,'blessing')
        self.assertEqual(saved.call_args.args[1].name,'choice_effects_7_20.png')
        self.assertEqual(main.progress.record.call_args.args,('star_effects_observed',))
        self.assertNotIn('kind',main.progress.record.call_args.kwargs)

    def test_runtime_recording_errors_are_optional_but_stop_is_not_swallowed(self):
        main,choices,_=self.task()
        with patch('pathlib.Path.mkdir'),patch('tasks.divergent_universe.star_effects.save_image',
                                                side_effect=RuntimeError('image encoder failed')):
            observe_effects(main,choices,'curio')
        self.assertEqual(main.progress.record.call_args.args,('star_candidate_frame_unavailable',))
        main,choices,_=self.task()
        with patch('pathlib.Path.mkdir'),patch('tasks.divergent_universe.star_effects.save_image',
                                                side_effect=TaskEnd()),self.assertRaises(TaskEnd):
            observe_effects(main,choices,'curio')


if __name__=='__main__':unittest.main()
