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
import numpy as np

from module.base.button import ClickButton
from module.base.timer import Timer
from module.base.utils import crop, rgb2luma
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from tasks.combat.assets.assets_combat_state import COMBAT_AUTO
from tasks.combat.state import CombatState
from tasks.map.control.joystick import JoystickContact, MapControlJoystick
from tasks.pure_fiction.assets.assets_pure_fiction_battle import PF_WAVE_FLAG, QUICK_CLEAR_CONFIRM
from tasks.pure_fiction.assets.assets_pure_fiction_map import BLANK_CLOSE, MAP_CHECK
from tasks.pure_fiction.assets.assets_pure_fiction_prep import PREP_CHECK


class AbyssStageNode:
    """
    A stage entry on an abyss stage-select screen.

    status: 'open' / 'cleared' / 'locked' / 'unknown'
    stars: 0-3 counted from gold star glyphs, None when unreadable
        (e.g. the selected tab in apocalyptic shadow renders enlarged)
    """

    def __init__(self, index, button):
        self.index: int = index
        self.button = button
        self.status: str = 'unknown'
        self.stars = None

    @property
    def enterable(self) -> bool:
        return self.status != 'locked'

    @property
    def full_starred(self) -> bool:
        return self.stars is not None and self.stars >= 3

    @property
    def stars_known_zero(self) -> bool:
        if self.stars is not None:
            return self.stars == 0
        # Stars unreadable: only un-attempted stages count as zero
        return self.status in ['open', 'unknown']

    def __repr__(self):
        stars = '?' if self.stars is None else self.stars
        return f'Stage_{self.index:02d}({self.status}, {stars}*)'


def abyss_count_stars(image, area) -> int:
    """
    Count gold star glyphs inside the area via connected components.
    Gold measures ~(241, 189, 110), one star is a 45-155 px cluster
    depending on the mode, empty star outlines and backgrounds measure 0.
    """
    img = crop(image, area, copy=False)
    height, width = img.shape[:2]
    px = img.reshape(-1, 3).astype(int)
    mask = (np.abs(px[:, 0] - 241) < 30) & (np.abs(px[:, 1] - 189) < 30) & (np.abs(px[:, 2] - 110) < 40)
    mask = mask.reshape(height, width).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    count = 0
    for i in range(1, n):
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        # Stars are roughly square blobs, gold decoration lines are thin
        if stats[i, cv2.CC_STAT_AREA] >= 12 and h >= 5 and w <= h * 3:
            count += 1
    return min(count, 3)


def abyss_select_target(nodes, mode='first_clear', attempts=None, max_retry=2):
    """
    Args:
        nodes: list of AbyssStageNode
        mode:
            'first_clear': lowest stage with zero stars
            'push': the first (lowest) stage that is not full-starred,
                hammer it until full or retries exhausted
            'sweep': all stages that are not full-starred, lowest first,
                each up to max_retry attempts
            'highest_only': the highest unlocked stage if not full-starred
        attempts: {stage_index: attempts_this_run}
        max_retry: max attempts per stage per run

    Returns:
        AbyssStageNode: or None if nothing left to do
    """
    attempts = attempts or {}

    def tried(n):
        return attempts.get(n.index, 0)

    enterable = [n for n in nodes if n.enterable]
    if not enterable:
        logger.warning('No enterable stage found')
        return None

    if mode == 'highest_only':
        top = max(enterable, key=lambda n: n.index)
        if top.full_starred or top.status == 'cleared' and top.stars is None:
            return None
        if tried(top) >= max_retry:
            return None
        return top
    if mode == 'push':
        nonfull = [n for n in enterable if not n.full_starred]
        if not nonfull:
            return None
        first = min(nonfull, key=lambda n: n.index)
        if tried(first) >= max_retry:
            return None
        return first
    if mode == 'sweep':
        candidates = [n for n in enterable if not n.full_starred and tried(n) < max_retry]
    else:
        # first_clear
        candidates = [n for n in enterable if n.stars_known_zero and tried(n) < max_retry]
    if not candidates:
        return None
    return min(candidates, key=lambda n: n.index)


def abyss_has_exhausted(nodes, mode='first_clear', attempts=None, max_retry=2) -> bool:
    """
    Whether some mode-relevant stage still needs work but ran out of retries.
    Used to decide between deferring the task and finishing the week.
    """
    attempts = attempts or {}

    def tried(n):
        return attempts.get(n.index, 0)

    enterable = [n for n in nodes if n.enterable]
    if mode == 'first_clear':
        relevant = [n for n in enterable if n.stars_known_zero]
    elif mode == 'highest_only':
        if not enterable:
            return False
        top = max(enterable, key=lambda n: n.index)
        relevant = [top] if not top.full_starred and top.stars is not None else []
    else:
        relevant = [n for n in enterable if not n.full_starred and n.stars is not None]
    return any(tried(n) >= max_retry for n in relevant)


class AbyssCombatLoop(MapControlJoystick, CombatState):
    # ButtonWrapper that detects the settlement screen and is clicked to leave it.
    # Override in subclasses.
    SETTLE_BUTTON = None

    _abyss_prev_frame = None
    _combat_auto_blind_clicked = False

    def abyss_home_check(self) -> bool:
        """
        Whether back at the mode's own stage screen. Override in subclasses.
        """
        raise NotImplementedError

    def abyss_goto(self):
        """Goto the mode's stage screen. Override in subclasses."""
        raise NotImplementedError

    def abyss_escape_stray_dialog(self):
        """
        Stray dialogs can cover the stage screen: a material-source popup
        from a mis-clicked reward icon, or the quick-clear offer that pops
        after clearing a high stage. Escape back to a known screen.
        """
        from tasks.base.page import page_guide, page_main
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
        from module.exception import GamePageUnknownError
        from tasks.base.page import page_guide
        try:
            self.ui_ensure(page_guide)
        except GamePageUnknownError:
            logger.warning('Page unknown, escape stray dialogs and retry')
            self.abyss_escape_stray_dialog()
            self.ui_ensure(page_guide)

    def abyss_exit_prep_if_stuck(self):
        """
        The stage prep screen is not a registered page, ui_ensure would fail
        there. If a previous run died on prep, back out first.
        Call at the start of the mode's goto.
        """
        from tasks.base.assets.assets_base_page import BACK, CLOSE
        from tasks.pure_fiction.assets.assets_pure_fiction_prep import PREP_CHECK
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

    def abyss_scan_stages(self) -> list:
        """Scan stage nodes. Override in subclasses."""
        raise NotImplementedError

    def abyss_prep_stage(self, node, team1_preset=1, team2_preset=2) -> bool:
        """Enter a stage and prepare teams. Override in subclasses."""
        raise NotImplementedError

    def abyss_run_challenges(self, mode='first_clear', team1_preset=1, team2_preset=2,
                             max_retry=2) -> tuple:
        """
        The main challenge loop shared by all modes: scan, select a target
        by mode and per-stage attempt counts, prep, fight, repeat. A failed
        battle leaves the stage unimproved so it gets selected again until
        its retries are exhausted.

        Returns:
            tuple: (battles_fought, exhausted)
                exhausted: some relevant stage ran out of retries, callers
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
            target = abyss_select_target(nodes, mode=mode, attempts=attempts, max_retry=max_retry)
            if target is None:
                exhausted = abyss_has_exhausted(nodes, mode=mode, attempts=attempts, max_retry=max_retry)
                logger.info(f'Abyss challenges finished, fought={fought}, exhausted={exhausted}')
                return fought, exhausted
            logger.hr(f'Challenge {target} (attempt {attempts.get(target.index, 0) + 1}/{max_retry})', level=1)
            if not self.abyss_prep_stage(target, team1_preset=team1_preset, team2_preset=team2_preset):
                # Locked or unsupported, never retry this run
                attempts[target.index] = 999
                continue
            attempts[target.index] = attempts.get(target.index, 0) + 1
            self.abyss_dungeon_loop()
            fought += 1
        logger.warning('abyss_run_challenges hit the loop bound')
        return fought, False

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
        # Battle UI buttons at top-right auto-hide when idle, so state
        # detection alone cannot see them. On battle entry blind-click the
        # auto button once: abyss battles always start with auto off, the
        # click both enables auto and wakes the hidden UI. While the UI is
        # awake handle_combat_state() verifies auto and enables 2x speed.
        was_in_battle = False
        battle_entry = Timer(2, count=2)
        # Ult cutscenes hide the wave flag for a few seconds mid-battle,
        # only consider the battle left after a sustained absence, otherwise
        # the entry click would fire again and toggle auto OFF
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

                in_battle = self.appear(PF_WAVE_FLAG)
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
                        battle_entry.reset()
                        self.combat_state_reset()
                        self._combat_auto_blind_clicked = False
                    # Blind-click auto shortly after entry, then let
                    # handle_combat_state verify and set 2x while UI is awake
                    if not self._combat_auto_blind_clicked:
                        if battle_entry.reached():
                            logger.info('Click auto battle on entry')
                            self.device.click(COMBAT_AUTO)
                            self._combat_auto_blind_clicked = True
                        continue
                    if self.handle_combat_state():
                        continue
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

    # ClickButton opening the star-reward panel from the mode's stage screen,
    # None when the mode has no claimable panel (apocalyptic shadow grants
    # clear rewards directly on the settlement screen)
    REWARD_ENTRY = None
    # Extra reward tabs to claim besides the default one
    REWARD_TABS = []
    # Close button of the reward panel, same position in PF and MoC panels
    REWARD_PANEL_CLOSE = None

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
