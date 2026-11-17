"""Replay network-dimmed and restored choices without OCR or device input."""
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import cv2

import tasks.divergent_universe.divergent_universe as du
from tasks.currency_wars.operator import Box


class SameChoiceRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).resolve().parents[3]/'StarRailCopilot/log/error/1792100962330'
        cls.images={}
        for key,name in (('loading','2026-10-16_05-48-48-184030.png'),
                         ('ready','2026-10-16_05-49-18-061524.png')):
            pixels=cv2.imread(str(folder/name))
            if pixels is None:raise FileNotFoundError(folder/name)
            cls.images[key]=cv2.cvtColor(pixels,cv2.COLOR_BGR2RGB)
        cls.names=('垫虫帝','天罚投票装置','铁臂侠')
        cls.boxes=[Box(270,313,78,34,cls.names[0]),Box(565,310,150,38,cls.names[1]),
                   Box(932,313,80,34,cls.names[2])]

    def task(self,frames):
        main=object.__new__(du.DivergentUniverse)
        index=[-1];clicked=[]
        op=NS(image=self.images['ready'],read_region=lambda *a,**k:self.boxes)
        def snapshot():
            index[0]+=1
            op.image=self.images[frames[index[0]][0]]
        op.snapshot=snapshot
        op.click_box=lambda *a,**k:clicked.append(('confirm',index[0])) or True
        op.click_point=lambda *a,**k:clicked.append(('select',index[0])) or True
        main.op=op;main.progress=NS(record=Mock())
        main.selection_names=lambda *a:self.names
        main.selection_kind=lambda:None if frames[index[0]][1]=='world' else 'equation'
        main.world_visible=lambda:frames[index[0]][1]=='world'
        main.is_combat_executing=lambda:False
        main.lobby_visible=lambda:False
        main.choice_confirm_button=lambda:Box(1080,637,47,26,'确认')
        main.confirm_enabled=lambda button:frames[index[0]][1] is True
        timer=NS(start=lambda:timer,reached=lambda:index[0]>=len(frames)-1)
        choice=NS(title=self.names[1],box=Box(491,140,298,452,'DU_CARD'))
        return main,choice,clicked,timer

    def test_actual_dimmer_is_not_a_ready_unselected_set(self):
        main,_,_,_=self.task([('ready',False)])
        for image,expected in (('loading',False),('ready',True)):
            main.op.image=self.images[image]
            self.assertEqual(main.selection_titles_unobscured((.08,.42,.96,.50),self.names),expected)

    def test_same_set_reselects_only_after_dimmer_has_cleared_stably(self):
        frames=[('ready',True),('ready',True),('loading',False),('loading',False),
                ('ready',False),('ready',False),('ready',True),('ready','world')]
        main,choice,clicked,timer=self.task(frames)
        with patch.object(du,'Timer',return_value=timer):main.confirm_selection('equation',choice)
        self.assertEqual(clicked,[('confirm',0),('confirm',1),('select',5),('confirm',6)])

    def test_used_confirm_budget_cannot_be_reset_by_same_set(self):
        frames=[('ready',True)]*3+[('ready',False)]*3
        main,choice,clicked,timer=self.task(frames)
        with patch.object(du,'Timer',return_value=timer),self.assertRaisesRegex(RuntimeError,'选择未确认'):
            main.confirm_selection('equation',choice)
        self.assertEqual(clicked,[('confirm',0),('confirm',1),('confirm',2)])


if __name__=='__main__':unittest.main()
