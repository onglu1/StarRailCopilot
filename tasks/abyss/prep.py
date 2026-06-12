"""
Stage-prep helpers shared by the abyss modes.

The prep screen of all three modes shares the same structure: a left
character picker (with a preset-team tab at fixed position), two team
rows on the right (one per node/half), an optional per-node effect slot
(buff in Pure Fiction, axiom in Apocalyptic Shadow, none in Memory of
Chaos), and an enter button at the bottom right. Only coordinates and
the enter button differ, subclasses bind them via class attributes.
"""
from module.base.button import ClickButton
from module.base.timer import Timer
from module.base.utils import crop, rgb2luma
from module.exception import RequestHumanTakeover
from module.logger import logger
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
        if preset not in PRESET_BLOCK:
            logger.warning(f'Invalid preset {preset}, fallback to 1')
            preset = 1
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
                    continue

            # Focus this node, wait out the focus animation
            self.device.click(slot)
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
            self.device.click(PRESET_BLOCK[preset])
            self.device.sleep((0.8, 1.0))
            self.device.screenshot()
            if self.abyss_team_filled(node_index):
                logger.info(f'Team of node {node_index} filled')
                return True
            logger.warning(f'Team of node {node_index} not filled after applying preset, trial {trial + 1}')

        logger.warning(f'Failed to fill team of node {node_index}')
        return False

    def abyss_set_effect(self, node_index: int, skip_first_screenshot=True):
        """
        Equip the first buff/axiom for the given node.
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
                    self.device.click(EFFECT_CARD_1)
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
