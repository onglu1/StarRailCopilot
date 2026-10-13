"""Reuse SRC screenshots, OCR, popup handling and touch controls for DU."""
import json
from collections import OrderedDict
from pathlib import Path
import time

import cv2
import numpy as np

from module.base.button import ClickButton
from module.base.timer import Timer

from tasks.currency_wars.operator import Box, MobileOperator


class DivergentOperator(MobileOperator):
    @staticmethod
    def region_pixels(region):
        if len(region) != 4 or not (0 <= region[0] < region[2] <= 1
                                   and 0 <= region[1] < region[3] <= 1):
            raise ValueError(f'DU recognition region outside the image: {region}')
        return MobileOperator.region_pixels(region)

    def __init__(self, device, config, evidence_dir=None):
        super().__init__(device, config, evidence_dir)
        # Currency Wars button templates must not suppress DU OCR fallbacks.
        self.fast_buttons = {}
        self.templates = Path(__file__).parent / 'templates'
        self._click_intervals = {}
        self.frame_cache = {}
        self._scaled_templates = {}

    def snapshot(self, ocr=False):
        from tasks.base.assets.assets_base_popup import MONTHLY_CARD_REWARD, MONTHLY_CARD_GET_ITEM
        timeout = Timer(45, count=3).start()
        while True:
            self.check()
            self.image = self.device.screenshot()
            self._ocr_cache.clear()
            self.frame_cache.clear()
            self.boxes = []
            handled = self.popups.handle_monthly_card_reward(interval=1)
            if not (handled or self.popups.appear(MONTHLY_CARD_REWARD)
                    or self.popups.appear(MONTHLY_CARD_GET_ITEM)):
                break
            if timeout.reached():
                raise TimeoutError('月卡奖励页面未能关闭')
        if self.image.shape[:2] != (720, 1280):
            raise ValueError(f'差分宇宙需要1280x720画面，实际为{self.image.shape}')
        if ocr:
            self.boxes = self.read_region((0, 0, 1, 1), snapshot=False)
        return self.boxes

    def check(self):
        if self.config.stop_event is not None and self.config.stop_event.is_set():
            from module.config.config import TaskEnd
            raise TaskEnd
        if time.monotonic() > self.deadline:
            raise TimeoutError('差分宇宙单局运行时间超过设置的上限')

    def click_point(self, x, y, tag='', interval=1, **kwargs):
        self.check()
        px, py = round(x * 1280), round(y * 720)
        if not (0 <= px < 1280 and 0 <= py < 720):
            raise ValueError(f'Invalid click coordinates: {(x, y)}')
        key = (tag, px // 40, py // 40)
        timer = self._click_intervals.setdefault(key, Timer(interval))
        if not timer.reached():
            return False
        self.device.click(ClickButton((px - 2, py - 2, px + 2, py + 2), name=tag or 'DU_CLICK'))
        timer.reset()
        return True

    def click_box(self, box, **kwargs):
        if box is None:
            return False
        x, y = box.center
        return self.click_point(x / 1280, y / 720, tag=box.source, **kwargs)

    def click_text(self, texts, region=(0, 0, 1, 1), exact=False, **kwargs):
        return self.click_box(self.text(texts, region, exact=exact), **kwargs)

    def wait_until(self, predicate, action=None, timeout=45, name='页面切换'):
        """Poll screenshots until the target is observed; never delay after a click."""
        limit = Timer(timeout, count=3).start()
        while True:
            self.snapshot()
            result = predicate()
            if result:
                return result
            if limit.reached():
                self.save('timeout_' + name)
                raise RuntimeError(f'{name}超时，目标界面未出现')
            if action is not None:
                action()

    def template(self, name, region=(0, 0, 1, 1), confidence=0.86):
        matches = self.template_matches(str(self.templates / f'{name}.png'), region, confidence)
        return matches[0] if matches else None

    def read_line(self, region, snapshot=True):
        if snapshot:
            self.snapshot()
        key = ('line', tuple(region))
        if key not in self._ocr_cache:
            self._ocr_cache[key] = self._reuse_ocr(key, region,
                lambda: MobileOperator.read_line(self, region, snapshot=False))
        return self._ocr_cache[key]

    def read_region(self, region, snapshot=True):
        if snapshot:
            self.snapshot()
        key = tuple(region)
        if key not in self._ocr_cache:
            self._ocr_cache[key] = self._reuse_ocr(('region', key), region,
                lambda: MobileOperator.read_region(self, region, snapshot=False))
        return self._ocr_cache[key]

    def _reuse_ocr(self, key, region, reader):
        x1, y1, x2, y2 = self.region_pixels(region)
        crop = self.image[y1:y2, x1:x2]
        cache = self.__dict__.setdefault('_stable_ocr', OrderedDict())
        previous = cache.get(key)
        if previous is not None and np.array_equal(crop, previous[0]):
            cache.move_to_end(key)
            return previous[1]
        result = reader()
        # Reuse only byte-identical small regions across screenshots. Changed
        # cards/buttons always invalidate, and large unknown pages aren't kept.
        if crop.nbytes <= 512 * 1024:
            cache[key] = (crop.copy(), result)
            cache.move_to_end(key)
            while len(cache) > 16:
                cache.popitem(last=False)
        return result

    def template_matches(self, path, region=(0, 0, 1, 1), confidence=0.83,
                         scales=(2 / 3, 0.75, 0.85, 1.0)):
        scales = tuple(scales)
        result_key = ('template_matches', str(path), tuple(region), confidence, scales)
        if result_key in self.frame_cache:
            return list(self.frame_cache[result_key])
        if path not in self._templates:
            self._templates[path] = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        template = self._templates[path]
        if template is None:
            return []
        x1, y1, x2, y2 = self.region_pixels(region)
        key = ('navigation_gray', tuple(region))
        if key not in self.frame_cache:
            gray = cv2.cvtColor(self.image[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
            self.frame_cache[key] = gray, None
        frame, small_frame = self.frame_cache[key]
        dense = len(scales) > 8
        if dense and small_frame is None:
            small_frame = cv2.resize(frame, None, fx=0.5, fy=0.5)
            self.frame_cache[key] = frame, small_frame
        matches = []
        for scale in scales:
            key = (path, float(scale))
            if key not in self._scaled_templates:
                sample = cv2.resize(template, None, fx=scale, fy=scale)
                h, w = sample.shape
                self._scaled_templates[key] = sample, cv2.resize(sample, (max(1, w // 2), max(1, h // 2)))
            sample, small_sample = self._scaled_templates[key]
            h, w = sample.shape
            if h >= frame.shape[0] or w >= frame.shape[1]:
                continue
            # Tiny features keep the original matcher. Larger templates use
            # a cheap candidate pass, then the original full-resolution score.
            reduced = dense and min(h, w) >= 16
            factor = (4 if reduced and min(h, w) >= 32
                      and Path(path).stem.startswith(('door_', 'event_')) else 2)
            if reduced and factor == 4:
                quarter_key = ('navigation_quarter', tuple(region))
                if quarter_key not in self.frame_cache:
                    self.frame_cache[quarter_key] = cv2.resize(frame, None, fx=0.25, fy=0.25)
                sample_key = (path, float(scale), 'quarter')
                if sample_key not in self._scaled_templates:
                    self._scaled_templates[sample_key] = cv2.resize(sample, (max(1, w // 4), max(1, h // 4)))
                search, needle = self.frame_cache[quarter_key], self._scaled_templates[sample_key]
            else:
                search = small_frame if reduced else frame
                needle = small_sample if reduced else sample
            nh, nw = needle.shape
            values = cv2.matchTemplate(search, needle, cv2.TM_CCOEFF_NORMED)
            # The coarser pass only proposes candidates. Acceptance still
            # uses the original pixels, scale and confidence below.
            threshold = (max(0.35, confidence - 0.30) if reduced and factor == 4
                         else max(0.45, confidence - 0.20) if reduced else confidence)
            while True:
                _, score, _, (px, py) = cv2.minMaxLoc(values)
                if score < threshold or len(matches) > 30:
                    break
                values[max(0, py - nh // 2):py + nh // 2 + 1,
                       max(0, px - nw // 2):px + nw // 2 + 1] = 0
                if reduced:
                    left, top = max(0, px * factor - 2 * factor), max(0, py * factor - 2 * factor)
                    crop = frame[top:min(frame.shape[0], py * factor + h + 2 * factor + 1),
                                 left:min(frame.shape[1], px * factor + w + 2 * factor + 1)]
                    if crop.shape[0] < h or crop.shape[1] < w:
                        continue
                    verified = cv2.matchTemplate(crop, sample, cv2.TM_CCOEFF_NORMED)
                    _, score, _, (dx, dy) = cv2.minMaxLoc(verified)
                    px, py = left + dx, top + dy
                if score >= confidence:
                    candidate = Box(x1 + px, y1 + py, w, h, Path(path).stem, score)
                    if all(candidate.distance(box) > min(w, h) / 2 for box in matches):
                        matches.append(candidate)
        matches.sort(key=lambda box: box.left)
        self.frame_cache[result_key] = tuple(matches)
        return list(matches)

    def save(self, name):
        if self.evidence_dir is None:
            return
        from module.base.utils import save_image
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        # Preserve the frame used for this decision, without taking a new
        # screenshot during a transition or replacing the recognition cache.
        save_image(self.image, self.evidence_dir / f'{name}.png')
        boxes = self.read_region((0, 0, 1, 1), snapshot=False)
        (self.evidence_dir / f'{name}.json').write_text(json.dumps(
            [{'text': b.source, 'box': b.button, 'score': b.score} for b in boxes],
            ensure_ascii=False, indent=2), encoding='utf-8')

    def back(self):
        # Android BACK opens the application's quit dialog. DU's in-game
        # return arrow / exit control has different semantics from PC Esc.
        if self.image.mean() < 3:
            return False
        if self.text('阈值协议', (0.12, 0.22, 0.3, 0.31), exact=True):
            return self.click_point(1058 / 1280, 195 / 720, tag='DU_PROTOCOL_INFO_CLOSE')
        if self.text('确认退出游戏', (0.25, 0.3, 0.8, 0.65)):
            return self.click_text('取消', (0.25, 0.4, 0.55, 0.7), exact=True)
        from tasks.base.assets.assets_base_page import CLOSE
        from tasks.rogue.assets.assets_rogue_weekly import REWARD_CLOSE
        for close in (REWARD_CLOSE, CLOSE):
            if close.match_template_luma(self.image):
                if self.popups.appear_then_click(close, interval=1):
                    return True
        button = self.template('back', (0.9, 0, 1, 0.15))
        button = button or self.template('divergent_universe_quit', (0, 0, 0.13, 0.18))
        if button:
            return self.click_box(button, interval=5)
        from tasks.base.assets.assets_base_page import BACK
        return self.popups.appear_then_click(BACK, interval=1)
