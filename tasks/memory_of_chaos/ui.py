import re

from module.base.button import ClickButton
from module.base.timer import Timer
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK
from tasks.base.page import page_guide
from tasks.base.ui import UI
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_NAV
from tasks.dungeon.ui.nav import DUNGEON_NAV_LIST
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import TELEPORT
from tasks.pure_fiction.abyss import AbyssStageNode, abyss_count_stars
from tasks.pure_fiction.ui import TAB_TREASURES_LIGHTWARD_CLICK
from tasks.pure_fiction.assets.assets_pure_fiction_nav import TAB_TREASURES_LIGHTWARD_CHECK


class MemoryOfChaosStageNode(AbyssStageNode):
    """
    MoC crystals show no status words, stars are the only state display.
    Locked stages are not visually distinguished, they are handled
    behaviorally: entering fails -> skip the stage.
    """
    pass


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
        self.abyss_exit_prep_if_stuck()
        self.abyss_ui_ensure_guide()
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

    def _moc_stage_stars(self, box) -> int:
        """
        Count gold stars right below a stage number box.
        One MoC star is a ~155 px cluster, crystal glow measures 0.
        """
        x_center = int((box[0] + box[2]) / 2)
        area = (max(0, x_center - 65), box[3], min(1280, x_center + 65), min(720, box[3] + 50))
        return abyss_count_stars(self.device.image, area)

    def moc_scan_stages(self, skip_first_screenshot=True) -> list[MemoryOfChaosStageNode]:
        """
        Scan visible stage crystals via OCR, multi-pass union since detection
        on the big stylized numbers is flaky.

        Pages:
            in: page_forgotten_hall
        """
        digits = {}
        # Star glint animation can hide a cluster in a single frame
        star_history = {}
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
            for key, (box, text) in digits.items():
                try:
                    index = int(re.sub(r'\D', '', text))
                except ValueError:
                    continue
                if not 1 <= index <= 12:
                    continue
                node = MemoryOfChaosStageNode(index, ClickButton(box, name=f'STAGE_{index:02d}'))
                count = self._moc_stage_stars(box)
                node.stars = star_history[key] = max(star_history.get(key, 0), count)
                node.status = 'cleared' if node.stars > 0 else 'open'
                nodes.append(node)
            nodes = sorted(nodes, key=lambda n: n.index)

            if attempt >= 1 and len(nodes) >= 3:
                break

        logger.info(f'Memory of chaos stages: {nodes}')
        return nodes

