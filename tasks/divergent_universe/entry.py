"""DU entry settings, applied only before starting a new exploration."""
import re
import unicodedata
import cv2
import numpy as np

from module.base.timer import Timer
from module.exception import RequestHumanTakeover
from module.logger import logger


class EntrySettings:
    LAUNCH = ('启动「差分宇宙」', '启动差分宇宙', '继续进度', '进入星阶模式')

    def __init__(self, main):
        self.main = main
        self.op = main.op
        self.config = main.config

    def prepare(self, calculation):
        op = self.op
        label = '常规演算' if calculation == 'standard' else '周期演算'

        if op.text('阈值协议', (0.12, 0.22, 0.3, 0.31), exact=True):
            op.wait_until(lambda: op.text(self.LAUNCH, (0.3, 0.65, 1, 1)),
                          action=lambda: op.click_point(1058 / 1280, 195 / 720, tag='DU_PROTOCOL_INFO_CLOSE'),
                          name='关闭阈值说明')

        def selected():
            if self.main.world_visible() or self.main.selection_kind() or self.main.is_combat_executing():
                return True
            if not op.text(self.LAUNCH, (0.3, 0.65, 1, 1)):
                return False
            periodic = op.text('周期演算', (0.48, 0.15, 1, 0.68))
            return bool(periodic) if calculation == 'periodic' else bool(
                not periodic and op.text(('常规演算', '难度'), (0.45, 0, 1, 0.68)))

        def select_mode():
            if op.text('模式选择', (0, 0, 0.3, 0.13)):
                op.click_text(label, (0, 0.13, 0.48, 0.88))
            elif op.text(self.LAUNCH, (0.3, 0.65, 1, 1)):
                op.back()
            elif self.main.lobby_visible():
                op.click_text('开始游戏', (0.05, 0.65, 1, 1))

        op.wait_until(selected, action=select_mode, name='选择' + label)
        logger.attr('DU calculation', calculation)
        op.save('calculation_' + calculation)
        if self.main.world_visible() or self.main.selection_kind() or self.main.is_combat_executing():
            logger.info('DU entered the retained run directly from mode selection')
            return
        if op.text('继续进度', (0.3, 0.65, 1, 1)):
            logger.info('DU continuing saved run; new difficulty settings apply to the next run')
            return
        if calculation == 'standard':
            self.configure_difficulty()
        else:
            self.configure_pollution()

    def configure_difficulty(self):
        mode = self.config.DivergentUniverse_DifficultyMode
        if mode == 'specified':
            level = self.config.DivergentUniverse_Difficulty
            if not self.select_base(level):
                raise RequestHumanTakeover(f'常规难度{level}尚不可挑战，未开始对局')
        elif mode == 'highest':
            if not any(self.select_base(level) for level in range(5, 0, -1)):
                raise RequestHumanTakeover('未识别到可挑战的常规难度，未开始对局')
        logger.attr('DU base difficulty', self.base_level())
        self.configure_pollution()
        self.op.save('difficulty_applied')

    def base_level(self):
        labels = self.op.read_region((0.45, 0.09, 0.96, 0.18), snapshot=False)
        text = unicodedata.normalize('NFKC', ' '.join(box.source for box in labels)).upper()
        match = re.search(r'难度\s*([IVX]+|[1-5])', text)
        if not match:
            return None
        value = match[1]
        return int(value) if value.isdigit() else {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'X': 10}.get(value)

    def select_base(self, level):
        if level not in range(1, 6):
            raise RequestHumanTakeover('基础难度必须是1至5')
        op = self.op
        limit = Timer(45, count=3).start()
        attempts = 0
        while not limit.reached():
            op.snapshot()
            if attempts and op.text(('未解锁', '解锁条件', '暂不可挑战'), (0.45, 0.18, 1, 1)):
                return False
            if self.base_level() == level:
                if op.text(('未解锁', '解锁条件', '暂不可挑战'), (0.45, 0.18, 1, 1)):
                    return False
                launch = op.text(self.LAUNCH, (0.65, 0.78, 1, 0.96))
                if launch and self.main.confirm_enabled(launch):
                    return True
            if not op.text('常规演算', (0, 0, 0.3, 0.13)):
                continue
            # Android's observed I–V list. Selection is confirmed from the
            # right-hand difficulty heading and enabled launch control.
            if attempts < 3 and op.click_point(106 / 1280, (130 + 90 * (level - 1)) / 720,
                                                tag=f'DU_DIFFICULTY_{level}', interval=3):
                attempts += 1
        return False

    def pollution_level(self):
        # The adjustable setting is Threshold Protocol. The boss's separate
        # pollution badge is descriptive and must never be used as its value.
        op = self.op
        if op.text('开启阈值协议', (0.70, 0.70, 1, 0.87)):
            return 0
        if not (op.template('protocol_active', (0.80, 0.75, 0.89, 0.86), confidence=0.80)
                or op.text('阈值协议', (0.78, 0.71, 0.91, 0.78))):
            return None
        crop = op.image[559:599, 1082:1120]
        red = crop[:, :, 0].astype(int) - np.maximum(crop[:, :, 1], crop[:, :, 2]).astype(int)
        clean = cv2.cvtColor(np.where(red > 80, 0, 255).astype('uint8'), cv2.COLOR_GRAY2RGB)
        value, _ = op.model.ocr_single_line(clean)
        match = re.fullmatch(r'\s*([1-4])\s*', value)
        return int(match[1]) if match else None

    def configure_pollution(self):
        mode = self.config.DivergentUniverse_PollutionMode
        if mode == 'current':
            return
        op = self.op
        target = self.config.DivergentUniverse_Pollution if mode == 'specified' else 4
        if target not in range(5):
            raise RequestHumanTakeover('阈值协议可选0至4，0表示关闭')
        limit = Timer(60, count=3).start()
        absent = Timer(2, count=3).start()
        previous = None
        while not limit.reached():
            op.snapshot()
            current = self.pollution_level()
            if current is None:
                if absent.reached() and op.text(self.LAUNCH, (0.65, 0.80, 1, 0.97)):
                    if target == 0 or mode == 'highest':
                        logger.info('DU current difficulty has no Threshold Protocol selector')
                        return
                    raise RequestHumanTakeover('当前难度没有阈值协议入口，未开始对局')
                continue
            absent.reset()
            if current == target:
                logger.attr('DU threshold protocol', current)
                op.save('protocol_applied')
                return
            if op.text(('尚未解锁', '未解锁', '需先通关'), (0.45, 0.15, 1, 0.95)):
                if mode == 'highest' and previous is not None:
                    logger.attr('DU highest unlocked protocol', previous)
                    return
                raise RequestHumanTakeover(f'阈值协议{target}尚未解锁，未开始对局')
            if current == 0:
                clicked = op.click_text('开启阈值协议', (0.70, 0.70, 1, 0.87), interval=2)
            else:
                if target > current:
                    # Disabled plus is grey; active controls are red. The
                    # observed level and enabled control define the max.
                    from module.base.utils import color_mask
                    crop = op.image[567:592, 1194:1220]
                    if mode == 'highest' and color_mask(crop, color=(226, 64, 71), threshold=65).sum() < 8:
                        logger.attr('DU highest unlocked protocol', current)
                        return
                clicked = op.click_point((1207 if target > current else 955) / 1280, 579 / 720,
                                         tag='DU_PROTOCOL_PLUS' if target > current else 'DU_PROTOCOL_MINUS', interval=2)
            if not clicked:
                continue
            previous = current
            op.wait_until(lambda: self.pollution_level() is not None and self.pollution_level() != current,
                          timeout=20, name='阈值协议等级更新')
        raise RequestHumanTakeover('阈值协议设置未确认，未开始对局')
