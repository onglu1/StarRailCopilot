from module.base.button import ClickButton
from module.base.timer import Timer
from module.exception import RequestHumanTakeover
from module.logger import logger
from tasks.abyss.assets.assets_abyss_prep import PREP_CHECK
from tasks.pure_fiction.assets.assets_pure_fiction_prep import ENTER_STORY
from tasks.pure_fiction.ui import PureFictionStageNode, PureFictionUI


class PureFictionPrep(PureFictionUI):
    # Stage prep screen, two team rows (node 1 / node 2)
    # Each row: trial character + 4 member slots + 1 buff slot
    TEAM_SLOT = {
        1: ClickButton((867, 452, 915, 488), name='TEAM_1_SLOT'),
        2: ClickButton((867, 547, 915, 583), name='TEAM_2_SLOT'),
    }
    # Node number badges left of the rows, clicking focuses without
    # selecting a member
    TEAM_ROW_FOCUS = {
        1: ClickButton((534, 452, 568, 505), name='TEAM_1_FOCUS'),
        2: ClickButton((534, 547, 568, 600), name='TEAM_2_FOCUS'),
    }
    TEAM_ROW_SLOTS = {
        1: (920, 448, 1160, 492),
        2: (920, 543, 1160, 587),
    }
    EFFECT_SLOT = {
        1: ClickButton((1174, 448, 1218, 492), name='BUFF_1_SLOT'),
        2: ClickButton((1174, 543, 1218, 587), name='BUFF_2_SLOT'),
    }
    ENTER_BUTTON = ENTER_STORY

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
                self._abyss_focused_node = None
                break
            if timeout.reached():
                logger.warning('pf_stage_enter timeout, rescan stages')
                nodes = self.abyss_scan_stages()
                match = [n for n in nodes if n.index == node.index]
                if not match:
                    raise RequestHumanTakeover(f'Stage {node.index} not found on stage map')
                node = match[0]
                timeout.reset()
            if interval.reached():
                self.device.click(node.button)
                interval.reset()

    def abyss_prep_stage(self, node, team1_preset=1, team2_preset=2) -> bool:
        """
        Full prep flow: enter stage, set teams and buffs for both nodes, enter story.

        Pages:
            in: page_pure_fiction
            out: loading screen towards in-dungeon map
        """
        self.pf_stage_enter(node)
        self.abyss_prep_teams_and_enter(team1_preset=team1_preset, team2_preset=team2_preset)
        return True
