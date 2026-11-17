"""Replay observed event frames with a recording device; no emulator input."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tasks.divergent_universe.events import DivergentEvent
from tasks.rogue.event import event as native_event


class EventConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence = Path(__file__).resolve().parents[3] / 'StarRailCopilot/log/error/1792094981797'
        cls.frames = {}
        for label, name in (
                ('top', '2026-10-16_04-09-25-614675.png'),
                ('bottom', '2026-10-16_04-09-29-184674.png')):
            image = cv2.imread(str(evidence / name))
            if image is None:
                raise FileNotFoundError(evidence / name)
            cls.frames[label] = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    def handler(self, initial, observations, interval_ready=True):
        pending = iter(observations)
        clicks = []
        device = SimpleNamespace(image=initial, stuck_record_add=Mock())
        def screenshot():
            device.image = next(pending)
            return device.image
        def click(button, control_check=True):
            clicks.append((tuple(button.button), control_check))
        device.screenshot = Mock(side_effect=screenshot)
        device.click = Mock(side_effect=click)
        handler = object.__new__(DivergentEvent)
        handler.device = device
        handler.interval_is_reached = Mock(return_value=interval_ready)
        handler.interval_reset = Mock()
        return handler, clicks

    def test_stale_bottom_position_is_replaced_by_fresh_native_top_match(self):
        handler, clicks = self.handler(self.frames['bottom'], [self.frames['top']] * 2)
        button = native_event.CHOOSE_OPTION_CONFIRM
        self.assertTrue(handler.appear(button))
        self.assertGreater(button.button[1], 500)
        self.assertTrue(handler.appear_then_click(button, interval=2))
        self.assertEqual(len(clicks), 1)
        rectangle, checked = clicks[0]
        self.assertTrue(230 <= rectangle[1] < rectangle[3] <= 275)
        self.assertTrue(checked)
        self.assertEqual(str(handler.device.click.call_args.args[0]), 'CHOOSE_OPTION_CONFIRM')
        handler.interval_reset.assert_called_once_with(button, interval=2)

    def test_row_change_between_fresh_frames_sends_no_click(self):
        handler, clicks = self.handler(self.frames['top'], [self.frames['bottom'], self.frames['top']])
        self.assertFalse(handler.appear_then_click(native_event.CHOOSE_OPTION_CONFIRM, interval=2))
        self.assertEqual(clicks, [])
        handler.interval_reset.assert_not_called()

    def test_disappeared_confirmation_sends_no_click(self):
        handler, clicks = self.handler(self.frames['top'], [np.zeros_like(self.frames['top'])])
        self.assertFalse(handler.appear_then_click(native_event.CHOOSE_OPTION_CONFIRM, interval=2))
        self.assertEqual(clicks, [])
        self.assertEqual(handler.device.screenshot.call_count, 1)

    def test_confirmation_disappearing_on_second_frame_sends_no_click(self):
        handler, clicks = self.handler(self.frames['top'],
                                       [self.frames['top'], np.zeros_like(self.frames['top'])])
        self.assertFalse(handler.appear_then_click(native_event.CHOOSE_OPTION_CONFIRM, interval=2))
        self.assertEqual(clicks, [])
        self.assertEqual(handler.device.screenshot.call_count, 2)

    def test_native_interval_is_preserved_without_extra_captures(self):
        handler, clicks = self.handler(self.frames['top'], [], interval_ready=False)
        self.assertFalse(handler.appear_then_click(native_event.CHOOSE_OPTION_CONFIRM, interval=2))
        self.assertEqual(clicks, [])
        handler.device.screenshot.assert_not_called()

    def test_other_event_controls_keep_native_dispatch(self):
        handler, _ = self.handler(self.frames['top'], [])
        with patch.object(native_event.RogueEvent, 'appear_then_click', return_value=True) as native:
            self.assertTrue(handler.appear_then_click(native_event.CHOOSE_STORY, interval=2))
        native.assert_called_once_with(native_event.CHOOSE_STORY, interval=2, similarity=0.85)
        handler.device.screenshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
