"""Bound optional workshop approach without changing the room/result."""
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_workshop import StarWorkshop,parse_rewrite_count
from tasks.divergent_universe.divergent_universe import DivergentUniverse


class WorkshopTests(unittest.TestCase):
    def test_offscreen_primary_chip_is_revealed_before_giving_up_on_blessing_rewrite(self):
        import numpy as np
        worker,main,trace=self.task();visible=[False]
        main.op.image=np.zeros((720,1280,3),dtype=np.uint8)
        main.op.snapshot=lambda:None
        main.op.text=lambda *a,**k:Box(600,104,65,24,'除魔士') if visible[0] else None
        worker.blessing_rewrite_progress=lambda primary:({'巡猎':6,'繁育':7},{'巡猎':9,'繁育':6}) if visible[0] else None
        def drag(start,end,**kwargs):
            trace.append((start,end));visible[0]=True;main.op.image[95:170,40:1230]=255
        main.device=SimpleNamespace(drag=drag,stuck_record_clear=lambda:None,click_record_clear=lambda:None)
        main.wait_until_stable=lambda *a:None
        def wait(predicate,action=None,**kwargs):
            for _ in range(4):
                result=predicate()
                if result:return result
                action()
            self.fail('Primary equation remained hidden')
        main.op.wait_until=wait
        self.assertEqual(worker.find_blessing_rewrite_progress('除魔士'),({'巡猎':6,'繁育':7},{'巡猎':9,'繁育':6}))
        self.assertEqual(trace,[((1130,133),(470,133))])

    def test_low_contrast_count_uses_detected_slash_without_guessing_digits(self):
        worker,main,_=self.task()
        main.op.text=lambda *a,**k:Box(959,104,58,24,'除魔士')
        main.op.read_line=lambda region,**k:Box(0,0,50,30,'6/9' if region[0]<(959+100)/1280 else '716')
        main.op.read_region=lambda *a,**k:[Box(1067,131,40,24,'7/6')]
        self.assertEqual(worker.blessing_rewrite_progress('除魔士'),({'巡猎':6,'繁育':7},{'巡猎':9,'繁育':6}))
        main.op.read_region=lambda *a,**k:[]
        self.assertIsNone(worker.blessing_rewrite_progress('除魔士'))

    def test_rewrite_accepts_another_equation_set_before_returning_to_list(self):
        worker,main,trace=self.task();frames=['equation','equation','list']
        main.selection_kind=lambda:frames[0]
        main.op.text=lambda name,*a,**k:Box(80,30,100,25,'方程覆写') if name=='方程覆写' and frames[0]=='list' else None
        main.handle_choice=lambda kind:(trace.append(kind),frames.pop(0))
        def wait(predicate,action,**kwargs):
            for _ in range(5):
                if predicate():return True
                action()
            raise RuntimeError('fixture timeout')
        main.op.wait_until=wait
        self.assertTrue(worker.finish_equation_rewrite())
        self.assertEqual(trace,['equation','equation'])
        self.assertNotIn('rewrites',worker.state())

    def test_rewrite_followup_has_bounded_choices_without_repaying(self):
        worker,main,trace=self.task()
        main.selection_kind=lambda:'equation'
        main.handle_choice=lambda kind:trace.append(kind)
        def wait(predicate,action,**kwargs):
            for _ in range(10):
                if predicate():return True
                action()
            raise RuntimeError('返回方程覆写列表超时')
        main.op.wait_until=wait
        with self.assertRaisesRegex(RuntimeError,'返回方程覆写列表超时'):
            worker.finish_equation_rewrite()
        self.assertEqual(trace,['equation']*6)
        self.assertNotIn('rewrites',worker.state())

    def test_workshop_title_can_precede_rendered_menu_text(self):
        worker,main,trace=self.task();rendered=[False];loaded=[False]
        main.wait_until_stable=lambda *a:None
        main.op.snapshot=lambda:None
        def text(names,region,**kwargs):
            if names==worker.NAMES:return Box(80,30,150,25,'造物调试台')
            if names=='选择加权奇物' and region[0]==.62 and rendered[0]:return Box(810,310,140,25,'选择加权奇物')
            if loaded[0] and (names=='加权奇物' or names==('方程覆写','祝福覆写','加权奇物','祝福强化')):return Box(80,30,150,25,'加权奇物')
        main.op.text=text
        def wait(predicate,**kwargs):
            if kwargs.get('name')=='造物台菜单项加载':rendered[0]=True
            return predicate()
        main.op.wait_until=wait
        main.op.click_box=lambda *a,**k:loaded.__setitem__(0,True) or True
        worker.equip_weighted=lambda:True
        self.assertTrue(worker.handle())
        self.assertTrue(rendered[0])
        self.assertTrue(loaded[0])

    def test_verified_forge_menu_is_not_given_to_legacy_close_on_narrow_header_miss(self):
        worker,main,trace=self.task();loaded=[False];header_reads=[0]
        main.forge_panel_visible=lambda:not loaded[0]
        main.wait_until_stable=lambda *a:None
        main.op.snapshot=lambda:None
        def text(names,region,**kwargs):
            if names==worker.NAMES:
                header_reads[0]+=1
                return None if header_reads[0]==1 else Box(85,40,150,25,'造物调试台')
            if names=='选择加权奇物' and region[0]==.62 and not loaded[0]:
                return Box(801,309,131,24,'选择加权奇物')
            if loaded[0] and (names=='加权奇物' or names==('方程覆写','祝福覆写','加权奇物','祝福强化')):
                return Box(85,40,150,25,'加权奇物')
            return None
        main.op.text=text
        def click(box,**kwargs):
            trace.append(box.source)
            if len(trace)==2:loaded[0]=True
            return True
        main.op.click_box=click
        def wait(predicate,action=None,**kwargs):
            for _ in range(4):
                result=predicate()
                if result:return result
                if action:action()
            self.fail('Visible forge function was not retried')
        main.op.wait_until=wait
        worker.equip_weighted=lambda:True
        self.assertTrue(worker.handle())
        self.assertEqual(trace,['选择加权奇物','选择加权奇物'])
        self.assertFalse(main.active['node_done'])

    def test_heat_counter_accepts_observed_terminal_dot_but_not_decimals(self):
        worker,main,_=self.task()
        main.op.text=lambda *a,**k:Box(0,0,100,25,'verified heading')
        for value,expected in [('4.',4),('4',4),('20',20),('4.3',None),('21',None),('?',None)]:
            main.op.read_line=lambda *a,**k:Box(0,0,32,28,value)
            self.assertEqual(worker.enhancement_heat(),expected,value)

    def test_unreadable_final_enhancement_cost_exits_optional_step_without_purchase(self):
        worker,main,trace=self.task()
        main.star_loadout=SimpleNamespace(core_equations=('unknown',),survival_blessings=('双极喷流',))
        main.progress.data={'star_path_order':['毁灭','欢愉','巡猎','虚无','记忆','繁育','智识','同谐']}
        main.wait_until_stable=lambda *a:None
        main.confirm_enabled=lambda button:True
        main.op.snapshot=lambda:None
        main.op.text=lambda label,*a,**k:None if label=='暂无可强化祝福' else Box(1080,640,60,30,str(label))
        main.op.read_region=lambda region,**k:[Box(90,315,100,30,'双极喷流')] if region[1]==.43 else []
        main.op.click_box=lambda box,**k:trace.append(box.source) or True
        main.op.wait_until=lambda predicate,**k:predicate()
        worker.enhancement_heat=lambda:5
        worker.enhancement_title=lambda:'双极喷流'
        costs=iter([1,None]);worker.enhancement_cost=lambda:next(costs)
        worker.return_to_menu=lambda:True
        self.assertTrue(worker.enhance())
        self.assertEqual(worker.state()['enhancement_outcome'],'selected_cost_unverified')
        self.assertEqual(trace,['双极喷流'])
        self.assertEqual(worker.state()['enhanced'],[])
        self.assertFalse(main.active['node_done'])

    def test_enhancement_digit_crop_avoids_multiplier_misread(self):
        worker,main,_=self.task()
        main.op.read_line=lambda region,**k:Box(945,640,21,34,'1' if region[0]==945/1280 else '.1')
        self.assertEqual(worker.enhancement_cost(),1)
        main.op.read_line=lambda region,**k:Box(940,641,35,35,'' if region[0]==945/1280 else 'x3')
        self.assertEqual(worker.enhancement_cost(),3)
        main.op.read_line=lambda region,**k:Box(940,641,35,35,'?')
        self.assertIsNone(worker.enhancement_cost())

    def test_visible_workshop_does_not_exhaust_after_twelve_distant_steps(self):
        worker,main,trace=self.task()
        main.event_direction=lambda box:-17.2
        main.op.text=lambda names,region,**k:Box(405,186,95,24,'造物调试台') if region==(.035,.15,.88,.46) else None
        worker.state()['moves']=12
        self.assertTrue(worker.navigate())
        self.assertEqual(worker.state()['moves'],13)
        self.assertEqual(trace[0][0],'move')
        worker.state()['moves']=worker.MAX_APPROACH_MOVES
        self.assertFalse(worker.navigate())
        self.assertEqual(len(trace),1)
        self.assertFalse(main.active['node_done'])

    def test_absent_workshop_search_covers_a_full_turn_then_stops(self):
        worker,main,trace=self.task()
        for _ in range(worker.MAX_SEARCH_TURNS):
            self.assertTrue(worker.navigate())
        self.assertFalse(worker.navigate())
        self.assertEqual(sum(row[1][0] for row in trace),360)
        self.assertFalse(main.active['node_done'])

    def test_selected_known_weighted_can_equip_without_unselected_icon_match(self):
        worker,main,trace=self.task()
        import json
        from pathlib import Path
        guides=json.loads((Path(__file__).resolve().parents[1]/'tasks/divergent_universe/star_guides.json').read_text('utf-8'))
        code=next(g['code'] for g in guides['guides'] if g['key']=='followup')
        main.star_loadout=SimpleNamespace(candidate='followup',guide_code=code)
        count=[0]
        main.op.read_line=lambda *a,**k:Box(40,90,200,25,f'{count[0]}/1')
        main.op.read_region=lambda *a,**k:[Box(880,90,180,25,'平行宇宙对讲机')]
        main.op.text=lambda *a,**k:Box(1000,640,100,30,'装备')
        main.op.wait_until=lambda predicate,**k:predicate()
        main.op.template_matches=lambda *a,**k:self.fail('The selected exact title is already verified')
        main.op.templates=Path('tasks/divergent_universe/templates')
        main.progress.record=lambda event,**data:trace.append((event,data))
        main.op.click_box=lambda box,**k:count.__setitem__(0,count[0]+1) or True
        worker.save_frame=lambda name:name+'.png'
        self.assertTrue(worker.equip_weighted())
        equipment=main.active['star']['weighted_equipment']
        self.assertEqual([(e['id'],e['name']) for e in equipment],[(1016,'平行宇宙对讲机')])
        self.assertFalse(main.active['node_done'])

    def test_recommended_weighted_uses_the_same_observed_title_alias_after_click(self):
        worker,main,trace=self.task()
        import json
        from pathlib import Path
        guides=json.loads((Path(__file__).resolve().parents[1]/'tasks/divergent_universe/star_guides.json').read_text('utf-8'))
        main.star_loadout=SimpleNamespace(candidate='dot',guide_code=next(g['code'] for g in guides['guides'] if g['key']=='dot'))
        main.active['star'].update(run_guide_verified=True,weighted_equipment=[{'id':1004,'name':'祈祷之路'}])
        count=[1];title=['祈祷之路']
        main.op.read_line=lambda *a,**k:Box(40,90,200,25,f'{count[0]}/2')
        main.op.read_region=lambda *a,**k:[Box(880,90,180,25,title[0])]
        main.op.text=lambda name,*a,**k:Box(1000,640,100,30,'装备') if name in ('装备',('装备','卸下')) else None
        main.op.wait_until=lambda predicate,**k:predicate()
        main.op.templates=Path('tasks/divergent_universe/templates')
        main.op.template_matches=lambda path,*a,**k:[Box(250,150,20,20,'recommended')] if 'recommended' in path else []
        main.wait_until_stable=lambda *a:None
        main.op.snapshot=lambda:None
        def click(box,**kwargs):
            trace.append(box.source)
            if box.source=='装备':count[0]+=1
            else:title[0]='尊严与热忧'
            return True
        main.op.click_box=click
        self.assertTrue(worker.equip_weighted())
        self.assertEqual([(x['id'],x['name']) for x in main.active['star']['weighted_equipment']],
                         [(1004,'祈祷之路'),(1009,'尊严与热忱')])
        self.assertEqual(trace.count('装备'),1)

    def test_unaccepted_initial_workshop_interaction_retries_current_prompt(self):
        worker,main,trace=self.task();visible=[True]
        main.world_visible=lambda:visible[0]
        main.op.text=lambda *a,**k:Box(820,410,160,25,'造物调试台')
        def interact(*a,**k):
            trace.append('interact')
            if len(trace)==2:visible[0]=False
            return True
        main.interact_with_label=interact
        def wait(predicate,action=None,**kwargs):
            for _ in range(4):
                if predicate():return True
                action()
            self.fail('Current visible workshop prompt was not retried')
        main.op.wait_until=wait
        self.assertTrue(worker.navigate())
        self.assertEqual(trace,['interact','interact'])

    def test_lost_workshop_prompt_uses_fresh_label_for_one_bounded_correction(self):
        worker,main,trace=self.task();visible=[True];near=[False]
        main.world_visible=lambda:visible[0]
        def text(names,region,**kwargs):
            if region==(.58,.48,.92,.70):
                return Box(820,410,160,25,'造物调试台') if near[0] else None
            return Box(120,180,160,25,'造物调试台')
        main.op.text=text
        main.event_direction=lambda target:23.5
        def move(direction,*a,**k):trace.append(('move',direction));near[0]=True
        main.move=move
        def interact(*a,**k):trace.append(('interact',));visible[0]=False;return True
        main.interact_with_label=interact
        def wait(predicate,action=None,**kwargs):
            for _ in range(5):
                if predicate():return True
                action()
            self.fail('Correction did not restore the prompt')
        main.op.wait_until=wait
        class ReadyTimer:
            def __init__(self,*a,**k):pass
            def start(self):return self
            def reached(self):return True
            def reset(self):pass
        with patch('tasks.divergent_universe.star_workshop.Timer',ReadyTimer):
            worker.wait_for_panel()
        self.assertEqual(trace,[('move',23.5),('interact',)])

    def test_rewrite_preview_reads_owned_count_before_the_arrow(self):
        for text in ('4>3/6','4》3/6','4»3/6','4≫3/6','4→3/6'):
            self.assertEqual(parse_rewrite_count(text),(4,6))
        self.assertEqual(parse_rewrite_count('2/9 ('),(2,9))
        for text in ('4>3/','4>8/6','未知','4/0'):
            self.assertIsNone(parse_rewrite_count(text))

    def test_confirmed_rewrite_records_spending_even_if_later_count_ocr_fails(self):
        worker,main,_=self.task()
        main.star_loadout=SimpleNamespace(core_equations=('拒火者',),survival_blessings=())
        main.active['star']['choices']=[]
        events=[]
        main.progress.record=lambda event,**data:events.append((event,data))
        worker.blessing_rewrite_progress=lambda primary:({'欢愉':1,'毁灭':2},{'欢愉':9,'毁灭':6})
        worker.blessing_rewrite_cards=lambda:[(Box(70,360,100,25,'正直的诺姆'),'正直的诺姆')]
        worker.blessing_rewrite_title=lambda:'正直的诺姆'
        worker.return_to_menu=lambda:True
        main.selection_kind=lambda:'blessing'
        main.handle_choice=lambda kind:None
        main.confirm_enabled=lambda b:True
        main.op.read_line=lambda region,**k:Box(0,0,20,20,'75' if region[0]<.5 else '200')
        main.op.text=lambda name,*a,**k:None if name=='已强化' else Box(1000,635,100,30,str(name))
        main.op.click_box=lambda *a,**k:True
        def wait(predicate,**kwargs):
            if kwargs.get('name')=='覆写后核心计数':
                raise RuntimeError('覆写后核心计数超时，目标界面未出现')
            return predicate()
        main.op.wait_until=wait
        self.assertTrue(worker.rewrite_blessings())
        self.assertEqual(worker.state()['blessing_rewrite_spent'],75)
        self.assertEqual(worker.state()['blessing_rewrite_reserved'],75)
        self.assertEqual(worker.state()['blessing_rewrite_outcome'],'core_counts_unreadable_after_confirmed_choice')
        observed=next(data for event,data in events if event=='star_blessing_rewrite_observed')
        self.assertIsNone(observed['core_counts'])
        self.assertFalse(main.active['node_done'])

    def test_primary_deficit_reserves_money_for_blessings_before_secondary_rewrites(self):
        worker,main,trace=self.task()
        main.star_loadout=SimpleNamespace(core_equations=('除魔士','铁臂侠'))
        main.active['star'].update(observed_equation_requirements={'除魔士':{'巡猎':9,'繁育':6}},
                                   path_counts={'巡猎':0,'繁育':3})
        worker.equation_cards=lambda:[(Box(50,200,100,100,'除魔士'),'除魔士'),
                                      (Box(200,200,100,100,'以太骇客'),'以太骇客')]
        def wait(predicate,**kwargs):
            return predicate() or predicate()
        main.op.wait_until=wait
        main.op.click_box=lambda *a,**k:self.fail('Do not pay for a secondary equation while the primary is empty')
        worker.return_to_menu=lambda:True
        self.assertTrue(worker.rewrite())
        self.assertTrue(worker.state()['rewrite_done'])
        self.assertEqual(worker.state()['rewrite_outcome'],'primary_needs_blessings')
        self.assertFalse(worker.state()['done'])

    def test_later_rewrite_price_can_use_real_funds_but_not_exceed_reserved_budget(self):
        worker,main,trace=self.task()
        main.star_loadout=SimpleNamespace(core_equations=('拒火者',),survival_blessings=())
        main.active['star']['choices']=[]
        worker.blessing_rewrite_progress=lambda primary:({'欢愉':1,'毁灭':2},{'欢愉':9,'毁灭':6})
        worker.blessing_rewrite_cards=lambda:[(Box(70,360,100,25,'正直的诺姆'),'正直的诺姆')]
        worker.blessing_rewrite_title=lambda:'正直的诺姆'
        worker.return_to_menu=lambda:True
        main.selection_kind=lambda:'blessing';main.handle_choice=lambda kind:None
        main.confirm_enabled=lambda b:True
        main.op.read_line=lambda region,**k:Box(0,0,20,20,'125' if region[0]<.5 else '250')
        main.op.text=lambda name,*a,**k:None if name=='已强化' else Box(1000,635,100,30,str(name))
        main.op.click_box=lambda *a,**k:trace.append('purchase') or True
        main.op.wait_until=lambda predicate,**kwargs:predicate()
        self.assertTrue(worker.rewrite_blessings())
        self.assertEqual(worker.state()['blessing_rewrite_spent'],125)
        self.assertEqual(worker.state()['blessing_rewrite_budget'],250)
        worker.state()['blessing_rewrite_reserved']=200
        self.assertTrue(worker.rewrite_blessings())
        self.assertEqual(trace,['purchase'])
        self.assertEqual(worker.state()['blessing_rewrite_outcome'],'blessing_rewrite_cost_budget')

    def test_observed_core_requirements_allow_deferred_secondary_equations_afterward(self):
        worker,main,_=self.task()
        main.star_loadout=SimpleNamespace(core_equations=('除魔士',))
        worker.state().update(rewrite_done=True,rewrite_outcome='primary_needs_blessings')
        worker.blessing_rewrite_progress=lambda primary:({'巡猎':9,'繁育':6},{'巡猎':9,'繁育':6})
        worker.return_to_menu=lambda:True
        self.assertTrue(worker.rewrite_blessings())
        self.assertTrue(worker.state()['blessing_rewrite_done'])
        self.assertFalse(worker.state()['rewrite_done'])
        self.assertEqual(main.active['star']['path_counts'],{'巡猎':9,'繁育':6})
        self.assertFalse(main.active['node_done'])

    def test_scrolled_grid_uses_observed_row_y_instead_of_old_fixed_caption_band(self):
        worker,main,_=self.task()
        worker.state()['blessing_grid_scrolled']=True
        calls=[]
        def read(region,**kwargs):
            calls.append(region)
            if region[2]==.18:
                return [Box(65,472,100,30,'背翼')]
            self.assertLessEqual(region[1]*720,472)
            self.assertGreaterEqual(region[3]*720,502)
            return [Box(65,472,100,30,'背翼'),Box(250,472,140,30,'光学导引的透镜')]
        main.op.read_region=read
        self.assertEqual([name for _,name in worker.blessing_rewrite_cards()],['背翼','光学导引的透镜'])
        self.assertEqual(len(calls),2)

    def test_swallowed_scroll_is_retried_only_within_budget_and_does_not_clear_watchdog(self):
        worker,main,trace=self.task()
        worker.state()['blessing_scrolls']=7
        main.op.snapshot=lambda:None
        main.op.text=lambda *a,**k:Box(40,30,160,30,'祝福覆写')
        main.wait_until_stable=lambda *a:None
        main.device=SimpleNamespace(drag=lambda *a,**k:trace.append('drag'),
                                    stuck_record_clear=lambda:trace.append('clear'),click_record_clear=lambda:trace.append('clear'))
        class Bar:
            length=160;total=460;name='fixture-scroll'
            def __init__(self,*a,**k):pass
            def match_color(self,*a):return None
            def cal_position(self,*a):return 0
            def position_to_screen(self,position,**kwargs):return (853,int(234+position*460),858,int(234+position*460))
        with patch('module.ui.scroll.Scroll',Bar):
            self.assertTrue(worker.scroll_blessing_list())
            self.assertFalse(worker.scroll_blessing_list())
        self.assertEqual(trace,['drag'])
        self.assertEqual(worker.state()['blessing_scroll_outcome'],'scan_budget_reached')
        self.assertFalse(main.active['node_done'])

    def test_equation_confirmation_returns_to_owner_before_next_rewrite(self):
        main=object.__new__(DivergentUniverse)
        main.active={'star':{}}
        main.star_loadout=SimpleNamespace(revision='star-workshop-v5')
        frame=0
        def snapshot():
            nonlocal frame
            frame+=1
        main.op=SimpleNamespace(snapshot=snapshot,click_box=lambda *a:True,
            text=lambda text,*a,**k:Box(40,25,180,40,'方程覆写') if frame==2 and text=='方程覆写' else None)
        main.selection_kind=lambda:'equation' if frame<2 else None
        main.selection_names=lambda *a:('拒火者','星星盗贼','除魔士')
        main.choice_confirm_button=lambda:Box(1000,630,120,40,'确认')
        main.world_visible=main.is_combat_executing=main.lobby_visible=lambda:False
        main.handle_misc=lambda:self.fail('A confirmed rewrite must not recursively enter the workshop')
        main.confirm_selection('equation')
        self.assertEqual(frame,2)

    def task(self):
        trace=[]
        main=SimpleNamespace(active={'id':'retained','node':8,'station':'铸造','node_done':False,'star':{}},
                             _node_done=False,ROTATION_BOX=(410,180,990,300))
        main.progress=SimpleNamespace(save=lambda *a:None,record=lambda *a,**k:None)
        main.op=SimpleNamespace(text=lambda *a,**k:None,wait_until=lambda *a,**k:None)
        main.move=lambda *a,**k:trace.append(('move',a,k))
        main.rotation_swipe=lambda *a,**k:trace.append(('rotate',a,k))
        main.interact_with_label=lambda *a,**k:trace.append(('interact',a,k)) or True
        main.world_visible=lambda:False
        main.forge_panel_visible=lambda:False
        main.reward_close_button=lambda:None
        worker=StarWorkshop(main);worker.save_frame=lambda *a:'fixture.png'
        return worker,main,trace

    def test_occluded_known_heading_is_bounded_then_rescans(self):
        worker,main,trace=self.task()
        worker.state().update(last_direction=12.5,last_seen=time.monotonic(),occluded_steps=0)
        for _ in range(4):self.assertTrue(worker.navigate())
        self.assertEqual([event[0] for event in trace],['move','move','move','rotate'])
        self.assertNotIn('last_direction',worker.state())
        self.assertEqual(main.active['id'],'retained')
        self.assertFalse(main.active['node_done'])

    def test_expired_heading_is_not_reused_after_reload_or_long_pause(self):
        worker,_,trace=self.task()
        worker.state().update(last_direction=12.5,last_seen=time.monotonic()-60)
        worker.navigate()
        self.assertEqual(trace[0][0],'rotate')

    def test_actual_prompt_can_recover_a_failed_search_but_not_repeat_finished_spending(self):
        worker,main,trace=self.task()
        main.op.text=lambda *a,**k:Box(822,410,140,25,'造物调试台')
        worker.state().update(done=True,outcome='no_reachable_workshop')
        self.assertTrue(worker.navigate())
        self.assertEqual(trace[0][0],'interact')
        worker.state().update(done=True,outcome='insufficient_rewrite_reserve')
        self.assertFalse(worker.navigate())
        self.assertEqual(len(trace),1)

    def test_second_menu_layer_closes_without_claiming_room_completed(self):
        worker,main,trace=self.task()
        worker.state().update(done=True,outcome='rewrite_budget_reached')
        worker.visible=lambda:True
        frames=[False,False,True]
        main.world_visible=lambda:frames[0]
        main.appear_then_click=lambda *a,**k:trace.append(('close',a,k)) or True
        def wait(predicate,action,**kwargs):
            for _ in range(3):
                if predicate():return True
                action();frames.pop(0)
            raise RuntimeError('fixture timeout')
        main.op.wait_until=wait
        self.assertTrue(worker.handle())
        self.assertEqual(len(trace),2)
        self.assertEqual(trace[0][0],'close')
        self.assertFalse(main.active['node_done'])
        self.assertNotIn('event_completed',main.active)

    def test_finished_workshop_world_label_never_clicks_close(self):
        worker,main,trace=self.task()
        worker.state()['done']=True
        worker.visible=lambda:True
        main.world_visible=lambda:True
        main.appear_then_click=lambda *a,**k:self.fail('World label is not a closeable menu')
        self.assertFalse(worker.handle())

    def test_unresponsive_workshop_close_has_three_request_limit(self):
        worker,main,trace=self.task()
        worker.visible=lambda:True
        main.appear_then_click=lambda *a,**k:trace.append('close') or True
        def wait(predicate,action,**kwargs):
            for _ in range(10):
                if predicate():return True
                action()
            raise RuntimeError('退出造物台返回场景超时')
        main.op.wait_until=wait
        with self.assertRaisesRegex(RuntimeError,'返回场景超时'):
            worker.close_panel()
        self.assertEqual(trace,['close']*3)
        self.assertFalse(main.active['node_done'])

    def test_v6_rewrite_budget_does_not_skip_independent_enhancement_heat(self):
        worker,main,trace=self.task()
        main.star_loadout=SimpleNamespace(revision='star-workshop-v6')
        main.appear_then_click=lambda *a,**k:trace.append(('close',a,k)) or True
        worker.close('insufficient_rewrite_reserve')
        self.assertTrue(worker.state()['rewrite_done'])
        self.assertFalse(worker.state()['done'])
        self.assertFalse(main.active['node_done'])

    def test_finished_rewrite_waits_for_menu_instead_of_reading_fading_cards(self):
        worker,main,trace=self.task()
        worker.state()['rewrite_done']=True
        main.op.text=lambda label,*a,**k:Box(85,40,120,30,'方程覆写') if label=='方程覆写' else None
        worker.rewrite=lambda:self.fail('Do not re-enter the closed equation page')
        worker.return_to_menu=lambda:trace.append(('return_to_menu',)) or True
        self.assertTrue(worker.handle())
        self.assertEqual(trace,[('return_to_menu',)])

    def test_confirmed_reentry_rearms_only_navigation_once(self):
        worker,main,trace=self.task()
        worker.state().update(entered=True,scans=6,moves=12,rewrites=3,enhanced=['受迫性跃迁'])
        self.assertTrue(worker.resume_approach(1))
        self.assertEqual((worker.state()['scans'],worker.state()['moves']),(0,0))
        self.assertEqual(worker.state()['rewrites'],3)
        self.assertEqual(worker.state()['enhanced'],['受迫性跃迁'])
        worker.state()['moves']=4
        self.assertFalse(worker.resume_approach(1))
        self.assertEqual(worker.state()['moves'],4)
        worker.state()['done']=True
        self.assertFalse(worker.resume_approach(2))

    def test_reward_overlay_is_closed_before_reading_workshop_values(self):
        worker,main,trace=self.task()
        main.reward_close_button=lambda:Box(568,650,140,30,'点击空白处关闭')
        main.op.text=lambda *a,**k:Box(555,50,160,40,'祝福强化')
        main.op.click_box=lambda b,**k:trace.append(b.source) or True
        worker.enhance=lambda:self.fail('An obtained-reward overlay has no heat counter')
        self.assertTrue(worker.handle())
        self.assertEqual(trace,['点击空白处关闭'])


if __name__=='__main__':unittest.main()
