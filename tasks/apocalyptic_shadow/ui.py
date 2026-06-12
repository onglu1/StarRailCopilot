import re

from module.base.button import ClickButton
from module.base.timer import Timer
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.base.assets.assets_base_page import APOCALYPTIC_SHADOW_CHECK
from tasks.base.page import page_guide
from tasks.base.ui import UI
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_NAV
from tasks.dungeon.ui.nav import DUNGEON_NAV_LIST
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import TELEPORT
from tasks.apocalyptic_shadow.assets.assets_apocalyptic_shadow_ui import AS_OVERVIEW_GO
from tasks.pure_fiction.assets.assets_pure_fiction_map import BLANK_CLOSE
from tasks.pure_fiction.assets.assets_pure_fiction_nav import TAB_TREASURES_LIGHTWARD_CHECK
from tasks.pure_fiction.ui import TAB_TREASURES_LIGHTWARD_CLICK

STATUS_LOCKED = '未解锁'
STATUS_OPEN = '尚未挑战'
# Cleared display after this season's first clear is unknown yet,
# treat score/star-ish texts as cleared
STATUS_CLEARED_WORDS = ['积分', '快速通关', '星']

FULLWIDTH_DIGITS = str.maketrans('０１２３４５６７８９', '0123456789')


class ApocalypticShadowStageNode:
    def __init__(self, index, button):
        self.index: int = index
        self.button = button
        self.status: str = 'unknown'

    @property
    def challengeable(self):
        return self.status in ['open', 'unknown']

    def __repr__(self):
        return f'Stage_{self.index:02d}({self.status})'


class ApocalypticShadowUI(UI):
    def as_in_stage_screen(self) -> bool:
        return self.appear(APOCALYPTIC_SHADOW_CHECK)

    def as_goto(self):
        """
        Goto the apocalyptic shadow stage screen.

        Pages:
            in: Any
            out: page_apocalyptic_shadow, stage strip at the bottom
        """
        logger.hr('Apocalyptic shadow goto', level=2)
        self.device.screenshot()
        if self.as_in_stage_screen():
            logger.info('Already in apocalyptic shadow')
            return
        self.ui_ensure(page_guide)
        self.as_guide_tab_goto()
        DUNGEON_NAV_LIST.select_row(KEYWORDS_DUNGEON_NAV.Apocalyptic_Shadow, main=self)
        self.as_teleport()

    def as_guide_tab_goto(self, skip_first_screenshot=True):
        timeout = Timer(10, count=10).start()
        click_interval = Timer(2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('as_guide_tab_goto timeout, continue anyway')
                break
            if self.match_template_color(TAB_TREASURES_LIGHTWARD_CHECK):
                logger.info('Treasures_Lightward tab selected')
                break
            if click_interval.reached():
                self.device.click(TAB_TREASURES_LIGHTWARD_CLICK)
                click_interval.reset()
                continue

        for _ in self.loop(timeout=4):
            DUNGEON_NAV_LIST.load_rows(main=self)
            if DUNGEON_NAV_LIST.cur_buttons:
                logger.info('Treasures_Lightward nav list loaded')
                break
        else:
            logger.warning('Wait Treasures_Lightward nav list timeout')

    def as_teleport(self, skip_first_screenshot=True):
        """
        Teleport into apocalyptic shadow. Passes through the season overview
        screen and possible one-time popups (mode update announcement).
        """
        logger.info('Apocalyptic shadow teleport')
        timeout = Timer(60, count=60).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.as_in_stage_screen():
                logger.info('Apocalyptic shadow stage screen entered')
                break
            if timeout.reached():
                logger.warning('as_teleport timeout')
                break
            if self.match_template_luma(BLANK_CLOSE, interval=2):
                logger.info(f'{BLANK_CLOSE} -> click blank')
                self.device.click(BLANK_CLOSE)
                continue
            if self.handle_tutorial():
                continue
            if self.appear_then_click(AS_OVERVIEW_GO, interval=2):
                continue
            if self.appear_then_click(TELEPORT, interval=3):
                continue
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue
            if self.handle_reward():
                continue

    def as_scan_stages(self, skip_first_screenshot=True) -> list[ApocalypticShadowStageNode]:
        """
        Scan the stage strip at the screen bottom via OCR. Tokens come in
        merged form like `01尚未挑战` or separated `03` + `尚未挑战`.
        The currently selected stage tab renders enlarged and its texts are
        often missed by OCR, scan before selecting anything.

        Pages:
            in: page_apocalyptic_shadow
        """
        digits = {}
        statuses = {}
        nodes = []
        for attempt in range(4):
            if skip_first_screenshot and attempt == 0:
                pass
            else:
                self.device.screenshot()

            region = [(140, 610, 1110, 678), (150, 605, 1100, 680)][attempt % 2]
            ocr = Ocr(ClickButton(region, name='OCR_AS_STAGE'), lang='cn')
            results = ocr.detect_and_ocr(self.device.image)

            for row in results:
                text = row.ocr_text.strip().translate(FULLWIDTH_DIGITS)
                box = tuple(row.box)
                m = re.match(r'^[0oO](\d)(.*)$', text.replace('o', '0').replace('O', '0'))
                if m:
                    # OCR may split like `01 7525`, strip separators
                    index, rest = int(m.group(1)), m.group(2).strip(' 丨|')
                    if 1 <= index <= 9:
                        self._merge(digits, box, (index, rest))
                        continue
                for word, status in [(STATUS_OPEN, 'open'), (STATUS_LOCKED, 'locked')]:
                    if word in text:
                        self._merge(statuses, box, status)
                        break
                else:
                    # A cleared stage tab shows its score, e.g. `7525`
                    if any(w in text for w in STATUS_CLEARED_WORDS) \
                            or re.fullmatch(r'\d{3,6}', text):
                        self._merge(statuses, box, 'cleared')

            nodes = []
            for box, (index, rest) in digits.values():
                node = ApocalypticShadowStageNode(index, ClickButton(box, name=f'STAGE_{index:02d}'))
                if STATUS_OPEN in rest:
                    node.status = 'open'
                elif STATUS_LOCKED in rest:
                    node.status = 'locked'
                elif any(w in rest for w in STATUS_CLEARED_WORDS) or re.fullmatch(r'\d{3,6}', rest):
                    node.status = 'cleared'
                else:
                    # Find a status token to the right of the number
                    best_dx = 140
                    for sbox, status in statuses.values():
                        dx = sbox[0] - box[2]
                        if -10 <= dx < best_dx and abs(sbox[1] - box[1]) < 25:
                            best_dx = dx
                            node.status = status
                # The same tab can be detected twice from merged and split
                # tokens, keep the one with a definite status
                existing = [n for n in nodes if n.index == node.index]
                if existing:
                    if existing[0].status == 'unknown' and node.status != 'unknown':
                        nodes.remove(existing[0])
                    else:
                        continue
                nodes.append(node)
            nodes = sorted(nodes, key=lambda n: n.index)

            if attempt >= 1 and len(nodes) >= 3 \
                    and all(n.status != 'unknown' for n in nodes):
                break

        logger.info(f'Apocalyptic shadow stages: {nodes}')
        return nodes

    @staticmethod
    def _merge(collection: dict, box, value):
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        for (cx, cy) in collection:
            if abs(cx - x) < 25 and abs(cy - y) < 25:
                return
        collection[(x, y)] = (box, value)

    def as_get_target_stage(self, nodes: list[ApocalypticShadowStageNode], mode='lowest_first', skipped=None):
        """
        Args:
            nodes:
            mode: 'lowest_first' or 'highest_only'
            skipped: set of stage indexes that failed to enter, e.g.
                star-origin stages that need 3 teams (unsupported yet)

        Returns:
            ApocalypticShadowStageNode: or None if nothing to do
        """
        skipped = skipped or set()
        candidates = [n for n in nodes if n.challengeable and n.index not in skipped]
        if mode == 'highest_only':
            unlocked = [n for n in nodes if n.status != 'locked' and n.index not in skipped]
            if not unlocked:
                logger.warning('No unlocked stage found')
                return None
            target = max(unlocked, key=lambda n: n.index)
            if target.status == 'cleared':
                logger.info(f'Highest unlocked stage {target} already cleared')
                return None
            return target
        if not candidates:
            logger.info('No open stage to challenge')
            return None
        return min(candidates, key=lambda n: n.index)
