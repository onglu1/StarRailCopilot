"""Read a native game strategy page instead of requiring a hand-written roster."""
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import random

import cv2
import numpy as np

from module.logger import logger
from tasks.currency_wars.characters import Character, Characters, Positioning
from tasks.currency_wars.operator import Box, normalize
from tasks.currency_wars.synergy import extract_traits, parse_synergy_targets
from tasks.currency_wars.strategy_config import extract_code


class NativeStrategy:
    def __init__(self, operator, game=None):
        self.op = operator
        self.game = game

    def open_catalog(self):
        op = self.op
        for _ in range(12):
            op.snapshot()
            if op.dismiss_currency_tutorial():
                continue
            if op.text('积分线已更新', (0.3, 0.35, 0.7, 0.62)):
                op.sleep(2)
                continue
            if op.text('积分奖励', (0, 0.2, 0.3, 0.35)):
                op.press_key('esc')
                op.sleep(0.5)
                continue
            if op.click_text(('点击空白处关闭', '点击空白处继续'), (0.1, 0.5, 0.9, 0.98), after_sleep=0.4):
                continue
            if op.text('赛季扩充说明', (0.1, 0.1, 0.9, 0.28)):
                op.press_key('esc')
                op.sleep(0.4)
                continue
            if op.text('攻略详情', (0, 0, 0.3, 0.12)):
                op.press_key('esc')
                op.sleep(0.4)
                continue
            if op.text('热门攻略', (0.25, 0.07, 0.65, 0.18)):
                return
            if op.click_text('收起', (0.87, 0.85, 1, 0.96), after_sleep=1.6, exact=True):
                # The shop can finish opening after the board transition.
                # Its overlay blocks the guide icon at the top right.
                continue
            if op.text(('补给阶段', '遭遇节点', '选择投资策略', '选择投资环境', '武装箱', '聘用书', '星徽秘典', '命运卜者', '盛会之星', '选择伙伴', '祈愿试炼', '我来当策划'), (0.1, 0, 0.95, 0.2)):
                if self.game is None or not self.game.handle_pending_selection():
                    raise RuntimeError('先完成当前节点选择，再打开攻略列表')
                continue
            if op.click_text('攻略大全', (0, 0.35, 0.3, 0.58), after_sleep=4):
                continue
            if op.click_text('货币战争', (0.5, 0.3, 0.9, 0.75), after_sleep=1, exact=True):
                continue
            if op.text(('备战阶段', '准备阶段'), (0, 0, 0.4, 0.13)):
                op.click_point(1020 / 1280, 36 / 720, after_sleep=3.5)
                continue
            op.sleep(0.4)
        raise RuntimeError('未能打开原生攻略列表')

    def choose_recommended(self, campaign):
        self.open_catalog()
        op = self.op
        # Spread selections across the native list, rather than the three
        # imported JSON presets. Prefer an unseen title for this campaign.
        skip_pages = random.randrange(0, 5)
        pages = set()
        for attempt in range(12):
            op.snapshot()
            if not op.text('热门攻略', (0.25, 0.07, 0.65, 0.18)):
                # A scroll can open a guide while the catalog is still moving.
                # Recover the catalog before using its coordinates again.
                self.open_catalog()
                op.snapshot()
            titles = [b for b in op.read_region((0.025, 0.24, 0.80, 0.85), snapshot=False) if '】' in b.source and '【' in b.source]
            if not titles:
                op.sleep(0.5)
                continue
            campaign.reload()
            seen = [normalize(title) for title in campaign.data['seen_strategies']]
            unused = [b for b in titles if not any(title.startswith(normalize(b.source)) or normalize(b.source).startswith(title) for title in seen)]
            page = tuple(normalize(b.source) for b in titles)
            choices = [] if attempt < skip_pages else unused or (titles if page in pages or attempt == 11 else [])
            pages.add(page)
            if choices:
                title = campaign.choose([b.source for b in choices], remember=False)
                op.click_box(next(b for b in choices if b.source == title), after_sleep=1)
                self.wait_detail()
                return self.read_detail()
            op.device.swipe((1180, 540), (1180, 235), duration=(0.2, 0.3), name='CW_GUIDE_NEXT')
            op.sleep(0.3)
        op.save('native_catalog_no_choices')
        raise RuntimeError('原生攻略列表未能识别可选条目')

    def open_code(self, code, read=True):
        code = extract_code(code)
        if not code:
            raise ValueError('无效的原生攻略码格式')
        self.open_catalog()
        op = self.op
        op.snapshot()
        if not op.click_text('输入攻略码', (0.5, 0.8, 0.85, 0.98), after_sleep=0.4):
            raise RuntimeError('输入攻略码按钮未识别')
        for attempt in range(12):
            op.snapshot()
            if op.click_text('请输入攻略码', (0.1, 0.3, 0.9, 0.6), after_sleep=0.3):
                break
            # A menu can still be animating when its text becomes visible.
            # Retry only while the catalog button is actually still present.
            if attempt in (2, 6, 10):
                op.click_text('输入攻略码', (0.5, 0.8, 0.85, 0.98), after_sleep=0.5)
            op.sleep(0.3)
        else:
            op.save('native_code_input_missing')
            raise RuntimeError('原生攻略码输入框未识别')
        op.copy(code)
        op.paste()
        op.sleep(0.2)
        op.snapshot()
        op.click_text('确定', (0.85, 0.85, 1, 1), after_sleep=0.3)
        op.snapshot()
        op.click_text('确认', (0.4, 0.4, 0.95, 0.95), after_sleep=1)
        self.wait_detail()
        return self.read_detail(code) if read else None

    def wait_detail(self, timeout=45):
        op = self.op
        deadline = time.monotonic() + timeout
        # Native guides can remain in a black loading transition. Wait
        # for the detail header and its footer instead of rejecting a valid
        # code after only twenty fast snapshots (about six seconds).
        while time.monotonic() < deadline:
            op.snapshot()
            if (op.text('攻略详情', (0, 0, 0.3, 0.12))
                    and op.text('复制攻略码', (0, 0.85, 0.3, 0.98))):
                return
            op.sleep(0.3)
        op.save('native_detail_timeout')
        raise TimeoutError('原生攻略详情加载超时，尚未确认导入结果')

    def return_to_game(self):
        for _ in range(5):
            self.op.snapshot()
            if self.op.text('开始货币战争', (0.5, 0.75, 1, 1)) or self.op.text(('备战阶段', '准备阶段'), (0, 0, 0.4, 0.14)):
                return
            self.op.press_key('esc')
            self.op.sleep(0.5)

    @staticmethod
    def card_slots(image):
        result = []
        for y, xs in [(320, (570, 680, 790, 900)), (524, (312, 417, 523, 629, 734, 841, 946, 1051, 1157))]:
            for x in xs:
                crop = image[y - 24:y + 24, x - 22:x + 22]
                if crop.std(axis=(0, 1)).mean() > 22:
                    result.append(Box(x - 44, y - 50, 88, 100, 'native_card'))
        return result

    @staticmethod
    def target_stars(image, box):
        return max(1, NativeStrategy.visible_stars(image, box))

    @staticmethod
    def visible_stars(image, box):
        """Count visible portrait stars; zero means no star target is shown."""
        x, y = box.center
        crop = image[y + 22:y + 50, x - 40:x + 40]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, np.array((8, 80, 160)), np.array((42, 255, 255)))
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        stars = 0
        for _, _, w, h, area in stats[1:]:
            # A glow joined to the portrait can extend a star group to 20px.
            if 10 <= h <= 22 and 9 <= w <= 44 and 25 <= area <= 350:
                stars += max(1, round(w / 13))
        return min(3, stars)

    @staticmethod
    def _contour_card_slots(image):
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        contours, _ = cv2.findContours(cv2.Canny(gray, 35, 100), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            cy = y + h / 2
            if 245 <= x <= 1220 and 65 <= w <= 135 and 80 <= h <= 130 and (270 <= cy <= 375 or 485 <= cy <= 565) and cv2.contourArea(contour) > w * h * 0.55:
                crop = image[y + 20:y + h - 15, x + 15:x + w - 15]
                if crop.size and crop.std(axis=(0, 1)).mean() > 22:
                    candidates.append(Box(x, y, w, h, 'native_card'))
        found = []
        for box in sorted(candidates, key=lambda b: b.width * b.height, reverse=True):
            if all(abs(box.center[0] - old.center[0]) > 35 or abs(box.center[1] - old.center[1]) > 40 for old in found):
                found.append(box)
        return sorted(found, key=lambda b: (b.center[1] > 420, b.left))

    @staticmethod
    def popup_bounds(image):
        edges = cv2.Canny(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY), 30, 100)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 40, minLineLength=400, maxLineGap=100)
        vertical = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = map(int, line[0])
                if abs(x1 - x2) <= 2 and abs(y1 - y2) >= 450:
                    vertical.append((round((x1 + x2) / 2), min(y1, y2), max(y1, y2)))
        pairs = []
        for left in sorted(vertical):
            for right in sorted(vertical):
                if 380 <= right[0] - left[0] <= 420:
                    top, bottom = min(left[1], right[1]), min(left[2], right[2])
                    if bottom - top >= 500:
                        pairs.append((left[0], top, right[0] - left[0], bottom - top))
        if pairs:
            return min(pairs, key=lambda b: abs(b[2] - 401))
        hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, np.array((10, 55, 100)), np.array((45, 255, 255)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if 350 <= w <= 450 and 500 <= h <= 670 and cv2.contourArea(contour) > w * h * 0.75:
                candidates.append((x, y, w, h))
        return max(candidates, key=lambda b: b[2] * b[3]) if candidates else None

    def clipboard_code(self):
        device = self.op.device
        device.scrcpy_init()
        from module.device.method.scrcpy import const
        control = device._scrcpy_control
        sock = control.control_socket
        with control.control_socket_lock:
            sock.setblocking(False)
            try:
                while sock.recv(1024):
                    pass
            except BlockingIOError:
                pass
            sock.settimeout(3)
            sock.sendall(struct.pack('>B', const.TYPE_GET_CLIPBOARD))

            def receive(length):
                data = bytearray()
                while len(data) < length:
                    packet = sock.recv(length - len(data))
                    if not packet:
                        raise ConnectionError('Scrcpy clipboard channel closed')
                    data.extend(packet)
                return bytes(data)

            kind, length = struct.unpack('>BI', receive(5))
            if kind != 0 or length > 65536:
                raise ValueError('Invalid clipboard response')
            code = extract_code(receive(length).decode('utf-8'))
            sock.setblocking(True)
        if not code:
            raise ValueError('Game clipboard did not contain a strategy code')
        return code

    def read_character(self, bounds, index):
        from tasks.currency_wars.mobile import MobileCurrencyWars
        op = self.op
        character = None
        name_box = Box(0, 0, 0, 0)
        # The tooltip border appears before its name has finished fading in.
        # Detection can drop the first glyph; retry the whole header line too.
        for _ in range(10):
            x, y, w, h = bounds
            region = ((x + 75) / 1280, (y + 30) / 720, (x + w - 45) / 1280, (y + 75) / 720)
            candidates = op.read_region(region, snapshot=False)
            candidates = [b for b in candidates if re.search(r'[\u4e00-\u9fffA-Za-z]', b.source)]
            for candidate in candidates:
                name_box = candidate
                character = MobileCurrencyWars.character_from_text(candidate.source)
                if character is not None:
                    return character
            line = op.read_line(region, snapshot=False)
            if re.search(r'[\u4e00-\u9fffA-Za-z]', line.source):
                name_box = line
                character = MobileCurrencyWars.character_from_text(line.source)
                if character is not None:
                    return character
            # Keep detection inside the name band; the adjacent positioning
            # row suppressed a glyph in the captured Evanescia tooltip.
            name_region = ((x + 75) / 1280, (y + 35) / 720, (x + w - 45) / 1280, (y + 65) / 720)
            for candidate in op.read_region(name_region, snapshot=False):
                character = MobileCurrencyWars.character_from_text(candidate.source)
                if character is not None:
                    return character
            op.sleep(0.2)
            op.snapshot()
            bounds = self.popup_bounds(op.image) or bounds
        x, y, w, h = bounds
        cost_box = op.read_line(((x + w - 30) / 1280, (y + 13) / 720, (x + w - 6) / 1280, (y + 55) / 720), snapshot=False)
        digits = re.findall(r'\d', cost_box.source)
        name = name_box.source.strip()
        if not name or not digits:
            op.save(f'native_character_unknown_{index}')
            raise RuntimeError('原生攻略角色名称或费用未能识别')
        cost = int(digits[-1])
        traits = ''.join(b.source for b in op.read_region(((x + 8) / 1280, (y + 95) / 720, (x + w - 8) / 1280, (y + 145) / 720), snapshot=False))
        if cost == 4 and any(word in traits for word in ('列车同行', '忆灵', '记忆', '开拓者')):
            Characters.set_username(name)
            op.config.CurrencyWars_Username = name
            return Characters.Trailblazer
        if len(normalize(name)) <= 1:
            op.save(f'native_character_unknown_{index}')
            raise RuntimeError('原生攻略单字角色名称未能确认')
        character = Character(name, cost, Positioning.OnOffField)
        Characters.characters[character.name] = character
        return character

    def read_character_traits(self, bounds):
        x, y, w, h = bounds
        region = ((x + 15) / 1280, (y + 110) / 720, (x + w - 15) / 1280, (y + 160) / 720)
        text = ' '.join(box.source for box in self.op.read_region(region, snapshot=False))
        return list(extract_traits(text))

    def ensure_final_roster_view(self):
        op = self.op
        for _ in range(8):
            op.snapshot()
            front = op.text('前台区域', (0.18, 0.28, 0.45, 0.40))
            back = op.text('后台区域', (0.18, 0.57, 0.45, 0.66))
            if front and back:
                return
            # Guide details remember their scroll position. Read the final
            # formation at the top, never the early/mid-game transition cards.
            if op.text('攻略详情', (0, 0, 0.3, 0.12)):
                op.device.swipe((1180, 230), (1180, 565), duration=(0.2, 0.3), name='CW_GUIDE_FINAL_ROSTER')
            op.sleep(0.4)
        op.save('native_final_roster_missing')
        raise RuntimeError('未确认攻略最终阵容的前后台区域')

    def read_detail(self, supplied_code=None):
        op = self.op
        self.ensure_final_roster_view()
        title_boxes = op.read_region((0.025, 0.1, 0.78, 0.165), snapshot=False)
        title = ' '.join(box.source for box in title_boxes)
        slots = self.card_slots(op.image)
        plan_image = op.image.copy()
        if not slots:
            op.save('native_roster_slots_missing')
            raise RuntimeError('原生攻略阵容未能识别')
        roster = {'on_field': {}, 'off_field': {}}
        guide_stars = {'on_field': {}, 'off_field': {}}
        character_traits = {}
        for index, box in enumerate(slots):
            op.click_point(box.center[0] / 1280, box.center[1] / 720,
                           after_sleep=0.25, tag=f'CW_GUIDE_CHARACTER_{index}')
            bounds = None
            for _ in range(20):
                op.snapshot(ocr=False)
                bounds = self.popup_bounds(op.image)
                if bounds:
                    break
                op.sleep(0.2)
            if not bounds:
                op.save(f'native_character_popup_missing_{index}')
                raise RuntimeError('攻略角色详情未能打开')
            character = self.read_character(bounds, index)
            bounds = self.popup_bounds(op.image) or bounds
            character_traits[character.name] = self.read_character_traits(bounds)
            group = 'on_field' if box.center[1] < 420 else 'off_field'
            # Keep visible guide targets separate from the purchase policy.
            visible = self.visible_stars(plan_image, box)
            stars = max(1, visible)
            roster[group][character.name] = stars
            guide_stars[group][character.name] = visible or None
            logger.info(f'Native strategy {group}: {character.name} -> {stars} stars')
            op.press_key('esc')
            op.sleep(0.2)
        op.snapshot()
        code = supplied_code
        if not code:
            if not op.click_text('复制攻略码', (0, 0.85, 0.3, 0.98), after_sleep=0.3):
                raise RuntimeError('复制攻略码按钮未识别')
            code = self.clipboard_code()
        level_match = re.search(r'(\d+)级', title)
        level = min(10, max(3, int(level_match.group(1)))) if level_match else 7
        costs = {name: Characters.get_character(name).cost for group in roster.values() for name in group}
        data = dict(title=title, share_code=code, min_coins=40, min_level=level, mid_level=9, character_costs=costs,
                    character_traits=character_traits, target_synergies=parse_synergy_targets(title),
                    guide_star_targets=guide_stars, purchase_floor=2,
                    star_target_note='on_field/off_field保留攻略识别值（无星标为1）；guide_star_targets的null表示无可见星标；purchase_floor是无星标角色的最低养成目标，不是攻略显示星级。',
                    **roster)
        from tasks.currency_wars.paths import STATE_DIR
        folder = STATE_DIR / 'native_strategies'
        folder.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256((code + '\n' + op.config.config_name).encode('utf-8')).hexdigest()[:16]
        path = folder / f'{key}.json'
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        op.save(f'native_strategy_{key}')
        return path, data
