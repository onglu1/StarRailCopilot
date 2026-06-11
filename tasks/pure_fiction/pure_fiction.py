import cv2

from module.base.timer import Timer
from module.base.utils import rgb2luma
from module.config.utils import get_server_next_monday_update
from module.exception import GameStuckError
from module.logger import logger
from tasks.combat.assets.assets_combat_state import COMBAT_AUTO
from tasks.map.control.joystick import JoystickContact, MapControlJoystick
from tasks.pure_fiction.assets.assets_pure_fiction_battle import (
    PF_WAVE_FLAG,
    QUICK_CLEAR_CONFIRM,
    SETTLE_BACK
)
from tasks.pure_fiction.assets.assets_pure_fiction_map import BLANK_CLOSE, MAP_CHECK
from tasks.pure_fiction.prep import PureFictionPrep


class PureFiction(PureFictionPrep, MapControlJoystick):
    _pf_prev_frame = None

    def _pf_battle_progressing(self) -> bool:
        """
        Whether the battle screen has changed since the last call.
        Used to detect a stalled battle (auto battle off, game waiting for input).
        """
        image = cv2.resize(rgb2luma(self.device.image), (160, 90))
        prev = self._pf_prev_frame
        self._pf_prev_frame = image
        if prev is None:
            return True
        diff = cv2.absdiff(prev, image).mean()
        # Stalled battle (idle background animation only) measures ~6 even at
        # 20s intervals, any real combat action measures 70+
        return diff > 12.0

    def pf_dungeon_loop(self):
        """
        State machine inside a pure fiction stage:
        - in-dungeon map: hold joystick forward, spam attack to trigger battle
        - battle (wave flag at top-left): watch for stall, toggle auto battle if stalled.
          PF battle hides pause/auto/2x most of the time (frequent ult cutscenes),
          so there is no reliable auto-state readout. A stalled screen for ~55s
          means auto battle is off, one blind click on the auto position fixes it.
          If auto is already on, the screen keeps changing and we never click.
        - mechanic intro overlay: click blank to close
        After node 1 battle ends, the game drops back to the map with team 2,
        walk and trigger again. Ends at the settlement screen.

        Pages:
            in: loading screen towards in-dungeon map
            out: page_pure_fiction, back at stage map
        """
        logger.hr('Pure fiction dungeon', level=2)
        contact = None
        # Re-issue joystick direction periodically
        walk_timer = Timer(3)
        # Walking this long without reaching any battle means stuck
        map_stuck = Timer(150, count=10)
        # Battle screen frozen this long means auto battle is off
        battle_stall = Timer(55, count=10)
        self._pf_prev_frame = None

        try:
            while 1:
                self.device.screenshot()

                if self.appear(SETTLE_BACK):
                    if contact is not None:
                        contact.up()
                        contact = None
                    logger.info('Pure fiction settlement appeared')
                    break

                in_battle = self.appear(PF_WAVE_FLAG)
                in_map = not in_battle and self.appear(MAP_CHECK)
                if not in_battle:
                    # Cutscenes hide the wave flag, that counts as progress
                    battle_stall.clear()
                    self._pf_prev_frame = None
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
                    if self._pf_battle_progressing():
                        battle_stall.reset()
                    if battle_stall.reached():
                        logger.info('Battle stalled, click auto battle')
                        self.device.click(COMBAT_AUTO)
                        battle_stall.reset()
                    continue

                if in_map:
                    # Walking spams A and RUN clicks for a while
                    self.device.stuck_record_clear()
                    self.device.click_record_clear()
                    if not map_stuck.started():
                        map_stuck.start()
                    if map_stuck.reached():
                        raise GameStuckError('Walked too long without triggering battle in pure fiction')
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
                if self.handle_forgotten_hall_buff():
                    continue
                if self.handle_popup_confirm():
                    continue
                if self.handle_popup_single():
                    continue
        finally:
            if contact is not None:
                contact.up()

        self.pf_settle_exit()

    def pf_settle_exit(self, skip_first_screenshot=True):
        """
        Leave the settlement screen, handle quick-clear popup and reward popups.

        Pages:
            in: settlement screen, SETTLE_BACK
            out: page_pure_fiction
        """
        logger.info('Pure fiction settle exit')
        timeout = Timer(60, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.pf_in_stage_map():
                logger.info('Back at pure fiction stage map')
                break
            if timeout.reached():
                logger.warning('pf_settle_exit timeout')
                break
            if self.appear_then_click(SETTLE_BACK, interval=3):
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

    def run(self):
        logger.hr('Pure Fiction', level=1)
        team1 = int(self.config.PureFiction_Team1Preset)
        team2 = int(self.config.PureFiction_Team2Preset)
        logger.attr('Team presets', f'{team1}, {team2}')

        # If a previous run died inside a dungeon, finish it first
        self.device.screenshot()
        if self.appear(PF_WAVE_FLAG) or self.appear(MAP_CHECK) or self.appear(SETTLE_BACK):
            logger.info('Resuming inside a pure fiction dungeon')
            self.pf_dungeon_loop()

        cleared = 0
        # At most all stages of a season plus margin
        for _ in range(6):
            self.pf_goto()
            nodes = self.pf_scan_stages()
            target = self.pf_get_target_stage(nodes)
            if target is None:
                logger.info('Pure fiction finished, nothing to challenge')
                break
            logger.hr(f'Challenge {target}', level=1)
            self.pf_prep_stage(target, team1_preset=team1, team2_preset=team2)
            self.pf_dungeon_loop()
            cleared += 1

            # Check progress to avoid retrying the same stage forever
            nodes = self.pf_scan_stages()
            after = [n for n in nodes if n.index == target.index]
            if after and after[0].status == 'open':
                logger.warning(f'{target} still not cleared after challenge, '
                               f'teams may be too weak, stop')
                break

        logger.attr('Stages challenged', cleared)
        # Pure fiction seasons rotate bi-weekly, run weekly is safe and simple
        monday = get_server_next_monday_update(self.config.Scheduler_ServerUpdate)
        self.config.task_delay(target=monday)
        self.ui_goto_main()
