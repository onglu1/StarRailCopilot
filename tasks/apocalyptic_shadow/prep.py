from module.base.button import ClickButton
from module.base.timer import Timer
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.abyss.assets.assets_abyss_prep import PREP_CHECK
from tasks.apocalyptic_shadow.assets.assets_apocalyptic_shadow_prep import (
    AS_BOSS_INFO_CHECK,
    AS_PREP_GO
)
from tasks.apocalyptic_shadow.assets.assets_apocalyptic_shadow_ui import AS_STAGE_GO
from tasks.apocalyptic_shadow.ui import ApocalypticShadowStageNode, ApocalypticShadowUI
from tasks.base.assets.assets_base_page import BACK, CLOSE

# Next-step / go-to-team button at the bottom right of the boss info dialog
AS_BOSS_INFO_NEXT = ClickButton((1008, 632, 1110, 672), name='AS_BOSS_INFO_NEXT')
# Title area on the prep screen right panel, reads 星启模式 on
# star-origin stages (3 nodes, level 90 bosses)
OCR_PREP_TITLE = ClickButton((500, 60, 1280, 240), name='OCR_AS_PREP_TITLE')


class ApocalypticShadowPrep(ApocalypticShadowUI):
    # AS prep screen: each node block shows boss preview and traits,
    # 4 member slots and an axiom (effect) slot
    TEAM_SLOT = {
        1: ClickButton((735, 285, 785, 330), name='AS_TEAM_1_SLOT'),
        2: ClickButton((735, 520, 785, 565), name='AS_TEAM_2_SLOT'),
    }
    # Node block header titles, clicking focuses the block without
    # selecting a member
    TEAM_ROW_FOCUS = {
        1: ClickButton((700, 172, 860, 190), name='AS_TEAM_1_FOCUS'),
        2: ClickButton((700, 402, 860, 420), name='AS_TEAM_2_FOCUS'),
    }
    TEAM_ROW_SLOTS = {
        1: (725, 275, 1020, 340),
        2: (725, 510, 1020, 575),
    }
    EFFECT_SLOT = {
        1: ClickButton((1172, 283, 1218, 330), name='AS_AXIOM_1_SLOT'),
        2: ClickButton((1172, 518, 1218, 565), name='AS_AXIOM_2_SLOT'),
    }
    ENTER_BUTTON = AS_PREP_GO

    def as_stage_enter(self, node: ApocalypticShadowStageNode, skip_first_screenshot=True) -> bool:
        """
        Select a stage tab, click challenge, click through the boss info
        dialog (shown once per period unless dismissed), reach the prep screen.

        Returns:
            bool: False if the prep screen never opened. Star-origin
                (3-node) stages or other blockers should be skipped.

        Pages:
            in: page_apocalyptic_shadow
            out: PREP_CHECK if True
        """
        logger.hr(f'Apocalyptic shadow stage enter: {node}', level=2)
        stage_interval = Timer(4)
        info_interval = Timer(2)
        timeout = Timer(30, count=15).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(PREP_CHECK):
                logger.info('Stage prep screen entered')
                self._abyss_focused_node = None
                return True
            if timeout.reached():
                logger.warning(f'{node} prep screen did not open, skip this stage')
                self.abyss_escape_stray_dialog()
                return False
            if self.handle_tutorial():
                continue
            if self.appear(AS_BOSS_INFO_CHECK, interval=2):
                if info_interval.reached():
                    self.device.click(AS_BOSS_INFO_NEXT)
                    info_interval.reset()
                continue
            if self.abyss_home_check() and stage_interval.reached():
                self.device.click(node.button)
                self.device.sleep((0.7, 0.9))
                self.device.click(AS_STAGE_GO)
                stage_interval.reset()
                continue
            if self.handle_popup_confirm():
                continue

    def as_prep_is_star_origin(self) -> bool:
        """
        Whether the current prep screen is a star-origin (星启模式) stage,
        which has 3 nodes and needs 3 teams, unsupported yet.

        Pages:
            in: PREP_CHECK
        """
        ocr = Ocr(OCR_PREP_TITLE, lang='cn')
        for row in ocr.detect_and_ocr(self.device.image):
            if '星启' in row.ocr_text:
                return True
        return False

    def as_prep_exit(self, skip_first_screenshot=True):
        """
        Back out from the prep screen to the stage screen.

        Pages:
            in: PREP_CHECK
            out: page_apocalyptic_shadow
        """
        logger.info('Apocalyptic shadow prep exit')
        timeout = Timer(20, count=10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.abyss_home_check():
                logger.info('Back at apocalyptic shadow stage screen')
                break
            if timeout.reached():
                logger.warning('as_prep_exit timeout')
                break
            if self.appear_then_click(BACK, interval=2):
                continue
            if self.appear_then_click(CLOSE, interval=2):
                continue
            if self.handle_popup_confirm():
                continue

    def abyss_prep_stage(self, node, team1_preset=1, team2_preset=2) -> bool:
        """
        Returns:
            bool: False if the stage could not be entered or is unsupported

        Pages:
            in: page_apocalyptic_shadow
            out: loading screen towards in-dungeon map if True,
                page_apocalyptic_shadow if False
        """
        if not self.as_stage_enter(node):
            return False
        self.device.screenshot()
        if self.as_prep_is_star_origin():
            logger.warning(f'{node} is a star-origin stage that needs 3 teams, '
                           f'not supported yet, skip')
            self.as_prep_exit()
            return False
        self.abyss_prep_teams_and_enter(team1_preset=team1_preset, team2_preset=team2_preset)
        return True
