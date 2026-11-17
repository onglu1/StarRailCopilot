"""Retain actual outcomes while rejecting mixed-code stability samples."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tasks.divergent_universe import progress


class StarExecutionTests(unittest.TestCase):
    def setUp(self):
        evidence=Path(__file__).resolve().parents[3]/'evidence'
        self.tmp=tempfile.TemporaryDirectory(prefix='star-execution-test-',dir=evidence)
        self.root_patch=patch.object(progress,'ROOT',Path(self.tmp.name));self.root_patch.start()
        self.worker=progress.Progress('isolated-fixture')

    def tearDown(self):
        self.root_patch.stop();self.tmp.cleanup()

    def test_code_change_then_restore_keeps_real_win_but_never_erases_change(self):
        active=self.worker.begin('star','standard');identity=active['id']
        with patch.object(self.worker,'disk_build',return_value='different-source'):
            self.worker.save('combat')
        self.worker.save('running')
        active['settlement_observed']=True
        self.worker.finish('win')
        recorded=self.worker.data['history'][0]
        self.assertEqual(recorded['id'],identity)
        self.assertEqual(recorded['result'],'win')
        self.assertTrue(recorded['execution']['disk_changed'])
        self.assertIsNone(self.worker.data['active'])

    def test_new_worker_version_preserves_same_run_and_records_both_versions(self):
        active=self.worker.begin('star','standard');identity=active['id'];first=self.worker.build
        with patch.object(progress.Progress,'disk_build',return_value='new-worker-build'):
            resumed=progress.Progress('isolated-fixture')
            result=resumed.begin('star','standard')
        self.assertEqual(result['id'],identity)
        self.assertEqual(result['execution']['worker_builds'],[first,'new-worker-build'])
        self.assertEqual(resumed.data['history'],[])

    def test_legacy_run_cannot_gain_start_proof_by_reloading(self):
        self.worker.data['active']={'id':'older-run','mode':'star','node':5}
        self.worker.save('running')
        self.worker.begin('star')
        self.assertFalse(self.worker.data['active']['execution']['tracked_from_start'])
        self.assertEqual(self.worker.data['active']['node'],5)

    def test_source_read_failure_marks_evidence_unverified_without_interrupting_game(self):
        active=self.worker.begin('star','standard');identity=active['id']
        with patch.object(self.worker,'disk_build',side_effect=PermissionError('editor replacing file')):
            self.worker.save('combat')
        self.assertEqual(self.worker.data['phase'],'combat')
        self.assertEqual(self.worker.data['active']['id'],identity)
        self.assertTrue(active['execution']['disk_changed'])
        self.assertEqual(self.worker.data['history'],[])


if __name__=='__main__':unittest.main()
