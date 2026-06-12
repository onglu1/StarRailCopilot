import re

from module.base.button import ClickButton
from module.base.timer import Timer
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.base.page import page_guide, page_pure_fiction
from tasks.base.ui import UI
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_NAV
from tasks.dungeon.ui.nav import DUNGEON_NAV_LIST
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import TELEPORT
from tasks.pure_fiction.assets.assets_pure_fiction_nav import TAB_TREASURES_LIGHTWARD_CHECK

# Guide tabs are icon-only, position may shift between game versions.
# Blind click as fallback when the selected-state template doesn't match.
TAB_TREASURES_LIGHTWARD_CLICK = ClickButton((424, 88, 494, 136), name='TAB_TREASURES_LIGHTWARD_CLICK')

# Stage node status texts below stage numbers
STATUS_LOCKED = '未解锁'
STATUS_OPEN = '尚未挑战'
STATUS_QUICK_CLEAR = '快速通关'
STATUS_SCORE = '积分'


class PureFictionStageNode:
    def __init__(self, index, button):
        self.index: int = index
        # OcrResultButton of the stage number, clickable
        self.button = button
        # one of: locked, open, cleared, unknown
        self.status: str = 'unknown'

    @property
    def challengeable(self):
        return self.status in ['open', 'unknown']

    def __repr__(self):
        return f'Stage_{self.index:02d}({self.status})'


class PureFictionUI(UI):
    def pf_goto(self, skip_first_screenshot=True):
        """
        Goto the pure fiction stage map screen.

        Pages:
            in: Any
            out: page_pure_fiction
        """
        logger.hr('Pure fiction goto', level=2)
        self.device.screenshot()
        if self.pf_in_stage_map():
            logger.info('Already in pure fiction')
            return
        self.ui_ensure(page_guide)
        self.pf_guide_tab_goto()
        DUNGEON_NAV_LIST.select_row(KEYWORDS_DUNGEON_NAV.Pure_Fiction, main=self)
        self.pf_teleport()

    def pf_in_stage_map(self) -> bool:
        return self.appear(page_pure_fiction.check_button)

    def pf_guide_tab_goto(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_guide
            out: page_guide, Treasures_Lightward tab, nav list loaded
        """
        timeout = Timer(10, count=10).start()
        click_interval = Timer(2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('pf_guide_tab_goto timeout, continue anyway')
                break
            if self.match_template_color(TAB_TREASURES_LIGHTWARD_CHECK):
                logger.info('Treasures_Lightward tab selected')
                break
            if click_interval.reached():
                self.device.click(TAB_TREASURES_LIGHTWARD_CLICK)
                click_interval.reset()
                continue

        # Wait until nav list shows Pure_Fiction related rows
        for _ in self.loop(timeout=4):
            DUNGEON_NAV_LIST.load_rows(main=self)
            if DUNGEON_NAV_LIST.cur_buttons:
                logger.info('Treasures_Lightward nav list loaded')
                break
        else:
            logger.warning('Wait Treasures_Lightward nav list timeout')

    def pf_teleport(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_guide, Treasures_Lightward tab, Pure_Fiction nav selected
            out: page_pure_fiction
                May pass through the one-time season intro animation,
                which auto advances into the stage map.
        """
        logger.info('Pure fiction teleport')
        timeout = Timer(60, count=60).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.pf_in_stage_map():
                logger.info('Pure fiction stage map entered')
                break
            if timeout.reached():
                logger.warning('pf_teleport timeout')
                break
            if self.appear_then_click(TELEPORT, interval=3):
                continue
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue
            if self.handle_reward():
                continue

    # OCR detection on the big stylized stage numbers is flaky and can randomly
    # miss one node per pass, so scan multiple passes with two slightly
    # different crop regions and merge results
    OCR_STAGE_REGIONS = [(430, 140, 1280, 620), (440, 60, 1280, 625)]

    @staticmethod
    def _pf_merge_box(collection: dict, box, value):
        """Dedup OCR results from multiple passes by box center distance."""
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        for (cx, cy) in collection:
            if abs(cx - x) < 25 and abs(cy - y) < 25:
                return
        collection[(x, y)] = (box, value)

    def pf_scan_stages(self, skip_first_screenshot=True) -> list[PureFictionStageNode]:
        """
        Scan stage nodes on the stage map via OCR.
        Stage numbers (01-12) with a status line below:
            未解锁 / 尚未挑战 / 快速通关 / 积分NNNNN

        Pages:
            in: page_pure_fiction
        """
        digits = {}
        statuses = {}
        nodes = []
        for attempt in range(4):
            if skip_first_screenshot and attempt == 0:
                pass
            else:
                self.device.screenshot()

            region = self.OCR_STAGE_REGIONS[attempt % 2]
            ocr = Ocr(ClickButton(region, name='OCR_PF_STAGE'), lang='cn')
            results = ocr.detect_and_ocr(self.device.image)

            for row in results:
                text = row.ocr_text.strip()
                box = tuple(row.box)
                if re.fullmatch(r'[0o]?\d', text.lower().replace('o', '0')) or re.fullmatch(r'\d{2}', text):
                    self._pf_merge_box(digits, box, text)
                elif STATUS_LOCKED in text:
                    self._pf_merge_box(statuses, box, 'locked')
                elif STATUS_OPEN in text:
                    self._pf_merge_box(statuses, box, 'open')
                elif STATUS_QUICK_CLEAR in text or STATUS_SCORE in text:
                    self._pf_merge_box(statuses, box, 'cleared')

            nodes = []
            for box, text in digits.values():
                try:
                    index = int(re.sub(r'\D', '', text))
                except ValueError:
                    continue
                if not 1 <= index <= 12:
                    continue
                button = ClickButton(box, name=f'STAGE_{index:02d}')
                node = PureFictionStageNode(index, button)
                # Find the nearest status text below the number in the same column
                x_center = (box[0] + box[2]) / 2
                best_dy = 120
                for sbox, status in statuses.values():
                    sx = (sbox[0] + sbox[2]) / 2
                    dy = sbox[1] - box[3]
                    if abs(sx - x_center) < 80 and -10 <= dy < best_dy:
                        best_dy = dy
                        node.status = status
                nodes.append(node)
            nodes = sorted(nodes, key=lambda n: n.index)

            # Every node paired with a status and every status paired with a node.
            # A season has 4 stages, don't trust a smaller self-consistent subset,
            # OCR may have missed nodes in both passes
            if attempt >= 1 and len(nodes) >= 4 and len(nodes) == len(statuses) \
                    and all(n.status != 'unknown' for n in nodes):
                break

        logger.info(f'Pure fiction stages: {nodes}')
        return nodes

    def pf_get_target_stage(self, nodes: list[PureFictionStageNode], mode: str = 'lowest_first'):
        """
        Args:
            nodes:
            mode: 'lowest_first' to climb stages from the lowest open one,
                fits all account strengths.
                'highest_only' to challenge the highest unlocked stage only,
                for strong accounts since 3-starring a high stage grants
                all lower stage rewards.

        Returns:
            PureFictionStageNode: or None if nothing to do
        """
        candidates = [node for node in nodes if node.challengeable]
        if mode == 'highest_only':
            unlocked = [node for node in nodes if node.status != 'locked']
            if not unlocked:
                logger.warning('No unlocked stage found')
                return None
            target = max(unlocked, key=lambda n: n.index)
            if target.status == 'cleared':
                logger.info(f'Highest unlocked stage {target} already cleared')
                return None
            return target
        # lowest_first
        if not candidates:
            logger.info('No open stage to challenge')
            return None
        return min(candidates, key=lambda n: n.index)

    def pf_exit_to_main(self):
        """
        Pages:
            in: page_pure_fiction
            out: page_main
        """
        self.ui_goto_main()
