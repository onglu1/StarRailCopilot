"""Reveal a clipped favorite row, without scrolling a different game page."""
from types import SimpleNamespace as NS
import unittest

from module.config.config import TaskEnd
from tasks.divergent_universe.star import StarPreparation


class FavoriteGuideTests(unittest.TestCase):
    def fixture(self, frames):
        pending = list(frames)
        swipes, stable, evidence = [], [], []
        row = object()
        op = NS(current=None)
        def snapshot():
            op.current = pending.pop(0)
            if op.current == 'stop':
                raise TaskEnd
        def text(label, region, exact=False):
            if label == '星星盗贼':
                self.assertLessEqual(region[3], 630/720)
                return row if op.current == 'visible' else None
            return op.current in ('clipped', 'visible') and label in ('攻略推荐', '攻略码')
        op.snapshot, op.text, op.check = snapshot, text, lambda: None
        main = NS(op=op, device=NS(swipe=lambda *args: swipes.append(args)),
                  wait_until_stable=lambda area: stable.append(area))
        prep = StarPreparation(main)
        prep.imported_details_visible = lambda: op.current == 'detail'
        prep.observe = lambda name: evidence.append(name)
        return prep, row, swipes, stable, evidence

    def test_third_row_is_revealed_by_one_native_scroll(self):
        prep, row, swipes, stable, _ = self.fixture(['clipped', 'visible'])
        self.assertIs(prep.find_favorite_guide('星星盗贼'), row)
        self.assertEqual(swipes, [((1120,590),(1120,380))])
        self.assertEqual(len(stable), 1)

    def test_visible_target_needs_no_scroll(self):
        prep, row, swipes, _, _ = self.fixture(['visible'])
        self.assertIs(prep.find_favorite_guide('星星盗贼'), row)
        self.assertEqual(swipes, [])

    def test_page_change_or_stop_cannot_send_a_second_swipe(self):
        for frame, error in (('detail', RuntimeError), ('world', RuntimeError), ('stop', TaskEnd)):
            prep, _, swipes, _, _ = self.fixture(['clipped', frame])
            with self.assertRaises(error):
                prep.find_favorite_guide('星星盗贼')
            self.assertEqual(len(swipes), 1)

    def test_missing_guide_exhausts_two_swipes_and_retains_evidence(self):
        prep, _, swipes, _, evidence = self.fixture(['clipped'] * 3)
        with self.assertRaises(RuntimeError):
            prep.find_favorite_guide('星星盗贼')
        self.assertEqual(len(swipes), 2)
        self.assertEqual(evidence, ['favorite_guide_missing'])


if __name__ == '__main__':
    unittest.main()
