"""Do not confuse HUD fades, revived allies or a merely long fight with depletion."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from tasks.divergent_universe.star_combat import StarCombat,observe_health,depleted_for_long_enough,first_health_region


class HealthRegionTests(unittest.TestCase):
    def frame(self,name='du_health_counter'):
        # Real 74x23 crops from b9 defeat_history_00 and da4 defeat_history_18.
        crop=np.asarray(Image.open(Path(__file__).parent/'fixtures'/f'{name}.png').convert('RGB'))
        image=np.zeros((720,1280,3),dtype=np.uint8)
        image[603:626,206:280]=crop
        return image

    def test_real_counter_is_excluded_without_extra_reads_or_other_slot_changes(self):
        regions=[]
        def read(region,**kwargs):
            regions.append(region)
            self.assertIs(kwargs.get('snapshot'),False)
            return SimpleNamespace(source='2685' if region[0]==217/1280 else '1234')
        self.assertEqual(observe_health(SimpleNamespace(image=self.frame(),read_line=read)),(2685,1234,1234,1234))
        self.assertEqual(regions,[(217/1280,603/720,280/1280,626/720)]+
                         [((r-74)/1280,603/720,r/1280,626/720) for r in (472,660,848)])

    def test_real_moon_cocoon_is_unknown_without_reading_its_icon_as_hp(self):
        op=SimpleNamespace(image=self.frame('du_health_moon'),read_line=lambda *a,**k:self.fail('No numeric HP baseline'))
        self.assertIsNone(first_health_region(op.image))
        self.assertIsNone(observe_health(op))

    def test_five_and_six_digit_hp_keep_their_leading_six(self):
        original=self.frame()
        glyphs={digit:original[603:626,238+10*i:248+10*i].copy() for i,digit in enumerate('2685')}
        for number in ('62685','662685'):
            with self.subTest(number=number):
                image=original.copy()
                image[603:626,218:280]=original[603:626,226:227]
                left=278-10*len(number)
                for i,digit in enumerate(number):
                    image[603:626,left+10*i:left+10*(i+1)]=glyphs[digit]
                region=first_health_region(image)
                self.assertLessEqual(region[0],left)  # Full original glyph tiles fit.
                self.assertEqual(region[2],280)
                calls=[]
                def read(roi,**kwargs):
                    calls.append(roi)
                    return SimpleNamespace(source=number if len(calls)==1 else '1234')
                self.assertEqual(observe_health(SimpleNamespace(image=image,read_line=read))[0],int(number))

    def test_no_counter_retains_full_original_width(self):
        image=self.frame()
        image[603:626,206:218]=0
        self.assertEqual(first_health_region(image),(206,603,280,626))

    def test_unseparated_hp_digit_is_not_clipped(self):
        image=np.zeros((720,1280,3),dtype=np.uint8)
        image[603:615,208:212]=255  # Higher counter.
        image[609:622,214:218]=255  # Lower digit too close for safe padding.
        image[609:622,269:276]=255
        self.assertIsNone(first_health_region(image))


class DepletionTests(unittest.TestCase):
    def test_needs_repeated_sustained_positive_observations(self):
        state={}
        for second in range(0,90,10):
            self.assertFalse(depleted_for_long_enough(state,(0,0,0,6284),second))
        self.assertTrue(depleted_for_long_enough(state,(0,0,0,6284),90))

    def test_revived_damage_slot_resets_the_window(self):
        state={'first_seen':0,'last_seen':80,'observations':9}
        self.assertFalse(depleted_for_long_enough(state,(1,0,0,6284),90))
        self.assertEqual(state,{})
        self.assertFalse(depleted_for_long_enough(state,(0,0,0,6284),100))

    def test_hidden_hud_and_long_observation_gap_cannot_prove_depletion(self):
        state={'first_seen':0,'last_seen':80,'observations':9}
        self.assertFalse(depleted_for_long_enough(state,None,90))
        self.assertFalse(depleted_for_long_enough(state,(0,0,0,6284),180))
        self.assertEqual(state['first_seen'],180)
        self.assertFalse(depleted_for_long_enough(state,(0,0,0,0),190))
        self.assertEqual(state,{})

    def test_a_partly_unknown_hud_is_not_depletion(self):
        state={'first_seen':0,'last_seen':80,'observations':9}
        self.assertFalse(depleted_for_long_enough(state,(0,0,0,None),90))


class HealthObservationTests(unittest.TestCase):
    def task(self,candidate='dot',members=None):
        events=[];saves=[]
        main=SimpleNamespace(active=dict(id='retained',mode='star',node=6,battles=3,
            star=dict(candidate=candidate,member_ids=members or [1410,1005,1309,1414])),
            op=SimpleNamespace(image=None),config=SimpleNamespace(config_name='fixture'))
        main.progress=SimpleNamespace(record=lambda event,**data:events.append((event,data)),
                                      save=lambda *a:saves.append(a))
        worker=StarCombat(main)
        worker.withdraw=lambda:self.fail('Ordinary party observation must not control battle')
        return worker,main,events,saves

    def observe_at(self,worker,second,health):
        with patch('tasks.divergent_universe.star_combat.time.monotonic',return_value=second), \
             patch('tasks.divergent_universe.star_combat.time.time',return_value=1000+second), \
             patch('tasks.divergent_universe.star_combat.observe_health',return_value=health):
            return worker.observe()

    def test_uses_only_existing_four_health_rois_without_new_screenshot(self):
        regions=[]
        def read(region,**kwargs):
            regions.append(region)
            self.assertIs(kwargs.get('snapshot'),False)
            return SimpleNamespace(source='1234')
        self.assertEqual(observe_health(SimpleNamespace(read_line=read)),(1234,)*4)
        self.assertEqual(regions,[((right-74)/1280,603/720,right/1280,626/720)
                                  for right in (280,472,660,848)])

    def test_invalid_hud_stays_unknown_in_event_and_summary(self):
        self.assertIsNone(observe_health(SimpleNamespace(read_line=lambda *a,**k:SimpleNamespace(source='--'))))
        worker,main,events,saves=self.task()
        self.assertFalse(self.observe_at(worker,0,None))
        self.assertIsNone(events[0][1]['health'])
        self.assertIsNone(events[0][1]['observed_zero_slots'])
        summary=main.active['star']['combat_health']['6:3']
        self.assertEqual(summary['observed_zero'],{})
        self.assertEqual(summary['unknown_samples'],1)
        self.assertNotIn('stop_requested',main.active)

    def test_dot_records_sustained_zero_slots_without_withdrawing(self):
        worker,main,events,saves=self.task()
        for second in range(0,121,10):
            self.assertFalse(self.observe_at(worker,second,(0,0,0,6284)))
        self.assertEqual([data['elapsed'] for _,data in events],[0,30,60,90,120])
        self.assertNotIn('stop_requested',main.active)
        self.assertEqual(main.active['node'],6)
        self.assertEqual(main.active['battles'],3)
        summary=main.active['star']['combat_health']['6:3']
        self.assertEqual(summary['observed_zero']['1']['first']['elapsed'],0)
        self.assertEqual(summary['observed_zero']['1']['last']['elapsed'],120)
        self.assertEqual(summary['observed_zero']['1']['observations'],13)
        self.assertNotIn('frames',summary)

    def test_logs_only_zero_slot_changes_or_thirty_second_cadence(self):
        worker,main,events,saves=self.task()
        samples=[(0,(100,200,300,400)),(10,(90,200,300,400)),(20,(80,200,300,400)),
                 (30,(0,200,300,400)),(40,(0,190,300,400)),(50,None),
                 (60,(0,170,300,400)),(70,(0,0,300,400)),(80,(10,0,300,400))]
        for second,health in samples:self.assertFalse(self.observe_at(worker,second,health))
        self.assertEqual([data['elapsed'] for _,data in events],[0,30,60,70,80])
        self.assertEqual([data['observed_zero_slots'] for _,data in events],[[],[1],[1],[1,2],[2]])
        summary=main.active['star']['combat_health']['6:3']
        self.assertEqual(summary['first']['health'],[100,200,300,400])
        self.assertEqual(summary['last']['health'],[10,0,300,400])
        self.assertEqual(summary['observed_zero']['2']['first']['elapsed'],70)
        self.assertEqual(summary['unknown_samples'],1)
        self.assertEqual(len(saves),len(events))

    def test_partial_none_does_not_create_or_remove_known_zero_slots(self):
        worker,main,events,saves=self.task()
        self.observe_at(worker,0,(0,200,300,400))
        self.observe_at(worker,10,(0,None,300,400))
        self.observe_at(worker,20,(0,200,300,400))
        self.assertEqual(len(events),1)
        summary=main.active['star']['combat_health']['6:3']
        self.assertEqual(summary['last_valid_zero_slots'],[1])
        self.assertEqual(summary['unknown_samples'],1)
        self.assertNotIn('2',summary['observed_zero'])

    def test_reads_at_ten_second_intervals_and_resets_for_new_battle(self):
        worker,main,events,saves=self.task()
        self.observe_at(worker,0,(100,200,300,400))
        with patch('tasks.divergent_universe.star_combat.time.monotonic',return_value=5), \
             patch('tasks.divergent_universe.star_combat.observe_health') as read:
            self.assertFalse(worker.observe())
            read.assert_not_called()
        self.observe_at(worker,10,(100,200,300,400))
        main.active['battles']=4
        self.observe_at(worker,11,(100,200,300,400))
        self.assertEqual(main.active['star']['combat_health']['6:3']['samples'],2)
        self.assertEqual(main.active['star']['combat_health']['6:4']['samples'],1)
        self.assertEqual(events[-1][1]['battle_index'],4)
        self.assertEqual(events[-1][1]['elapsed'],0)

    def test_unverified_or_nonstar_party_does_not_read_health(self):
        for mode,members in [('star',[]),('star',[1410,1005,1309]),('star',[1410,1410,1309,1414]),
                             ('star',[1410,1005,None,1414]),('full',[1410,1005,1309,1414])]:
            with self.subTest(mode=mode,members=members):
                worker,main,events,saves=self.task()
                main.active['mode']=mode
                main.active['star']['member_ids']=members
                with patch('tasks.divergent_universe.star_combat.observe_health') as read:
                    self.assertFalse(worker.observe())
                    read.assert_not_called()
                self.assertEqual(events,[])

    def test_only_original_verified_fuxuan_party_retains_existing_withdrawal(self):
        worker,main,events,saves=self.task('followup_fuxuan',[1220,8008,1403,1208])
        withdrew=[];worker.withdraw=lambda:withdrew.append(True) or True
        with patch('tasks.divergent_universe.star_combat.Path.mkdir'), \
             patch('tasks.divergent_universe.star_combat.save_image'):
            for second in range(0,90,10):
                self.assertFalse(self.observe_at(worker,second,(0,0,0,6284)))
            self.assertTrue(self.observe_at(worker,90,(0,0,0,6284)))
        self.assertEqual(withdrew,[True])
        self.assertEqual(main.active['exit_reason'],'combat_damage_slots_depleted')
        self.assertEqual(events[-1][0],'star_combat_depleted')
        wrong,wrong_main,_,_=self.task('followup_fuxuan',[1220,8008,1403,1414])
        for second in range(0,101,10):
            self.assertFalse(self.observe_at(wrong,second,(0,0,0,6284)))
        self.assertNotIn('stop_requested',wrong_main.active)


if __name__=='__main__':unittest.main()
