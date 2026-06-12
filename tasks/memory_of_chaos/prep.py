from module.base.button import ClickButton
from module.base.timer import Timer
from module.logger import logger
from tasks.abyss.assets.assets_abyss_prep import PREP_CHECK
from tasks.memory_of_chaos.assets.assets_memory_of_chaos_prep import MOC_ENTER
from tasks.memory_of_chaos.ui import MemoryOfChaosStageNode, MemoryOfChaosUI


class MemoryOfChaosPrep(MemoryOfChaosUI):
    # MoC prep screen: boss preview + 4 member slots per node, no effect slot.
    # The character picker is open by default when the prep screen is entered.
    TEAM_SLOT = {
        1: ClickButton((888, 440, 932, 484), name='MOC_TEAM_1_SLOT'),
        2: ClickButton((888, 530, 932, 574), name='MOC_TEAM_2_SLOT'),
    }
    # Node number badges left of the rows, clicking focuses without
    # selecting a member
    TEAM_ROW_FOCUS = {
        1: ClickButton((537, 442, 578, 492), name='MOC_TEAM_1_FOCUS'),
        2: ClickButton((537, 532, 578, 582), name='MOC_TEAM_2_FOCUS'),
    }
    TEAM_ROW_SLOTS = {
        1: (888, 440, 1205, 484),
        2: (888, 530, 1205, 574),
    }
    EFFECT_SLOT = {}
    ENTER_BUTTON = MOC_ENTER

    def moc_stage_enter(self, node: MemoryOfChaosStageNode) -> bool:
        """
        Click a stage crystal and wait for the prep screen.

        Returns:
            bool: False if the prep screen never opened, the stage is
                probably locked, callers should skip this stage.

        Pages:
            in: page_forgotten_hall
            out: PREP_CHECK if True
        """
        logger.hr(f'Memory of chaos stage enter: {node}', level=2)
        interval = Timer(3)
        timeout = Timer(15, count=10).start()
        while 1:
            self.device.screenshot()

            if self.appear(PREP_CHECK):
                logger.info('Stage prep screen entered')
                self._abyss_focused_node = None
                return True
            if timeout.reached():
                logger.warning(f'{node} prep screen did not open, stage may be locked')
                self.abyss_escape_stray_dialog()
                return False
            if self.handle_popup_confirm():
                continue
            if interval.reached():
                self.device.click(node.button)
                interval.reset()

    def abyss_prep_stage(self, node, team1_preset=1, team2_preset=2) -> bool:
        """
        Returns:
            bool: False if the stage could not be entered (probably locked)
        """
        if not self.moc_stage_enter(node):
            return False
        self.abyss_prep_teams_and_enter(team1_preset=team1_preset, team2_preset=team2_preset)
        return True
