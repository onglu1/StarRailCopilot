"""A paired visible inventory can guide one ordinary DOT reward, without new reads."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tasks.currency_wars.operator import Box
from tasks.divergent_universe.star_inventory import StarInventory
from tasks.divergent_universe.star_policy import (
    StarLoadout, decision_inventory, rank_star_choices, visible_secondary_growth,
)


class VisibleSecondaryGrowthTests(unittest.TestCase):
    def state(self):
        # Actual 3065/N4/11: equation and blessing observations 28807/28810;
        # the nine existing choice records are not used as ownership proof.
        counts={'记忆':2,'虚无':5,'巡猎':3,'毁灭':0,'欢愉':0,'繁育':2,'智识':1,'同谐':2}
        watermark=dict(run_id='3065',session='worker',node=4,selection=11,choice_index=9,observation=123)
        star=dict(choices=[{'kind':'unrelated'} for _ in range(9)],guide_signature='verified-guide',
            secondary_equation_evidence=dict(source='verified_import_secondary_cards',
                names=['永恒竞走'],guide_signature='verified-guide'),
            observed_equation_requirements={'永恒竞走':{'虚无':6,'巡猎':4}},
            inventory_path_counts=counts,inventory_choice_index=9,inventory_node=4,
            inventory_screenshot='blessing_inventory_4.png',inventory_equation_watermark=dict(watermark),
            equation_inventory=dict(counts={'expanded':0,'unexpanded':2},visible_tab='unexpanded',
                visible_only=True,visible_names=['永恒竞走'],visible_expanded_names=[],node=4,
                screenshot='equation_inventory_4.png',decision_watermark=watermark))
        active=dict(id='3065',mode='star',node=4,selections=11,star=star)
        loadout=StarLoadout('dot_blackswan',('a','b','c','d'),'unused',
                          core_equations=('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        return active,loadout

    def card(self,title,path,text,tags=(),recommended=False,rarity=1):
        return NS(title=title,paths=(path,) if path else (),effect_text=text,effect_tags=tags,
                  recommended=recommended,rarity=rarity,uncollected=False)

    def offer(self):
        # Actual event28813: destruction's path OCR was empty. It is not
        # silently repaired; only the Hunt candidate has positive path proof.
        return [self.card('双极喷流',None,'受到的伤害降低。',('defense',)),
                self.card('眼斑','繁育','施放普攻、战技时造成的暴击伤害提高'),
                self.card('激箭流星远','巡猎','我方目标速度提高5%，全队每经过12个回合后，当前我方目标行动提前100%。',
                          ('cycle',),True,2)]

    def target(self,active,loadout,kind='blessing',session='worker',inventory=None):
        return visible_secondary_growth(active,loadout,inventory or decision_inventory(active['star']),kind,session)

    def rank(self,active,loadout,target,choices=None,**kwargs):
        return rank_star_choices(choices or self.offer(),loadout,'blessing',threshold=5,
            requirements=active['star']['observed_equation_requirements'],
            path_counts=active['star']['inventory_path_counts'],secondary_growth=target,**kwargs)

    def test_real_3065_offer_changes_winner_without_inventing_core_absence(self):
        active,loadout=self.state();before=deepcopy(active)
        target=self.target(active,loadout)
        old=self.rank(active,loadout,None);new=self.rank(active,loadout,target)
        self.assertEqual((old[0][0].title,old[0][1][4:6]),('双极喷流',(6,2)))
        self.assertEqual(new[0][0].title,'激箭流星远')
        self.assertEqual(new[0][1][:7],(True,0,False,0,True,2,2))
        self.assertEqual(target['primary_ownership'],'not_inferred')
        self.assertEqual(active,before)
        # A currently visible but distant primary does not falsely disable
        # the rule as if its absence had been established.
        active['star']['equation_inventory']['visible_names'].append('概念献祭典仪')
        self.assertIsNotNone(self.target(active,loadout))

    def test_rejects_missing_unpaired_or_stale_positive_inventory_evidence(self):
        cases=('run','session','node','selection','choice','pair','index','expanded','target_expanded',
               'invisible','wrong_tab','needs','guide','counts','uncertain','stop','transaction','kind','family')
        for case in cases:
            with self.subTest(case=case):
                active,loadout=self.state();star=active['star'];kind='blessing';session='worker'
                if case=='run':active['id']='other'
                elif case=='session':session='new-worker'
                elif case=='node':active['node']=5
                elif case=='selection':active['selections']=12
                elif case=='choice':star['choices'].append({'kind':'equation','title':'永恒竞走'})
                elif case=='pair':star['inventory_equation_watermark']['observation']=122
                elif case=='index':star['inventory_choice_index']=8
                elif case=='expanded':star['equation_inventory']['counts']['expanded']=1
                elif case=='target_expanded':star['equation_inventory']['visible_expanded_names']=['永恒竞走']
                elif case=='invisible':star['equation_inventory']['visible_names']=[]
                elif case=='wrong_tab':star['equation_inventory']['visible_tab']='expanded'
                elif case=='needs':star['observed_equation_requirements']={}
                elif case=='guide':star['secondary_equation_evidence']['guide_signature']='other'
                elif case=='stop':active['stop_requested']=True
                elif case=='transaction':star['workshops']={'4':{'blessing_choice_pending':True}}
                elif case=='kind':kind='discard'
                elif case=='family':loadout=replace(loadout,candidate='aglaea')
                inventory=decision_inventory(star)
                if case=='counts':inventory['upper_counts']['巡猎']=4
                if case=='uncertain':inventory['requires_refresh']=True
                self.assertIsNone(self.target(active,loadout,kind,session,inventory))
        active,loadout=self.state();active['star']['equation_inventory'].pop('decision_watermark')
        self.assertIsNone(self.target(active,loadout))  # Legacy history is not upgraded.

    def test_gap_one_or_two_only_and_no_other_equation_or_catalog_fallback(self):
        for hunt,nihility,accepted in ((3,5,True),(3,6,True),(2,5,False),(4,6,False)):
            active,loadout=self.state();active['star']['inventory_path_counts'].update(巡猎=hunt,虚无=nihility)
            self.assertEqual(self.target(active,loadout) is not None,accepted)
        active,loadout=self.state()
        active['star']['secondary_equation_evidence']['names']=['巴掌侠']
        self.assertIsNone(self.target(active,loadout))
        active,loadout=self.state();active['star']['observed_equation_requirements']['永恒竞走']={'虚无':6}
        self.assertIsNone(self.target(active,loadout))

    def test_insurance_primary_completion_and_transaction_completion_remain_higher(self):
        active,loadout=self.state();target=self.target(active,loadout)
        for text,tags in (('抵抗致命伤害。',('revive',)),('敌方受持续伤害我方全体回复生命',('heal','dot_team_heal'))):
            insurance=self.card('保险','智识',text,tags)
            self.assertEqual(self.rank(active,loadout,target,self.offer()+[insurance])[0][0].title,'保险')
        active['star']['inventory_path_counts'].update(虚无=8,毁灭=6)
        target=self.target(active,loadout)
        primary=self.card('主核缺的虚无','虚无','已有条件效果')
        self.assertEqual(self.rank(active,loadout,target,self.offer()+[primary])[0][0].title,primary.title)
        active,loadout=self.state();active['star']['inventory_path_counts']['巡猎']=4
        target=self.target(active,loadout)
        completion=dict(name='永恒竞走',source='same_frame_rewrite_strip',requirements={'虚无':6,'巡猎':4},
                        counts_after_removal={'虚无':5,'巡猎':4})
        ranked=self.rank(active,loadout,target,self.offer()+[primary],secondary_completion=completion)
        self.assertEqual(ranked[0][0].title,primary.title)
        self.assertTrue(ranked[0][1][2]);self.assertEqual(len(ranked[0][1]),9)

    def test_no_target_keeps_exact_old_scores_and_ambiguous_paths_never_gain_priority(self):
        active,loadout=self.state();target=self.target(active,loadout)
        expected=[(True,0,False,0,6,2,False,False,1),
                  (True,0,False,0,3,0,False,False,1),(True,0,False,0,2,2,False,True,2)]
        self.assertEqual([score for _,score in self.rank(active,loadout,None)],expected)
        for paths in ((),('巡猎','同谐')):
            choices=self.offer();choices[2].paths=paths
            self.assertEqual(self.rank(active,loadout,target,choices)[0][0].title,'双极喷流')
        for candidate in ('aglaea','aglaea_sustain','followup'):
            ranked=self.rank(active,replace(loadout,candidate=candidate),target)
            self.assertTrue(all(len(score)==9 for _,score in ranked))

    def test_pair_metadata_uses_existing_observations_and_does_not_reuse_old_equation_read(self):
        active,loadout=self.state();star=active['star'];phase=['equation']
        tabs=[Box(160,90,90,30,'已展开0'),Box(280,90,90,30,'未展开2')]
        op=NS(image=None,snapshot=Mock(),
              read_line=Mock(return_value=Box(150,140,170,30,'未展开方程')),
              read_region=Mock(side_effect=lambda region,**kw:tabs if region[1]<.2 else [Box(540,350,120,30,'永恒竞走')]),
              match=Mock(return_value=[]),template=Mock(return_value=Box(40,200,20,20,'tab')),
              text=lambda *a,**kw:phase[0]=='equation',
              click_box=Mock(side_effect=lambda *a,**kw:phase.__setitem__(0,'blessing')))
        main=NS(active=active,star_loadout=loadout,op=op,config=NS(config_name='fixture'),
            progress=NS(session_id='worker',data={'star_path_order':['记忆','虚无','巡猎','毁灭','欢愉','繁育','智识','同谐']},
                        save=Mock(),record=Mock()),world_visible=lambda:False,is_combat_executing=lambda:False)
        worker=StarInventory(main);worker.blessing_page=lambda:phase[0]=='blessing'
        worker.wait_inventory=lambda predicate,**kw:predicate()
        worker.read_counts=Mock(return_value=(dict(star['inventory_path_counts']),15))
        with patch('tasks.divergent_universe.star_inventory.save_image') as saved,patch('pathlib.Path.mkdir'):
            worker.read(close=False,force=True)
            self.assertEqual(saved.call_count,2)  # Existing equation and blessing saves only.
            self.assertEqual(op.snapshot.call_count,1)
            self.assertEqual(op.read_region.call_count,2);self.assertEqual(op.read_line.call_count,1)
            self.assertEqual(star['inventory_equation_watermark'],star['equation_inventory']['decision_watermark'])
            self.assertIsNotNone(self.target(active,loadout))
            worker.read(close=False,force=True)  # Already on blessing tab: no new equation evidence.
            self.assertIsNone(star['inventory_equation_watermark'])
            self.assertIsNone(self.target(active,loadout))


if __name__=='__main__':unittest.main()
