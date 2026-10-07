from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tasks.currency_wars.mobile import MobileCurrencyWars
from tasks.currency_wars.progress import Campaign
from tasks.currency_wars.star_plan import build_star_plan


class StarPlanTests(unittest.TestCase):
    def test_caps_three_star_chases_at_two_and_stops_others_at_two(self):
        plan = build_star_plan({'辅助': 3, '副核': 3, '主核': 3, '挂件': 1}, '【3群攻】主核队')
        self.assertEqual(plan['cores'], ['主核', '辅助'])
        self.assertEqual(plan['targets'], {'辅助': 3, '副核': 2, '主核': 3, '挂件': 2})

    def test_herta_is_the_primary_chase_in_the_five_level_guide(self):
        plan = build_star_plan({'大黑塔': 3, '缇宝': 2, '瓦尔特': 2, '黑塔': 3, '花火': 2}, '【3量子同频3群攻】黑塔纪元 5级搜牌')
        self.assertEqual(plan['cores'], ['黑塔', '大黑塔'])
        self.assertEqual(plan['primary'], '黑塔')

    def test_complete_name_is_preferred_to_its_substring(self):
        plan = build_star_plan({'黑塔': 3, '大黑塔': 3}, '大黑塔队')
        self.assertEqual(plan['cores'], ['大黑塔', '黑塔'])

    def test_aglaea_guide_keeps_only_its_two_explicit_three_stars(self):
        plan = build_star_plan({'阿格莱雅': 3, '昔涟': 1, '瓦尔特': 3, '藿藿': 2}, '2000速阿格莱雅 速升9级')
        self.assertEqual(plan['cores'], ['阿格莱雅', '瓦尔特'])
        self.assertEqual(plan['targets']['昔涟'], 2)

    def test_unmarked_guide_chooses_only_one_carry(self):
        plan = build_star_plan({'银狼LV.999': 1, '火花': 1, '缇宝': 1}, '星核猎手加阿哈')
        self.assertEqual(plan['cores'], ['银狼LV.999'])
        self.assertEqual(list(plan['targets'].values()), [3, 2, 2])

    def test_takeover_keeps_plan_and_next_game_gets_its_own(self):
        folder = Path(__file__).resolve().parents[2] / 'state' / 'test-temp'
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            path = Path(directory) / 'progress.json'
            campaign = Campaign(path)
            campaign.begin('standard', 'guide')
            original = build_star_plan({'A': 3, 'B': 2}, 'A队')
            self.assertEqual(campaign.ensure_star_plan(original), original)
            resumed = Campaign(path)
            changed = build_star_plan({'A': 2, 'B': 3}, 'B队')
            self.assertEqual(resumed.ensure_star_plan(changed), original)
            saved = resumed.settle({'result': 'win'})
            self.assertEqual(saved['star_plan'], original)
            resumed.begin('standard', 'guide2')
            self.assertEqual(resumed.ensure_star_plan(changed), changed)

    def test_mobile_uses_fixed_targets_without_rewriting_source_guide(self):
        game = MobileCurrencyWars(SimpleNamespace(), 1)
        game.raw_star_targets = {'A': 3, 'B': 3, 'C': 3, 'D': 1}
        game.strategy_data = {'title': 'C队'}
        game.configure_star_plan()
        self.assertEqual(game.three_star_cores, ['C', 'A'])
        self.assertEqual(game.strategy_characters['B'], 2)
        self.assertEqual(game.strategy_characters['D'], 2)
        self.assertEqual(game.raw_star_targets['B'], 3)


if __name__ == '__main__':
    unittest.main()
