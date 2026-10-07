"""SRC device/OCR bridge for the imported Currency Wars strategy engine."""
from dataclasses import dataclass
from math import hypot
from pathlib import Path
import re
import time

import cv2
import numpy as np

from module.base.button import ClickButton
from module.logger import logger
from module.ocr.models import OCR_MODEL


@dataclass
class Box:
    left: int
    top: int
    width: int
    height: int
    source: str = ''
    score: float = 1.0

    @property
    def center(self):
        return self.left + self.width // 2, self.top + self.height // 2

    @property
    def button(self):
        return self.left, self.top, self.left + self.width, self.top + self.height

    @property
    def text(self):
        return self.source

    def distance(self, other):
        return hypot(self.center[0] - other.center[0], self.center[1] - other.center[1])


def normalize(text):
    return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9.+/\-]', '', text).replace('博奔', '博弈')


# OCR labels use the Android UI. Templates are reserved for non-text controls.
LABELS = {
    'start_currency_wars': ('开始货币战争',),
    'preparation_stage': ('准备阶段',),
    'enter_game': ('标准进入', '进入对局'),
    'continue_progress': ('继续进度',),
    'start_game': ('开始对局',),
    'next_step': ('下一步',),
    'next_page': ('下一页',),
    'back_currency_wars': ('返回货币战争',),
    'click_blank': ('点击空白处关闭', '点击空白处继续'),
    'invest_environment': ('选择投资环境', '投资环境'),
    'select_invest_strategy': ('选择投资策略',),
    'replenish_stage': ('补给阶段',),
    'encounter_node': ('遭遇节点',),
    'FortuneTeller': ('命运卜者',),
    'ThePlanetOfFestivities': ('盛会之星',),
    'silver_wolf_lv999': ('我来当策划',),
    'battle': ('战斗', '开始战斗'),
    'skip': ('跳过',),
    'settle': ('结算',),
    'continue': ('继续',),
    'quit': ('退出',),
    'withdraw_and_settle': ('撤资并结算', '结束并结算'),
    'retreat': ('撤退',),
    'strategy': ('攻略',),
    'hot_strategies': ('热门攻略',),
    'enter_strategy_code': ('输入攻略码', '导入攻略码', '攻略码'),
    'apply_strategy': ('应用攻略',),
    'equipment_recommend': ('装备推荐', '推荐装备'),
    'equip': ('装备', '穿戴'),
    'synthesis': ('合成',),
    'confirm_selection': ('确认选择', '确认'),
    'ensure': ('确认',),
    'ensure2': ('确认',),
    'collection': ('未收集',),
    'select_simple_equipment': ('选择初级装备', '选择简易装备'),
    'cannot_be_fielded': ('无法上场', '无法上阵', '无法编入', '无法出战', '备战席已满'),
    'return_highest_rank': ('返回最高职级',),
    'fold': ('收起',),
    'open': ('开启',),
    'instructions': ('赛季扩充说明',),
}


class MobileOperator:
    type = 'Local'

    def __init__(self, device, config, evidence_dir=None):
        self.device = device
        self.config = config
        self.window_context = type('WindowContext', (), {'width': 1280, 'height': 720})()
        self.model = OCR_MODEL.get_by_lang('cn')
        self.image = None
        self.boxes = []
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        self.deadline = time.monotonic() + max(1, config.CurrencyWars_MaxMinutes) * 60
        self._clipboard = ''
        self._templates = {}
        self._ocr_cache = {}
        from tasks.currency_wars.mobile_assets import FAST_BUTTONS
        self.fast_buttons = FAST_BUTTONS
        from tasks.base.popup import PopupHandler
        self.popups = PopupHandler(config=config, device=device)
        self.campaign = None
        self.phase = 'preparing'
        self._last_heartbeat = 0.0
        self.progress_callback = None

    def check(self):
        event = self.config.stop_event
        if event is not None and event.is_set():
            from module.config.config import TaskEnd
            raise TaskEnd
        if time.monotonic() > self.deadline:
            raise TimeoutError('货币战争单局运行时间超过设置的上限')

    def sleep(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            time.sleep(min(0.2, max(0, end - time.monotonic())))

    def snapshot(self, ocr=False):
        self.check()
        # The native SRC handler covers the 04:00 monthly-card popup and its
        # reward page. It operates before any Currency Wars screen decisions.
        from tasks.base.assets.assets_base_popup import MONTHLY_CARD_REWARD, MONTHLY_CARD_GET_ITEM
        for _ in range(40):
            self.image = self.device.screenshot()
            handled = self.popups.handle_monthly_card_reward(interval=1)
            visible = handled or self.popups.appear(MONTHLY_CARD_REWARD) or self.popups.appear(MONTHLY_CARD_GET_ITEM)
            if not visible:
                break
            self.device.stuck_record_clear()
            self.sleep(0.2)
        else:
            raise TimeoutError('月卡奖励弹窗尚未关闭，停止货币战争操作')
        if self.image.shape[:2] != (720, 1280):
            raise ValueError(f'货币战争需要 SRC 的 1280x720 画面，实际为 {self.image.shape}')
        self._ocr_cache.clear()
        self.boxes = []
        if self.campaign is not None and time.monotonic() - self._last_heartbeat >= 10:
            self.campaign.heartbeat(self.phase)
            self._last_heartbeat = time.monotonic()
        if ocr:
            self.boxes = self.read_region((0, 0, 1, 1), snapshot=False)
        return self.boxes

    def read_region(self, region, snapshot=True):
        if snapshot:
            self.snapshot(ocr=False)
        key = tuple(region)
        if key in self._ocr_cache:
            return self._ocr_cache[key]
        x1, y1, x2, y2 = self.region_pixels(region)
        crop = self.image[y1:y2, x1:x2]
        if not crop.size:
            return []
        result = []
        for item in self.model.detect_and_ocr(crop):
            points = np.asarray(item.box)
            left, top = points.min(axis=0).astype(int)
            right, bottom = points.max(axis=0).astype(int)
            result.append(Box(int(left + x1), int(top + y1), int(right - left), int(bottom - top), item.ocr_text, float(item.score)))
        result = sorted(result, key=lambda box: (box.top // 20, box.left))
        self._ocr_cache[key] = result
        return result

    def read_line(self, region, snapshot=True):
        if snapshot:
            self.snapshot(ocr=False)
        x1, y1, x2, y2 = self.region_pixels(region)
        text, score = self.model.ocr_single_line(self.image[y1:y2, x1:x2])
        return Box(x1, y1, x2 - x1, y2 - y1, text, float(score))

    def read_character_name(self):
        return [self.read_line((925 / 1280, 69 / 720, 1095 / 1280, 105 / 720))]

    def read_shop_names(self):
        self.snapshot(ocr=False)
        regions = [(154 + 224 * i, 222, 297 + 224 * i, 255) for i in range(5)]
        crops = [self.image[y1:y2, x1:x2] for x1, y1, x2, y2 in regions]
        results = self.model.ocr_lines(crops)
        return [Box(x1, y1, x2 - x1, y2 - y1, text, float(score)) for (x1, y1, x2, y2), (text, score) in zip(regions, results) if text.strip()]

    def read_shop_prices(self):
        # Trial / upgraded shop units cost more than a one-star character.
        crops = [self.image[220:255, 317 + 224 * i:348 + 224 * i] for i in range(5)]
        prices = []
        for text, _ in self.model.ocr_lines(crops):
            match = re.search(r'\d+', text)
            prices.append(int(match.group()) if match else None)
        return prices

    @staticmethod
    def region_pixels(region):
        x1, y1, x2, y2 = region
        return max(0, round(x1 * 1280)), max(0, round(y1 * 720)), min(1280, round(x2 * 1280)), min(720, round(y2 * 720))

    def match(self, texts, region=(0, 0, 1, 1), exact=False):
        if isinstance(texts, str):
            texts = (texts,)
        x1, y1, x2, y2 = self.region_pixels(region)
        fast = getattr(self, 'fast_buttons', {})
        pixels = getattr(self, 'image', None)
        matched = []
        if pixels is not None:
            for text in texts:
                for button in fast.get(normalize(text), []):
                    self.device.stuck_record_add(button)
                    if button.match_template_luma(pixels, similarity=0.87):
                        left, top, right, bottom = button.button
                        box = Box(left, top, right - left, bottom - top, text)
                        cx, cy = box.center
                        if x1 <= cx <= x2 and y1 <= cy <= y2:
                            matched.append(box)
            if matched:
                return matched
            if all(normalize(text) in fast for text in texts):
                return []
        candidates = []
        boxes = self.read_region(region, snapshot=False) if pixels is not None and hasattr(self, 'model') else self.boxes
        for box in boxes:
            cx, cy = box.center
            if not (x1 <= cx <= x2 and y1 <= cy <= y2):
                continue
            value = normalize(box.source)
            if any((normalize(text) == value if exact else normalize(text) in value) for text in texts):
                candidates.append(box)
        return candidates

    def text(self, texts, region=(0, 0, 1, 1), exact=False):
        matches = self.match(texts, region, exact)
        return matches[0] if matches else None

    def text_ocr(self, texts, region, exact=False):
        if isinstance(texts, str):
            texts = (texts,)
        for box in self.read_region(region, snapshot=False):
            value = normalize(box.source)
            if any((value == normalize(text) if exact else normalize(text) in value) for text in texts):
                return box
        return None

    def is_currency_settlement(self):
        footer = self.text(('下一步', '下一页', '返回货币战争'), (0.1, 0.65, 1, 1))
        if not footer:
            return False
        if normalize(footer.source) in ('下一页', '返回货币战争'):
            return True
        return bool(self.text(('挑战成功', '挑战失败', '对局评价', '对局胜利', '对局未完成'), (0.1, 0.05, 0.9, 0.5)))

    def is_currency_battle(self):
        return any(re.search(r'[1-3]\s*-\s*\d+', box.source) for box in self.read_region((0.28, 0, 0.46, 0.08), snapshot=False))

    def dismiss_equipment_combine(self):
        cancel = self.text('EquipmentCombineCancel', (0.75, 0.45, 0.87, 0.65))
        confirm = self.text('EquipmentCombineConfirm', (0.83, 0.45, 0.97, 0.65))
        if cancel and confirm:
            logger.info('CW dismiss accidental equipment-combine prompt')
            self.click_box(cancel, after_sleep=0.3)
            return True
        return False

    @staticmethod
    def equipment_rectangles(image):
        x0, y0 = 975, 105
        crop = cv2.cvtColor(image[y0:440, x0:1275], cv2.COLOR_RGB2GRAY)
        contours, _ = cv2.findContours(cv2.Canny(crop, 30, 100), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if 50 <= w <= 76 and 50 <= h <= 76 and 0.8 <= w / h <= 1.2 and cv2.contourArea(contour) > w * h * 0.55:
                box = Box(x + x0, y + y0, w, h, 'CW_EQUIPMENT_SLOT')
                if all(box.distance(old) > 15 for old in boxes):
                    boxes.append(box)
        return boxes

    def dismiss_currency_interrupt(self):
        if self.text('是否中断挑战', (0.32, 0.30, 0.85, 0.43)):
            self.click_point(1058 / 1280, 195 / 720, after_sleep=0.5, tag='CW_KEEP_PLAYING')
            return True
        return False

    def dismiss_currency_tutorial(self):
        if self.text(('超频博弈规则', '货币战争规则'), (0.35, 0.07, 0.70, 0.18)):
            if not self.click_text('关闭', (0.3, 0.82, 0.7, 0.96), after_sleep=0.5, exact=True):
                self.click_point(1215 / 1280, 334 / 720, after_sleep=0.5, tag='CW_TUTORIAL_NEXT')
            return True
        return False

    def click_point(self, x, y, after_sleep=0, tag='', trace=True, **kwargs):
        self.check()
        px, py = round(x * 1280), round(y * 720)
        if not (0 <= px < 1280 and 0 <= py < 720):
            raise ValueError(f'Invalid click coordinates: {(x, y)}')
        name = tag or f'CW_{px}_{py}'
        self.device.click(ClickButton((px - 2, py - 2, px + 2, py + 2), name=name))
        self.sleep(after_sleep)
        return True

    def click_box(self, box, after_sleep=0, **kwargs):
        if box is None:
            return False
        x, y = box.center
        return self.click_point(x / 1280, y / 720, after_sleep=after_sleep, tag=box.source)

    def click_text(self, texts, region=(0, 0, 1, 1), after_sleep=0.5, exact=False):
        return self.click_box(self.text(texts, region, exact), after_sleep=after_sleep)

    def drag_to(self, x1, y1, x2, y2, **kwargs):
        self.check()
        self.device.drag((round(x1 * 1280), round(y1 * 720)), (round(x2 * 1280), round(y2 * 720)), point_random=(-2, -2, 2, 2), name='CW_DRAG')
        return True

    def locate(self, img, **kwargs):
        self.snapshot()
        return self._locate(img, **kwargs)

    def _locate(self, img, **kwargs):
        stem = Path(img).stem
        region = tuple(kwargs.get(k, v) for k, v in zip(('from_x', 'from_y', 'to_x', 'to_y'), (0, 0, 1, 1)))
        if stem in LABELS:
            matches = self.match(LABELS[stem], region, exact=stem in ('continue', 'battle', 'equip', 'synthesis', 'ensure', 'ensure2'))
            if matches:
                return matches[0]
            return None
        # Textless PC controls are matched at Android pixel scale.
        if stem not in ('star', 'down_arrow', 'invest_env_refresh', 'invest_strategy_refresh', 'right'):
            return None
        matches = self.template_matches(img, region, confidence=kwargs.get('confidence', 0.83))
        return matches[0] if matches else None

    def template_matches(self, path, region=(0, 0, 1, 1), confidence=0.83):
        if path not in self._templates:
            template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            self._templates[path] = template
        template = self._templates[path]
        if template is None:
            return []
        x1, y1, x2, y2 = self.region_pixels(region)
        frame = cv2.cvtColor(self.image[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
        matches = []
        for scale in (2 / 3, 0.75, 0.85, 1.0):
            sample = cv2.resize(template, None, fx=scale, fy=scale)
            h, w = sample.shape
            if h >= frame.shape[0] or w >= frame.shape[1]:
                continue
            values = cv2.matchTemplate(frame, sample, cv2.TM_CCOEFF_NORMED)
            while True:
                _, score, _, point = cv2.minMaxLoc(values)
                if score < confidence or len(matches) > 30:
                    break
                px, py = point
                candidate = Box(x1 + px, y1 + py, w, h, Path(path).stem, score)
                if all(candidate.distance(box) > min(w, h) / 2 for box in matches):
                    matches.append(candidate)
                values[max(0, py - h // 2):py + h // 2 + 1, max(0, px - w // 2):px + w // 2 + 1] = 0
        return sorted(matches, key=lambda box: box.left)

    def locate_all(self, img, **kwargs):
        self.snapshot()
        stem = Path(img).stem
        region = tuple(kwargs.get(k, v) for k, v in zip(('from_x', 'from_y', 'to_x', 'to_y'), (0, 0, 1, 1)))
        if stem in LABELS:
            return self.match(LABELS[stem], region)
        return self.template_matches(img, region, kwargs.get('confidence', 0.83))

    def locate_any(self, images, **kwargs):
        self.snapshot()
        for i, path in enumerate(images):
            box = self._locate(path, **kwargs)
            if box:
                return i, box
        return -1, None

    def wait_any_img(self, images, timeout=30, interval=0.5, **kwargs):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.locate_any(images, **kwargs)
            if found[0] >= 0:
                return found
            self.sleep(interval)
        return -1, None

    def wait_img(self, img, **kwargs):
        return self.wait_any_img([img], **kwargs)[1]

    def click_img(self, img, after_sleep=0, **kwargs):
        return self.click_box(self.locate(img, **kwargs), after_sleep)

    def ocr_boxes(self, from_x=0, from_y=0, to_x=1, to_y=1, **kwargs):
        return self.read_region((from_x, from_y, to_x, to_y))

    def ocr(self, **kwargs):
        return [([[b.left, b.top], [b.left + b.width, b.top], [b.left + b.width, b.top + b.height], [b.left, b.top + b.height]], b.source, b.score) for b in self.ocr_boxes(**kwargs)]

    def rectangle_detect(self, *args, **kwargs):
        self.snapshot(ocr=False)
        region = tuple(kwargs.get(k, v) for k, v in zip(('from_x', 'from_y', 'to_x', 'to_y'), (0.1, 0.52, 0.86, 0.7)))
        return self.board_rectangles(self.image, region)

    @classmethod
    def board_rectangles(cls, image, region=(0.1, 0.52, 0.97, 0.7)):
        x1, y1, x2, y2 = cls.region_pixels(region)
        # Legacy callers use .86, which can cut through a wide backend row.
        x2 = max(x2, round(0.97 * 1280))
        gray = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
        contours, _ = cv2.findContours(cv2.Canny(gray, 30, 100), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        weak = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if 55 <= w <= 125 and 65 <= h <= 125:
                box = Box(x1 + x, y1 + y, w, h, 'CW_BACK_SLOT')
                weak.append(box)
                if cv2.contourArea(contour) > w * h * 0.45:
                    found.append(box)
        distinct = []
        for box in sorted(found, key=lambda box: box.width * box.height, reverse=True):
            if all(abs(box.center[0] - other.center[0]) > 25 for other in distinct):
                distinct.append(box)
        if not 6 <= len(distinct) <= 10:
            return []
        distinct.sort(key=lambda box: box.left)
        xs = np.array([box.center[0] for box in distinct])
        gaps = np.diff(xs)
        regular = gaps[(gaps >= 60) & (gaps <= 125)]
        if not len(regular):
            return []
        spacing = float(np.median(regular))
        indices = np.rint((xs - xs[0]) / spacing).astype(int)
        if len(set(indices)) != len(distinct) or not 6 <= indices[-1] + 1 <= 10:
            return []
        spacing, origin = np.polyfit(indices, xs, 1)
        if np.max(np.abs(xs - (origin + spacing * indices))) > 8:
            return []
        cy = float(np.median([box.center[1] for box in distinct]))
        if any(abs(box.center[1] - cy) > 12 for box in distinct):
            return []
        width = round(float(np.median([box.width for box in distinct])))
        height = round(float(np.median([box.height for box in distinct])))
        observed = dict(zip(indices, distinct))
        # Upgrade glows can open an otherwise full slot border. Recover such
        # endpoints only when an observed contour fits the established row.
        for box in weak:
            index = round((box.center[0] - origin) / spacing)
            if (abs(box.center[0] - (origin + spacing * index)) <= 8
                    and abs(box.center[1] - cy) <= 12
                    and abs(box.width - width) <= 20 and abs(box.height - height) <= 20):
                observed.setdefault(index, box)
        first, last = min(observed), max(observed)
        if not 6 <= last - first + 1 <= 10:
            return []
        # Fill internal gaps only between endpoints supported by image edges.
        return [observed.get(index) or Box(round(origin + spacing * index) - width // 2,
                                          round(cy) - height // 2, width, height, 'CW_BACK_SLOT')
                for index in range(first, last + 1)]

    def press_key(self, key, presses=1, interval=0, **kwargs):
        for _ in range(presses):
            if key.lower() == 'esc':
                self.device.adb_shell(['input', 'keyevent', '4'])
            elif key.lower() in ('f', 'd'):
                self.snapshot()
                if not self.click_text(('购买经验', '升级') if key.lower() == 'f' else ('刷新',), region=(0, 0.65, 1, 1)):
                    raise RuntimeError(f'未识别到商店操作按钮 {key}')
            elif key.lower() == 'v':
                from tasks.combat.assets.assets_combat_state import COMBAT_AUTO
                self.device.click(COMBAT_AUTO)
            else:
                raise ValueError(f'Unsupported Android action: {key}')
            self.sleep(interval)

    def move_to(self, *args, **kwargs):
        pass  # Android has no hovering mouse cursor.

    def copy(self, text):
        self._clipboard = text

    def paste(self):
        import shlex
        self.device.adb_shell('input text ' + shlex.quote(self._clipboard))

    def mouse_down(self, x, y, **kwargs):
        self.device.long_click(ClickButton((x - 2, y - 2, x + 2, y + 2), name='CW_OPEN'), duration=1.1)

    def mouse_up(self, *args, **kwargs):
        pass

    def do_while(self, action, condition, interval=1, max_iterations=10, **kwargs):
        for _ in range(max_iterations):
            action()
            self.sleep(interval)
            if condition():
                return True
        return False

    def save(self, name):
        if self.evidence_dir is None:
            return
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot(ocr=True)
        from module.base.utils import save_image
        save_image(self.image, self.evidence_dir / f'{name}.png')
        import json
        (self.evidence_dir / f'{name}.json').write_text(json.dumps([{'text': b.source, 'box': b.button, 'score': b.score} for b in self.boxes], ensure_ascii=False, indent=2), encoding='utf-8')
