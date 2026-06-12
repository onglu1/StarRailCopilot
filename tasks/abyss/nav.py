"""
Navigation into the three abyss-like weekly modes, all entered from the
Treasures Lightward tab of the interastral guide, plus recovery helpers
for screens outside the page system (stage prep, stray dialogs).
"""
from module.base.button import ClickButton
from module.base.timer import Timer
from module.exception import GamePageUnknownError
from module.logger import logger
from tasks.abyss.assets.assets_abyss_battle import QUICK_CLEAR_CONFIRM
from tasks.abyss.assets.assets_abyss_map import BLANK_CLOSE
from tasks.abyss.assets.assets_abyss_nav import TAB_TREASURES_LIGHTWARD_CHECK
from tasks.abyss.assets.assets_abyss_prep import PREP_CHECK
from tasks.base.assets.assets_base_page import BACK, CLOSE
from tasks.base.page import page_guide, page_main
from tasks.base.ui import UI
from tasks.dungeon.ui.nav import DUNGEON_NAV_LIST
from tasks.forgotten_hall.assets.assets_forgotten_hall_ui import TELEPORT

# Guide tabs are icon-only, position may shift between game versions.
# Blind click as fallback when the selected-state template doesn't match.
TAB_TREASURES_LIGHTWARD_CLICK = ClickButton((424, 88, 494, 136), name='TAB_TREASURES_LIGHTWARD_CLICK')


class AbyssNav(UI):
    # KEYWORDS_DUNGEON_NAV keyword of the mode, override in subclasses
    NAV_KEYWORD = None

    def abyss_home_check(self) -> bool:
        """
        Whether at the mode's own stage screen. Override in subclasses.
        """
        raise NotImplementedError

    def abyss_goto(self):
        """
        Goto the mode's stage screen.

        Pages:
            in: Any
            out: the mode's stage screen, abyss_home_check
        """
        logger.hr(f'Abyss goto: {self.NAV_KEYWORD}', level=2)
        self.device.screenshot()
        if self.abyss_home_check():
            logger.info('Already at the abyss stage screen')
            return
        self.abyss_exit_prep_if_stuck()
        self.abyss_ui_ensure_guide()
        self.abyss_guide_tab_goto()
        DUNGEON_NAV_LIST.select_row(self.NAV_KEYWORD, main=self)
        self.abyss_teleport()

    def abyss_guide_tab_goto(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_guide
            out: page_guide, Treasures_Lightward tab, nav list loaded
        """
        timeout = Timer(10, count=10).start()
        click_interval = Timer(2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('abyss_guide_tab_goto timeout, continue anyway')
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

    def abyss_teleport_handler(self) -> bool:
        """
        Mode-specific handler during teleport, e.g. apocalyptic shadow
        passes through a season overview screen.

        Returns:
            bool: If handled
        """
        return False

    def abyss_teleport(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_guide, Treasures_Lightward tab, mode nav row selected
            out: the mode's stage screen
                May pass through one-time popups: season intro animation,
                mechanic update announcements, unlock tutorials.
        """
        logger.info('Abyss teleport')
        timeout = Timer(60, count=60).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.abyss_home_check():
                logger.info('Abyss stage screen entered')
                break
            if timeout.reached():
                logger.warning('abyss_teleport timeout')
                break
            if self.match_template_luma(BLANK_CLOSE, interval=2):
                logger.info(f'{BLANK_CLOSE} -> click blank')
                self.device.click(BLANK_CLOSE)
                continue
            if self.handle_tutorial():
                continue
            if self.abyss_teleport_handler():
                continue
            if self.appear_then_click(TELEPORT, interval=3):
                continue
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue
            if self.handle_reward():
                continue

    def abyss_exit_prep_if_stuck(self):
        """
        The stage prep screen is not a registered page, ui_ensure would fail
        there. If a previous run died on prep, back out first.
        """
        if not self.appear(PREP_CHECK):
            return
        logger.info('Stuck on a stage prep screen, back out first')
        timeout = Timer(20, count=10).start()
        while 1:
            self.device.screenshot()
            if not self.appear(PREP_CHECK):
                logger.info('Left the stage prep screen')
                break
            if timeout.reached():
                logger.warning('abyss_exit_prep_if_stuck timeout')
                break
            if self.appear_then_click(BACK, interval=2):
                continue
            if self.appear_then_click(CLOSE, interval=2):
                continue
            if self.handle_popup_confirm():
                continue

    def abyss_escape_stray_dialog(self):
        """
        Stray dialogs can cover the stage screen: a material-source popup
        from a mis-clicked reward icon, or the quick-clear offer that pops
        after clearing a high stage. Escape back to a known screen.
        """
        for _ in range(6):
            self.device.screenshot()
            if self.abyss_home_check():
                return
            if self.ui_page_appear(page_main) or self.ui_page_appear(page_guide):
                return
            if self.appear_then_click(QUICK_CLEAR_CONFIRM, interval=2):
                self.device.sleep((0.8, 1.0))
                continue
            if self.match_template_luma(BLANK_CLOSE):
                logger.info(f'{BLANK_CLOSE} -> click blank')
                self.device.click(BLANK_CLOSE)
                self.device.sleep((0.6, 0.8))
                continue
            if self.handle_popup_single():
                continue
            if self.handle_popup_confirm():
                continue
            if self.handle_reward():
                continue
            # Click outside a centered modal
            logger.info('Escape stray dialog, click outside modal')
            self.device.click(ClickButton((80, 420, 180, 540), name='OUTSIDE_MODAL'))
            self.device.sleep((0.6, 0.8))

    def abyss_ui_ensure_guide(self):
        """
        ui_ensure(page_guide) with one recovery attempt: a stray dialog
        makes the page unknown, escape it then retry.
        """
        try:
            self.ui_ensure(page_guide)
        except GamePageUnknownError:
            logger.warning('Page unknown, escape stray dialogs and retry')
            self.abyss_escape_stray_dialog()
            self.ui_ensure(page_guide)
