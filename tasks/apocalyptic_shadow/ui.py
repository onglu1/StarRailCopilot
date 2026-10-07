import re

from module.base.button import ClickButton
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.abyss.combat import AbyssCombatLoop
from tasks.abyss.stage import AbyssStageNode, abyss_count_stars
from tasks.apocalyptic_shadow.assets.assets_apocalyptic_shadow_ui import AS_OVERVIEW_GO
from tasks.base.assets.assets_base_page import APOCALYPTIC_SHADOW_CHECK
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_NAV

STATUS_LOCKED = '未解锁'
STATUS_OPEN = '尚未挑战'
# A cleared stage tab shows its score
STATUS_CLEARED_WORDS = ['积分', '快速通关']

FULLWIDTH_DIGITS = str.maketrans('０１２３４５６７８９', '0123456789')


class ApocalypticShadowStageNode(AbyssStageNode):
    pass


class ApocalypticShadowUI(AbyssCombatLoop):
    NAV_KEYWORD = KEYWORDS_DUNGEON_NAV.Apocalyptic_Shadow

    def abyss_home_check(self) -> bool:
        return self.appear(APOCALYPTIC_SHADOW_CHECK)

    def abyss_teleport_handler(self) -> bool:
        # Teleport lands on a season overview screen first
        if self.appear_then_click(AS_OVERVIEW_GO, interval=2):
            return True
        return False

    def abyss_scan_stages(self, skip_first_screenshot=True) -> list[ApocalypticShadowStageNode]:
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
        # Star glint animation can hide a cluster in a single frame
        star_history = {}
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
            for key, (box, (index, rest)) in digits.items():
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
                # Gold stars sit right of the stage token at +38..+109 px,
                # keep the band tight, gold tab ornaments sit further right
                star_area = (
                    min(box[2] + 25, 1279), max(box[1] - 6, 0),
                    min(box[2] + 112, 1280), min(box[3] + 6, 720),
                )
                count = abyss_count_stars(self.device.image, star_area)
                node.stars = star_history[key] = max(star_history.get(key, 0), count)
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
