"""Temporary-leave requests must respect overlays and retain the same run."""
from types import SimpleNamespace
import unittest
import numpy as np

from tasks.currency_wars.operator import Box
from tasks.divergent_universe.divergent_universe import DivergentUniverse


class RecoveryUITests(unittest.TestCase):
    def run_leave(self, frames):
        main=object.__new__(DivergentUniverse)
        main.active={'id':'retained','node':18,'node_done':False}
        frame=[-1];clicked=[]
        op=SimpleNamespace(image=None)
        def snapshot():
            frame[0]+=1
            self.assertLess(frame[0],len(frames),'Leave did not reach the observed hub')
            op.image=np.full((720,1280,3),60 if frames[frame[0]]=='loading' else 255,dtype=np.uint8)
        def text(names,region,**kwargs):
            current=frames[frame[0]]
            if isinstance(names,tuple) and '暂离' in names and current!='hub':
                return Box(780,554,48,31,'暂离')
            if names=='确认' and current=='confirm':
                return Box(800,550,50,30,'确认')
            return None
        op.snapshot=snapshot;op.text=text
        op.click_box=lambda box,**kwargs:clicked.append(box.source) or True
        op.back=lambda:self.fail('Never close/reopen the menu after a leave request')
        main.op=op
        main.adventure_intro_visible=main.world_visible=main.is_in_main=lambda:False
        main.lobby_visible=lambda:frames[frame[0]]=='hub'
        main.confirm_enabled=lambda box:True
        main.go_to_lobby=lambda:None
        main.progress=SimpleNamespace(save=lambda *a:None)
        main.device=SimpleNamespace(click_record_clear=lambda:None)
        main.reenter_station()
        self.assertEqual(main.active['id'],'retained')
        self.assertEqual(main.active['node'],18)
        self.assertFalse(main.active['node_done'])
        self.assertNotIn('settlement_observed',main.active)
        return clicked

    def test_spinner_dimming_menu_does_not_repeat_background_click(self):
        self.assertEqual(self.run_leave(['menu','loading','loading','loading','hub']),['暂离'])

    def test_confirmation_is_handled_before_visible_background_menu(self):
        self.assertEqual(self.run_leave(['menu','confirm','hub']),['暂离','确认'])

    def test_bright_unchanged_menu_retries_have_a_hard_limit(self):
        self.assertEqual(self.run_leave(['menu']*8+['hub']),['暂离']*3)


if __name__=='__main__':unittest.main()
