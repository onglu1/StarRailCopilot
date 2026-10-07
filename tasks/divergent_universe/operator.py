"""Reuse SRC screenshots, OCR, popup handling and touch controls for DU."""
import json
from pathlib import Path

from tasks.currency_wars.operator import MobileOperator


class DivergentOperator(MobileOperator):
    def __init__(self, device, config, evidence_dir=None):
        super().__init__(device, config, evidence_dir)
        # Currency Wars button templates must not suppress DU OCR fallbacks.
        self.fast_buttons = {}
        self.templates = Path(__file__).parent / 'templates'

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
        self.snapshot()
        if self.image.mean() < 3:
            self.sleep(0.5)
            return
        if self.text('确认退出游戏', (0.25, 0.3, 0.8, 0.65)):
            self.click_text('取消', (0.25, 0.4, 0.55, 0.7), after_sleep=0.5, exact=True)
            return
        from tasks.base.assets.assets_base_page import CLOSE
        from tasks.rogue.assets.assets_rogue_weekly import REWARD_CLOSE
        for close in (REWARD_CLOSE, CLOSE):
            if close.match_template_luma(self.image):
                self.device.click(close)
                self.sleep(0.5)
                return
        button = self.template('back', (0.9, 0, 1, 0.15))
        button = button or self.template('divergent_universe_quit', (0, 0, 0.13, 0.18))
        if button:
            self.click_box(button, after_sleep=0.6)
            return
        raise RuntimeError('差分宇宙返回控件未识别')
