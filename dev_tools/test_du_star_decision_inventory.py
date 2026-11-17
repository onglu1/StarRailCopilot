"""Observed counts stay intact while confirmed choices bound later decisions."""
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest

from tasks.divergent_universe.star_policy import decision_inventory,rank_star_choices,StarLoadout,uncertain_growth_threshold


class DecisionInventoryTests(unittest.TestCase):
    def star(self,counts=None):
        return {'path_counts':counts or {'欢愉':0,'智识':0},'inventory_path_counts':dict(counts or {'欢愉':0,'智识':0}),'inventory_choice_index':0,'inventory_node':1,'choices':[]}

    def test_actual_zero_snapshot_and_new_unique_rewards_give_exact_counts(self):
        star=self.star();star['choices']=[dict(kind='blessing',title='《白日漫漫路》',paths=['欢愉']),
                                        dict(kind='blessing',title='分区对齐的包裹',paths=['智识']),
                                        dict(kind='blessing',title='《死神骑车来》',paths=['欢愉'])]
        original=deepcopy(star)
        result=decision_inventory(star)
        self.assertEqual(result['counts'],{'欢愉':2,'智识':1})
        self.assertEqual(result['upper_counts'],result['counts'])
        self.assertEqual(star,original)

    def test_unseen_items_and_duplicate_titles_are_not_invented_as_new(self):
        star=self.star({'欢愉':4,'智识':1})
        star['choices']=[dict(kind='blessing',title='《猫镇》',paths=['欢愉'])]*2
        result=decision_inventory(star)
        self.assertEqual((result['counts']['欢愉'],result['upper_counts']['欢愉']),(4,5))

    def test_known_pre_snapshot_item_is_not_counted_again(self):
        star=self.star({'欢愉':4,'智识':0});star['inventory_choice_index']=1
        star['choices']=[dict(kind='blessing',title='《猫镇》',paths=['欢愉'])]*2
        result=decision_inventory(star)
        self.assertEqual(result['counts'],result['upper_counts'])

    def test_current_path_overrides_legacy_catalogue_and_unknown_removal_refreshes(self):
        star=self.star({'同谐':0,'巡猎':0})
        star['choices']=[dict(kind='blessing',title='直行旋律',paths=['同谐'])]
        self.assertEqual(decision_inventory(star)['counts'],{'同谐':1,'巡猎':0})
        star['choices'].append(dict(kind='discard',title='未在选择记录中的祝福'))
        self.assertTrue(decision_inventory(star)['requires_refresh'])

    def test_confirmed_removal_decrements_and_never_creates_negative_counts(self):
        star=self.star();star['choices']=[dict(kind='blessing',title='《猫镇》',paths=['欢愉']),
                                         dict(kind='discard',title='《猫镇》')]
        result=decision_inventory(star)
        self.assertEqual(result['counts'],{'欢愉':0,'智识':0})
        self.assertEqual(result['upper_counts'],result['counts'])

    def test_legacy_snapshot_without_watermark_requires_real_observation(self):
        star=self.star();star.pop('inventory_choice_index')
        self.assertTrue(decision_inventory(star)['requires_refresh'])

    def test_partial_workshop_observation_does_not_replace_the_inventory_baseline(self):
        star=self.star({'欢愉':0,'智识':0})
        star['path_counts']['欢愉']=2
        star['choices']=[dict(kind='blessing',title='《猫镇》',paths=['欢愉'])]
        self.assertEqual(decision_inventory(star)['counts']['欢愉'],1)

    def test_intermediate_threshold_is_uncertain_even_when_both_endpoints_choose_same(self):
        loadout=StarLoadout('followup',('a','b','c','d'),'unused',core_equations=('测试方程',))
        bounds=dict(counts={'巡猎':2,'毁灭':2},upper_counts={'巡猎':3,'毁灭':3})
        self.assertTrue(uncertain_growth_threshold(loadout,bounds,{'测试方程':{'巡猎':3,'毁灭':3}}))

    def test_refresh_finishes_the_original_choice_before_workshop_continues(self):
        from unittest.mock import patch
        from tasks.divergent_universe.divergent_universe import DivergentUniverse
        order=[]
        main=NS(handle_choice=lambda kind:order.append(('choose',kind)))
        def read(worker,**kwargs):
            order.append(('read',kwargs))
            return {'巡猎':3}
        with patch('tasks.divergent_universe.star_inventory.StarInventory.read',read):
            main.op=None
            DivergentUniverse.refresh_choice_inventory(main,'blessing')
        self.assertEqual(order,[('read',{'force':True}),('choose','blessing')])
        self.assertEqual(main._star_refresh_depth,0)

    def test_departed_reward_does_not_reenter_stale_choice_after_refresh(self):
        from unittest.mock import patch
        from tasks.divergent_universe.divergent_universe import DivergentUniverse
        main=NS(op=None,handle_choice=lambda kind:self.fail('The reward has already ended'))
        with patch('tasks.divergent_universe.star_inventory.StarInventory.read',return_value=None):
            self.assertIsNone(DivergentUniverse.refresh_choice_inventory(main,'blessing'))
        self.assertEqual(main._star_refresh_depth,0)

    def test_bridge_target_applies_only_until_this_visit_finishes(self):
        loadout=StarLoadout('dot',('a','b','c','d'),'unused',core_equations=('概念献祭典仪',))
        choices=[NS(title='虚无填充',paths=('虚无',),rarity=1,recommended=False),
                 NS(title='毁灭填充',paths=('毁灭',),rarity=1,recommended=True)]
        bridge=dict(name='据说之地',requirements={'虚无':3,'毁灭':3},done=False)
        ranked=rank_star_choices(choices,loadout,'blessing',path_counts={'虚无':5,'毁灭':2},threshold=5,growth_target=bridge)
        self.assertEqual(ranked[0][0].title,'毁灭填充')
        bridge['done']=True;choices[1].recommended=False
        ranked=rank_star_choices(choices,loadout,'blessing',path_counts={'虚无':5,'毁灭':2},threshold=5,growth_target=bridge)
        self.assertEqual(ranked[0][0].title,'虚无填充')
        self.assertEqual(loadout.core_equations,('概念献祭典仪',))


if __name__=='__main__':unittest.main()
