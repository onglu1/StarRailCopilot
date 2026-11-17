"""Preparation gates and real-rank accounting, without emulator operations."""
import copy
import base64
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from tasks.divergent_universe.star_policy import (
    StarLoadout, campaign_summary, decode_guide_plan, guide_codes_equivalent, star_choice,
    validate_guide_code, verified_start, loadout_from_guide, catalog_name, star_catalog, observed_blessings, star_station_order,
    equation_requirements, verified_star_rank,
)


class StarPolicyTests(unittest.TestCase):
    def test_new_guide_uses_complete_verified_in_game_core_order(self):
        guide=next(g for g in self.guides if g['key']=='dot')
        core=['概念献祭典仪','铁臂侠','彗星调教师','祖宗战神']
        proof=dict(import_verified=True,guide_signature=hashlib.sha256(guide['code'].encode()).hexdigest(),core_equations=core)
        self.assertEqual(loadout_from_guide(guide,proof).core_equations,tuple(core))
        for invalid in [None,dict(proof,guide_signature='other'),dict(proof,core_equations=core[:3]),
                        dict(proof,core_equations=['未知方程']+core[1:]),dict(proof,core_equations=[core[0]]*4)]:
            with self.assertRaises(ValueError):loadout_from_guide(guide,invalid)

    def test_imported_card_order_ignores_single_pixel_ocr_baseline_difference(self):
        from tasks.divergent_universe.star_policy import reconcile_imported_core_order
        guide=next(g for g in self.guides if g['key']=='dot')
        names=['丧气侠','概念献祭典仪','骰铸人生','失心博士']
        proof=dict(import_verified=True,guide_signature=hashlib.sha256(guide['code'].encode()).hexdigest(),
                   core_equations=names,labels=[
                       {'text':'丧气侠','box':[566,181,626,205]},
                       {'text':'概念献祭典仪','box':[278,182,405,205]},
                       {'text':'殷铸人生','box':[278,254,365,277]},
                       {'text':'失心博士','box':[566,254,650,277]}])
        loadout=loadout_from_guide(guide,proof)
        self.assertEqual(loadout.core_equations,('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        active={'node':1,'selections':2,'star':{'choices':[{'title':'existing'}],
            'loadout':dict(candidate='dot',team=guide['candidate_team'],guide_code=guide['code'],core_equations=names)}}
        correction=reconcile_imported_core_order(active,guide,proof)
        self.assertEqual(correction['before'],names)
        self.assertEqual(active['star']['choices'],[{'title':'existing'}])
        self.assertTrue(active['execution']['policy_corrected_during_run'])
        self.assertIsNone(reconcile_imported_core_order(active,guide,proof))

    def test_x5_keeps_collecting_primary_path_before_its_equation_is_offered(self):
        guide=next(g for g in self.guides if g['key']=='followup')
        loadout=loadout_from_guide(guide)
        table=star_catalog()['blessings']
        hunt=next(name for name,info in table.items() if info['path']=='巡猎')
        propagation=next(name for name,info in table.items() if info['path']=='繁育')
        choices=[SimpleNamespace(title=hunt,recommended=False,rarity=1),
                 SimpleNamespace(title=propagation,recommended=True,rarity=3)]
        counts={'巡猎':6,'繁育':6,'智识':3,'欢愉':4,'毁灭':4}
        self.assertEqual(star_choice(choices,loadout,'blessing',path_counts=counts).title,propagation)
        self.assertEqual(star_choice(choices,loadout,'blessing',path_counts=counts,threshold=5).title,hunt)

    def test_rank_planning_never_overrides_current_run_requirements(self):
        self.assertEqual(equation_requirements('星星盗贼',threshold=4),{'欢愉':7,'巡猎':5})
        self.assertEqual(equation_requirements('星星盗贼',threshold=5),{'欢愉':9,'巡猎':6})
        actual={'星星盗贼':{'欢愉':11,'巡猎':8}}
        self.assertEqual(equation_requirements('星星盗贼',actual,threshold=7),actual['星星盗贼'])
        self.assertEqual(star_catalog()['equations']['星星盗贼']['requires'],{'欢愉':6,'巡猎':4})

    def test_x5_route_does_not_treat_base_catalog_counts_as_a_finished_core(self):
        star=dict(threshold=5,boss_rewards_seen=True,loadout={'core_equations':['星星盗贼']},
                  choices=[{'kind':'equation','title':'星星盗贼'}],weighted_equipment=[{'id':1009}],
                  path_counts={'欢愉':6,'巡猎':4})
        self.assertEqual(star_station_order({'star':star})[:2],['战斗','奖励'])

    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'tasks/divergent_universe/star_guides.json'
        self.guides = json.loads(path.read_text('utf-8'))['guides']
        guide = self.guides[0]
        self.loadout = StarLoadout(guide['key'], tuple(guide['candidate_team']), guide['code'],
                                   core_equations=('测试核心方程',))
        self.observation = dict(members=list(self.loadout.team), threshold=9, title='万机之王',
                                observed_text='阈值协议 9', mode='拓星模式',
                                guide_policy_applied=True,
                                guide_signature=hashlib.sha256(guide['code'].encode()).hexdigest(),
                                team_screenshot='observed_team.png', rank_screenshot='observed_rank.png')

    def test_all_supplied_codes_checksum_valid_and_exact_bytes_preserved(self):
        for guide in self.guides:
            self.assertEqual(validate_guide_code(guide['code']), guide['code'])
            self.assertEqual(validate_guide_code('分享 ' + guide['code']), guide['code'])

    def test_aglaea_sustain_is_a_distinct_verified_team_with_unchanged_guide(self):
        original=next(g for g in self.guides if g['key']=='aglaea')
        variant=next(g for g in self.guides if g['key']=='aglaea_sustain')
        self.assertEqual(variant['code'],original['code'])
        self.assertEqual(variant['selected_team_ids'],[1402,1415,1409,1414])
        self.assertEqual(variant['core_equations'],original['core_equations'])
        old,new=loadout_from_guide(original),loadout_from_guide(variant)
        self.assertNotEqual(old.signature,new.signature)
        self.assertEqual(new.team,('阿格莱雅','昔涟','风堇','丹恒•腾荒'))
        with self.assertRaises(ValueError):
            verified_start(new,dict(self.observation,members=list(old.team)))

    def test_followup_fuxuan_changes_only_verified_survival_slot(self):
        original=next(g for g in self.guides if g['key']=='followup')
        variant=next(g for g in self.guides if g['key']=='followup_fuxuan')
        self.assertEqual(variant['code'],original['code'])
        self.assertEqual(variant['core_equations'],original['core_equations'])
        self.assertEqual(variant['selected_team_ids'],[1220,8008,1403,1208])
        old,new=loadout_from_guide(original),loadout_from_guide(variant)
        self.assertEqual(old.team[:3],new.team[:3])
        self.assertEqual(new.team[-1],'符玄')
        self.assertNotEqual(old.signature,new.signature)
        self.assertFalse(variant['availability_verified'])
        with self.assertRaises(ValueError):verified_start(new,dict(self.observation,members=list(old.team)))

    def test_supplied_lineups_preserve_alternatives_instead_of_flattening_slots(self):
        plans = {g['key']: decode_guide_plan(g['code']) for g in self.guides}
        self.assertEqual(plans['phainon']['teams'], [[[1408], [1415], [1303, 1403], [8008]]])
        self.assertEqual(plans['aglaea']['teams'], [[[1402], [1415], [1403], [1414]]])
        self.assertEqual(len(plans['followup']['teams']), 2)
        self.assertEqual(plans['followup']['teams'][1], [[1220], [8008], [1403], [1414]])
        self.assertEqual(plans['dot']['teams'], [[[1410], [1005], [1309], [1414]]])

    def test_corrupt_and_oversized_code_rejected(self):
        for code in ['', 'DIV##invalid$$UNI', 'DIV##' + 'A' * 9000 + '$$UNI']:
            with self.assertRaises(ValueError):
                validate_guide_code(code)
        damaged = self.loadout.guide_code.replace('AQAAAB+', 'AgAAAB+')
        with self.assertRaises(ValueError):
            validate_guide_code(damaged)

    def test_game_export_header_variant_does_not_allow_changed_build(self):
        original = self.loadout.guide_code
        encoded = original.split('##')[1].split('$$')[0]
        raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4))
        data = bytearray(gzip.decompress(raw[4:]))
        def encode(value):
            return 'DIV##' + base64.b64encode(raw[:4] + gzip.compress(value)).decode().rstrip('=') + '$$UNI'
        data[4] = 2
        self.assertTrue(guide_codes_equivalent(original, encode(data)))
        data[-1] ^= 1
        self.assertFalse(guide_codes_equivalent(original, encode(data)))

    def test_old_random_preset_or_unapplied_guide_cannot_launch(self):
        for field, value in [('members', ['old1', 'old2', 'old3', 'old4']),
                             ('guide_signature', 'not-applied'), ('threshold', None),
                             ('threshold', True), ('mode', '练习模式'), ('team_screenshot', ''),
                             ('guide_policy_applied',False)]:
            observation = dict(self.observation, **{field: value})
            with self.assertRaises(ValueError):
                verified_start(self.loadout, observation)

    def test_verified_team_rank_and_guide_retained_as_start_evidence(self):
        record = verified_start(self.loadout, self.observation)
        self.assertEqual(record['threshold'], 9)
        self.assertEqual(record['threshold_text'], '阈值协议 9')
        self.assertEqual(record['rank_title'], '万机之王')
        self.assertEqual(verified_star_rank(record), 10)
        self.assertEqual(record['star_rank_evidence']['entry_screenshot'], record['rank_screenshot'])
        self.assertEqual(record['star_rank_evidence']['mapping_source'],
                         'https://www.miyoushe.com/sr/article/77624815')
        self.assertEqual(record['members'], self.observation['members'])
        self.assertEqual(record['policy_signature'], self.loadout.signature)

    def test_unknown_numeric_rank_keeps_protocol_and_title_without_blocking_launch(self):
        record = verified_start(self.loadout, dict(self.observation, threshold=5,
                                title='决策智能', observed_text='阈值协议 5'))
        self.assertEqual(record['threshold'], 5)
        self.assertEqual(record['rank_title'], '决策智能')
        self.assertIsNone(record['star_rank'])
        self.assertIsNone(record['star_rank_evidence'])
        self.assertIsNone(verified_star_rank(record))

    def test_bare_protocol_nine_or_ten_and_claimed_numeric_rank_are_not_x10_proof(self):
        records = []
        for threshold in (9, 10):
            star = verified_start(self.loadout, dict(self.observation, threshold=threshold, title=''))
            self.assertIsNone(star['star_rank'])
            records.append(dict(id=str(threshold), star=dict(star, star_rank=10),
                                settlement_observed=True, result='win'))
        before = copy.deepcopy(records)
        summary = campaign_summary(records)
        self.assertEqual(summary['observed_target_runs'], 0)
        self.assertEqual(summary['unverified_rank_runs'], 2)
        self.assertFalse(summary['achieved'])
        self.assertEqual(records, before)

    def test_entry_rank_evidence_must_match_title_protocol_screenshot_and_source(self):
        star = verified_start(self.loadout, self.observation)
        for field, value in [('threshold', 10), ('rank_title', '决策智能'),
                             ('star_rank', 10.0), ('rank_screenshot', 'other.png'),
                             ('star_rank_evidence', None)]:
            self.assertIsNone(verified_star_rank(dict(star, **{field: value})))
        evidence = dict(star['star_rank_evidence'], mapping_source='unverified')
        self.assertIsNone(verified_star_rank(dict(star, star_rank_evidence=evidence)))
        # A relocated per-run entry screenshot remains bound to its proof.
        moved = dict(star, rank_screenshot='run/entry.png',
                     star_rank_evidence=dict(star['star_rank_evidence'], entry_screenshot='run/entry.png'))
        self.assertEqual(verified_star_rank(moved), 10)

    def test_promotion_to_x10_does_not_change_the_rank_played(self):
        star = verified_start(self.loadout, dict(self.observation, threshold=8, title='未核实称号'))
        run = dict(id='promotion', star=star, result='win', settlement_observed=True,
                   settlement_title='星阶提升', settlement_rank_title='万机之王',
                   next_entry_rank=10,
                   execution=dict(tracked_from_start=True, worker_builds=['build-a'], disk_changed=False))
        self.assertEqual(campaign_summary([run])['observed_target_runs'], 0)

    def test_survival_and_core_beat_unrelated_uncollected_high_rarity(self):
        choices = [SimpleNamespace(title='未收录无关祝福', uncollected=True, recommended=True, rarity=3),
                   SimpleNamespace(title='超高速云际介质', uncollected=False, recommended=False, rarity=3),
                   SimpleNamespace(title='测试核心方程', uncollected=False, recommended=False, rarity=3)]
        self.assertEqual(star_choice(choices, self.loadout, 'blessing').title, '超高速云际介质')
        self.assertEqual(star_choice([choices[0], choices[2]], self.loadout, 'equation').title, '测试核心方程')
        self.assertEqual(star_choice(choices, self.loadout, 'discard', owned=['超高速云际介质']).title,
                         '未收录无关祝福')

    def test_current_path_deficits_beat_unrelated_recommendation(self):
        loadout = loadout_from_guide(self.guides[0])
        def c(name):
            return SimpleNamespace(title=name,recommended=name=='子实体',rarity=2)
        self.assertEqual(star_choice([c('子实体'),c('《猫镇》')],loadout,'blessing').title,'《猫镇》')
        elation = [name for name,info in star_catalog()['blessings'].items() if info['path']=='欢愉'][:6]
        self.assertEqual(star_choice([c('《猫镇》'),c('相接双星')],loadout,'blessing',owned=elation).title,'相接双星')

    def test_live_requirement_overrides_older_catalog_count(self):
        loadout=loadout_from_guide(self.guides[0])
        elation=[name for name,info in star_catalog()['blessings'].items() if info['path']=='欢愉'][:6]
        choices=[SimpleNamespace(title='《猫镇》',recommended=False,rarity=2),
                 SimpleNamespace(title='相接双星',recommended=False,rarity=1)]
        actual={'拒火者':{'欢愉':7,'毁灭':5}}
        self.assertEqual(star_choice(choices,loadout,'blessing',owned=elation,requirements=actual).title,'《猫镇》')

    def test_actual_inventory_includes_automatic_rewards_missing_from_log(self):
        loadout=loadout_from_guide(self.guides[0])
        choices=[SimpleNamespace(title='《猫镇》',recommended=True,rarity=2),
                 SimpleNamespace(title='相接双星',recommended=False,rarity=1)]
        self.assertEqual(star_choice(choices,loadout,'blessing',owned=[],path_counts={'欢愉':9,'毁灭':1}).title,
                         '相接双星')
        with self.assertRaises(ValueError):
            star_choice(choices,loadout,'blessing',path_counts={'欢愉':-1})

    def test_clipped_current_title_requires_unique_prefix(self):
        table=star_catalog()['blessings']
        self.assertEqual(catalog_name('《白日漫漫路》',table),'《白日漫漫路迢迢》')
        self.assertIsNone(catalog_name('无关标题',table))
        equations=star_catalog()['equations']
        self.assertEqual(catalog_name('殷铸人生',equations),'骰铸人生')
        self.assertEqual(catalog_name('首美丽的诗',equations),'一首美丽的诗')
        self.assertEqual(catalog_name('梦魔主',equations),'梦魇主')
        self.assertEqual(equations[catalog_name('梦魔主',equations)]['rarity'],3)
        self.assertIsNone(catalog_name('白铸人生',equations))

    def test_discarded_and_duplicate_blessings_do_not_fill_path_deficits(self):
        rows=[dict(kind='blessing',title='《猫镇》'),dict(kind='blessing',title='《猫镇》'),
              dict(kind='blessing',title='相接双星'),dict(kind='discard',title='猫镇')]
        self.assertEqual(observed_blessings(rows),['相接双星'])

    def test_route_phase_uses_real_boss_rewards_not_a_fixed_node(self):
        self.assertEqual(star_station_order(dict(node=8,star={}))[:2],['战斗','奖励'])
        self.assertEqual(star_station_order(dict(node=5,star={'boss_rewards_seen':True}))[:2],['铸造','战斗'])

    def test_missing_primary_after_first_equipment_does_not_seek_weighted_only_forges(self):
        star=dict(threshold=5,boss_rewards_seen=True,loadout={'core_equations':['星星盗贼']},
                  choices=[],weighted_equipment=[{'id':1009}],path_counts={'欢愉':5,'巡猎':3})
        self.assertEqual(star_station_order({'star':star})[:2],['战斗','奖励'])
        star['weighted_equipment']=[]
        self.assertEqual(star_station_order({'star':star})[0],'铸造')

    def test_owned_core_without_enough_blessings_prioritizes_real_rewards(self):
        star=dict(boss_rewards_seen=True,loadout={'core_equations':['拒火者']},
                  choices=[{'kind':'equation','title':'拒火者'}],
                  weighted_equipment=[{'id':1011}],
                  observed_equation_requirements={'拒火者':{'欢愉':9,'毁灭':6}},
                  path_counts={'欢愉':0,'毁灭':5})
        self.assertEqual(star_station_order({'star':star})[:2],['战斗','奖励'])
        star['path_counts']={'欢愉':9,'毁灭':6}
        self.assertEqual(star_station_order({'star':star})[0],'战斗')

    def test_first_weighted_curio_is_not_delayed_until_a_far_away_core_is_complete(self):
        star=dict(boss_rewards_seen=True,loadout={'core_equations':['星星盗贼']},
                  choices=[{'kind':'equation','title':'星星盗贼'}],
                  observed_equation_requirements={'星星盗贼':{'欢愉':9,'巡猎':6}},
                  path_counts={'欢愉':4,'巡猎':2})
        self.assertEqual(star_station_order({'star':star})[0],'铸造')
        star['path_counts']={'欢愉':9,'巡猎':5}
        self.assertEqual(star_station_order({'star':star})[0],'战斗')
        star['path_counts']={'欢愉':4,'巡猎':2}
        star['weighted_equipment']=[{'id':1009}]
        self.assertEqual(star_station_order({'star':star})[0],'战斗')

    def test_counter_excludes_launches_lower_difficulty_losses_and_duplicates(self):
        star = verified_start(self.loadout, self.observation)
        execution=dict(tracked_from_start=True,worker_builds=['build-a'],disk_changed=False)
        history = [dict(id=f'win-{i}', star=star, execution=execution, settlement_observed=True, result='win') for i in range(11)]
        self.assertFalse(campaign_summary(history[:10])['achieved'])
        noise = [copy.deepcopy(history[0]), dict(id='launched', star=star),
                 dict(id='loss', star=star, settlement_observed=True, result='loss'),
                 dict(id='interrupted', star=star, settlement_observed=True, result='interrupted'),
                 dict(id='x8', star=dict(star, threshold=8), settlement_observed=True, result='win'),
                 dict(id='unverified', star=dict(star, members=['old']), settlement_observed=True, result='win')]
        summary = campaign_summary(history + noise)
        self.assertEqual(summary['wins'], 11)
        self.assertEqual(summary['nonwins'], 4)
        self.assertTrue(summary['achieved'])

    def test_stability_counter_does_not_pool_different_strategies_or_hide_unconfirmed(self):
        star=verified_start(self.loadout,self.observation)
        history=[dict(id=f'win-{i}',star=dict(star,policy_signature=f'candidate-{i//6}'),
                      execution=dict(tracked_from_start=True,worker_builds=['build-a'],disk_changed=False),
                      settlement_observed=True,result='win') for i in range(11)]
        summary=campaign_summary(history,unconfirmed=[dict(id='unconfirmed-loss',star=star,result='loss')])
        self.assertEqual(summary['wins'],11)
        self.assertEqual(summary['qualifying_wins'],6)
        self.assertEqual(summary['nonwins'],1)
        self.assertFalse(summary['achieved'])

    def test_code_changes_and_legacy_proof_do_not_become_a_frozen_cohort(self):
        star=verified_start(self.loadout,self.observation)
        history=[dict(id=f'win-{i}',star=star,settlement_observed=True,result='win',
                      execution=dict(tracked_from_start=True,worker_builds=['build-a' if i<6 else 'build-b'],
                                     disk_changed=False)) for i in range(11)]
        history.extend([dict(id='legacy',star=star,settlement_observed=True,result='win'),
                        dict(id='changed',star=star,settlement_observed=True,result='win',
                             execution=dict(tracked_from_start=True,worker_builds=['build-a'],disk_changed=True)),
                        dict(id='mixed',star=star,settlement_observed=True,result='win',
                             execution=dict(tracked_from_start=True,worker_builds=['build-a','build-b'],disk_changed=False))])
        history.append(dict(id='real-loss',star=star,result='loss',settlement_observed=True,
                            execution=dict(tracked_from_start=True,worker_builds=['build-a'],disk_changed=False)))
        summary=campaign_summary(history)
        self.assertEqual(summary['wins'],14)
        self.assertEqual(summary['qualifying_wins'],6)
        self.assertEqual(summary['unqualified_wins'],3)
        self.assertFalse(summary['achieved'])
        self.assertEqual(summary['cohort_attempts'][star['policy_signature']+':build-a'],7)
        self.assertAlmostEqual(summary['cohort_success_rates'][star['policy_signature']+':build-a'],6/7)

    def test_core_and_survival_rules_participate_in_strategy_identity(self):
        from dataclasses import replace
        self.assertNotEqual(self.loadout.signature,replace(self.loadout,core_equations=('另一个核心',)).signature)
        self.assertNotEqual(self.loadout.signature,replace(self.loadout,survival_blessings=('另一个生存祝福',)).signature)


if __name__ == '__main__':
    unittest.main()
