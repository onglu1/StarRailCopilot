"""Local fixtures for the bounded v8 workshop growth experiment; no device/OCR."""
from types import SimpleNamespace
import unittest

from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_workshop import StarWorkshop


class GrowthTests(unittest.TestCase):
    def task(self,revision='star-workshop-v8'):
        events=[];payments=[]
        main=SimpleNamespace(active={'id':'retained','node':6,'station':'首领','star':{
            'choices':[], 'observed_equation_requirements':{
                '概念献祭典仪':{'虚无':9,'毁灭':6},
                '据说之地':{'虚无':3,'毁灭':3},
                '痴王':{'虚无':6,'欢愉':4},
                '超级体育生':{'智识':6,'巡猎':4}}}},
            star_loadout=SimpleNamespace(revision=revision,candidate='dot',core_equations=('概念献祭典仪',),survival_blessings=()))
        main.progress=SimpleNamespace(save=lambda *a:None,record=lambda event,**data:events.append((event,data)))
        def wait(predicate,action=None,**kwargs):
            for _ in range(3):
                result=predicate()
                if result:return result
                if action:action()
            raise RuntimeError(kwargs.get('name','fixture')+'超时')
        main.op=SimpleNamespace(wait_until=wait,text=lambda *a,**k:None,
            read_region=lambda *a,**k:[],snapshot=lambda:None)
        main.confirm_enabled=lambda button:True
        worker=StarWorkshop(main)
        worker.save_frame=lambda *a:'fixture.png'
        worker.return_to_menu=lambda:True
        return worker,main,events,payments

    def equation_task(self,revision='star-workshop-v8',funds=900):
        worker,main,events,payments=self.task(revision)
        money=[funds];cost=[50];screen=['list']
        target=Box(100,260,100,30,'拒火者')
        worker.equation_cards=lambda:[(target,'拒火者')]
        worker.selected_equation=lambda:'拒火者'
        main.op.read_line=lambda region,**k:Box(0,0,30,20,str(cost[0] if region[0]==.72 else money[0]))
        main.op.text=lambda name,*a,**k:Box(1000,640,80,30,'覆写') if name=='覆写' else None
        def click(box,**kwargs):
            if box.source=='覆写':
                payments.append(cost[0]);money[0]-=cost[0];screen[0]='equation'
            return True
        main.op.click_box=click
        main.selection_kind=lambda:screen[0]
        worker.finish_equation_rewrite=lambda:screen.__setitem__(0,'list')
        return worker,main,events,payments,money,cost

    def bridge_task(self,visible=('据说之地','痴王','超级体育生')):
        worker,main,events,payments=self.task()
        progress={'据说之地':({'虚无':5,'毁灭':2},{'虚无':3,'毁灭':3}),
                  '痴王':({'虚无':5,'欢愉':3},{'虚无':6,'欢愉':4}),
                  '超级体育生':({'智识':5,'巡猎':4},{'智识':6,'巡猎':4})}
        main.op.read_region=lambda region,**k:([Box(880,240,60,25,'智识')] if region==(.685,.33,.81,.375) else
            [Box(200+i*200,100,100,25,name) for i,name in enumerate(visible)])
        worker.blessing_rewrite_progress=lambda name:progress.get(name) if name in visible else None
        worker.blessing_rewrite_cards=lambda:[(Box(70,360,100,25,'正直的诺姆'),'正直的诺姆')]
        worker.blessing_rewrite_title=lambda:'正直的诺姆'
        main.op.read_line=lambda region,**k:Box(0,0,30,20,'25' if region[0]<.5 else '400')
        main.op.text=lambda name,*a,**k:None if name=='已强化' else Box(1000,640,90,30,str(name))
        main.op.click_box=lambda box,**k:payments.append(box.source) or True
        main.selection_kind=lambda:'blessing'
        main.handle_choice=lambda kind:progress.update({'据说之地':({'虚无':5,'毁灭':3},{'虚无':3,'毁灭':3})})
        return worker,main,events,payments,progress

    def test_v8_reserves_majority_and_stops_before_exceeding_initial_budget(self):
        worker,main,events,payments,money,cost=self.equation_task(funds=300)
        worker.rewrite()
        self.assertEqual(worker.state()['equation_rewrite_budget'],100)
        self.assertEqual(worker.state()['equation_rewrite_reserved'],50)
        cost[0]=100
        worker.rewrite()
        self.assertEqual(payments,[50])
        self.assertEqual(worker.state()['rewrite_outcome'],'equation_rewrite_growth_budget')
        self.assertEqual(money[0],250)
        self.assertFalse(worker.state()['done'])

    def test_v8_caps_two_requests_even_with_affordable_remaining_budget(self):
        worker,main,events,payments,money,cost=self.equation_task()
        worker.rewrite();worker.rewrite();worker.rewrite()
        self.assertEqual(payments,[50,50])
        self.assertEqual(worker.state()['equation_rewrite_budget'],200)
        self.assertEqual(worker.state()['rewrite_outcome'],'rewrite_budget_reached')

    def test_v7_keeps_existing_request_limit_and_does_not_create_v8_budget(self):
        worker,main,events,payments,money,cost=self.equation_task('star-workshop-v7')
        worker.rewrite();worker.rewrite();worker.rewrite()
        self.assertEqual(payments,[50,50,50])
        self.assertNotIn('equation_rewrite_budget',worker.state())

    def test_interrupted_payment_keeps_reservation_and_is_not_repaid_after_reload(self):
        worker,main,events,payments,money,cost=self.equation_task()
        def interrupted():raise RuntimeError('fixture interrupted after payment')
        worker.finish_equation_rewrite=interrupted
        with self.assertRaisesRegex(RuntimeError,'interrupted'):
            worker.rewrite()
        reloaded=StarWorkshop(main);reloaded.return_to_menu=lambda:True
        reloaded.rewrite()
        self.assertEqual(payments,[50])
        self.assertEqual(reloaded.state()['equation_rewrite_reserved'],50)
        self.assertEqual(reloaded.state()['rewrite_outcome'],'equation_rewrite_unconfirmed')

    def test_reload_never_replenishes_an_existing_budget_from_new_balance(self):
        worker,main,events,payments,money,cost=self.equation_task()
        worker.state().update(equation_rewrite_budget=100,equation_rewrite_reserved=75)
        worker.rewrite()
        self.assertEqual(payments,[])
        self.assertEqual(worker.state()['equation_rewrite_budget'],100)

    def test_bridge_requires_visible_strip_not_historical_choices(self):
        worker,main,events,payments,progress=self.bridge_task(())
        main.active['star']['choices']=[{'kind':'equation','title':'据说之地'}]
        self.assertIsNone(worker.select_blessing_bridge('概念献祭典仪'))
        self.assertNotIn('blessing_bridge_target',worker.state())

    def test_bridge_rejects_unknown_requirements_already_complete_and_unshared_paths(self):
        worker,main,events,payments,progress=self.bridge_task()
        main.active['star']['observed_equation_requirements'].pop('据说之地')
        progress['痴王']=({'虚无':6,'欢愉':4},{'虚无':6,'欢愉':4})
        self.assertIsNone(worker.select_blessing_bridge('概念献祭典仪'))

    def test_bridge_rejects_missing_current_counts_or_gap_larger_than_two(self):
        worker,main,events,payments,progress=self.bridge_task(('据说之地','痴王'))
        progress['据说之地']=None
        progress['痴王']=({'虚无':3,'欢愉':3},{'虚无':6,'欢愉':4})
        self.assertIsNone(worker.select_blessing_bridge('概念献祭典仪'))

    def test_bridge_selects_smallest_live_gap_and_records_experimental_basis(self):
        worker,main,events,payments,progress=self.bridge_task()
        bridge=worker.select_blessing_bridge('概念献祭典仪')
        self.assertEqual(bridge['name'],'据说之地')
        self.assertEqual(bridge['deficit'],1)
        self.assertFalse(bridge['effects_verified'])
        self.assertEqual(bridge['counts'],{'虚无':5,'毁灭':2})
        self.assertEqual(events[-1][0],'star_blessing_bridge_selected')

    def test_bridge_completion_does_not_rearm_equations_or_change_loadout(self):
        worker,main,events,payments,progress=self.bridge_task()
        worker.state().update(rewrite_done=True,rewrite_outcome='primary_needs_blessings')
        worker.rewrite_blessings()
        state=worker.state()
        self.assertEqual(payments,['覆写'])
        self.assertTrue(state['blessing_rewrite_done'])
        self.assertTrue(state['rewrite_done'])
        self.assertEqual(state['blessing_rewrite_outcome'],'bridge_requirements_met')
        self.assertTrue(state['blessing_bridge_target']['done'])
        self.assertEqual(state['blessing_bridge_target']['counts'],{'虚无':5,'毁灭':3})
        self.assertEqual(main.star_loadout.core_equations,('概念献祭典仪',))

    def test_bridge_rechecks_live_counts_after_selection_before_payment(self):
        worker,main,events,payments,progress=self.bridge_task()
        main.op.snapshot=lambda:progress.__setitem__('据说之地',None)
        worker.rewrite_blessings()
        self.assertEqual(payments,[])
        self.assertEqual(worker.state()['blessing_rewrite_outcome'],'bridge_progress_unreadable')
        self.assertTrue(worker.state()['blessing_bridge_target']['done'])

    def test_bridge_budget_stop_marks_target_done_without_spending(self):
        worker,main,events,payments,progress=self.bridge_task()
        worker.state().update(blessing_rewrite_budget=100,blessing_rewrite_reserved=90)
        worker.rewrite_blessings()
        self.assertEqual(payments,[])
        self.assertEqual(worker.state()['blessing_rewrite_outcome'],'blessing_rewrite_cost_budget')
        self.assertTrue(worker.state()['blessing_bridge_target']['done'])

    def test_fixed_bridge_does_not_switch_to_another_candidate_after_reload(self):
        worker,main,events,payments,progress=self.bridge_task()
        worker.select_blessing_bridge('概念献祭典仪')
        progress['据说之地']=None
        worker.rewrite_blessings()
        self.assertEqual(payments,[])
        self.assertEqual(worker.state()['blessing_bridge_target']['name'],'据说之地')
        self.assertTrue(worker.state()['blessing_bridge_target']['done'])

    def test_no_safe_fodder_finishes_bridge_and_completed_visit_cannot_pay_again(self):
        worker,main,events,payments,progress=self.bridge_task()
        worker.blessing_rewrite_cards=lambda:[]
        worker.scroll_blessing_list=lambda:False
        worker.rewrite_blessings()
        self.assertEqual(worker.state()['blessing_rewrite_outcome'],'no_safe_visible_blessing')
        self.assertTrue(worker.state()['blessing_bridge_target']['done'])
        worker.blessing_rewrite_progress=lambda name:self.fail('Finished target must not be reopened')
        worker.rewrite_blessings()
        self.assertEqual(payments,[])

    def test_v7_does_not_select_bridge_when_primary_is_unreadable(self):
        worker,main,events,payments,progress=self.bridge_task()
        main.star_loadout.revision='star-workshop-v7'
        worker.rewrite_blessings()
        self.assertEqual(payments,[])
        self.assertNotIn('blessing_bridge_target',worker.state())
        self.assertEqual(worker.state()['blessing_rewrite_outcome'],'primary_progress_unreadable')

    def test_v8_protected_actual_path_is_skipped_without_payment_or_repeated_selection(self):
        worker,main,events,payments,progress=self.bridge_task()
        original=main.op.read_region
        main.op.read_region=lambda region,**k:([Box(880,240,60,25,'毁灭')] if region==(.685,.33,.81,.375)
                                              else original(region,**k))
        worker.scroll_blessing_list=lambda:False
        worker.rewrite_blessings()
        self.assertEqual(payments,[])
        self.assertEqual(worker.state()['blessing_rewrite_path_skips'],['正直的诺姆'])
        self.assertFalse(worker.state()['blessing_bridge_target']['done'])
        self.assertEqual(events[-1][0],'star_blessing_rewrite_path_protected')
        worker.rewrite_blessings()
        self.assertEqual(payments,[])
        self.assertEqual(worker.state()['blessing_rewrite_outcome'],'no_safe_visible_blessing')

    def test_v8_unknown_or_ambiguous_actual_path_ends_optional_rewrite(self):
        for labels in ([],['未知'],['智识','毁灭']):
            with self.subTest(labels=labels):
                worker,main,events,payments,progress=self.bridge_task()
                original=main.op.read_region
                main.op.read_region=lambda region,**k:([Box(880,240,60,25,label) for label in labels]
                    if region==(.685,.33,.81,.375) else original(region,**k))
                worker.rewrite_blessings()
                self.assertEqual(payments,[])
                self.assertEqual(worker.state()['blessing_rewrite_outcome'],'blessing_rewrite_path_unknown')
                self.assertTrue(worker.state()['blessing_bridge_target']['done'])

    def test_v8_uses_current_path_even_when_old_catalog_marks_it_protected(self):
        from unittest.mock import patch
        from tasks.divergent_universe.star_policy import star_catalog
        worker,main,events,payments,progress=self.bridge_task()
        table=star_catalog()['blessings']
        with patch.dict(table['正直的诺姆'],path='毁灭'):
            worker.rewrite_blessings()
        self.assertEqual(payments,['覆写'])
        discarded=next(c for c in main.active['star']['choices'] if c['kind']=='discard')
        self.assertEqual(discarded['paths'],['智识'])
        requested=next(data for event,data in events if event=='star_blessing_rewrite_requested')
        self.assertEqual(requested['paths'],['智识'])

    def test_v8_protects_real_heal_and_revive_descriptions_not_only_old_names(self):
        for text in ('角色可抵抗致命伤害，并回复自身生命值。','回复我方全体生命值。'):
            with self.subTest(text=text):
                worker,main,events,payments,progress=self.bridge_task()
                main.active['star']['choices']=[{'kind':'blessing','title':'正直的诺姆','effect_text':text}]
                worker.scroll_blessing_list=lambda:False
                worker.rewrite_blessings()
                self.assertEqual(payments,[])
                self.assertEqual(worker.state()['blessing_rewrite_outcome'],'no_safe_visible_blessing')

    def test_v7_keeps_legacy_fodder_behavior_and_does_not_require_actual_path(self):
        worker,main,events,payments,progress=self.bridge_task()
        main.star_loadout.revision='star-workshop-v7'
        main.star_loadout.core_equations=('据说之地',)
        main.active['star']['choices']=[{'kind':'blessing','title':'正直的诺姆',
                                       'effect_text':'角色可抵抗致命伤害，并回复自身生命值。'}]
        main.op.read_region=lambda *a,**k:self.fail('v7 must not add the new path observation')
        worker.rewrite_blessings()
        self.assertEqual(payments,['覆写'])
        discarded=next(c for c in main.active['star']['choices'] if c['kind']=='discard')
        self.assertNotIn('paths',discarded)

    def test_growth_target_is_enabled_only_for_paid_replacement_choice(self):
        worker,main,events,payments,progress=self.bridge_task()
        original=main.handle_choice
        def choose(kind):
            self.assertEqual(payments,['覆写'])
            self.assertTrue(worker.state()['blessing_choice_pending'])
            original(kind)
        main.handle_choice=choose
        worker.rewrite_blessings()
        self.assertFalse(worker.state()['blessing_choice_pending'])

    def test_interrupted_paid_choice_keeps_pending_marker_for_resume(self):
        worker,main,events,payments,progress=self.bridge_task()
        def interrupted(kind):raise RuntimeError('fixture interrupted paid choice')
        main.handle_choice=interrupted
        with self.assertRaisesRegex(RuntimeError,'interrupted paid choice'):
            worker.rewrite_blessings()
        self.assertEqual(payments,['覆写'])
        self.assertTrue(worker.state()['blessing_choice_pending'])
        self.assertFalse(worker.state()['blessing_bridge_target']['done'])

    def test_optional_finish_clears_old_paid_choice_marker(self):
        worker,main,events,payments,progress=self.bridge_task()
        worker.state().update(blessing_choice_pending=True,blessing_rewrite_budget=0)
        worker.rewrite_blessings()
        self.assertEqual(payments,[])
        self.assertFalse(worker.state()['blessing_choice_pending'])
        self.assertTrue(worker.state()['blessing_bridge_target']['done'])


if __name__=='__main__':unittest.main()
