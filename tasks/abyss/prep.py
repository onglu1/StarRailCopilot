"""
Stage-prep helpers shared by the abyss modes.

The prep screen of all three modes shares the same structure: a left
character picker (with a preset-team tab at fixed position), two team
rows on the right (one per node/half), an optional per-node effect slot
(buff in Pure Fiction, axiom in Apocalyptic Shadow, none in Memory of
Chaos), and an enter button at the bottom right. Only coordinates and
the enter button differ, subclasses bind them via class attributes.
"""
import random

import cv2

from module.base.button import ClickButton
from module.base.timer import Timer
from module.base.utils import crop, rgb2luma
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.abyss.assets.assets_abyss_prep import (
    EQUIP_EFFECT,
    PREP_CHECK,
    TAB_PRESET_CHECK,
    TAB_PRESET_CLICK
)
from tasks.abyss.nav import AbyssNav

# First effect card on the buff/axiom selection screen, same in PF and AS
EFFECT_CARD_1 = ClickButton((760, 150, 1140, 225), name='EFFECT_CARD_1')
# Preset blocks in the preset team tab, top to bottom.
# Click the portrait strip of the block, the title row is not reliable
PRESET_BLOCK = {
    1: ClickButton((60, 175, 460, 265), name='PRESET_1'),
    2: ClickButton((60, 348, 460, 438), name='PRESET_2'),
    3: ClickButton((60, 520, 460, 610), name='PRESET_3'),
}
# Preset rows repeat at a fixed pitch, three rows fit the panel viewport
PRESET_ROW_PITCH = 172
PRESET_PANEL = (30, 140, 460, 690)


# Strip of the panel used to measure scroll distance. Taken low enough
# that after a one-row drag it still lands inside the panel viewport
PRESET_SHIFT_STRIP = (30, 380, 460, 500)


def abyss_panel_shift(before_strip, after_image) -> int:
    """
    How many pixels the preset panel content moved up between two frames.

    Args:
        before_strip: crop of the panel at PRESET_SHIFT_STRIP before the drag
        after_image: the full frame after the drag

    Returns:
        int: upward shift in pixels, 0 when the strip cannot be located
    """
    panel = crop(after_image, PRESET_PANEL, copy=False)
    res = cv2.matchTemplate(panel, before_strip, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < 0.60:
        return 0
    found_y = PRESET_PANEL[1] + max_loc[1]
    return PRESET_SHIFT_STRIP[1] - found_y


class AbyssPrep(AbyssNav):
    # {node_index: ClickButton}, the first member slot of each team row
    TEAM_SLOT = {}
    # {node_index: (x1, y1, x2, y2)}, strip over the 4 member slots.
    # Bright portraits when filled (luma std 60-90), dark placeholder
    # circles when empty (std ~21), dimmed unfocused filled rows ~44
    TEAM_ROW_SLOTS = {}
    TEAM_FILLED_STD = 33
    # {node_index: ClickButton} or empty dict when the mode has no effect slot
    EFFECT_SLOT = {}
    # ButtonWrapper, the enter button at the bottom right of the prep screen
    ENTER_BUTTON = None

    # Which node row our clicks last focused, None when unknown. Clicking a
    # team slot of an unfocused row only focuses the row, but clicking the
    # slot of an already-focused row acts on the member itself
    _abyss_focused_node = None
    # {node_index: '1' / '2' / '3' / 'random'}, which effect card to equip
    _abyss_effect_select = None

    def _abyss_preset_scroll_top(self):
        for _ in range(2):
            self.device.swipe((240, 240), (240, 620), name='PRESET_SCROLL_TOP')
            self.device.sleep((0.4, 0.6))

    def _abyss_click_preset(self, preset: int) -> bool:
        """
        Click a preset block in the preset tab. The top 3 rows are visible
        after scrolling to the top, lower presets are reached by dragging
        row by row, measuring the actual scroll distance from the frames
        (the list scrolls freely, nominal drag distances drift).

        Pages:
            in: PREP_CHECK with the preset tab open
        """
        if not 1 <= preset <= 12:
            logger.warning(f'Invalid preset {preset}, fallback to 1')
            preset = 1
        self._abyss_preset_scroll_top()
        if preset in PRESET_BLOCK:
            self.device.click(PRESET_BLOCK[preset])
            return True

        offset = 0
        for _ in range(14):
            target_top = 175 + (preset - 1) * PRESET_ROW_PITCH - offset
            if target_top <= 520:
                if target_top < PRESET_PANEL[1]:
                    logger.warning(f'Preset {preset} scrolled past, list shorter than expected')
                    break
                button = ClickButton((60, target_top, 460, target_top + 90), name=f'PRESET_{preset}')
                self.device.click(button)
                return True
            self.device.screenshot()
            before = crop(self.device.image, PRESET_SHIFT_STRIP, copy=True)
            self.device.swipe((240, 520), (240, 520 - PRESET_ROW_PITCH), name='PRESET_SCROLL')
            self.device.sleep((0.5, 0.7))
            self.device.screenshot()
            shift = abyss_panel_shift(before, self.device.image)
            if shift < 8:
                logger.warning(f'Preset list bottom reached before preset {preset}')
                break
            offset += shift
        logger.warning(f'Cannot reach preset {preset}, fallback to the last visible row')
        self.device.click(PRESET_BLOCK[3])
        return False

    def abyss_team_filled(self, node_index: int) -> bool:
        """
        Whether the 4 member slots of a team row show character portraits.
        Call after device.screenshot().
        """
        luma = rgb2luma(crop(self.device.image, self.TEAM_ROW_SLOTS[node_index], copy=False))
        return float(luma.std()) > self.TEAM_FILLED_STD

    def abyss_set_team(self, node_index: int, preset: int) -> bool:
        """
        Apply an in-game preset team to the given node, verify the slots
        actually got filled and retry, clicks during the node-focus animation
        can be swallowed by the game.

        Pages:
            in: PREP_CHECK
            out: PREP_CHECK, with character picker panel open, team applied
        """
        logger.info(f'Set team for node {node_index} with preset {preset}')
        slot = self.TEAM_SLOT[node_index]

        for trial in range(3):
            # Open character picker
            timeout = Timer(15, count=5).start()
            while 1:
                self.device.screenshot()
                # Preset tab visible in either state means picker is open
                if self.match_template_luma(TAB_PRESET_CLICK) or self.match_template_color(TAB_PRESET_CHECK):
                    break
                if timeout.reached():
                    logger.warning('abyss_set_team open picker timeout')
                    break
                if self.appear(PREP_CHECK, interval=2):
                    self.device.click(slot)
                    self._abyss_focused_node = node_index
                    continue

            # Focus this node only when another row is focused,
            # wait out the focus animation
            if self._abyss_focused_node != node_index:
                self.device.click(slot)
                self._abyss_focused_node = node_index
                self.device.sleep((0.6, 0.8))

            # Switch to preset tab
            timeout = Timer(15, count=5).start()
            while 1:
                self.device.screenshot()
                if self.match_template_color(TAB_PRESET_CHECK):
                    break
                if timeout.reached():
                    logger.warning('abyss_set_team preset tab timeout')
                    break
                if self.match_template_luma(TAB_PRESET_CLICK, interval=2):
                    self.device.click(TAB_PRESET_CLICK)
                    continue

            # Apply preset and verify
            self._abyss_click_preset(preset)
            self.device.sleep((0.8, 1.0))
            self.device.screenshot()
            if self.abyss_team_filled(node_index):
                logger.info(f'Team of node {node_index} filled')
                return True
            logger.warning(f'Team of node {node_index} not filled after applying preset, trial {trial + 1}')

        logger.warning(f'Failed to fill team of node {node_index}')
        return False

    def _abyss_effect_card(self, node_index: int) -> ClickButton:
        """
        The configured effect card to click for the node. Card heights vary
        with their description text, so cards beyond the first are anchored
        by OCR of the card titles on the left edge of the panel.

        Pages:
            in: EQUIP_EFFECT, effect selection screen
        """
        select = str((self._abyss_effect_select or {}).get(node_index, '1'))
        if select == 'random':
            select = random.choice(['1', '2', '3'])
            logger.info(f'Random effect card: {select}')
        if select == '1':
            return EFFECT_CARD_1
        ocr = Ocr(ClickButton((706, 140, 1270, 660), name='OCR_EFFECT_TITLES'), lang='cn')
        titles = []
        for row in ocr.detect_and_ocr(self.device.image):
            text = row.ocr_text.strip()
            box = tuple(row.box)
            # Card titles are short, left-aligned at the panel edge.
            # Mechanic footnotes and the equip button sit elsewhere
            if box[0] > 790 or not text or len(text) > 6:
                continue
            if '机制' in text or '效果' in text:
                continue
            titles.append(box)
        titles.sort(key=lambda b: b[1])
        index = int(select) - 1
        if index < len(titles):
            return ClickButton(titles[index], name=f'EFFECT_CARD_{select}')
        logger.warning(f'Effect card {select} not found among {len(titles)} titles, '
                       f'fallback to card 1')
        return EFFECT_CARD_1

    def abyss_set_effect(self, node_index: int, skip_first_screenshot=True):
        """
        Equip the configured buff/axiom for the given node.
        Idempotent, re-equipping the same effect is harmless.

        Pages:
            in: PREP_CHECK
            out: PREP_CHECK, effect equipped
        """
        if not self.EFFECT_SLOT:
            return
        logger.info(f'Set effect for node {node_index}')
        slot = self.EFFECT_SLOT[node_index]
        interval = Timer(2)
        timeout = Timer(20, count=10).start()
        # Enter effect selection screen
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(EQUIP_EFFECT):
                logger.info('Effect selection screen entered')
                break
            if timeout.reached():
                logger.warning('abyss_set_effect enter timeout')
                return
            if self.appear(PREP_CHECK, interval=2):
                self.device.click(slot)
                continue

        # Select first card then equip
        selected = False
        interval.clear()
        timeout = Timer(20, count=10).start()
        while 1:
            self.device.screenshot()

            if self.appear(PREP_CHECK) and not self.appear(EQUIP_EFFECT):
                logger.info(f'Effect equipped for node {node_index}')
                break
            if timeout.reached():
                logger.warning('abyss_set_effect equip timeout')
                return
            if self.appear(EQUIP_EFFECT) and interval.reached():
                if not selected:
                    self.device.click(self._abyss_effect_card(node_index))
                    selected = True
                    self.device.sleep((0.3, 0.5))
                self.device.click(EQUIP_EFFECT)
                interval.reset()

    def abyss_enter_dungeon(self, skip_first_screenshot=True):
        """
        Click the enter button and wait until leaving the prep screen.

        Pages:
            in: PREP_CHECK
            out: loading screen towards in-dungeon map

        Raises:
            RequestHumanTakeover: If blocked by invalid teams
        """
        logger.info('Abyss enter dungeon')
        interval = Timer(3)
        attempts = 0
        timeout = Timer(25, count=10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.appear(PREP_CHECK):
                logger.info('Left stage prep screen')
                break
            if timeout.reached() or attempts >= 5:
                raise RequestHumanTakeover(
                    'Cannot enter abyss stage, team or effect may be invalid. '
                    'Please check in-game team presets: two presets must exist and must not share characters'
                )
            if self.handle_popup_confirm():
                continue
            if interval.reached():
                self.device.click(self.ENTER_BUTTON)
                attempts += 1
                interval.reset()

    def abyss_prep_teams_and_enter(self, team1_preset=1, team2_preset=2):
        """
        Set teams and effects for both nodes, verify, then enter.

        Pages:
            in: PREP_CHECK
            out: loading screen towards in-dungeon map
        """
        for node_index, preset in [(1, team1_preset), (2, team2_preset)]:
            self.abyss_set_team(node_index, preset)
            self.abyss_set_effect(node_index)

        # Final check before entering
        self.device.screenshot()
        for node_index in (1, 2):
            if not self.abyss_team_filled(node_index):
                raise RequestHumanTakeover(
                    f'Team of node {node_index} is still empty after applying presets. '
                    f'Check in-game presets: they must exist and must not share characters with each other'
                )
        self.abyss_enter_dungeon()
