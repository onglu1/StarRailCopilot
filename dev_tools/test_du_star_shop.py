"""The merchant inspection uses native interactions and preserves the run."""
from types import SimpleNamespace
import unittest
from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_shop import StarShop
from module.exception import RequestHumanTakeover


class ShopInspectionTests(unittest.TestCase):
    def test_completed_room_does_not_reenter_or_repeat_purchases(self):
        worker,main=self.task()
        main.active['star']['shops']={'7':{'done':True,'purchases':[{'name':'already acquired'}]}}
        main.world_visible=lambda:True
        main.op.text=lambda *a,**k:self.fail('Completed shop needs no more UI work')
        self.assertFalse(worker.handle_room('retained'))

    def test_unverified_purchase_is_not_closed_or_reported_as_finished(self):
        worker,main=self.task()
        main.active['star']['shops']={'7':{'pending_purchase':{'name':'pending'}}}
        main.world_visible=lambda:False
        worker.visible=lambda:False
        worker.buy_equations=lambda expected_run:{'pending':{'name':'pending'}}
        worker.leave=lambda *a:self.fail('Do not discard an unverified receipt')
        with self.assertRaisesRegex(RuntimeError,'禁止重复付款'):
            worker.handle_room('retained')

    def test_native_floor_projection_keeps_behind_player_quadrants(self):
        from tasks.rogue.route.exit import RogueExit
        self.assertLess(RogueExit.screen2direction((385,914),at_floor=True),-90)
        self.assertGreater(RogueExit.screen2direction((900,914),at_floor=True),90)
        self.assertEqual(abs(RogueExit.screen2direction((640,914),at_floor=True)),180)
        self.assertEqual(RogueExit.screen2direction((640,500),at_floor=True),0)

    def task(self):
        main=SimpleNamespace(active={'id':'retained','node':7,'station':'商店','star':{},'node_done':False},
                             ROTATION_BOX=(410,180,990,300))
        # A real star run has prepared metadata, not an empty dictionary.
        main.active['star']={'candidate':'fixture'}
        main.is_combat_executing=lambda:False
        main.progress=SimpleNamespace(record=lambda *a,**k:None,save=lambda *a:None)
        main.op=SimpleNamespace(snapshot=lambda:None,text=lambda *a,**k:None)
        main.wait_until_stable=lambda *a:None
        worker=StarShop(main);worker.save_frame=lambda name:name+'.png'
        return worker,main

    def test_wrong_run_or_room_cannot_issue_input(self):
        worker,main=self.task()
        main.op.snapshot=lambda:self.fail('Wrong identity must fail before device access')
        with self.assertRaises(RequestHumanTakeover):worker.inspect('other-run')
        main.active['station']='战斗'
        with self.assertRaises(RequestHumanTakeover):worker.inspect('retained')

    def test_stale_shop_checkpoint_cannot_treat_next_station_page_as_merchant(self):
        worker,main=self.task()
        main.world_visible=lambda:False
        main.op.read_region=lambda *a,**k:self.fail('No merchant was actually interacted with')
        with self.assertRaises(RequestHumanTakeover):worker.inspect('retained')

    def test_observed_native_merchant_opens_an_inspection_without_purchase(self):
        worker,main=self.task();world=[True];trace=[]
        main.world_visible=lambda:world[0]
        main.wait_until_stable=lambda *a:None
        main.op.text=lambda *a,**k:Box(825,410,100,30,'阮·梅')
        main.op.read_region=lambda region,**k:[Box(80,30,100,30,'商店')] if region[1]<.1 else []
        def interact(label,**kwargs):trace.append(label.source);world[0]=False;return True
        main.interact_with_label=interact
        result=worker.inspect('retained')
        self.assertEqual(trace,['阮·梅'])
        self.assertFalse(result['purchased'])
        self.assertEqual(main.active['id'],'retained')
        self.assertFalse(main.active['node_done'])

    def test_missing_merchant_search_is_bounded_without_guessing_a_click(self):
        from pathlib import Path
        worker,main=self.task();rotations=[]
        main.world_visible=lambda:True
        main.op.templates=Path('.')
        main.op.template_matches=lambda *a,**k:[]
        main.rotation_swipe=lambda angle,**kwargs:rotations.append(angle)
        main.interact_with_label=lambda *a,**k:self.fail('No current merchant prompt')
        with self.assertRaises(RequestHumanTakeover):worker.inspect('retained')
        self.assertEqual(sum(rotations),360)
        self.assertFalse(main.active['node_done'])

    def test_backing_away_from_exit_is_not_undone_by_the_next_gate_approach(self):
        from pathlib import Path
        worker,main=self.task();moves=[]
        main.world_visible=lambda:True
        main.op.templates=Path('.')
        main.op.template_matches=lambda *a,**k:[]
        main.op.text=lambda names,*a,**k:Box(820,410,100,30,'随意门') if names==('随意门','前往下一区域') and not moves else None
        main.find_near_portal=lambda:Box(550,180,260,135,'door_face_near')
        main.rotation_swipe=lambda *a,**k:None
        main.move=lambda direction,*a,**k:moves.append(direction)
        with self.assertRaises(RequestHumanTakeover):worker.inspect('retained')
        self.assertEqual(len(moves),worker.MAX_GATE_BACKOFFS)
        self.assertTrue(all(abs(direction)>90 for direction in moves),moves)


if __name__=='__main__':unittest.main()
