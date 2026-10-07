import unittest
from types import SimpleNamespace
from tasks.currency_wars.characters import Character, Positioning
from tasks.currency_wars.mobile import MobileCurrencyWars
from tasks.currency_wars.synergy import extract_traits, parse_synergy_targets, select_team


class SynergyTests(unittest.TestCase):
    def unit(self, name, cost, traits, stars=1, position=Positioning.OnOffField):
        return Character(name, cost, position, stars=stars, traits=traits)

    def test_native_title_reads_only_roster_synergies_not_search_level(self):
        self.assertEqual(parse_synergy_targets('【7仙舟3量子同频】煌煌威灵 速升8级'), {'仙舟': 7, '量子同频': 3})
        self.assertEqual(parse_synergy_targets('【7追击3公司】飞霄 6级搜牌'), {'追击': 7, '公司': 3})

    def test_tooltip_trait_decorations_and_followup_alias(self):
        self.assertEqual(extract_traits('感列车同行 图追加攻击'), ('列车同行', '追击'))

    def test_completing_a_synergy_precedes_an_unrelated_high_cost_unit(self):
        units = [self.unit('A', 1, ('仙舟',)), self.unit('B', 2, ('仙舟',)), self.unit('C', 5, ('公司',))]
        self.assertEqual(select_team(units, {'A': 2, 'B': 2, 'C': 2}, {'仙舟': 2}, 2), {'A', 'B'})

    def test_same_synergy_prefers_cost_before_stars(self):
        units = [self.unit('高费', 4, ('仙舟',), stars=1), self.unit('低费', 2, ('仙舟',), stars=3)]
        self.assertEqual(select_team(units, {'高费': 2, '低费': 3}, {'仙舟': 1}, 1), {'高费'})

    def test_equal_cost_prefers_stars(self):
        units = [self.unit('A', 4, ('仙舟',), stars=1), self.unit('B', 4, ('仙舟',), stars=2)]
        self.assertEqual(select_team(units, {'A': 2, 'B': 2}, {'仙舟': 1}, 1), {'B'})

    def test_duplicate_copies_do_not_count_twice_towards_a_synergy(self):
        units = [self.unit('A', 2, ('仙舟',), stars=1), self.unit('A', 2, ('仙舟',), stars=2), self.unit('B', 4, ('公司',))]
        self.assertEqual(select_team(units, {'A': 2, 'B': 2}, {'仙舟': 2}, 2), {'A', 'B'})

    def test_unavailable_front_capacity_chooses_the_best_feasible_subset(self):
        units = [self.unit(str(i), i, (), position=Positioning.OnField) for i in range(1, 6)]
        self.assertEqual(select_team(units, {str(i): 2 for i in range(1, 6)}, {}, 5, front_slots=4), {'2', '3', '4', '5'})

    def test_retired_temporary_front_does_not_refill_before_selected_support(self):
        op = SimpleNamespace(sleep=lambda seconds: None, drag_to=lambda *args, **kwargs: None,
                             locate=lambda *args, **kwargs: None)
        game = MobileCurrencyWars(op, 1)
        base = self.unit('core', 3, ('仙舟',), position=Positioning.OnField)
        extra = self.unit('temporary', 5, ('公司',), position=Positioning.OnField)
        support = self.unit('support', 1, ('仙舟',), position=Positioning.OffField)
        base.is_placed = extra.is_placed = True
        game.on_field_character[:2] = [base, extra]
        game.in_hand_character[0] = support
        game.max_team_size = 2
        game.strategy_characters = {'core': 2, 'support': 2}
        game.target_synergies = {'仙舟': 2}
        game.handle_special_event = lambda: None
        game.place_character()
        self.assertIs(game.on_field_character[0], base)
        self.assertIs(game.off_field_character[0], support)
        self.assertEqual(game.current_team_size, 2)
        self.assertIs(game.in_hand_character[1], extra)


if __name__ == '__main__':
    unittest.main()
