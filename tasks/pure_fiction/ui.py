import re

from module.base.button import ClickButton
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.abyss.combat import AbyssCombatLoop
from tasks.abyss.stage import AbyssStageNode, abyss_count_stars
from tasks.base.page import page_pure_fiction
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_NAV

# Stage node status texts below stage numbers
STATUS_LOCKED = '未解锁'
STATUS_OPEN = '尚未挑战'
STATUS_QUICK_CLEAR = '快速通关'
STATUS_SCORE = '积分'


class PureFictionStageNode(AbyssStageNode):
    pass


class PureFictionUI(AbyssCombatLoop):
    NAV_KEYWORD = KEYWORDS_DUNGEON_NAV.Pure_Fiction

    def abyss_home_check(self) -> bool:
        return self.appear(page_pure_fiction.check_button)

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

    def abyss_scan_stages(self, skip_first_screenshot=True) -> list[PureFictionStageNode]:
        """
        Scan stage nodes on the stage map via OCR.
        Stage numbers (01-12) with a status line below:
            未解锁 / 尚未挑战 / 快速通关 / 积分NNNNN
        and a gold star row right below the number.

        Pages:
            in: page_pure_fiction
        """
        digits = {}
        statuses = {}
        # Star glint animation can hide a cluster in a single frame,
        # keep the max count seen across passes per node
        star_history = {}
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
            for key, (box, text) in digits.items():
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
                # Gold star row sits right below the stage number
                star_area = (
                    int(x_center) - 60, box[3] + 2,
                    int(x_center) + 60, min(box[3] + 40, 720),
                )
                count = abyss_count_stars(self.device.image, star_area)
                node.stars = star_history[key] = max(star_history.get(key, 0), count)
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
