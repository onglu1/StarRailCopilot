"""Small OCR coordinate changes must not bypass a control's click interval."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tasks.divergent_universe.operator import DivergentOperator


class ClickIntervalTests(unittest.TestCase):
    def setUp(self):
        self.op=object.__new__(DivergentOperator)
        self.op.check=lambda:None
        self.op._click_intervals={}
        self.clicks=[]
        self.op.device=SimpleNamespace(click=lambda button:self.clicks.append(button))

    def test_jitter_across_old_pixel_buckets_does_not_duplicate_input(self):
        with patch('module.base.timer.time',return_value=100):
            self.assertTrue(self.op.click_point(1199/1280,264/720,tag='收起',interval=2))
            self.assertFalse(self.op.click_point(1201/1280,265/720,tag='收起',interval=2))
            self.assertTrue(self.op.click_point(1148/1280,34/720,tag='查看方程详情',interval=2))
            self.assertFalse(self.op.click_point(1149/1280,40/720,tag='查看方程详情',interval=2))
        self.assertEqual(len(self.clicks),2)

    def test_current_interval_is_honored_and_separate_buttons_remain_independent(self):
        with patch('module.base.timer.time',return_value=100):
            self.op.click_point(800/1280,570/720,tag='①确认',interval=1)
        with patch('module.base.timer.time',return_value=101.2):
            self.assertFalse(self.op.click_point(802/1280,571/720,tag='确认',interval=2))
            self.assertTrue(self.op.click_point(1080/1280,640/720,tag='确认',interval=2))
        with patch('module.base.timer.time',return_value=102.2):
            self.assertTrue(self.op.click_point(802/1280,571/720,tag='确认',interval=2))
        self.assertEqual(len(self.clicks),3)


if __name__=='__main__':unittest.main()
