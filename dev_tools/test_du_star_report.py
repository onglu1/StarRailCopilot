"""Protocol-labelled reports preserve unknown historical star ranks."""
import json
from pathlib import Path
import tempfile
import unittest

from dev_tools.du_star_report import analyze


class StarReportTests(unittest.TestCase):
    def test_protocol_five_report_does_not_claim_verified_x5(self):
        run = dict(id='legacy', star=dict(threshold=5, candidate='dot', members=['a','b','c','d']),
                   result='win', settlement_observed=True, node=20)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for profile in ('wly', 'currency'):
                (root/f'{profile}.json').write_text(json.dumps(dict(history=[run], active=None)), encoding='utf-8')
                (root/f'{profile}.events.jsonl').write_text('', encoding='utf-8')
            report = analyze(root, {})
        self.assertNotIn('x5_summary', report)
        self.assertEqual(len(report['protocol5_summary']), 2)
        self.assertIn('x5_summary', report['caveats'][0])
        for row in report['runs']:
            self.assertEqual(row['threshold'], 5)
            self.assertIsNone(row['rank_title'])
            self.assertIsNone(row['star_rank'])
            self.assertIsNone(row['verified_star_rank'])
        self.assertEqual(run['star'], dict(threshold=5, candidate='dot', members=['a','b','c','d']))


if __name__ == '__main__':
    unittest.main()
