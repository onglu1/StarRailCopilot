"""
In-dungeon state machine and reward claiming shared by the abyss modes.

All three share the same structure once a stage is entered:
loading -> (mechanic intro overlay) -> in-dungeon map walking -> battle
-> back to map with team 2 -> battle -> settlement screen.

Verified facts these helpers rely on:
- Auto and 2x speed are driven by the upstream combat state machine
  (handle_combat_state) exactly like normal combat: it is gated on the
  pause button being visible and reads the real active-state of each
  button, so it never toggles something that is already on.
- The abyss battle HUD auto-hides when idle (the gate then blocks all
  state handling), but its touch areas persist: when the HUD is hidden
  and auto/2x are not verified yet, one click on the auto button both
  wakes the HUD and flips auto on (abyss battles always start with auto
  off; in the rare case auto was already on, the state machine detects
  the mis-toggle and corrects it).
- The state machine only acts after the gate passes two consecutive
  frames, the fade-in animation of the waking HUD misreads button
  borders otherwise.
- Ult cutscenes hide the wave flag for a few seconds mid-battle, the
  battle-left debounce keeps the battle state stable across them.
- The wave flag at top-left is the only reliable battle HUD element,
  shared by all three modes.
- Device-level stuck/click records must be cleared during the long
  battle and walking phases, same as upstream combat.
"""
import cv2

from module.base.button import ClickButton
from module.base.timer import Timer
from module.base.utils import rgb2luma
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.abyss.assets.assets_abyss_battle import QUICK_CLEAR_CONFIRM, WAVE_FLAG
from tasks.abyss.assets.assets_abyss_map import BLANK_CLOSE, MAP_CHECK
from tasks.abyss.assets.assets_abyss_prep import PREP_CHECK
from tasks.abyss.prep import AbyssPrep
from tasks.abyss.stage import abyss_has_exhausted, abyss_select_target
from tasks.combat.assets.assets_combat_state import COMBAT_AUTO
from tasks.combat.state import CombatState
from tasks.map.control.joystick import JoystickContact, MapControlJoystick


class AbyssCombatLoop(AbyssPrep, MapControlJoystick, CombatState):
    # ButtonWrapper that detects the settlement screen and is clicked to leave it.
    # Override in subclasses.
    SETTLE_BUTTON = None
    # ClickButton opening the star-reward panel from the mode's stage screen,
    # None when the mode has no claimable panel (apocalyptic shadow grants
    # clear rewards directly on the settlement screen)
    REWARD_ENTRY = None
    # Extra reward tabs to claim besides the default one
    REWARD_TABS = []
    # Close button of the reward panel, same position in PF and MoC panels
    REWARD_PANEL_CLOSE = None

    _abyss_prev_frame = None

    def abyss_scan_stages(self) -> list:
        """Scan stage nodes. Override in subclasses."""
        raise NotImplementedError

    def abyss_prep_stage(self, node, team1_preset=1, team2_preset=2) -> bool:
        """Enter a stage and prepare teams. Override in subclasses."""
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

    def abyss_run(self, config_prefix: str):
        """
        Tool entry: resume an interrupted dungeon, run challenges by the
        configured strategy, claim rewards, then stop. Not scheduled, runs
        when started from the tool page.

        Args:
            config_prefix: task name in config, e.g. 'PureFiction'
        """
        logger.hr(config_prefix, level=1)
        team1 = int(getattr(self.config, f'{config_prefix}_Team1Preset'))
        team2 = int(getattr(self.config, f'{config_prefix}_Team2Preset'))
        mode = getattr(self.config, f'{config_prefix}_ChallengeMode')
        max_retry = int(getattr(self.config, f'{config_prefix}_MaxRetry'))
        swap = bool(getattr(self.config, f'{config_prefix}_SwapOnRetry', True))
        assigned = int(getattr(self.config, f'{config_prefix}_AssignedStage', 1))
        # Buff/axiom card selection per node, only pure fiction exposes it
        self._abyss_effect_select = {
            1: str(getattr(self.config, f'{config_prefix}_Node1Buff', '1')),
            2: str(getattr(self.config, f'{config_prefix}_Node2Buff', '1')),
        }
        logger.attr('ChallengeMode', mode)

        # If a previous run died inside a dungeon, finish it first
        self.device.screenshot()
        if self.appear(self.SETTLE_BUTTON) or self.appear(WAVE_FLAG) or self.appear(MAP_CHECK):
            logger.info('Resuming inside an abyss dungeon')
            self.abyss_dungeon_loop()

        fought, exhausted = self.abyss_run_challenges(
            mode=mode, team1_preset=team1, team2_preset=team2,
            max_retry=max_retry, assigned=assigned, swap_on_retry=swap)
        logger.attr('Battles fought', fought)

        self.abyss_claim_rewards()
        if exhausted:
            logger.info('Stage rounds exhausted without full stars, '
                        'adjust teams and start again when ready')
        self.ui_goto_main()

    def abyss_run_challenges(self, mode='highest', team1_preset=1, team2_preset=2,
                             max_retry=2, assigned=1, swap_on_retry=True) -> tuple:
        """
        The main challenge loop shared by all modes: scan, select a target
        by mode and per-stage round counts, prep, fight, repeat. A failed
        battle leaves the stage unimproved so it gets selected again until
        its rounds are exhausted; with swap_on_retry every retry swaps the
        node order of the two teams.

        Returns:
            tuple: (battles_fought, exhausted)
                exhausted: the relevant stage ran out of rounds, callers
                decide between deferring the task and finishing the week
        """
        attempts = {}
        fought = 0
        # Bounded by: 12 stages * retries plus rescans, far above any real run
        for _ in range(50):
            self.abyss_goto()
            # Let screen transition fades finish, dimmed gold stars
            # during a fade undercount otherwise
            self.device.sleep((0.8, 1.0))
            self.device.screenshot()
            nodes = self.abyss_scan_stages()
            target = abyss_select_target(
                nodes, mode=mode, attempts=attempts, max_retry=max_retry, assigned=assigned)
            if target is None:
                exhausted = abyss_has_exhausted(
                    nodes, mode=mode, attempts=attempts, max_retry=max_retry, assigned=assigned)
                logger.info(f'Abyss challenges finished, fought={fought}, exhausted={exhausted}')
                return fought, exhausted
            att = attempts.get(target.index, 0)
            logger.hr(f'Challenge {target} (round {att + 1}/{max_retry})', level=1)
            if swap_on_retry and att % 2 == 1:
                logger.info('Retry with team order swapped')
                t1, t2 = team2_preset, team1_preset
            else:
                t1, t2 = team1_preset, team2_preset
            if not self.abyss_prep_stage(target, team1_preset=t1, team2_preset=t2):
                # Locked or unsupported, never retry this run
                attempts[target.index] = 999
                continue
            attempts[target.index] = att + 1
            self.abyss_dungeon_loop()
            fought += 1
        logger.warning('abyss_run_challenges hit the loop bound')
        return fought, False

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
        # Wake clicks without any screen change, see below
        stall_clicks = 0
        was_in_battle = False
        # The hidden HUD is woken at most this often, see module docstring
        hud_wake = Timer(3, count=3)
        hud_wake_clicks = 0
        # Consecutive frames with the pause button visible, the state
        # machine acts only on a stable HUD
        gate_streak = 0
        # Ult cutscenes hide the wave flag for a few seconds mid-battle,
        # only consider the battle left after a sustained absence
        battle_left = Timer(8, count=3)
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
                # A lost battle returns to the stage prep screen after its
                # fail dialog. Back out, the run loop rescans and retries
                if self.appear(PREP_CHECK):
                    if contact is not None:
                        contact.up()
                        contact = None
                    logger.info('Returned to prep screen, battle probably failed')
                    self.abyss_exit_prep_if_stuck()
                    return

                in_battle = self.appear(WAVE_FLAG)
                in_map = not in_battle and self.appear(MAP_CHECK)
                if in_battle:
                    battle_left.clear()
                else:
                    # Cutscenes hide the wave flag, that counts as progress.
                    # Auto battle does not persist between halves, re-arm the
                    # entry click only after a sustained absence
                    battle_stall.clear()
                    self._abyss_prev_frame = None
                    if was_in_battle:
                        if not battle_left.started():
                            battle_left.start()
                        if battle_left.reached():
                            was_in_battle = False
                if not in_map:
                    map_stuck.clear()

                if in_battle:
                    # Battle legitimately runs for minutes without clicks
                    self.device.stuck_record_clear()
                    self.device.click_record_clear()
                    if contact is not None:
                        contact.up()
                        contact = None
                    if not was_in_battle:
                        logger.info('Abyss battle entered')
                        was_in_battle = True
                        self.combat_state_reset()
                        hud_wake.reset()
                        hud_wake_clicks = 0
                        gate_streak = 0
                    # Auto and 2x are driven by the upstream state machine,
                    # it reads real button states and never mis-toggles.
                    # Only act on a stable HUD, the fade-in of a waking HUD
                    # misreads button borders
                    if self.is_combat_executing():
                        gate_streak += 1
                        if gate_streak >= 2 and self.handle_combat_state():
                            continue
                    else:
                        gate_streak = 0
                        # HUD hidden with auto/2x not verified yet: one click
                        # on auto wakes the HUD (and flips auto on, abyss
                        # battles start with auto off; a mis-toggle would be
                        # corrected by the state machine)
                        if not (self._combat_auto_checked and self._combat_2x_checked) \
                                and hud_wake_clicks < 3 and hud_wake.reached():
                            logger.info('Battle HUD hidden, wake it via the auto button')
                            self.device.click(COMBAT_AUTO)
                            hud_wake.reset()
                            hud_wake_clicks += 1
                            continue
                    if not battle_stall.started():
                        battle_stall.start()
                    if self._abyss_battle_progressing():
                        battle_stall.reset()
                        stall_clicks = 0
                    if battle_stall.reached():
                        # A stray click may have opened a modal (e.g. ult target
                        # selection) that hides the battle controls, waking
                        # would then do nothing forever. Escalate to a
                        # task-level restart after repeated dead wakes.
                        if stall_clicks >= 3:
                            raise GameStuckError(
                                'Battle stalled even after repeated wake clicks')
                        logger.info('Battle stalled, re-verify auto/2x')
                        if not self.is_combat_executing():
                            self.device.click(COMBAT_AUTO)
                        self.combat_state_reset()
                        gate_streak = 0
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

    def abyss_claim_rewards(self):
        """
        Claim star-count rewards from the mode's reward panel.

        Pages:
            in: the mode's stage screen
            out: the mode's stage screen
        """
        if self.REWARD_ENTRY is None:
            logger.info('This mode has no reward panel, skip claiming')
            return
        logger.hr('Abyss claim rewards', level=2)
        if not self._abyss_reward_open():
            return
        for tab in [None] + list(self.REWARD_TABS):
            if tab is not None:
                self.device.click(tab)
                self.device.sleep((0.8, 1.0))
            self._abyss_reward_claim_tab()
        self._abyss_reward_close()

    def _abyss_reward_panel_visible(self) -> bool:
        ocr = Ocr(ClickButton((150, 170, 350, 620), name='OCR_REWARD_PANEL'), lang='cn')
        for row in ocr.detect_and_ocr(self.device.image):
            if '累计获得' in row.ocr_text or '馈赠' in row.ocr_text:
                return True
        return False

    def _abyss_reward_open(self) -> bool:
        logger.info('Open reward panel')
        timeout = Timer(20, count=10).start()
        interval = Timer(3)
        while 1:
            self.device.screenshot()
            if self._abyss_reward_panel_visible():
                return True
            if timeout.reached():
                logger.warning('Cannot open reward panel, skip claiming')
                return False
            if self.match_template_luma(BLANK_CLOSE, interval=2):
                self.device.click(BLANK_CLOSE)
                continue
            if self.handle_popup_single():
                continue
            if interval.reached():
                self.device.click(self.REWARD_ENTRY)
                interval.reset()

    def _abyss_reward_claim_tab(self):
        for _ in range(12):
            self.device.screenshot()
            if self.match_template_luma(BLANK_CLOSE, interval=1):
                logger.info(f'{BLANK_CLOSE} -> click blank')
                self.device.click(BLANK_CLOSE)
                self.device.sleep((0.6, 0.8))
                continue
            if self.handle_reward():
                continue
            ocr = Ocr(ClickButton((930, 170, 1120, 665), name='OCR_CLAIM'), lang='cn')
            buttons = [row for row in ocr.detect_and_ocr(self.device.image)
                       if row.ocr_text.strip() == '领取']
            if not buttons:
                logger.info('No more claimable rewards in this tab')
                break
            box = buttons[0].box
            logger.info(f'Claim reward at {box}')
            self.device.click(ClickButton(tuple(box), name='CLAIM'))
            self.device.sleep((1.0, 1.3))

    def _abyss_reward_close(self):
        logger.info('Close reward panel')
        timeout = Timer(20, count=10).start()
        while 1:
            self.device.screenshot()
            if self.abyss_home_check() and not self._abyss_reward_panel_visible():
                break
            if timeout.reached():
                logger.warning('Close reward panel timeout')
                break
            if self.match_template_luma(BLANK_CLOSE, interval=2):
                self.device.click(BLANK_CLOSE)
                continue
            if self.handle_reward():
                continue
            if self.REWARD_PANEL_CLOSE is not None:
                self.device.click(self.REWARD_PANEL_CLOSE)
                self.device.sleep((0.8, 1.0))
