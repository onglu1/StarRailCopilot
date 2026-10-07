from pathlib import Path
import tempfile
import unittest

from tasks.currency_wars.progress import Campaign


class ProgressTests(unittest.TestCase):
    def test_resume_and_settlement_are_not_counted_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            first = Campaign(path)
            active = first.begin('standard', 'test')
            resumed = Campaign(path)
            self.assertEqual(active['id'], resumed.begin('standard')['id'])
            resumed.settle({'result': 'win'}, run_id=active['id'])
            resumed.settle({'result': 'win'}, run_id=active['id'])
            self.assertEqual(resumed.completed, 1)

    def test_two_workers_reserve_distinct_games_and_share_total(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            primary, secondary = Campaign(path, 'currency'), Campaign(path, 'wly')
            a, b = primary.begin('standard'), secondary.begin('overclock')
            self.assertNotEqual(a['id'], b['id'])
            primary.settle({'result': 'win'}, a['id'])
            secondary.settle({'result': 'loss'}, b['id'])
            primary.reload()
            self.assertEqual(primary.completed, 2)
            self.assertEqual(primary.data['active'], {})

    def test_random_selection_covers_pool_before_repeating(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Campaign(Path(directory) / 'progress.json')
            chosen = [campaign.choose(['a', 'b', 'c']) for _ in range(3)]
            self.assertEqual(set(chosen), {'a', 'b', 'c'})

    def test_old_acceptance_target_does_not_limit_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            primary = Campaign(path, 'currency')
            primary.data['target'] = 1
            primary.save()
            self.assertIsNotNone(primary.begin('standard'))
            self.assertIsNotNone(Campaign(path, 'wly').begin('standard'))

    def test_stop_after_return_restores_original_settlement_before_next_game(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            first = Campaign(path)
            active = first.begin('standard', 'test')
            first.mark_strategy_applied()
            staged = first.stage_settlement({
                'result': 'win', 'strategy_imported': False,
                'evidence_dir': 'original-evidence',
            })
            first.heartbeat('stopped')

            resumed = Campaign(path)
            self.assertEqual(resumed.begin('standard')['id'], active['id'])
            self.assertEqual(resumed.completed, 0)
            self.assertEqual(resumed.pending_settlement(), staged)
            self.assertTrue(staged['strategy_imported'])
            self.assertEqual(staged['profile'], 'currency')
            self.assertEqual(staged['evidence_dir'], 'original-evidence')

            completed = resumed.complete_pending_settlement()
            self.assertEqual(completed, staged)
            self.assertEqual(resumed.data['settlements'], [completed])
            self.assertEqual(resumed.completed, 1)
            self.assertIsNone(resumed.complete_pending_settlement())
            self.assertEqual(Campaign(path).completed, 1)
            next_run = resumed.begin('standard')
            self.assertNotEqual(next_run['id'], active['id'])
            self.assertNotIn('strategy_applied', next_run)
            self.assertIsNone(resumed.pending_settlement())

    def test_pending_settlements_are_independent_between_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            primary, secondary = Campaign(path, 'currency'), Campaign(path, 'wly')
            a, b = primary.begin('standard'), secondary.begin('overclock')
            primary.stage_settlement({'result': 'win'})
            secondary.stage_settlement({'result': 'loss'})

            completed = Campaign(path, 'currency').complete_pending_settlement()
            self.assertEqual(completed['id'], a['id'])
            remaining = Campaign(path, 'wly')
            self.assertEqual(remaining.pending_settlement()['id'], b['id'])
            self.assertEqual(remaining.data['active']['wly']['id'], b['id'])
            self.assertEqual(remaining.completed, 1)
            self.assertEqual(remaining.complete_pending_settlement()['result'], 'loss')
            self.assertEqual(remaining.completed, 2)
            self.assertEqual(remaining.data['active'], {})

    def test_pending_settlement_does_not_limit_other_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            campaign = Campaign(path)
            campaign.data['target'] = 1
            campaign.save()
            campaign.begin('standard')
            campaign.stage_settlement({'result': 'win'})
            self.assertEqual(campaign.completed, 0)
            self.assertIsNotNone(Campaign(path, 'wly').begin('standard'))
            campaign.complete_pending_settlement()
            self.assertEqual(campaign.data['phase'], 'running')
            self.assertIsNotNone(campaign.begin('standard'))

    def test_settle_returns_saved_record_with_import_evidence_and_deduplication(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Campaign(Path(directory) / 'progress.json')
            active = campaign.begin('standard')
            campaign.mark_strategy_applied()
            original = {'result': 'win', 'strategy_imported': False}
            saved = campaign.settle(original)
            self.assertTrue(saved['strategy_imported'])
            self.assertFalse(original['strategy_imported'])
            self.assertEqual(saved, campaign.data['settlements'][0])
            duplicate = campaign.settle({'result': 'loss'}, run_id=active['id'])
            self.assertEqual(duplicate, saved)
            self.assertEqual(campaign.completed, 1)

    def test_observed_mode_survives_restart_with_different_configured_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            campaign = Campaign(path)
            active = campaign.begin('overclock')
            campaign.stage_settlement({'result': 'loss'})
            campaign.set_mode('standard')
            resumed = Campaign(path)
            restored = resumed.begin('overclock')
            self.assertEqual(restored['id'], active['id'])
            self.assertEqual(restored['mode'], 'standard')
            self.assertEqual(resumed.pending_settlement()['mode'], 'standard')
            self.assertEqual(resumed.stage_settlement({'result': 'loss'})['mode'], 'standard')

    def test_completion_without_pending_does_not_clear_an_active_game(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Campaign(Path(directory) / 'progress.json')
            self.assertIsNone(campaign.pending_settlement())
            self.assertIsNone(campaign.complete_pending_settlement())
            self.assertIsNone(campaign.stage_settlement({'result': 'win'}))
            active = campaign.begin('standard')
            self.assertIsNone(campaign.complete_pending_settlement())
            self.assertEqual(campaign.data['active']['currency']['id'], active['id'])
            self.assertEqual(campaign.completed, 0)
