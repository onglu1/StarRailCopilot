"""Reuse SRC screenshots, OCR, popup handling and touch controls for DU."""
import json
from pathlib import Path
import time

from module.base.button import ClickButton
from module.base.timer import Timer

from tasks.currency_wars.operator import MobileOperator


class DivergentOperator(MobileOperator):
    def __init__(self, device, config, evidence_dir=None):
        super().__init__(device, config, evidence_dir)
        # Currency Wars button templates must not suppress DU OCR fallbacks.
        self.fast_buttons = {}
        self.templates = Path(__file__).parent / 'templates'
        self._click_intervals = {}
        self.frame_cache = {}

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
            return self.click_box(button)
        from tasks.base.assets.assets_base_page import BACK
        return self.popups.appear_then_click(BACK, interval=1)
