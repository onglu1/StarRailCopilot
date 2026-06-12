import re

from module.base.button import ClickButton
from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK
from tasks.base.page import page_guide
from tasks.base.ui import UI
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_NAV
from tasks.dungeon.ui.nav import DUNGEON_NAV_LIST
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import TELEPORT
from tasks.pure_fiction.ui import TAB_TREASURES_LIGHTWARD_CLICK
from tasks.pure_fiction.assets.assets_pure_fiction_nav import TAB_TREASURES_LIGHTWARD_CHECK

# Gold star color under cleared stage crystals
STAR_COLOR_BRIGHT = 150
STAR_PIXEL_COUNT = 80


class MemoryOfChaosStageNode:
    def __init__(self, index, button):
        self.index: int = index
        self.button = button
        # 'cleared' when gold stars are present under the number, else 'open'.
        # Locked stages are not visually distinguished here, they are handled
        # behaviorally: entering fails -> skip the stage
        self.status: str = 'open'

    @property
    def challengeable(self):
        return self.status == 'open'

    def __repr__(self):
        return f'Stage_{self.index:02d}({self.status})'


class MemoryOfChaosUI(UI):
    def moc_in_stage_screen(self) -> bool:
        # FORGOTTEN_HALL_CHECK also matches the prep screen (same top-left
        # emblem), exclude prep by its 编队 label
        from tasks.pure_fiction.assets.assets_pure_fiction_prep import PREP_CHECK
        return self.appear(FORGOTTEN_HALL_CHECK) and not self.appear(PREP_CHECK)

    def moc_goto(self):
        """
        Goto the memory of chaos stage screen.

        Pages:
            in: Any
            out: page_forgotten_hall, memory of chaos crystal list
        """
        logger.hr('Memory of chaos goto', level=2)
        self.device.screenshot()
        if self.moc_in_stage_screen():
            logger.info('Already in memory of chaos')
            return
        self.ui_ensure(page_guide)
        self.moc_guide_tab_goto()
        DUNGEON_NAV_LIST.select_row(KEYWORDS_DUNGEON_NAV.Forgotten_Hall, main=self)
        self.moc_teleport()

    def moc_guide_tab_goto(self, skip_first_screenshot=True):
        timeout = Timer(10, count=10).start()
        click_interval = Timer(2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('moc_guide_tab_goto timeout, continue anyway')
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

    def moc_teleport(self, skip_first_screenshot=True):
        logger.info('Memory of chaos teleport')
        timeout = Timer(60, count=60).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.moc_in_stage_screen():
                logger.info('Memory of chaos stage screen entered')
                break
            if timeout.reached():
                logger.warning('moc_teleport timeout')
                break
            if self.appear_then_click(TELEPORT, interval=3):
                continue
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue
            if self.handle_reward():
                continue

    def _moc_stage_has_stars(self, box) -> bool:
        """
        Whether gold stars are present right below a stage number box.
        """
        x_center = int((box[0] + box[2]) / 2)
        area = (max(0, x_center - 65), box[3], min(1280, x_center + 65), min(720, box[3] + 50))
        image = crop(self.device.image, area, copy=False)
        px = image.reshape(-1, 3).astype(int)
        # Gold stars measure ~(241, 189, 110), a single star is ~150 px,
        # crystal glow and background measure 0 with this tolerance
        mask = (abs(px[:, 0] - 241) < 30) & (abs(px[:, 1] - 189) < 30) & (abs(px[:, 2] - 110) < 40)
        return int(mask.sum()) > STAR_PIXEL_COUNT

    def moc_scan_stages(self, skip_first_screenshot=True) -> list[MemoryOfChaosStageNode]:
        """
        Scan visible stage crystals via OCR, multi-pass union since detection
        on the big stylized numbers is flaky.

        Pages:
            in: page_forgotten_hall
        """
        digits = {}
        nodes = []
        for attempt in range(4):
            if skip_first_screenshot and attempt == 0:
                pass
            else:
                self.device.screenshot()

            region = [(140, 240, 1280, 570), (150, 230, 1270, 580)][attempt % 2]
            ocr = Ocr(ClickButton(region, name='OCR_MOC_STAGE'), lang='cn')
            results = ocr.detect_and_ocr(self.device.image)
            for row in results:
                text = row.ocr_text.strip()
                if re.fullmatch(r'[0oO]?\d{1,2}', text.replace('o', '0').replace('O', '0')):
                    box = tuple(row.box)
                    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                    if not any(abs(cx - x) < 30 and abs(cy - y) < 30 for cx, cy in digits):
                        digits[(x, y)] = (box, text)

            nodes = []
            for box, text in digits.values():
                try:
                    index = int(re.sub(r'\D', '', text))
                except ValueError:
                    continue
                if not 1 <= index <= 12:
                    continue
                node = MemoryOfChaosStageNode(index, ClickButton(box, name=f'STAGE_{index:02d}'))
                if self._moc_stage_has_stars(box):
                    node.status = 'cleared'
                nodes.append(node)
            nodes = sorted(nodes, key=lambda n: n.index)

            if attempt >= 1 and len(nodes) >= 3:
                break

        logger.info(f'Memory of chaos stages: {nodes}')
        return nodes

    def moc_get_target_stage(self, nodes: list[MemoryOfChaosStageNode], mode='lowest_first', skipped=None):
        """
        Args:
            nodes:
            mode: 'lowest_first' or 'highest_only'
            skipped: set of stage indexes that failed to enter (locked)

        Returns:
            MemoryOfChaosStageNode: or None
        """
        skipped = skipped or set()
        candidates = [n for n in nodes if n.challengeable and n.index not in skipped]
        if not candidates:
            logger.info('No open memory of chaos stage to challenge')
            return None
        if mode == 'highest_only':
            top = max(nodes, key=lambda n: n.index)
            if top.status == 'cleared' or top.index in skipped:
                logger.info(f'Highest visible stage {top} already cleared or skipped')
                return None
            return top
        return min(candidates, key=lambda n: n.index)
