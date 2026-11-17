"""Effect applicability and observed-card crop boundaries, without game input."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from tasks.divergent_universe.star_effects import effect_features, observe_effects
from tasks.divergent_universe.star_policy import StarLoadout, rank_star_choices, upgrade_effect_policy


def card(title, text='', paths=(), rarity=1, recommended=False, candidate='followup'):
    return NS(title=title, effect_text=text, effect_tags=effect_features(text,candidate), paths=paths,
              rarity=rarity, recommended=recommended, uncollected=False)


class EffectPolicyTests(unittest.TestCase):
    def test_retained_run_policy_change_is_audited_not_a_new_run(self):
        import json
        from pathlib import Path
        guide=json.loads((Path(__file__).resolve().parents[1]/'tasks/divergent_universe/star_guides.json').read_text('utf-8'))['guides'][0]
        saved=dict(candidate='phainon',team=guide['candidate_team'],guide_code=guide['code'],revision='star-workshop-v6')
        active=dict(id='original',node=6,star=dict(loadout=saved,choices=[{'title':'kept'}]))
        self.assertEqual(upgrade_effect_policy(active)['node'],6)
        self.assertEqual(active['id'],'original')
        self.assertEqual(active['star']['choices'],[{'title':'kept'}])
        self.assertTrue(active['execution']['policy_corrected_during_run'])
        self.assertIsNone(upgrade_effect_policy(active))
    def loadout(self, candidate='followup'):
        return StarLoadout(candidate,('a','b','c','d'),'unused',core_equations=('除魔士',))

    def pick(self, cards, candidate='followup', **kwargs):
        return rank_star_choices(cards,self.loadout(candidate),'blessing',**kwargs)[0][0].title

    def test_current_effect_direction_overrides_the_old_name_assumption(self):
        text='敌方目标每陷入1个持续伤害状态，受到的伤害提高。'
        self.assertEqual(effect_features(text,'dot'),('damage',))
        self.assertNotIn('defense',effect_features(text,'dot'))
        self.assertEqual(effect_features(text,'followup'),())

    def test_live_fatal_damage_insurance_does_not_claim_repeatable_healing(self):
        text='角色可抵抗致命伤害，并回复自身生命值，我方全体生效次数有限。'
        for candidate in ('followup_fuxuan','dot'):
            self.assertEqual(effect_features(text,candidate),('revive',))
        choices=[card('巡猎填充',paths=('巡猎',)),
                 card('治疗候选','我方目标发动追加攻击后，回复生命值。',paths=('欢愉',))]
        held=effect_features(text,'followup_fuxuan')
        self.assertEqual(self.pick(choices,'followup_fuxuan',path_counts={'巡猎':3,'繁育':2},
                                   threshold=5,owned_effect_tags=held),'治疗候选')

    def test_live_simplified_base_effects_do_not_require_an_explicit_subject(self):
        examples={
            '受到的伤害降低。':('defense',),
            '防御力提高，忆灵额外提高。':('defense',),
            '消耗战技点时，防御力提高。':('defense',),
            '施放终结技后，生命上限提高。':('defense',),
            '造成的伤害提高。':('damage',),
            '造成的伤害提高，忆灵额外提高。':('damage',),
            '处于弱点击破状态下的敌方目标，防御力降低。':('damage',),
        }
        for candidate in ('followup_fuxuan','dot'):
            for text,tags in examples.items():
                with self.subTest(candidate=candidate,text=text):
                    self.assertEqual(effect_features(text,candidate),tags)

    def test_observed_conditional_defense_is_not_healing_or_an_enemy_effect(self):
        for text in ('消耗战技点后，受到的伤害降低。',
                     '生命百分比低于50%时，受到的伤害降低，回复量提高。'):
            self.assertEqual(effect_features(text,'dot'),('defense',))
            self.assertEqual(effect_features(text,'dot_blackswan'),('defense',))
        for text in ('消耗战技点后，敌方目标受到的伤害降低。',
                     '敌方目标生命百分比低于50%时，受到的伤害降低，回复量提高。',
                     '生命百分比低于35%时，受到的伤害降低，回复量提高。',
                     '能量百分比低于50%时，受到的伤害降低，回复量提高。'):
            self.assertNotIn('defense',effect_features(text,'dot'))
        self.assertEqual(effect_features('回复量提高。','dot'),())

    def test_actual_wly_n5_offer_values_sp_triggered_damage_reduction(self):
        loadout=StarLoadout('dot',('a','b','c','d'),'unused',
            core_equations=('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        choices=[card('互食联星','生命值或护盾量降低后，效果抵抗提高。',paths=('毁灭',),candidate='dot'),
                 card('端感棒','消耗战技点后，受到的伤害降低。',paths=('繁育',),rarity=2,candidate='dot'),
                 card('秋月行天','消灭敌方目标后，为我方全体目标回复生命值。',paths=('巡猎',),recommended=True,candidate='dot')]
        ranked=rank_star_choices(choices,loadout,'blessing',threshold=5,owned_effect_tags=['heal','revive'],
            path_counts={'记忆':1,'虚无':2,'巡猎':1,'毁灭':4,'欢愉':1,'繁育':3,'智识':0,'同谐':1},
            requirements={'铁臂侠':{'巡猎':6,'毁灭':4},'智人大冲浪':{'智识':6,'欢愉':4},'以太骇客':{'欢愉':6,'智识':4}})
        self.assertEqual(ranked[0][0].title,'端感棒')
        self.assertEqual(ranked[0][1][:6],(True,0,False,0,5,2))
        self.assertEqual(next(score[4] for c,score in ranked if c.title=='互食联星'),4)

    def test_actual_currency_n1_offer_values_explicit_low_health_defense(self):
        loadout=StarLoadout('dot_blackswan',('a','b','c','d'),'unused',
            core_equations=('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        choices=[card('原始陈述','造成的击破伤害提高。',paths=('同谐',),candidate='dot_blackswan'),
                 card('致密型闪焰','受到攻击时，使【耀变】伤害提高。',paths=('毁灭',),rarity=2,candidate='dot_blackswan'),
                 card('放射性衰变','生命百分比低于50%时，受到的伤害降低，回复量提高。',paths=('毁灭',),rarity=2,candidate='dot_blackswan')]
        ranked=rank_star_choices(choices,loadout,'blessing',threshold=5,
            path_counts={'记忆':0,'虚无':2,'巡猎':0,'毁灭':0,'欢愉':0,'繁育':1,'智识':1,'同谐':2},
            requirements={'丧气侠':{'繁育':6,'虚无':4},'威乐曼号':{'欢愉':6,'巡猎':4},'智人大冲浪':{'智识':6,'欢愉':4}})
        self.assertEqual(ranked[0][0].title,'放射性衰变')
        self.assertEqual(ranked[0][1][:6],(True,0,False,0,6,2))
        self.assertEqual(next(score[4] for c,score in ranked if c.title=='致密型闪焰'),4)

    def test_live_special_triggers_stay_distinct_from_base_effects(self):
        texts=(
            '阿哈行动后，我方全体目标获得护盾。',
            '我方目标造成欢愉伤害时的弱点击破效率提高。',
            '忆灵行动后，我方全体暴击率提高。',
            '【发牌员】造成伤害时，使攻击目标造成的伤害降低。',
            '使用【罐中脑】施放终结技时，我方全体造成的伤害提高。',
            '【魂茧】变为【蝶魄】时，回复生命值，并使该状态下造成的伤害提高。',
        )
        for candidate in ('followup_fuxuan','dot'):
            for text in texts:
                with self.subTest(candidate=candidate,text=text):
                    self.assertEqual(effect_features(text,candidate),())
            self.assertEqual(effect_features(
                '我方全体目标的防御力提高，阿哈首次行动后，额外提高。',candidate),('defense',))
        # Negative controls: a condition cannot become a guaranteed defense
        # or cycle benefit just because the same keywords occur afterward.
        self.assertEqual(effect_features('阿哈行动后，我方全体速度提高。','followup_fuxuan'),())
        self.assertEqual(effect_features('敌方目标的防御力提高。','dot'),())

    def test_observed_murmur_damage_and_charge_efficiency_fit_dot_only(self):
        texts=('【呢喃】伤害提高。', '【呢喃】获得充能时的充能效率提高。',
               '【呢喃】获得充能时的充能效率提高20%。')
        for text in texts:
            self.assertEqual(effect_features(text,'dot'),('damage',))
            self.assertEqual(effect_features(text,'followup_fuxuan'),())
        self.assertEqual(effect_features('【呢喃】充能上限提高20%。','dot'),())

    def test_live_murmur_automatic_links_match_only_the_two_dot_families(self):
        examples={
            '敌方目标陷入持续伤害时，为【呢喃】充能。':('damage',),
            '敌方目标每回合首次受到攻击后，触发1次【呢喃】伤害。':('damage',),
            '敌方目标回合结束时，【呢喃】获得充能值':('damage',),
            '敌方目标每次受到【呢喃】伤害后，造成的伤害降低。':('enemy_weaken',),
        }
        for text,tags in examples.items():
            for candidate in ('dot','dot_blackswan'):
                self.assertEqual(effect_features(text,candidate),tags)
            for candidate in ('aglaea','aglaea_sustain','phainon','followup','followup_fuxuan'):
                self.assertEqual(effect_features(text,candidate),())

    def test_murmur_corrupt_text_caps_and_other_triggers_remain_unknown(self):
        texts=(
            '【呢敌方目标回合结束时，喃】获得充能值。',
            '[呢敌方目标回合结束时，】获得充能值',
            '【呢喃】的清除阈值提高。',
            '【呢喃】的清除值上限提高。',
            '我方目标回合结束时，【呢喃】获得充能值。',
            '敌方目标每次受到【呢喃】伤害后，造成的伤害提高。',
            '敌方目标每回合首次受到攻击后，触发1次【魂茧】伤害。',
            '敌方目标回合结束时，【罐中脑】获得充能值。',
            '阿哈行动后，为【呢喃】充能。',
        )
        for candidate in ('dot','dot_blackswan'):
            for text in texts:
                self.assertEqual(effect_features(text,candidate),())
        # The known title cannot substitute for missing or corrupt text.
        self.assertEqual(card('启蒙与灭尽',texts[0],candidate='dot').effect_tags,())
        self.assertEqual(card('从存在到存在者','',candidate='dot').effect_tags,())

    def test_actual_9f_n9_murmur_enemy_weaken_changes_winner_without_new_weights(self):
        loadout=StarLoadout('dot',('a','b','c','d'),'unused',
            core_equations=('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        choices=[card('感知：锋刃的温度','攻击力提高。',paths=('记忆',),candidate='dot'),
                 card('放射性衰变','生命百分比低于50%时，受到的伤害降低，回复量提高。',
                      rarity=2,candidate='dot'),
                 card('眼泪与圣徒','敌方目标每次受到【呢喃】伤害后，造成的伤害降低。',
                      paths=('虚无',),rarity=2,recommended=True,candidate='dot')]
        context=dict(threshold=5,owned_effect_tags=['heal','dot_team_heal','revive'],
            requirements={'概念献祭典仪':{'虚无':9,'毁灭':6}},
            path_counts={'记忆':3,'虚无':7,'巡猎':0,'毁灭':6,'欢愉':1,'繁育':1,'智识':2,'同谐':1})
        choices[2].effect_tags=()
        old=rank_star_choices(choices,loadout,'blessing',**context)
        self.assertEqual((old[0][0].title,old[0][1][4:6]),('放射性衰变',(4,2)))
        choices[2].effect_tags=effect_features(choices[2].effect_text,'dot')
        new=rank_star_choices(choices,loadout,'blessing',**context)
        self.assertEqual((new[0][0].title,new[0][1][:6]),('眼泪与圣徒',(True,0,False,0,6,2)))

    def test_actual_9f_n15_murmur_charge_changes_winner_without_new_weights(self):
        loadout=StarLoadout('dot',('a','b','c','d'),'unused',
            core_equations=('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        choices=[card('启蒙与灭尽','敌方目标回合结束时，【呢喃】获得充能值',
                      paths=('虚无',),rarity=2,candidate='dot'),
                 card('凝滞织体','击破敌方目标弱点后，使其行动延后。',
                      paths=('同谐',),recommended=True,candidate='dot'),
                 card('秋月行天','消灭敌方目标后，为我方全体目标回复生命值。',
                      paths=('巡猎',),candidate='dot')]
        context=dict(threshold=5,owned_effect_tags=['heal','dot_team_heal','revive'],
            requirements={'概念献祭典仪':{'虚无':9,'毁灭':6}},
            path_counts={'记忆':3,'虚无':9,'巡猎':0,'毁灭':8,'欢愉':1,'繁育':3,'智识':4,'同谐':1})
        choices[0].effect_tags=()
        old=rank_star_choices(choices,loadout,'blessing',**context)
        self.assertEqual((old[0][0].title,old[0][1][4:6]),('凝滞织体',(3,3)))
        choices[0].effect_tags=effect_features(choices[0].effect_text,'dot')
        new=rank_star_choices(choices,loadout,'blessing',**context)
        self.assertEqual((new[0][0].title,new[0][1][:6]),('启蒙与灭尽',(True,0,False,0,4,2)))

    def test_explicit_superbreak_damage_keeps_the_complete_attack_condition(self):
        text='攻击处于弱点击破状态下的敌方目标后，造成超击破伤害。'
        for candidate in ('dot','dot_blackswan','aglaea','followup_fuxuan'):
            self.assertEqual(effect_features(text,candidate),('damage',))
            self.assertEqual(effect_features(text.replace('目标','自标'),candidate),('damage',))
        for partial in ('攻击处于弱点击破状态下的敌方目标后，',
                        '攻击敌方目标后，造成超击破伤害。',
                        '攻击处于非弱点击破状态下的敌方目标后，造成超击破伤害。',
                        text.replace('敌方','我方'),text.replace('目标','白标'),
                        '阿哈行动后，'+text):
            self.assertEqual(effect_features(partial,'dot'),())

    def actual_9f_n15_superbreak_offer(self):
        # 9fbd... N15 selection50: all three are recommended. The two
        # Harmony cards have the same path affinity; functional was 2 vs 0.
        loadout=StarLoadout('dot',('a','b','c','d'),'unused',
            core_equations=('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        choices=[card('安全擦除的舆图','终结技的暴击伤害提高',
                      paths=('智识',),recommended=True,candidate='dot'),
                 card('通奏的低音','攻击处于弱点击破状态下的敌方自标后，造成超击破伤害。',
                      paths=('同谐',),rarity=2,recommended=True,candidate='dot'),
                 card('厄运爵士','处于弱点击破状态下的敌方目标，防御力降低。',
                      paths=('同谐',),recommended=True,candidate='dot')]
        context=dict(threshold=5,requirements={'概念献祭典仪':{'虚无':9,'毁灭':6}},
            path_counts={'记忆':3,'虚无':9,'巡猎':0,'毁灭':8,'欢愉':1,'繁育':3,'智识':4,'同谐':1})
        return loadout,choices,context

    def test_actual_three_recommended_cards_use_rarity_after_equal_damage_tier(self):
        loadout,choices,context=self.actual_9f_n15_superbreak_offer()
        choices[1].effect_tags=()
        old=rank_star_choices(choices,loadout,'blessing',**context)
        self.assertEqual((old[0][0].title,old[0][1]),('厄运爵士',(True,0,False,0,2,2,False,True,1)))
        choices[1].effect_tags=effect_features(choices[1].effect_text,'dot')
        new=rank_star_choices(choices,loadout,'blessing',**context)
        self.assertEqual(new[0][0].title,'通奏的低音')
        self.assertEqual(new[0][1],(True,0,False,0,2,2,False,True,2))
        self.assertEqual(choices[0].effect_tags,())

    def test_superbreak_does_not_override_missing_insurance_or_one_card_core_completion(self):
        loadout,choices,context=self.actual_9f_n15_superbreak_offer()
        for title,text,paths in (
                ('最后的言者','敌方目标每受到1次持续伤害，我方全体回复生命值。',('虚无',)),
                ('新星爆发','角色可抵抗致命伤害，并回复自身生命值，我方全体生效次数有限。',('毁灭',))):
            insurance=card(title,text,paths=paths,candidate='dot')
            self.assertEqual(rank_star_choices(choices+[insurance],loadout,'blessing',**context)[0][0].title,title)
        counts=dict(context['path_counts'],虚无=8,毁灭=6)
        completing=card('虚无填充',paths=('虚无',),candidate='dot')
        context['path_counts']=counts
        self.assertEqual(rank_star_choices(choices+[completing],loadout,'blessing',**context)[0][0].title,'虚无填充')

    def test_independent_atk_clause_survives_only_its_observed_unknown_tail(self):
        text='攻击力提高，获得或消耗战技点后，为【魂茧】充能。'
        for candidate in ('aglaea','aglaea_sustain','dot','dot_blackswan'):
            self.assertEqual(effect_features(text,candidate),('damage',))
            self.assertEqual(effect_features('我方目标'+text,candidate),('damage',))
        for candidate in ('followup','followup_fuxuan','phainon','unreviewed_party'):
            self.assertEqual(effect_features(text,candidate),())
        for changed in (text.replace('攻击力提高','攻击力降低'), '敌方目标'+text,
                        text.replace('攻击力提高','攻击力提髙'),
                        '获得或消耗战技点后，为【魂茧】充能。',
                        '攻击力提高。进入战斗时为【魂茧】充能。',
                        '【蝶魄】状态下，攻击力提高。',
                        '攻击力提高，获得或消耗战技点后，为【魂茧】'):
            self.assertEqual(effect_features(changed,'dot'),())

    def test_debuff_atk_requires_the_complete_positive_dot_trigger(self):
        text='施加负面状态后，攻击力提高。'
        for candidate in ('dot','dot_blackswan'):
            self.assertEqual(effect_features(text,candidate),('damage',))
            self.assertEqual(effect_features('我方目标'+text,candidate),('damage',))
            for changed in ('敌方目标'+text,text.replace('提高','降低'),
                            '施加负面状态后，攻击力', '终结技的暴击伤害提高。'):
                self.assertEqual(effect_features(changed,candidate),())
        for candidate in ('aglaea','followup_fuxuan','unreviewed_party'):
            self.assertEqual(effect_features(text,candidate),())

    def actual_atk_clause_offers(self):
        core=('概念献祭典仪','丧气侠','骰铸人生','失心博士')
        # currency d23 N6/16: other unknown mechanics keep their old scores.
        mushi=[card('《甘草披萨·薄荷刨冰》',
                    '每经过50点行动值，【发牌员】会永久获得1点充能。【发牌员】充能越多，中立战斗事件，我方全体目标及其召唤物的速度越高。',
                    paths=('欢愉',),rarity=3,candidate='dot_blackswan'),
               card('随机自由程激波','我方目标每回合首次发动攻击后，对攻击目标造成基于【耀变】的附加伤害。',
                    rarity=3,recommended=True,candidate='dot_blackswan'),
               card('穆氏拟态','攻击力提高，获得或消耗战技点后，为【魂茧】充能',
                    paths=('繁育',),rarity=3,recommended=True,candidate='dot_blackswan')]
        # wly 9f N6/30: both original leading white cards had affinity=4.
        inner=[card('晶体谐振的灯塔','施放终结技后，生命上限提高。',
                    paths=('智识',),recommended=True,candidate='dot'),
               card('双瓣结构','效果抵抗提高。',paths=('毁灭',),recommended=True,candidate='dot'),
               card('内在体验','施加负面状态后，攻击力提高。',
                    paths=('虚无',),recommended=True,candidate='dot')]
        return [
            (StarLoadout('dot_blackswan',('a','b','c','d'),'unused',core_equations=core),mushi,
             dict(threshold=5,requirements={'丧气侠':{'繁育':6,'虚无':4}},
                  path_counts={'记忆':0,'虚无':3,'巡猎':1,'毁灭':2,'欢愉':0,'繁育':4,'智识':2,'同谐':3}),
             '随机自由程激波','穆氏拟态',(5,2)),
            (StarLoadout('dot',('a','b','c','d'),'unused',core_equations=core),inner,
             dict(threshold=5,requirements={'概念献祭典仪':{'虚无':9,'毁灭':6}},
                  path_counts={'记忆':1,'虚无':6,'巡猎':0,'毁灭':5,'欢愉':0,'繁育':1,'智识':3,'同谐':1}),
             '双瓣结构','内在体验',(6,2)),
        ]

    def test_actual_atk_clause_offers_change_only_the_unsupported_bonus(self):
        for loadout,choices,context,old_title,new_title,new_tier in self.actual_atk_clause_offers():
            target=next(c for c in choices if c.title==new_title)
            target.effect_tags=()
            self.assertEqual(rank_star_choices(choices,loadout,'blessing',**context)[0][0].title,old_title)
            target.effect_tags=effect_features(target.effect_text,loadout.candidate)
            ranked=rank_star_choices(choices,loadout,'blessing',**context)
            self.assertEqual((ranked[0][0].title,ranked[0][1][4:6]),(new_title,new_tier))

    def test_atk_clause_bonus_does_not_override_insurance_or_core_completion(self):
        for loadout,choices,context,_,_,_ in self.actual_atk_clause_offers():
            for title,text,path in (
                    ('新星爆发','角色可抵抗致命伤害，并回复自身生命值，我方全体生效次数有限。','毁灭'),
                    ('最后的言者','敌方目标每受到1次持续伤害，我方全体回复生命值。','虚无')):
                insurance=card(title,text,paths=(path,),candidate=loadout.candidate)
                self.assertEqual(rank_star_choices(choices+[insurance],loadout,'blessing',**context)[0][0].title,title)
            context=dict(context,path_counts=dict(context['path_counts'],虚无=8,毁灭=6))
            completion=card('虚无填充',paths=('虚无',),candidate=loadout.candidate)
            ranked=rank_star_choices(choices+[completion],loadout,'blessing',**context)
            self.assertTrue(ranked[0][1][2])

    def test_unverified_reverse_critical_wording_does_not_claim_damage(self):
        text='我方目标回合开始时，每持有1层【逆会心】，受到的伤害提高0.8%，持续至下回合开始时。'
        for candidate in ('followup','followup_fuxuan'):
            self.assertEqual(effect_features(text,candidate),())
            self.assertEqual(effect_features(text.replace('我方','敌方'),candidate),())
            self.assertEqual(effect_features(text.replace('逆会心','会心'),candidate),())
            self.assertEqual(effect_features('敌方目标的【逆会心】层数上限提高5层。',candidate),())
            self.assertEqual(effect_features(
                '我方目标消灭敌方目标后，行动提前100%，并使其他敌方目标获得4层【逆会心】。',candidate),())
        self.assertEqual(effect_features(text,'dot'),())

    def test_heal_trigger_must_fit_the_actual_team(self):
        text='我方目标发动追加攻击后，回复生命值。'
        self.assertIn('heal',effect_features(text,'followup'))
        self.assertEqual(effect_features(text,'dot'),())
        self.assertEqual(effect_features('消灭敌方目标后，我方全体回复生命值。','followup'),('kill_heal',))
        self.assertEqual(effect_features('受到回味伤害后，回复生命值。','followup'),())

    def test_observed_dot_team_heal_requires_explicit_party_scope_and_trigger(self):
        texts=('敌方目标每受到1次持续伤害，我方全体回复生命值。',
               '敌方目标每受到1次持续伤害，我方全体回复等同于各自1.0%生命上限的生命值。')
        for text in texts:
            for candidate in ('dot','dot_blackswan'):
                self.assertEqual(effect_features(text,candidate),('heal','dot_team_heal'))
            self.assertEqual(effect_features(text,'followup'),())
        for text in ('击破敌方目标弱点后，回复生命值。','消耗战技点时，回复生命值。',
                     '敌方目标每受到1次持续伤害，自身回复生命值。'):
            self.assertNotIn('dot_team_heal',effect_features(text,'dot'))
        self.assertEqual(effect_features('消灭敌方目标后，我方全体回复生命值。','dot'),('kill_heal',))

    def observed_dot_rewrite_offer(self):
        # currency d23f... N6 selection20: the actual inventory needs one
        # Erudition blessing for the current provisional equation target.
        text='敌方目标每受到1次持续伤害，我方全体回复生命值。'
        loadout=StarLoadout('dot_blackswan',('a','b','c','d'),'unused',
            core_equations=('概念献祭典仪','丧气侠','骰铸人生','失心博士'))
        choices=[card('重启：终末神经',paths=('智识',),rarity=2,recommended=True,candidate='dot_blackswan'),
                 card('最后的言者',text,paths=('虚无',),rarity=2,candidate='dot_blackswan'),
                 card('通奏的低音','攻击处于弱点击破状态下的敌方目标后，造成超击破伤害。',
                      paths=('同谐',),rarity=2,candidate='dot_blackswan')]
        context=dict(path_counts={'记忆':0,'虚无':4,'巡猎':0,'毁灭':3,'欢愉':0,'繁育':4,'智识':2,'同谐':2},
                     threshold=5,growth_target=dict(name='物理魔法少女',requirements={'毁灭':3,'智识':3},done=False))
        return loadout,choices,context

    def test_actual_selection20_generic_heals_do_not_fill_dot_team_gap(self):
        loadout,choices,context=self.observed_dot_rewrite_offer()
        held=[tag for text in ('击破敌方目标弱点后，回复生命值。','消耗战技点时，回复生命值。')
              for tag in effect_features(text,'dot_blackswan')]
        ranked=rank_star_choices(choices,loadout,'blessing',owned_effect_tags=held,**context)
        self.assertEqual(ranked[0][0].title,'最后的言者')
        self.assertEqual(ranked[0][1][1],2)
        by_name={c.title:s for c,s in ranked}
        self.assertTrue(by_name['重启：终末神经'][2])
        choices.append(card('新星爆发','角色可抵抗致命伤害，并回复自身生命值，我方全体生效次数有限。',
                            paths=('毁灭',),candidate='dot_blackswan'))
        self.assertEqual(rank_star_choices(choices,loadout,'blessing',owned_effect_tags=held,**context)[0][0].title,'新星爆发')

    def test_existing_dot_team_heal_recomputed_from_saved_text_restores_core_priority(self):
        import json
        loadout,choices,context=self.observed_dot_rewrite_offer()
        # Older histories only stored heal; the production caller recomputes
        # tags from the retained effect text for its actual candidate family.
        saved=json.loads(json.dumps(dict(effect_text=choices[1].effect_text,effect_tags=['heal'])))
        held=effect_features(saved['effect_text'],loadout.candidate)
        self.assertIn('dot_team_heal',held)
        ranked=rank_star_choices(choices,loadout,'blessing',owned_effect_tags=held,**context)
        self.assertEqual(ranked[0][0].title,'重启：终末神经')
        self.assertEqual(next(s[1] for c,s in ranked if c.title=='最后的言者'),0)

    def test_discard_protects_observed_dot_team_heal_without_new_priority_level(self):
        loadout,choices,context=self.observed_dot_rewrite_offer()
        ranked=rank_star_choices(choices[:2],loadout,'discard',
            owned_effect_tags=['heal','dot_team_heal'],**context)
        self.assertEqual(ranked[0][0].title,'重启：终末神经')
        self.assertEqual(ranked[-1][0].title,'最后的言者')

    def test_on_build_heal_beats_distant_primary_filler(self):
        choices=[card('巡猎填充',paths=('巡猎',),rarity=2),
                 card('《灰币金黄》','我方目标发动追加攻击后，回复生命值。',paths=('欢愉',))]
        self.assertEqual(self.pick(choices,path_counts={'巡猎':3,'繁育':2},threshold=5),'《灰币金黄》')

    def test_one_card_completion_beats_ordinary_effect_but_not_first_revive(self):
        choices=[card('巡猎填充',paths=('巡猎',)),card('《猫镇》','我方目标发动追加攻击后，速度提高。',paths=('欢愉',))]
        counts={'巡猎':8,'繁育':6}
        self.assertEqual(self.pick(choices,path_counts=counts,threshold=5),'巡猎填充')
        choices.append(card('顺序写入的轨道','角色受到致命攻击时，不会陷入无法战斗状态。',paths=('智识',)))
        self.assertEqual(self.pick(choices,path_counts=counts,threshold=5),'顺序写入的轨道')

    def test_fuxuan_avoids_observed_shared_damage_and_discard_reverses_it(self):
        choices=[card('超高速云际介质','受到攻击时，我方目标所受伤害由我方全体分摊。',paths=('毁灭',),rarity=3),
                 card('巡猎填充',paths=('巡猎',))]
        self.assertEqual(self.pick(choices,'followup_fuxuan'),'巡猎填充')
        ranked=rank_star_choices(choices,self.loadout('followup_fuxuan'),'discard')
        self.assertEqual(ranked[0][0].title,'超高速云际介质')

    def test_second_heal_does_not_permanently_starve_the_primary(self):
        choices=[card('巡猎填充',paths=('巡猎',)),
                 card('《灰币金黄》','我方目标发动追加攻击后，回复生命值。',paths=('欢愉',))]
        self.assertEqual(self.pick(choices,path_counts={'巡猎':8,'繁育':6},threshold=5,owned_effect_tags=['heal']),'巡猎填充')

    def test_unrecognized_or_wrong_team_descriptions_add_no_mechanic_bonus(self):
        self.assertEqual(effect_features('敌方目标陷入持续伤害后，呢喃充能提高。','dot'),())
        self.assertEqual(effect_features('随机效果提高。','followup'),())

    def test_observed_aha_action_energy_is_not_unconditional_energy(self):
        self.assertEqual(effect_features('阿哈行动时，为我方全体恢复能量。','dot'),())

    def test_description_crops_stay_inside_real_cards_and_skip_marker_fallback(self):
        regions=[]
        op=NS(image=object(),read_region=lambda region,**kw: regions.append(region) or [])
        main=NS(op=op,star_loadout=self.loadout(),config=NS(config_name='fixture'),
                active={'id':'fixture','node':1,'selections':2},progress=NS(record=lambda *a,**k:None))
        choices=[NS(title='left',box=NS(left=165,width=270,top=155,height=417)),
                 NS(title='right',box=NS(left=1200,width=200,top=155,height=417)),
                 NS(title='fallback',box=NS(left=370,width=210,top=210,height=300))]
        with patch('tasks.divergent_universe.star_effects.save_image'),patch('pathlib.Path.mkdir'):
            observe_effects(main,choices,'blessing')
        self.assertEqual(len(regions),1)
        x1,y1,x2,y2=regions[0]
        self.assertTrue(165/1280<x1<x2<435/1280)
        self.assertEqual((y1,y2),(390/720,528/720))
        self.assertFalse(hasattr(choices[-1],'effect_text'))


if __name__=='__main__':unittest.main()
