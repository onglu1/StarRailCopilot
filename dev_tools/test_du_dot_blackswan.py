"""The Black Swan comparison reuses a guide, never the old team's proof."""
import hashlib
import json
from pathlib import Path
import re
import unittest

from tasks.character.keywords import CharacterList
from tasks.divergent_universe.star_policy import decode_guide_plan,loadout_from_guide,verified_start
from tasks.divergent_universe.star_effects import effect_features


ROOT=Path(__file__).resolve().parents[1]


class BlackSwanComparisonTests(unittest.TestCase):
    def test_new_candidate_keeps_current_dot_and_murmur_effect_interpretation(self):
        for text in ('【呢喃】获得充能时的充能效率提高。','【呢喃】伤害提高。',
                     '敌方目标每受到1次持续伤害，我方全体回复生命值。'):
            self.assertEqual(effect_features(text,'dot_blackswan'),effect_features(text,'dot'))
            self.assertTrue(effect_features(text,'dot_blackswan'))

    def setUp(self):
        guides=json.loads((ROOT/'tasks/divergent_universe/star_guides.json').read_text('utf-8'))['guides']
        self.original=next(guide for guide in guides if guide['key']=='dot')
        self.variant=next(guide for guide in guides if guide['key']=='dot_blackswan')
        self.proof=dict(import_verified=True,
            guide_signature=hashlib.sha256(self.original['code'].encode()).hexdigest(),
            core_equations=['概念献祭典仪','丧气侠','骰铸人生','失心博士'])

    def test_only_third_actual_slot_changes_and_guide_bytes_stay_exact(self):
        self.assertEqual(self.variant['code'],self.original['code'])
        self.assertEqual(self.variant['decoded'],self.original['decoded'])
        plan=decode_guide_plan(self.variant['code'])
        self.assertEqual(plan['weighted_curio_ids'],[1004,1009])
        self.assertEqual(plan['teams'],[[[1410],[1005],[1309],[1414]]])
        self.assertEqual(self.variant['selected_team_ids'],[1410,1005,1307,1414])
        self.assertEqual(self.variant['import_key'],'dot')
        self.assertFalse(self.variant['availability_verified'])
        self.assertNotIn('availability_evidence',self.variant)
        self.assertEqual(self.original['candidate_team'],['海瑟音','卡芙卡','知更鸟','丹恒•腾荒'])

    def test_native_keyword_and_portrait_back_the_selected_black_swan_identity(self):
        members=[CharacterList.instances[identity] for identity in self.variant['selected_team_ids']]
        self.assertEqual([member.cn for member in members],self.variant['selected_team_names'])
        black_swan=members[2]
        self.assertEqual((black_swan.id,black_swan.name,black_swan.cn),(1307,'BlackSwan','黑天鹅'))
        image=(ROOT/'assets/character'/f'{black_swan.name}.png').read_bytes()
        self.assertEqual(image[:8],b'\x89PNG\r\n\x1a\n')
        self.assertGreater(len(image),1000)

    def test_same_imported_core_still_has_a_distinct_actual_team_signature(self):
        old=loadout_from_guide(self.original,self.proof)
        new=loadout_from_guide(self.variant,self.proof)
        self.assertEqual(new.core_equations,old.core_equations)
        self.assertEqual(new.team,('海瑟音','卡芙卡','黑天鹅','丹恒•腾荒'))
        self.assertEqual(old.team[:2]+old.team[3:],new.team[:2]+new.team[3:])
        self.assertNotEqual(new.signature,old.signature)

    def test_old_four_slot_observation_cannot_validate_the_variant(self):
        old=loadout_from_guide(self.original,self.proof)
        new=loadout_from_guide(self.variant,self.proof)
        observation=dict(members=list(old.team),mode='拓星模式',threshold=5,
                         guide_signature=self.proof['guide_signature'],guide_policy_applied=True,
                         team_screenshot='fixture_old_team.png',rank_screenshot='fixture_rank.png')
        with self.assertRaisesRegex(ValueError,'实际队伍'):
            verified_start(new,observation)
        verified=verified_start(new,dict(observation,members=list(new.team),team_screenshot='fixture_new_team.png'))
        self.assertEqual(verified['candidate'],'dot_blackswan')
        self.assertEqual(verified['members'],list(new.team))

    def test_reusing_import_key_does_not_bypass_actual_guide_proof(self):
        for proof in (None,dict(self.proof,guide_signature='different'),
                      dict(self.proof,import_verified=False)):
            with self.assertRaises(ValueError):loadout_from_guide(self.variant,proof)

    def test_gui_option_and_generated_defaults_are_consistent(self):
        args=json.loads((ROOT/'module/config/argument/args.json').read_text('utf-8'))
        gui=args['DivergentUniverse']['DivergentUniverse']['StarStrategy']
        yaml=(ROOT/'module/config/argument/argument.yaml').read_text('utf-8')
        match=re.search(r'  StarStrategy:\s*\n    value: (\w+)\s*\n    option: \[([^\]]+)\]',yaml)
        self.assertIsNotNone(match)
        self.assertEqual(gui['option'],[name.strip() for name in match[2].split(',')])
        self.assertEqual(gui['option'].count('dot_blackswan'),1)
        self.assertEqual(gui['value'],match[1])
        generated=(ROOT/'module/config/config_generated.py').read_text('utf-8')
        assignment=next(line for line in generated.splitlines() if 'DivergentUniverse_StarStrategy =' in line)
        self.assertIn("= 'phainon'",assignment)
        self.assertIn('dot_blackswan',assignment)
        translation=json.loads((ROOT/'module/config/i18n/zh-CN.json').read_text('utf-8'))
        label=translation['DivergentUniverse']['StarStrategy']['dot_blackswan']
        self.assertIn('黑天鹅',label)
        self.assertIn('待验证',label)


if __name__=='__main__':unittest.main()
