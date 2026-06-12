"""
Shared in-dungeon state machine for the three abyss-like weekly modes:
Pure Fiction / Memory of Chaos / Apocalyptic Shadow.

All three share the same structure once a stage is entered:
loading -> (mechanic intro overlay) -> in-dungeon map walking -> battle
-> back to map with team 2 -> battle -> settlement screen.

Verified facts these helpers rely on:
- Abyss battles do not render pause/auto/2x at the standard top-right
  position, the wave flag at top-left is the only reliable battle HUD
  element (PF_WAVE_FLAG, shared across modes).
- Auto battle does not persist between halves. There is no readable
  auto-state either, so a stall watchdog clicks the (invisible but
  touch-active) auto position after ~55s of a frozen battle screen.
  If auto is already on the screen keeps changing and we never click.
- Device-level stuck/click records must be cleared during the long
  battle and walking phases, same as upstream combat.
"""
import cv2

from module.base.timer import Timer
from module.base.utils import rgb2luma
from module.exception import GameStuckError
from module.logger import logger
from tasks.combat.assets.assets_combat_state import COMBAT_AUTO
from tasks.map.control.joystick import JoystickContact, MapControlJoystick
from tasks.pure_fiction.assets.assets_pure_fiction_battle import PF_WAVE_FLAG, QUICK_CLEAR_CONFIRM
from tasks.pure_fiction.assets.assets_pure_fiction_map import BLANK_CLOSE, MAP_CHECK


class AbyssCombatLoop(MapControlJoystick):
    # ButtonWrapper that detects the settlement screen and is clicked to leave it.
    # Override in subclasses.
    SETTLE_BUTTON = None

    _abyss_prev_frame = None

    def abyss_home_check(self) -> bool:
        """
        Whether back at the mode's own stage screen. Override in subclasses.
        """
        raise NotImplementedError

    def abyss_mid_settle_handler(self) -> bool:
        """
        Mode-specific handler that runs before the settlement check each loop,
        e.g. Apocalyptic Shadow shows a mid-run settlement after node 1 where
        both "exit" and "go to node 2" are present, "go to node 2" must win.

        Returns:
            bool: If handled
        """
        return False

    def _abyss_battle_progressing(self) -> bool:
        """
        Whether the battle screen has changed since the last call.
        Used to detect a stalled battle (auto battle off, game waiting for input).
        """
        image = cv2.resize(rgb2luma(self.device.image), (160, 90))
        prev = self._abyss_prev_frame
        self._abyss_prev_frame = image
        if prev is None:
            return True
        diff = cv2.absdiff(prev, image).mean()
        # Stalled battle (idle background animation only) measures ~6 even at
        # 20s intervals, any real combat action measures 70+
        return diff > 12.0

    def abyss_dungeon_loop(self):
        """
        State machine inside an abyss stage, see module docstring.

        Pages:
            in: loading screen towards in-dungeon map
            out: back at the mode's stage screen (abyss_home_check)
        """
        logger.hr('Abyss dungeon', level=2)
        contact = None
        # Re-issue joystick direction periodically
        walk_timer = Timer(3)
        # Walking this long without reaching any battle means stuck
        map_stuck = Timer(150, count=10)
        # Battle screen frozen this long means auto battle is off
        battle_stall = Timer(55, count=10)
        # Auto clicks without any screen change, see below
        stall_clicks = 0
        self._abyss_prev_frame = None

        try:
            while 1:
                self.device.screenshot()

                if self.abyss_mid_settle_handler():
                    continue
                if self.appear(self.SETTLE_BUTTON):
                    if contact is not None:
                        contact.up()
                        contact = None
                    logger.info('Abyss settlement appeared')
                    break
                # Defensive: some exit paths (e.g. failed node 1 in apocalyptic
                # shadow) land back on the stage screen without a settlement
                if self.abyss_home_check():
                    if contact is not None:
                        contact.up()
                        contact = None
                    logger.info('Back at abyss stage screen without settlement')
                    return

                in_battle = self.appear(PF_WAVE_FLAG)
                in_map = not in_battle and self.appear(MAP_CHECK)
                if not in_battle:
                    # Cutscenes hide the wave flag, that counts as progress
                    battle_stall.clear()
                    self._abyss_prev_frame = None
                if not in_map:
                    map_stuck.clear()

                if in_battle:
                    # Battle legitimately runs for minutes without clicks
                    self.device.stuck_record_clear()
                    self.device.click_record_clear()
                    if contact is not None:
                        contact.up()
                        contact = None
                    if not battle_stall.started():
                        battle_stall.start()
                    if self._abyss_battle_progressing():
                        battle_stall.reset()
                        stall_clicks = 0
                    if battle_stall.reached():
                        # A stray click may have opened a modal (e.g. ult target
                        # selection) that hides the battle controls, clicking
                        # auto would then do nothing forever. Escalate to a
                        # task-level restart after repeated dead clicks.
                        if stall_clicks >= 3:
                            raise GameStuckError(
                                'Battle stalled even after repeated auto battle clicks')
                        logger.info('Battle stalled, click auto battle')
                        self.device.click(COMBAT_AUTO)
                        battle_stall.reset()
                        stall_clicks += 1
                    continue

                if in_map:
                    # Walking spams A and RUN clicks for a while
                    self.device.stuck_record_clear()
                    self.device.click_record_clear()
                    if not map_stuck.started():
                        map_stuck.start()
                    if map_stuck.reached():
                        raise GameStuckError('Walked too long without triggering battle in abyss dungeon')
                    if contact is None:
                        contact = JoystickContact(self)
                        contact.set(direction=0, run=True)
                        walk_timer.reset()
                    elif walk_timer.reached():
                        contact.set(direction=0, run=True)
                        walk_timer.reset()
                    self.handle_map_run_2x()
                    self.handle_map_A()
                    continue

                # Overlays and popups (loading screens fall through harmlessly)
                if self.match_template_luma(BLANK_CLOSE, interval=2):
                    logger.info(f'{BLANK_CLOSE} -> click blank')
                    self.device.click(BLANK_CLOSE)
                    continue
                if self.handle_tutorial():
                    continue
                if self.handle_forgotten_hall_buff():
                    continue
                if self.handle_popup_confirm():
                    continue
                if self.handle_popup_single():
                    continue
        finally:
            if contact is not None:
                contact.up()

        self.abyss_settle_exit()

    def abyss_settle_exit(self, skip_first_screenshot=True):
        """
        Leave the settlement screen, handle quick-clear popup and reward popups.

        Pages:
            in: settlement screen, SETTLE_BUTTON
            out: the mode's stage screen
        """
        logger.info('Abyss settle exit')
        timeout = Timer(60, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.abyss_home_check():
                logger.info('Back at abyss stage screen')
                break
            if timeout.reached():
                logger.warning('abyss_settle_exit timeout')
                break
            if self.appear_then_click(self.SETTLE_BUTTON, interval=3):
                continue
            if self.appear_then_click(QUICK_CLEAR_CONFIRM, interval=2):
                continue
            if self.match_template_luma(BLANK_CLOSE, interval=2):
                logger.info(f'{BLANK_CLOSE} -> click blank')
                self.device.click(BLANK_CLOSE)
                continue
            if self.handle_reward():
                continue
            if self.handle_battle_pass_notification():
                continue
            if self.handle_popup_confirm():
                continue
            if self.handle_popup_single():
                continue
