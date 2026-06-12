import re

from module.base.button import ClickButton
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.abyss.assets.assets_abyss_prep import PREP_CHECK
from tasks.abyss.combat import AbyssCombatLoop
from tasks.abyss.stage import AbyssStageNode, abyss_count_stars
from tasks.base.assets.assets_base_page import FORGOTTEN_HALL_CHECK
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_NAV


class MemoryOfChaosStageNode(AbyssStageNode):
    """
    MoC crystals show no status words, stars are the only state display.
    Locked stages are not visually distinguished, they are handled
    behaviorally: entering fails -> skip the stage.
    """
    pass


class MemoryOfChaosUI(AbyssCombatLoop):
    NAV_KEYWORD = KEYWORDS_DUNGEON_NAV.Forgotten_Hall

    def abyss_home_check(self) -> bool:
        # FORGOTTEN_HALL_CHECK also matches the prep screen (same top-left
        # emblem), exclude prep by its team label
        return self.appear(FORGOTTEN_HALL_CHECK) and not self.appear(PREP_CHECK)

    def _moc_stage_stars(self, box) -> int:
        """
        Count gold stars right below a stage number box.
        One MoC star is a ~155 px cluster, crystal glow measures 0.
        """
        x_center = int((box[0] + box[2]) / 2)
        area = (max(0, x_center - 65), box[3], min(1280, x_center + 65), min(720, box[3] + 50))
        return abyss_count_stars(self.device.image, area)

    def abyss_scan_stages(self, skip_first_screenshot=True) -> list[MemoryOfChaosStageNode]:
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
