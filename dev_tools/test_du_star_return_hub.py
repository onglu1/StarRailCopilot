"""Observed delayed menu transitions must not queue a second CLOSE."""
from types import SimpleNamespace as NS
from unittest.mock import patch
import unittest

from module.config.config import TaskEnd
from module.exception import RequestHumanTakeover
from tasks.divergent_universe.star import StarPreparation


class ReturnHubTests(unittest.TestCase):
    def scenario(self, frames):
        pending = list(frames)
        closed, native_entry, evidence = [], [], []
        op = NS(current=None)

        def snapshot():
            frame = pending.pop(0)
            if frame == 'stop':
                raise TaskEnd
            op.current = frame

        op.snapshot = snapshot
        op.text = lambda label, *args, **kwargs: op.current == label
        main = NS(op=op, lobby_visible=lambda: op.current == 'hub',
                  world_visible=lambda: op.current == 'du_world',
                  is_combat_executing=lambda: op.current == 'combat',
                  is_in_main=lambda: op.current == 'main',
                  go_to_lobby=lambda: native_entry.append(op.current))
        preparation = StarPreparation(main)
        preparation.imported_details_visible = lambda: op.current == 'details'
        preparation.entry_back = lambda: closed.append(op.current) or True
        preparation.observe = lambda name: evidence.append(name)
        timer = NS(start=lambda: timer, reached=lambda: not pending)
        return preparation, timer, closed, native_entry, evidence

    def run_scenario(self, frames):
        preparation, timer, closed, native, evidence = self.scenario(frames)
        with patch('tasks.divergent_universe.star.Timer', return_value=timer):
            preparation.return_to_hub()
        return closed, native, evidence

    def test_delayed_guide_close_is_sent_once_until_page_changes(self):
        # Actual 11:05:07.953 CLOSE -> 08.038 old list -> 09.492 hub.
        closed, native, evidence = self.run_scenario(
            ['details'] * 4 + ['攻略推荐'] * 5 + ['transition', 'hub', 'hub'])
        self.assertEqual(closed, ['details', '攻略推荐'])
        self.assertEqual(native, [])
        self.assertEqual(evidence, [])

    def test_one_hub_frame_followed_by_overworld_is_not_success(self):
        closed, native, _ = self.run_scenario(['hub', 'main', 'hub', 'hub'])
        self.assertEqual(closed, [])
        self.assertEqual(native, ['main'])

    def test_existing_hub_is_confirmed_without_closing_it(self):
        self.assertEqual(self.run_scenario(['hub', 'hub']), ([], [], []))

    def test_stop_during_pending_close_propagates(self):
        preparation, timer, closed, _, _ = self.scenario(['攻略推荐', '攻略推荐', 'stop'])
        with patch('tasks.divergent_universe.star.Timer', return_value=timer):
            with self.assertRaises(TaskEnd):
                preparation.return_to_hub()
        self.assertEqual(closed, ['攻略推荐'])

    def test_unconfirmed_close_exhausts_existing_budget_without_repeat_input(self):
        preparation, timer, closed, _, evidence = self.scenario(['攻略推荐'] * 6)
        with patch('tasks.divergent_universe.star.Timer', return_value=timer):
            with self.assertRaises(RuntimeError):
                preparation.return_to_hub()
        self.assertEqual(closed, ['攻略推荐'])
        self.assertEqual(evidence, ['return_hub_timeout'])

    def test_unknown_page_keeps_original_takeover_without_guessing_back(self):
        preparation, timer, closed, _, _ = self.scenario(['unknown'] * 4)
        with patch('tasks.divergent_universe.star.Timer', return_value=timer):
            with self.assertRaises(RequestHumanTakeover):
                preparation.return_to_hub()
        self.assertEqual(closed, [])

    def test_actual_exploration_still_stops_without_back_or_lobby_reentry(self):
        for page in ('du_world', 'combat'):
            preparation, timer, closed, native, _ = self.scenario([page])
            with patch('tasks.divergent_universe.star.Timer', return_value=timer):
                with self.assertRaises(RequestHumanTakeover):
                    preparation.return_to_hub()
            self.assertEqual((closed, native), ([], []))

    def test_failed_preparation_routes_login_before_setup_and_preserves_recovery(self):
        recovery = dict(run_id=None, node=None, attempts=2, faults=1, deadline=123)
        main = NS(active=None, op=NS(), progress=NS(data={'recovery': recovery.copy()}))
        for error in (TaskEnd, RuntimeError):
            with self.subTest(error=error):
                def route():
                    raise error
                main.go_to_lobby = route
                with self.assertRaises(error):
                    StarPreparation(main).begin_run()
                self.assertEqual(main.progress.data['recovery'], recovery)
                self.assertIsNone(main.active)


if __name__ == '__main__':
    unittest.main()
