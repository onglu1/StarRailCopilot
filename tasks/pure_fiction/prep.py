from module.base.button import ClickButton
from module.base.timer import Timer
from module.base.utils import crop, rgb2luma
from module.exception import RequestHumanTakeover
from module.logger import logger
from tasks.base.ui import UI
from tasks.pure_fiction.assets.assets_pure_fiction_prep import (
    ENTER_STORY,
    EQUIP_EFFECT,
    PREP_CHECK,
    TAB_PRESET_CHECK,
    TAB_PRESET_CLICK
)
from tasks.pure_fiction.ui import PureFictionStageNode, PureFictionUI

# Stage prep screen, two team rows (node 1 / node 2)
# Each row: trial character + 4 member slots + 1 buff slot
TEAM_SLOT = {
    1: ClickButton((867, 452, 915, 488), name='TEAM_1_SLOT'),
    2: ClickButton((867, 547, 915, 583), name='TEAM_2_SLOT'),
}
BUFF_SLOT = {
    1: ClickButton((1174, 448, 1218, 492), name='BUFF_1_SLOT'),
    2: ClickButton((1174, 543, 1218, 587), name='BUFF_2_SLOT'),
}
# First buff card on the buff selection screen
BUFF_CARD_1 = ClickButton((760, 150, 1140, 225), name='BUFF_CARD_1')
# Preset blocks in the preset team tab, top to bottom.
# Click the portrait strip of the block, the title row is not reliable
PRESET_BLOCK = {
    1: ClickButton((60, 175, 460, 265), name='PRESET_1'),
    2: ClickButton((60, 348, 460, 438), name='PRESET_2'),
    3: ClickButton((60, 520, 460, 610), name='PRESET_3'),
}
# The 4 member slots of each team row, bright portraits when filled
# (luma std 69-88), dark placeholder circles when empty (std ~21)
TEAM_ROW_SLOTS = {
    1: (920, 448, 1160, 492),
    2: (920, 543, 1160, 587),
}


class PureFictionPrep(PureFictionUI):
    def pf_stage_enter(self, node: PureFictionStageNode, skip_first_screenshot=True):
        """
        Pages:
            in: page_pure_fiction
            out: PREP_CHECK, stage prep screen
        """
        logger.hr(f'Pure fiction stage enter: {node}', level=2)
        interval = Timer(3)
        timeout = Timer(20, count=10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(PREP_CHECK):
                logger.info('Stage prep screen entered')
                break
            if timeout.reached():
                logger.warning('pf_stage_enter timeout, rescan stages')
                nodes = self.pf_scan_stages()
                match = [n for n in nodes if n.index == node.index]
                if not match:
                    raise RequestHumanTakeover(f'Stage {node.index} not found on stage map')
                node = match[0]
                timeout.reset()
            if interval.reached():
                self.device.click(node.button)
                interval.reset()

    def pf_set_buff(self, node_index: int, skip_first_screenshot=True):
        """
        Equip the first buff for the given node.
        Idempotent, re-equipping the same buff is harmless.

        Pages:
            in: PREP_CHECK
            out: PREP_CHECK, buff equipped
        """
        logger.info(f'Set buff for node {node_index}')
        slot = BUFF_SLOT[node_index]
        interval = Timer(2)
        timeout = Timer(20, count=10).start()
        # Enter buff selection screen
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(EQUIP_EFFECT):
                logger.info('Buff selection screen entered')
                break
            if timeout.reached():
                logger.warning('pf_set_buff enter timeout')
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
                logger.info(f'Buff equipped for node {node_index}')
                break
            if timeout.reached():
                logger.warning('pf_set_buff equip timeout')
                return
            if self.appear(EQUIP_EFFECT) and interval.reached():
                if not selected:
                    self.device.click(BUFF_CARD_1)
                    selected = True
                    self.device.sleep((0.3, 0.5))
                self.device.click(EQUIP_EFFECT)
                interval.reset()

    def pf_team_filled(self, node_index: int) -> bool:
        """
        Whether the 4 member slots of a team row show character portraits.
        Call after device.screenshot().
        """
        luma = rgb2luma(crop(self.device.image, TEAM_ROW_SLOTS[node_index], copy=False))
        return float(luma.std()) > 45

    def pf_set_team(self, node_index: int, preset: int) -> bool:
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
        slot = TEAM_SLOT[node_index]

        for trial in range(3):
            # Open character picker
            timeout = Timer(15, count=5).start()
            while 1:
                self.device.screenshot()
                # Preset tab visible in either state means picker is open
                if self.match_template_luma(TAB_PRESET_CLICK) or self.match_template_color(TAB_PRESET_CHECK):
                    break
                if timeout.reached():
                    logger.warning('pf_set_team open picker timeout')
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
                    logger.warning('pf_set_team preset tab timeout')
                    break
                if self.match_template_luma(TAB_PRESET_CLICK, interval=2):
                    self.device.click(TAB_PRESET_CLICK)
                    continue

            # Apply preset and verify
            self.device.click(PRESET_BLOCK[preset])
            self.device.sleep((0.8, 1.0))
            self.device.screenshot()
            if self.pf_team_filled(node_index):
                logger.info(f'Team of node {node_index} filled')
                return True
            logger.warning(f'Team of node {node_index} not filled after applying preset, trial {trial + 1}')

        logger.warning(f'Failed to fill team of node {node_index}')
        return False

    def pf_enter_story(self, skip_first_screenshot=True):
        """
        Click ENTER_STORY and wait until leaving the prep screen.

        Pages:
            in: PREP_CHECK
            out: loading screen towards in-dungeon map

        Raises:
            RequestHumanTakeover: If blocked by invalid teams
        """
        logger.info('Enter story')
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
                    'Cannot enter pure fiction stage, team or buff may be invalid. '
                    'Please check in-game team presets: two presets must exist and must not share characters'
                )
            if self.handle_popup_confirm():
                continue
            if interval.reached():
                self.device.click(ENTER_STORY)
                attempts += 1
                interval.reset()

    def pf_prep_stage(self, node: PureFictionStageNode, team1_preset=1, team2_preset=2):
        """
        Full prep flow: enter stage, set teams and buffs for both nodes, enter story.

        Pages:
            in: page_pure_fiction
            out: loading screen towards in-dungeon map
        """
        self.pf_stage_enter(node)
        for node_index, preset in [(1, team1_preset), (2, team2_preset)]:
            self.pf_set_team(node_index, preset)
            self.pf_set_buff(node_index)

        # Final check before entering
        self.device.screenshot()
        for node_index in (1, 2):
            if not self.pf_team_filled(node_index):
                raise RequestHumanTakeover(
                    f'Team of node {node_index} is still empty after applying presets. '
                    f'Check in-game presets: they must exist and must not share characters with each other'
                )
        self.pf_enter_story()
