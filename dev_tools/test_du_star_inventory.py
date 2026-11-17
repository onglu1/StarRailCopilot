"""A scrolled group heading is not an individual equation's expansion proof."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_inventory import StarInventory


class InventoryTests(unittest.TestCase):
    def numeric_task(self,narrow,expanded,total,fallback='?'):
        order=['记忆','虚无','巡猎','毁灭','欢愉','繁育','智识','同谐']
        calls=[];events=[]
        totals=total if isinstance(total,tuple) else (total,total)
        fields={(194,101,224,122):totals[0],(198,101,224,122):totals[1],
                (193,104,224,118):fallback}
        for index in range(8):
            x=284+100*index
            fields[(x+12,101,x+49,122)]=str(narrow[index])
            fields[(x+6,101,x+49,122)]=str(expanded[index])
        def read(region,**kwargs):
            self.assertIs(kwargs.get('snapshot'),False)
            pixels=tuple(round(value*(1280 if index%2==0 else 720)) for index,value in enumerate(region))
            calls.append(pixels)
            self.assertIn(pixels,fields)
            return SimpleNamespace(source=fields[pixels])
        main=SimpleNamespace(op=SimpleNamespace(read_line=read,snapshot=lambda:None),
            active={'node':14,'star':{'path_counts':{'虚无':99},'inventory_path_counts':{'虚无':99}}},
            world_visible=lambda:False,is_combat_executing=lambda:False,
            progress=SimpleNamespace(data={'star_path_order':order},record=lambda event,**data:events.append((event,data))))
        worker=StarInventory(main);worker.blessing_page=lambda:True
        return worker,main,order,calls,events

    def test_real_truncated_eleven_and_icon_fragment_are_resolved_by_current_total(self):
        # Recorded model outputs from 317424... / inventory_14. The expanded
        # crop restores 11 but also admits the destruction icon as 57.
        worker,main,order,calls,events=self.numeric_task(
            [1,1,0,7,1,6,3,2],[1,11,0,57,1,6,3,2],'31')
        counts,total=worker.read_counts(order)
        self.assertEqual(counts,dict(zip(order,[1,11,0,7,1,6,3,2])))
        self.assertEqual(total,31)
        self.assertEqual(events[-1][0],'star_inventory_counts_reconciled')
        self.assertEqual(len(calls),18)
        self.assertTrue(all(y2-y1==21 and x2-x1<=43 for x1,y1,x2,y2 in calls))

    def test_consistent_real_decrease_is_accepted_without_old_inventory_override(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,5,3,4,1,3,4,1],[1,15,3,54,1,3,4,1],'22')
        counts,total=worker.read_counts(order)
        self.assertEqual((counts['虚无'],counts['毁灭'],total),(5,4,22))
        self.assertEqual(len(calls),18)
        self.assertEqual(events,[])

    def test_unknown_narrow_digit_can_use_one_unique_expanded_reading(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,'?',0,7,1,6,3,2],[1,11,0,57,1,6,3,2],'31')
        self.assertEqual(worker.read_counts(order)[0]['虚无'],11)

    def test_two_different_assignments_with_the_same_total_are_rejected(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,1,0,7,1,6,3,2],[11,11,0,7,1,6,3,2],'31')
        with self.assertRaisesRegex(RuntimeError,'连续3帧'):
            worker.read_counts(order)
        self.assertEqual([event for event,_ in events].count('star_inventory_counts_unverified'),3)
        self.assertEqual(events[-1],('star_inventory_counts_retry',{
            'attempt':3,'reason':'same_frame_total_unreadable_or_not_unique'}))

    def test_inconsistent_sum_never_overwrites_the_existing_observed_inventory(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,1,0,7,1,6,3,2],[1,11,0,57,1,6,3,2],'32')
        before=dict(main.active['star'])
        with self.assertRaisesRegex(RuntimeError,'连续3帧'):
            worker.read(close=False,force=True)
        self.assertEqual(main.active['star'],before)

    def test_unknown_total_is_not_replaced_by_old_counts_or_sum_of_reads(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,11,0,7,1,6,3,2],[1,11,0,7,1,6,3,2],'?')
        with self.assertRaisesRegex(RuntimeError,'连续3帧'):
            worker.read_counts(order)
        self.assertEqual(len(calls),57)

    def test_new_seventeen_frames_use_independent_underline_free_total(self):
        for narrow,expanded in (([2,2,2,4,1,4,2,0],[2,2,2,4,1,4,2,0]),
                                ([2,5,3,1,0,2,2,2],[2,5,3,51,0,2,2,2])):
            with self.subTest(narrow=narrow):
                worker,main,order,calls,events=self.numeric_task(narrow,expanded,('1.7 ','7'),fallback='17')
                counts,total=worker.read_counts_frame(order)
                self.assertEqual((counts,total),(dict(zip(order,narrow)),17))
                self.assertEqual(calls[-1],(193,104,224,118))
                self.assertEqual(len(calls),19)
                self.assertEqual(events[-1][1]['total_readings'][0]['text'],'1.7 ')
                self.assertEqual(events[-1][1]['total_readings'][-1]['text'],'17')

    def test_failed_original_totals_still_collect_expanded_category_candidates(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,1,0,7,1,6,3,2],[1,11,0,57,1,6,3,2],('?','?'),fallback='31')
        counts,total=worker.read_counts_frame(order)
        self.assertEqual((counts['虚无'],counts['毁灭'],total),(11,7,31))
        self.assertEqual(len(calls),19)

    def test_new_total_fallback_never_overrides_ambiguity_or_repairs_punctuation(self):
        from tasks.divergent_universe.star_inventory import InventoryCountsUnverified
        for narrow,expanded,totals,fallback in (
                ([7]+[0]*7,[17]+[0]*7,('7','17'),'17'),
                ([2,2,2,4,1,4,2,0],[2,2,2,4,1,4,2,0],('1.7','7'),'1.7')):
            worker,main,order,calls,events=self.numeric_task(narrow,expanded,totals,fallback=fallback)
            with self.assertRaises(InventoryCountsUnverified):worker.read_counts_frame(order)
            self.assertEqual(main.active['star']['path_counts'],{'虚无':99})

    def test_unique_original_total_does_not_read_the_extra_roi(self):
        worker,main,order,calls,events=self.numeric_task(
            [2,2,2,4,1,4,2,0],[2,2,2,4,1,4,2,0],('17','7'),fallback='99')
        self.assertEqual(worker.read_counts_frame(order)[1],17)
        self.assertEqual(len(calls),18)
        self.assertNotIn((193,104,224,118),calls)

    def test_zero_inventory_is_a_valid_same_frame_observation(self):
        worker,main,order,calls,events=self.numeric_task([0]*8,[0]*8,'0')
        counts,total=worker.read_counts(order)
        self.assertEqual(counts,dict.fromkeys(order,0))
        self.assertEqual(total,0)
        self.assertIn((194,101,224,122),calls)
        self.assertIn((198,101,224,122),calls)
        self.assertNotIn((192,101,224,122),calls)

    def test_eight_zero_categories_never_override_unknown_or_nonzero_total(self):
        for total in ('?','20'):
            with self.subTest(total=total):
                worker,main,order,calls,events=self.numeric_task([0]*8,[0]*8,total)
                with self.assertRaisesRegex(RuntimeError,'连续3帧'):
                    worker.read_counts(order)
                self.assertEqual(main.active['star']['path_counts'],{'虚无':99})
                self.assertNotIn('star_inventory_counts_reconciled',[event for event,_ in events])

    def test_one_transient_bad_frame_retries_and_accepts_only_the_new_complete_frame(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,1,0,7,1,6,3,2],[1,11,0,57,1,6,3,2],'31')
        frames=[0];original=main.op.read_line
        main.op.snapshot=lambda:frames.__setitem__(0,frames[0]+1)
        def read(region,**kwargs):
            if frames[0]==1 and region in ((194/1280,101/720,224/1280,122/720),
                                          (198/1280,101/720,224/1280,122/720)):
                return SimpleNamespace(source='32')
            return original(region,**kwargs)
        main.op.read_line=read
        counts,total=worker.read_counts(order)
        self.assertEqual(frames[0],2)
        self.assertEqual((counts['虚无'],counts['毁灭'],total),(11,7,31))
        self.assertEqual([event for event,_ in events].count('star_inventory_counts_retry'),1)

    def test_counts_from_different_frames_are_never_combined_to_make_a_total(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,1,0,7,1,6,3,2],[1,1,0,7,1,6,3,2],'41')
        frames=[0];original=main.op.read_line
        main.op.snapshot=lambda:frames.__setitem__(0,frames[0]+1)
        def read(region,**kwargs):
            # Each frame offers only one +10 alternative (sum31), never
            # both. Combining candidates across frames would falsely get41.
            chosen=0 if frames[0] in (1,3) else 1
            x=284+chosen*100
            if region==((x+6)/1280,101/720,(x+49)/1280,122/720):
                return SimpleNamespace(source='11')
            return original(region,**kwargs)
        main.op.read_line=read
        with self.assertRaisesRegex(RuntimeError,'连续3帧'):
            worker.read_counts(order)
        self.assertEqual(frames[0],3)
        self.assertNotIn('star_inventory_counts_reconciled',[event for event,_ in events])
        self.assertEqual(main.active['star']['path_counts'],{'虚无':99})

    def test_each_new_frame_requires_the_blessing_inventory_page(self):
        worker,main,order,calls,events=self.numeric_task([0]*8,[0]*8,'0')
        frames=[0]
        main.op.snapshot=lambda:frames.__setitem__(0,frames[0]+1)
        worker.blessing_page=lambda:frames[0]>=2
        self.assertEqual(worker.read_counts(order)[1],0)
        self.assertEqual(frames[0],2)
        self.assertEqual(len(calls),18)
        self.assertEqual(events[0],('star_inventory_counts_retry',{
            'attempt':1,'reason':'blessing_page_unconfirmed'}))

    def test_return_to_world_or_combat_during_number_retry_yields_without_reads(self):
        for destination in ('world','combat'):
            with self.subTest(destination=destination):
                worker,main,order,calls,events=self.numeric_task([0]*8,[0]*8,'0')
                frames=[0];before=dict(main.active['star'])
                main.op.snapshot=lambda:frames.__setitem__(0,frames[0]+1)
                main.world_visible=lambda:destination=='world' and frames[0]>=2
                main.is_combat_executing=lambda:destination=='combat' and frames[0]>=2
                self.assertIsNone(worker.read(close=False,force=True))
                self.assertEqual(calls,[])
                self.assertEqual(main.active['star'],before)
                self.assertEqual(events[-1][0],'star_inventory_page_changed')

    def test_actual_six_uses_independent_total_reading_not_the_icon_prefix(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,3,0,0,0,0,0,2],[1,3,0,0,0,0,0,2],('26 ','6'))
        counts,total=worker.read_counts(order)
        self.assertEqual(total,6)
        self.assertEqual(counts['虚无'],3)
        self.assertEqual(events[-1][1]['total_readings'][0]['text'],'26 ')
        self.assertEqual(events[-1][1]['total_readings'][1]['text'],'6')

    def test_tighter_total_crop_cannot_override_real_tens_in_41_and_46(self):
        for expected,counts,totals in (
                (41,[2,11,1,8,1,7,6,5],('41 ','1 ')),
                (46,[3,11,2,9,1,7,8,5],('46','6'))):
            with self.subTest(expected=expected):
                narrow=list(counts);narrow[1]=1
                worker,main,order,calls,events=self.numeric_task(narrow,counts,totals)
                actual,total=worker.read_counts(order)
                self.assertEqual(total,expected)
                self.assertEqual(actual,dict(zip(order,counts)))

    def test_consistent_first_total_does_not_bypass_another_globally_valid_solution(self):
        # Narrow categories match0, expanded categories can match20, and
        # both totals were actually read. Choosing the first pair is unsafe.
        worker,main,order,calls,events=self.numeric_task([0]*8,[20]+[0]*7,('0','20'))
        with self.assertRaisesRegex(RuntimeError,'连续3帧'):
            worker.read_counts(order)
        self.assertNotIn('star_inventory_counts_reconciled',[event for event,_ in events])
        self.assertEqual(main.active['star']['path_counts'],{'虚无':99})

    def test_category_sum_is_not_used_as_total_without_an_independent_reading(self):
        worker,main,order,calls,events=self.numeric_task(
            [1,3,0,0,0,0,0,2],[1,3,0,0,0,0,0,2],('26','16'))
        with self.assertRaisesRegex(RuntimeError,'连续3帧'):
            worker.read_counts(order)
        self.assertNotIn('star_inventory_counts_reconciled',[event for event,_ in events])

    def test_optional_refresh_returns_when_reward_has_already_closed(self):
        events=[]
        op=SimpleNamespace(snapshot=lambda:None)
        main=SimpleNamespace(op=op,world_visible=lambda:True,is_combat_executing=lambda:False,
                             progress=SimpleNamespace(record=lambda event,**kw:events.append(event)))
        self.assertIsNone(StarInventory(main).read(force=True))
        self.assertEqual(events,['star_inventory_page_changed'])

    def test_world_transition_during_overview_wait_stops_before_more_input(self):
        worker=StarInventory(SimpleNamespace(op=None))
        phase=[0];clicks=[];events=[]
        def wait(predicate,action,**kwargs):
            phase[0]=1
            if predicate():return True
            action()
            self.fail('A completed reward must not wait for a hidden inventory button')
        worker.op=SimpleNamespace(snapshot=lambda:None,read_line=lambda *a,**k:SimpleNamespace(source='选择祝福'),
                                  text=lambda *a,**k:None,click_text=lambda *a,**k:clicks.append(a),wait_until=wait)
        worker.main=SimpleNamespace(op=worker.op,world_visible=lambda:phase[0]==1,is_combat_executing=lambda:False,
            active={'node':13,'star':{}},progress=SimpleNamespace(record=lambda event,**kw:events.append(event)))
        self.assertIsNone(worker.read(force=True))
        self.assertEqual(clicks,[])
        self.assertEqual(events,['star_inventory_page_changed'])

    def test_detail_and_overview_layers_use_their_observed_close_controls(self):
        phase=[0];trace=[]
        def close_detail(*a,**kwargs):
            trace.append('native-close');phase[0]=1;return True
        def collapse(*a,**kwargs):
            trace.append('collapse-overview');phase[0]=2;return True
        def text(names,*a,**kwargs):
            if phase[0]==0 and isinstance(names,tuple):return Box(85,40,80,25,'方程')
            if phase[0]==1 and names=='拥有祝福':return Box(30,30,100,25,'拥有祝福')
            return None
        def wait(predicate,action,**kwargs):
            for _ in range(4):
                if predicate():return True
                action()
            self.fail('The original reward page was not restored')
        op=SimpleNamespace(snapshot=lambda:None,text=text,read_line=lambda *a,**k:Box(85,40,80,25,'方程'),
                           template=lambda *a,**k:Box(1114,248,133,37,'collapse') if phase[0]==1 else None,
                           click_text=collapse,click_box=collapse,wait_until=wait)
        main=SimpleNamespace(op=op,world_visible=lambda:False,is_combat_executing=lambda:False,
                             selection_kind=lambda:'blessing' if phase[0]==2 else None,
                             appear_then_click=close_detail)
        StarInventory(main).close()
        self.assertEqual(trace,['native-close','collapse-overview'])

    def test_late_detail_close_never_clicks_overview_equation_entry(self):
        # The actual fault alternated detail / overview / detail. A detail
        # close request must be dropped if the fresh frame is now overview.
        phase=['detail'];trace=[];snapshots=[]
        def snapshot():
            snapshots.append(phase[0])
            if phase[0]=='detail':phase[0]='overview'
        def text(names,*a,**kwargs):
            if names=='拥有祝福' and phase[0]=='overview':return Box(30,30,100,25,'拥有祝福')
            if isinstance(names,tuple) and phase[0]=='detail':return Box(85,40,80,25,'方程')
            return None
        def collapse(*a,**kwargs):
            self.assertEqual(phase[0],'overview')
            trace.append('collapse-overview');phase[0]='reward';return True
        def wait(predicate,action,**kwargs):
            for _ in range(4):
                if predicate():return True
                action()
            self.fail('Fresh overview was not safely collapsed')
        op=SimpleNamespace(snapshot=snapshot,text=text,read_line=lambda *a,**k:Box(85,40,80,25,''),
            template=lambda *a,**k:Box(1114,248,133,37,'collapse') if phase[0]=='overview' else None,
            click_box=collapse,click_text=collapse,wait_until=wait)
        main=SimpleNamespace(op=op,world_visible=lambda:False,is_combat_executing=lambda:False,
            selection_kind=lambda:'blessing' if phase[0]=='reward' else None,
            appear_then_click=lambda *a,**k:self.fail('Stale GUIDE_CLOSE would reopen equation details'))
        StarInventory(main).close()
        self.assertEqual(trace,['collapse-overview'])
        self.assertEqual(snapshots,['detail','overview'])

    def test_close_revalidation_yields_to_world_without_touching_it(self):
        phase=['detail'];clicks=[]
        def wait(predicate,action,**kwargs):
            self.assertFalse(predicate())
            action()
            self.assertTrue(predicate())
            return True
        op=SimpleNamespace(snapshot=lambda:phase.__setitem__(0,'world'),
            text=lambda names,*a,**k:Box(85,40,80,25,'方程') if isinstance(names,tuple) else None,
            read_line=lambda *a,**k:Box(85,40,80,25,''),wait_until=wait)
        main=SimpleNamespace(op=op,world_visible=lambda:phase[0]=='world',is_combat_executing=lambda:False,
            selection_kind=lambda:None,appear_then_click=lambda *a,**k:clicks.append(a))
        StarInventory(main).close()
        self.assertEqual(clicks,[])

    def test_mixed_groups_require_each_cards_own_expanded_marker(self):
        names=[Box(230,350,120,30,'打榜双子星'),Box(845,350,125,30,'星星盗贼')]
        tabs=[Box(160,90,90,30,'已展开1'),Box(280,90,90,30,'未展开3')]
        markers=[Box(160,202,62,21,'已展开')]
        op=SimpleNamespace(image=None,read_line=lambda *a,**k:Box(150,140,170,30,'已展开方程'),
                           read_region=lambda region,**k:tabs if region[1]<.2 else names,
                           match=lambda *a,**k:markers)
        main=SimpleNamespace(op=op,config=SimpleNamespace(config_name='offline-fixture'),
                             active={'id':'fixture','node':11,'star':{}},
                             star_loadout=SimpleNamespace(core_equations=('星星盗贼',)),
                             progress=SimpleNamespace(record=lambda *a,**k:None,save=lambda *a:None))
        with patch('tasks.divergent_universe.star_inventory.save_image'),patch.object(Path,'mkdir'):
            StarInventory(main).observe_equations()
            observed=main.active['star']['equation_inventory']
            self.assertEqual(observed['visible_names'],['打榜双子星','星星盗贼'])
            self.assertEqual(observed['visible_expanded_names'],['打榜双子星'])
            self.assertEqual(observed['visible_expanded_core'],[])
            markers[:]=[Box(786,202,62,21,'已展开')]
            StarInventory(main).observe_equations()
        self.assertEqual(main.active['star']['equation_inventory']['visible_expanded_core'],['星星盗贼'])


if __name__=='__main__':unittest.main()
