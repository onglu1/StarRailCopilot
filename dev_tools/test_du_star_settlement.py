"""A missing save is never enough to invent a star result."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
from PIL import Image

from tasks.currency_wars.operator import Box
from tasks.divergent_universe.divergent_universe import DivergentUniverse


class FrameReader:
    def __init__(self):
        self.image=np.full((720,1280,3),240,dtype=np.uint8)

    def text(self,names,region,**kwargs):
        marker=int(self.image[0,0,0])
        if marker==240 and names=='进入星阶模式':
            return Box(940,630,220,40,names)
        if marker in (100,120) and isinstance(names,tuple) and '智瞳熄灭' in names:
            return Box(550,50,180,40,'智瞳熄灭')
        if marker==100 and names=='确认结算':
            return Box(580,640,120,30,names)
        return None


class SavedStarDefeatTests(unittest.TestCase):
    def task(self):
        main=object.__new__(DivergentUniverse)
        main.active={'id':'retained','mode':'star','node':6,'star':{'candidate':'followup'},
                     'pending_settlement':True,'result':'loss','settlement_confirmed':False}
        main.config=SimpleNamespace(config_name='fixture')
        main.op=FrameReader()
        main.progress=SimpleNamespace(record=lambda *a,**k:None,save=lambda *a:None)
        return main

    def test_same_run_saved_title_and_footer_can_recover_only_the_observed_loss(self):
        main=self.task()
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root=Path(directory);folder=root/'log/divergent_universe/fixture/star_runs/retained'
            folder.mkdir(parents=True)
            path=folder/'pending_123.png'
            Image.fromarray(np.full((720,1280,3),100,dtype=np.uint8)).save(path)
            with patch('tasks.divergent_universe.divergent_universe.ROOT',root):
                self.assertEqual(main.recover_saved_star_defeat(),'loss')
            self.assertTrue(main.active['settlement_observed'])
            self.assertFalse(main.active['settlement_confirmed'])
            self.assertEqual(main.active['settlement_screenshot'],str(path))
            self.assertEqual(main.active['id'],'retained')
            self.assertTrue((main.op.image==240).all())

    def test_entry_battle_loss_and_title_without_footer_cannot_complete_a_run(self):
        main=self.task()
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root=Path(directory);folder=root/'log/divergent_universe/fixture/star_runs/retained'
            folder.mkdir(parents=True)
            Image.fromarray(np.full((720,1280,3),120,dtype=np.uint8)).save(folder/'pending_123.png')
            with patch('tasks.divergent_universe.divergent_universe.ROOT',root):
                self.assertIsNone(main.recover_saved_star_defeat())
            self.assertNotIn('settlement_observed',main.active)

    def test_live_extinguished_title_still_requires_settlement_button(self):
        main=self.task();main.op.image[:]=120
        self.assertIsNone(main.settlement_title())
        main.op.image[:]=100
        self.assertEqual(main.settlement_title().source,'智瞳熄灭')


if __name__=='__main__':unittest.main()
