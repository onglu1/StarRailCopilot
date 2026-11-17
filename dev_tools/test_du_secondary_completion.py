"""One real DOT secondary completion during one bounded rewrite transaction."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from module.config.config import TaskEnd
from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_policy import (
    StarLoadout, pending_secondary_completion, rank_star_choices,
    verified_secondary_equations,
)
from dev_tools import test_du_star_growth as growth_fixtures


class SecondaryCompletionTests(unittest.TestCase):
    def guide_and_proof(self):
        guide=next(g for g in json.loads((Path(__file__).resolve().parents[1]/
            'tasks/divergent_universe/star_guides.json').read_text('utf-8'))['guides'] if g['key']=='dot')
        signature=hashlib.sha256(guide['code'].encode()).hexdigest()
        # Actual imported DOT secondary-card labels and their image boxes.
        labels=[dict(text=name,box=box) for name,box in (
            ('智商税务官',[279,378,370,397]),('永恒竞走',[567,376,642,399]),
            ('永恒杀伐迷宫',[279,452,387,474]),('据说之地',[563,448,643,477]),
            ('反向冒险家',[276,525,371,551]))]
        return guide,dict(import_verified=True,guide_signature=signature,
                          screenshot='actual_guide.png',labels=labels)

    def worker(self):
        worker,main,events,payments,progress=growth_fixtures.GrowthTests().bridge_task(
            visible=('概念献祭典仪','永恒竞走'))
        guide,proof=self.guide_and_proof()
        main.star_loadout=StarLoadout('dot_blackswan',('a','b','c','d'),guide['code'],
            core_equations=('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        main.active.update(mode='star',selections=24)
        main.progress.session_id='worker-a'
        main.active['star'].update(guide_signature=proof['guide_signature'],
            secondary_equation_evidence=verified_secondary_equations(guide,proof),
            inventory_path_counts={'虚无':8,'巡猎':3,'毁灭':1,'智识':3},
            inventory_choice_index=0,
            observed_equation_requirements={'概念献祭典仪':{'虚无':9,'毁灭':6},
                                            '永恒竞走':{'虚无':6,'巡猎':4}})
        progress.update({'概念献祭典仪':({'虚无':8,'毁灭':1},{'虚无':9,'毁灭':6}),
                         '永恒竞走':({'虚无':8,'巡猎':3},{'虚无':6,'巡猎':4})})
        worker.blessing_rewrite_cards=lambda:[(Box(70,360,150,25,'光学导引的透镜'),'光学导引的透镜')]
        worker.blessing_rewrite_title=lambda:'光学导引的透镜'
        return worker,main,events,payments,progress

    def pending(self):
        worker,main,events,payments,progress=self.worker()
        target=worker.observe_secondary_completion('光学导引的透镜','智识',2)
        worker.state().update(blessing_choice_pending=True,blessing_rewrites=2,secondary_completion=target)
        main.active['star']['choices'].append(dict(kind='discard',title='光学导引的透镜',
            source='blessing_rewrite',paths=['智识']))
        return worker,main,target

    def card(self,title,path,text='',tags=(),recommended=True,rarity=1):
        return NS(title=title,paths=(path,) if path else (),effect_text=text,effect_tags=tags,
                  recommended=recommended,rarity=rarity,uncollected=False)

    def actual_offer(self):
        # 3065 N6 selection24, with the recorded empty OCR description for Hunt.
        return [self.card('排则正','巡猎'),
                self.card('交叉节拍','同谐','击破敌方目标弱点后，我方全体击破特攻提高。',recommended=False),
                self.card('相接双星','毁灭','生命上限提高。')]

    def rank(self,choices,main,target,**kwargs):
        context=dict(threshold=5,path_counts={'虚无':8,'巡猎':3,'毁灭':1,'智识':2},
                     requirements=main.active['star']['observed_equation_requirements'])
        context.update(kwargs)
        return rank_star_choices(choices,main.star_loadout,'blessing',secondary_completion=target,**context)

    def test_verified_import_secondaries_do_not_invent_bazhang_or_partial_labels(self):
        guide,proof=self.guide_and_proof()
        evidence=verified_secondary_equations(guide,proof)
        self.assertIn('永恒竞走',evidence['names'])
        self.assertNotIn('巴掌侠',evidence['names'])
        self.assertEqual(evidence['guide_signature'],proof['guide_signature'])
        for invalid in (dict(proof,import_verified=False),dict(proof,guide_signature='other'),
                        dict(proof,labels=proof['labels'][:4]),dict(proof,screenshot='')):
            self.assertIsNone(verified_secondary_equations(guide,invalid))
        misplaced=deepcopy(proof);misplaced['labels'][1]['box'][1]=182
        self.assertIsNone(verified_secondary_equations(guide,misplaced))

    def test_actual_same_frame_strip_is_one_short_after_unrelated_removal(self):
        worker,main,_,_,progress=self.worker()
        baseline=deepcopy(main.active['star']['inventory_path_counts'])
        target=worker.observe_secondary_completion('光学导引的透镜','智识',2)
        self.assertEqual(target['counts_before_removal'],{'虚无':8,'巡猎':3})
        self.assertEqual(target['counts_after_removal'],{'虚无':8,'巡猎':3})
        self.assertEqual(main.active['star']['inventory_path_counts'],baseline)
        self.assertIsNone(worker.observe_secondary_completion('巡猎牌','巡猎',2))
        self.assertIsNone(worker.observe_secondary_completion('未知牌',None,2))
        progress['永恒竞走']=({'虚无':6,'巡猎':3},{'虚无':6,'巡猎':4})
        self.assertIsNone(worker.observe_secondary_completion('虚无牌','虚无',2))

    def test_complete_invisible_ambiguous_or_unverified_secondary_does_not_arm(self):
        for value in (None,({'虚无':8,'巡猎':4},{'虚无':6,'巡猎':4}),
                      ({'虚无':8,'巡猎':2},{'虚无':6,'巡猎':4}),
                      ({'虚无':8,'巡猎':'3'},{'虚无':6,'巡猎':4})):
            worker,main,_,_,progress=self.worker();progress['永恒竞走']=value
            self.assertIsNone(worker.observe_secondary_completion('光学导引的透镜','智识',2))
        worker,main,_,_,_=self.worker()
        main.active['star']['secondary_equation_evidence']['names']=['巴掌侠']
        self.assertIsNone(worker.observe_secondary_completion('光学导引的透镜','智识',2))
        worker,main,_,_,_=self.worker();main.active['star']['observed_equation_requirements'].pop('永恒竞走')
        self.assertIsNone(worker.observe_secondary_completion('光学导引的透镜','智识',2))

    def test_transaction_binding_rejects_stale_target_and_reload(self):
        worker,main,target=self.pending()
        self.assertIs(pending_secondary_completion(main.active,'blessing','worker-a'),target)
        for mutation in ('node','request','selection','choice','guide','stopped','page','session'):
            worker,main,target=self.pending();kind='blessing';session='worker-a'
            if mutation=='node':target['node']=5
            elif mutation=='request':target['request']=1
            elif mutation=='selection':main.active['selections']+=1
            elif mutation=='choice':main.active['star']['choices'].append(dict(kind='blessing',title='already chosen'))
            elif mutation=='guide':target['guide_signature']='other'
            elif mutation=='stopped':main.active['stop_requested']=True
            elif mutation=='page':kind='equation'
            else:session='new-worker'
            self.assertIsNone(pending_secondary_completion(main.active,kind,session))
            self.assertNotIn('secondary_completion',worker.state())

    def test_actual_3065_page_completes_imported_secondary_even_with_primary_held(self):
        _,main,target=self.pending();choices=self.actual_offer()
        self.assertEqual(self.rank(choices,main,None)[0][0].title,'相接双星')
        ranked=self.rank(choices,main,target)
        self.assertEqual(ranked[0][0].title,'排则正')
        self.assertEqual(ranked[0][1][:4],(True,0,True,0))
        self.assertEqual(main.star_loadout.core_equations[0],'概念献祭典仪')
        # Later N6/26's old aggregate still read Hunt=3, but the actual
        # post-transaction strip was 4/4. Only that strip may arm a target.
        worker,main,_,_,progress=self.worker()
        main.active['star']['path_counts']={'虚无':8,'巡猎':3}
        progress['永恒竞走']=({'虚无':8,'巡猎':4},{'虚无':6,'巡猎':4})
        self.assertIsNone(worker.observe_secondary_completion('另一张牌','同谐',4))

    def test_real_candidate_path_is_required_and_ordinary_rewards_get_no_target(self):
        worker,main,target=self.pending();choices=self.actual_offer()
        for paths in ((),('巡猎','同谐')):
            choices[0].paths=paths
            self.assertEqual(self.rank(choices,main,target)[0][0].title,'相接双星')
        worker.state()['blessing_choice_pending']=False
        self.assertIsNone(pending_secondary_completion(main.active,'blessing','worker-a'))

    def test_insurance_and_offered_primary_completion_stay_above_secondary(self):
        _,main,target=self.pending();choices=self.actual_offer()
        for text,tags in (('抵抗致命伤害。',('revive',)),
                          ('我方全体回复生命值。',('heal','dot_team_heal'))):
            insurance=self.card('保险','智识',text,tags)
            self.assertEqual(self.rank(choices+[insurance],main,target)[0][0].title,'保险')
        primary=self.card('主核最后虚无','虚无','普通效果')
        ranked=self.rank(choices+[primary],main,target,path_counts={'虚无':8,'毁灭':6,'巡猎':3})
        self.assertEqual(ranked[0][0].title,'主核最后虚无')
        self.assertFalse(next(score[2] for c,score in ranked if c.title=='排则正'))

    def test_same_frame_primary_one_away_beats_stale_inventory_even_before_choice(self):
        worker,main,_,_,progress=self.worker()
        main.active['star']['path_counts']={'虚无':6,'毁灭':2,'巡猎':3}
        for actual in (({'虚无':8,'毁灭':6},{'虚无':9,'毁灭':6}),
                       ({'虚无':9,'毁灭':6},{'虚无':9,'毁灭':6}),None):
            progress['概念献祭典仪']=actual
            self.assertIsNone(worker.observe_secondary_completion('光学导引的透镜','智识',2))

    def test_bazhang_and_other_candidate_families_cannot_gain_this_exception(self):
        _,main,target=self.pending();target=dict(target,name='巴掌侠')
        self.assertEqual(self.rank(self.actual_offer(),main,target)[0][0].title,'相接双星')
        _,main,target=self.pending()
        main.star_loadout=StarLoadout('aglaea',('a','b','c','d'),'unused',core_equations=('概念献祭典仪',))
        self.assertEqual(self.rank(self.actual_offer(),main,target)[0][0].title,'相接双星')

    def test_one_payment_keeps_primary_budget_and_clears_optional_target(self):
        worker,main,_,payments,progress=self.worker();seen=[]
        def choose(kind):
            seen.append(pending_secondary_completion(main.active,kind,'worker-a'))
            progress['永恒竞走']=({'虚无':8,'巡猎':4},{'虚无':6,'巡猎':4})
        main.handle_choice=choose
        worker.rewrite_blessings()
        self.assertEqual(payments,['覆写'])
        self.assertEqual(seen[0]['name'],'永恒竞走')
        self.assertNotIn('secondary_completion',worker.state())
        self.assertNotIn('blessing_bridge_target',worker.state())
        self.assertFalse(worker.state().get('blessing_rewrite_done',False))
        self.assertEqual(worker.state()['blessing_rewrite_spent'],25)

    def test_payment_failure_stop_and_page_departure_clear_without_swallowing(self):
        for failure in ('payment','stop','departure','selection'):
            worker,main,_,_,_=self.worker()
            def fail(*args,**kwargs):raise RuntimeError('fixture failure')
            if failure=='payment':main.op.click_box=fail
            elif failure=='stop':
                def stopped(*args,**kwargs):raise TaskEnd()
                main.handle_choice=stopped
            elif failure=='departure':main.selection_kind=lambda:'world'
            else:main.handle_choice=fail
            with self.assertRaises(TaskEnd if failure=='stop' else RuntimeError):
                worker.rewrite_blessings()
            self.assertNotIn('secondary_completion',worker.state())

    def test_unsent_payment_never_applies_optional_target(self):
        worker,main,_,_,_=self.worker();main.op.click_box=lambda *a,**k:False
        main.handle_choice=lambda kind:self.assertIsNone(pending_secondary_completion(main.active,kind,'worker-a'))
        worker.rewrite_blessings()
        self.assertNotIn('secondary_completion',worker.state())


if __name__=='__main__':unittest.main()
