"""Android port of StarRailAssistant's current Divergent Universe strategy.

AGPL-3.0; see THIRD_PARTY.md. Native SRC supplies login, screenshots, OCR,
joystick contacts, combat auto/speed controls and monthly reward handling.
"""
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import re
import time

import cv2
import numpy as np
from filelock import FileLock, Timeout

from module.base.timer import Timer
from module.config.config import TaskEnd
from module.exception import RequestHumanTakeover
from module.logger import logger, save_error_log
from tasks.currency_wars.operator import Box, normalize
from tasks.currency_wars.paths import STATE_DIR
from tasks.divergent_universe.operator import DivergentOperator
from tasks.divergent_universe.progress import Progress, ROOT
from tasks.divergent_universe.selection import read_choices, choose
from tasks.divergent_universe.assets import DU_INTERACT
from tasks.dungeon.ui.nav import DungeonUINav
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_TAB, KEYWORDS_DUNGEON_NAV
from tasks.map.control.joystick import JoystickContact
from tasks.map.control.control import MapControl
from tasks.rogue.route.exit import RogueExit
from tasks.rogue.keywords import RogueEventTitle


class DivergentUniverse(DungeonUINav, MapControl):
    INTERACT_BUTTON = DU_INTERACT
    # A recovery stage includes login and returning to the retained run. Its
    # deadline survives worker reloads; observed next-node progress clears it.
    RECOVERY_WINDOW_SECONDS = 600
    # The DU status panel covers x < 384; keep native gestures off that HUD.
    ROTATION_BOX = (410, 180, 990, 300)
    # Observed DU titles/variants missing from the native SU catalogue. The
    # thin leading 一 is omitted on 一抹色彩; 规划航线 is a newer DU event.
    # Keep these matches exact; do not fuzzy-match arbitrary HUD text.
    EVENT_NAMES = frozenset(normalize(event.cn) for event in RogueEventTitle.instances.values()) | {
        '抹色彩', '规划航线', '神秘链接', '运输任务',
        # Actual outlined-world-label OCR of 冒牌眷属; the canonical title is
        # already in SRC. Keep these observed variants exact, not fuzzy.
        '冒牌属', '冒牌春属',
    }
    STATION_TYPES = ('战斗', '精英', '首领', '转化', '商店', '事件', '冒险', '铸造',
                     '奖励', '休整', '异常', '财富', '空白', '储蓄间')
    REWARD_TITLES = ('方程展开', '祝福强化', '获得奇物', '获得祝福',
                     '获得物品', '信标已部署', '站点卡升级', '已修复以下奇物')
    SETTLEMENT_TITLES = ('探索成功', '探索失败', '探索结束', '探索终止',
                         '探索中断', '演算结束', '星阶提升', '智瞳点亮', '战斗失败')
    CHOICES = {
        'mask': ('选择一张面具', '选择面具'),
        'blessing': ('选择祝福', '选取祝福', '获取祝福'),
        'equation': ('选择方程', '获取方程'),
        'curio': ('选择奇物', '获取奇物'),
        'station_card': ('选择站点卡',),
        'miracle': ('选择惊世奇迹', '选择奇迹', '选择你的奇迹'),
        'area': ('选择区域', '人才管理阶段'),
        'effect': ('选择基础效果',),
        'discard': ('丢弃奇物', '丢弃祝福', '奇物损毁', '摧毁奇物'),
    }

    def prepare_entry(self):
        """Apply entry settings without starting or clearing an exploration."""
        from tasks.divergent_universe.entry import EntrySettings
        lock = STATE_DIR / f'{self.config.config_name}.controller.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(lock), timeout=0):
            self.progress = Progress(self.config.config_name)
            self._initialize()
            self.go_to_lobby()
            self.active = self.progress.data.get('active')
            pause_limit = Timer(180, count=3).start()
            while self.world_visible() or self.selection_kind() or self.is_combat_executing():
                if not self.active or pause_limit.reached():
                    raise RequestHumanTakeover('当前探索暂离未确认，已保留进度')
                if self.is_combat_executing():
                    self.combat_execute()
                elif self.selection_kind():
                    self.handle_choice(self.selection_kind())
                else:
                    self.reenter_station()
                self.op.snapshot()
            self.op.wait_until(lambda: self.op.text(EntrySettings.LAUNCH, (0.3, 0.65, 1, 1))
                               or self.op.text(('常规演算', '周期演算'), (0, 0, 0.48, 0.88)),
                               action=lambda: self.op.click_text('开始游戏', (0.70, 0.84, 0.88, 0.94)) or self.op.back(),
                               name='演算入口')
            EntrySettings(self).prepare(self.config.DivergentUniverse_Calculation)

    @contextmanager
    def error_frame_history(self):
        if not self.config.Error_SaveError:
            yield
            return
        original_limit = self.device.screenshot_deque.maxlen
        expanded = original_limit < 65
        if expanded:
            # Native capture already supplies these frames. Keep enough of
            # them to inspect the 60-frame watchdog window after a failure;
            # no extra device captures or image writes during healthy play.
            self.device.__dict__['screenshot_deque'] = deque(self.device.screenshot_deque, maxlen=65)
        try:
            yield
        finally:
            if expanded:
                self.device.__dict__['screenshot_deque'] = deque(
                    self.device.screenshot_deque, maxlen=original_limit)

    def run(self):
        if self.config.Emulator_GameLanguage != 'cn':
            raise RequestHumanTakeover('差分宇宙当前适配简体中文 Android 界面')
        if self.config.DivergentUniverse_Runs < 0 or self.config.DivergentUniverse_RecoveryRetries < 0:
            raise RequestHumanTakeover('差分宇宙运行次数和恢复次数不能为负数')
        lock = STATE_DIR / f'{self.config.config_name}.controller.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(lock), timeout=0), self.error_frame_history():
                self.progress = Progress(self.config.config_name)
                self.progress.record('task_started', intended_mode=self.config.DivergentUniverse_Mode,
                                     intended_calculation=self.config.DivergentUniverse_Calculation)
                completed = 0
                while self.config.DivergentUniverse_Runs == 0 or completed < self.config.DivergentUniverse_Runs:
                    try:
                        self._initialize()
                        if not self.go_to_lobby():
                            break  # Explicit weekly point limit, not a completed run.
                        self.resume_failed_position()
                        self.active = self.progress.begin(self.config.DivergentUniverse_Mode,
                                                          self.config.DivergentUniverse_Calculation)
                        result = self.play_run()
                        self.progress.finish(result)
                        completed += 1
                        logger.info(f'DU completed run {completed}: {result}')
                        self.config.load()
                        self.config.bind(self.config.task)
                    except TaskEnd:
                        self.progress.save('stopped')
                        raise
                    except RequestHumanTakeover as error:
                        self.progress.record('terminal_error', error=str(error), error_type=type(error).__name__)
                        self.progress.save('error')
                        save_error_log(config=self.config, device=self.device, png_compress_level=1)
                        raise
                    except Exception as error:
                        recovery = self.prepare_recovery()
                        self.progress.data['error'] = str(error)
                        self.progress.save('error')
                        self.progress.record('fault', error=str(error), error_type=type(error).__name__,
                                             recovery_attempt=recovery['attempts'] + 1,
                                             recovery_action=recovery['action'])
                        logger.exception(f'DU task failed: {type(error).__name__}: {error}')
                        save_error_log(config=self.config, device=self.device, png_compress_level=1)
                        self.recover_checkpoint(error)
                if self.config.DivergentUniverse_ClaimRewards:
                    self.claim_points()
                self.progress.save('finished')
        except Timeout:
            raise RequestHumanTakeover('该配置已有货币战争或差分宇宙控制进程，请先停止它')

    def prepare_recovery(self):
        active = self.progress.data.get('active') or {}
        identity = (active.get('id'), active.get('node'))
        recovery = self.progress.data.get('recovery')
        if recovery is None or (recovery['run_id'], recovery['node']) != identity:
            recovery = dict(run_id=identity[0], node=identity[1], faults=0, attempts=0,
                            action='resume', deadline=time.time() + self.RECOVERY_WINDOW_SECONDS)
            self.progress.data['recovery'] = recovery
        recovery['faults'] += 1
        # More battles/options in the same room are not evidence that its
        # recurring navigation/dialogue failure has been resolved.
        abandon = (active.get('mode') == 'full' and active.get('node')
                   and recovery['faults'] >= 2 and not active.get('settlement_observed'))
        if self.config.DivergentUniverse_RecoveryRetries > 0 and (abandon or active.get('stop_requested')):
            if recovery['action'] != 'settle':
                recovery['action'] = 'settle'
                recovery['deadline'] = time.time() + self.RECOVERY_WINDOW_SECONDS
            if not active.get('stop_requested'):
                active.update(stop_requested=True, exit_reason='recovery_same_node')
                self.progress.record('recovery_settlement_requested', faults=recovery['faults'],
                                     attempts=recovery['attempts'])
        # A normal run timeout must not leave the recovery itself with an
        # already-expired operator clock. The persistent stage limit still
        # applies and cannot be renewed by retries or worker reloads.
        self._run_deadline = time.monotonic() + self.RECOVERY_WINDOW_SECONDS
        if getattr(self, 'op', None) is not None:
            self.apply_recovery_deadline()
        return recovery

    def apply_recovery_deadline(self):
        recovery = self.progress.data.get('recovery')
        deadline = self._run_deadline
        if recovery:
            deadline = min(deadline, time.monotonic() + max(0, recovery['deadline'] - time.time()))
        self.op.deadline = deadline

    def recover_checkpoint(self, error):
        # A failed native login must consume the next restart attempt before
        # returning to go_to_lobby. Otherwise it waits for the same stuck
        # startup screen for another full login window without restarting.
        recovery = self.progress.data['recovery']
        while (recovery['attempts'] < self.config.DivergentUniverse_RecoveryRetries
               and time.time() < recovery['deadline']):
            if self.config.stop_event is not None and self.config.stop_event.is_set():
                self.progress.save('stopped')
                raise TaskEnd
            recovery['attempts'] += 1
            # Persist before the external action, including failed logins.
            self.progress.save('error')
            logger.warning(f'DU recovery {recovery["attempts"]}: restart game, {recovery["action"]}: {error}')
            try:
                self.login_from_current(restart=True)
            except TaskEnd:
                self.progress.save('stopped')
                raise
            except RequestHumanTakeover as takeover:
                self.progress.record('terminal_error', error=str(takeover), error_type=type(takeover).__name__)
                self.progress.data['error'] = str(takeover)
                self.progress.save('error')
                save_error_log(config=self.config, device=self.device, png_compress_level=1)
                raise
            except Exception as restart_error:
                self.progress.record('restart_failed', error=str(restart_error),
                                     recovery_attempt=recovery['attempts'])
                logger.warning(f'DU login recovery did not finish: {restart_error}')
                error = restart_error
            else:
                return
        self.progress.record('recovery_exhausted', attempts=recovery['attempts'], action=recovery['action'])
        self.progress.data['error'] = str(error)
        self.progress.save('error')
        save_error_log(config=self.config, device=self.device, png_compress_level=1)
        raise RequestHumanTakeover(f'差分宇宙自动恢复后仍失败，已保留现场：{error}') from error

    def resume_failed_position(self):
        # App restart preserves the player's position, including a position
        # behind the boss or against a wall. Temporary leave/resume restores
        # this room's entry without discarding the exploration checkpoint.
        if self.active and (self.active.get('stop_requested') or (
                self.active.get('station') == '冒险'
                and self.request_adventure_exit(self.active.get('adventure_kind', '')))):
            return  # Resume the requested settlement, not the skipped room.
        if (self.progress.data.get('phase') == 'error' and self.active
                and self.active.get('node') and self.world_visible()):
            logger.info('DU failed checkpoint resumed on map; restore the room entry before retrying')
            self.progress.record('recovery_reentry_begin')
            self.reenter_station()
            self.progress.record('recovery_reentry_complete')

    def _initialize(self):
        logger.attr('DU control revision', self.progress.build[:12])
        from dev_tools.du_recovery_probe import probe_path
        self._recovery_probe_path = probe_path(ROOT, os.environ.get('DU_RECOVERY_PROBE'), self.config.config_name)
        self.active = self.progress.data.get('active')
        if self.active and self.active.get('station') == '储蓄间':
            # Each bounded task recovery may reset the position once again.
            self.active.pop('navigation_reentry_completed', None)
        if self.active and self.active.get('station') in ('事件', '异常', '奖励', '财富', '铸造'):
            if not self.active.get('event_completed'):
                self.active['node_done'] = False
        folder = ROOT / 'log/divergent_universe' / self.config.config_name
        self.op = DivergentOperator(self.device, self.config, folder if self.config.DivergentUniverse_SaveEvidence else None)
        self._run_deadline = time.monotonic() + max(1, self.config.DivergentUniverse_MaxMinutes) * 60
        self.apply_recovery_deadline()
        self._node_done = False
        self._entry_prepared = False
        self._native_event = None
        self._settlement_exit_wait = Timer(8)
        self._du_auto_off_confirm = Timer(1, count=2).start()
        self._launch_attempts = 0
        self.combat_state_reset()
        if not self.device.app_is_running():
            self.login_from_current()

    def login_from_current(self, restart=False):
        from tasks.login.login import Login
        timeout = Timer(300, count=3).start()
        def resumed():
            self.op.check()  # User stop and the recovery deadline also bound native login.
            self.op.image = self.device.image
            self.op._ocr_cache.clear()
            self.op.frame_cache.clear()
            if (self.world_visible() or self.adventure_intro_visible() or self.adventure_result_button()
                    or self.discard_confirmation_visible() or self.selection_kind()
                    or self.lobby_visible() or self.settlement_title()
                    or self.op.text('差分宇宙', (0.02, 0, 0.27, 0.065))
                    or self.op.text('差分宇宙', (0.58, 0.45, 0.96, 0.68))):
                return True
            if timeout.reached():
                raise RuntimeError('差分宇宙登录等待超时，准备按恢复次数重试')
            return False
        login = Login(self.config, device=self.device)
        login.login_expected_end = resumed
        self.progress.record('restart_begin' if restart else 'login_begin')
        if restart:
            login.app_stop()
        login.app_start()
        self.progress.record('restart_login_complete' if restart else 'login_complete')

    def header_text(self):
        if 'header' not in self.op.frame_cache:
            title = self.op.read_line((0.055, 0.046, 0.365, 0.096), snapshot=False).source
            known = [label for labels in self.CHOICES.values() for label in labels]
            known += list(self.REWARD_TITLES) + ['选择下一站', '选择下一个站点', '欢愉假面',
                      '事件', '常规演算', '周期演算', '模式选择', '星阶模式', '造物调试台']
            if not any(label in normalize(title) for label in known):
                title = self.op.read_line((0.16, 0.11, 0.85, 0.17), snapshot=False).source
            if not any(label in normalize(title) for label in known):
                title = ' '.join(box.source for box in self.op.read_region((0.015, 0, 0.97, 0.18), snapshot=False))
            self.op.frame_cache['header'] = title
        return self.op.frame_cache['header']

    def selection_kind(self):
        if 'selection' in self.op.frame_cache:
            return self.op.frame_cache['selection']
        result = None
        if not self.world_visible() and not self.is_combat_executing():
            title = normalize(self.header_text())
            if '选择下一站' in title or '选择下一个站点' in title:
                result = 'next_station'
            elif '欢愉假面' in title or '选择面具' in title or '选择一张面具' in title:
                result = 'mask'
            else:
                result = next((kind for kind, labels in self.CHOICES.items()
                               if any(label in title for label in labels)), None)
        self.op.frame_cache['selection'] = result
        return result

    def adventure_intro_visible(self):
        return bool(self.op.template('adventure_intro', (0.15, 0.30, 0.32, 0.60), confidence=0.90))

    def world_visible(self):
        if 'world' not in self.op.frame_cache:
            if self.adventure_intro_visible():
                self.op.frame_cache['world'] = False
                return False
            from tasks.base.assets.assets_base_page import MAP_EXIT_OE
            # Common walking frames need only small template checks, no OCR.
            menu = self.op.template('world_menu', (0.09, 0.04, 0.20, 0.15), confidence=0.90)
            world = bool(menu and (self.appear(MAP_EXIT_OE)
                         or self.op.template('divergent_universe_quit', (0, 0, 0.13, 0.18))))
            if not world:
                title = self.op.read_line((0.025, 0.005, 0.43, 0.055), snapshot=False).source
                world = bool(re.search(r'\d+\s*/\s*\d+.*位面', title))
            self.op.frame_cache['world'] = world
        return self.op.frame_cache['world']

    def lobby_visible(self):
        return bool(self.op.text('开始游戏', (0.70, 0.84, 0.88, 0.94)))

    def go_to_lobby(self):
        from tasks.base.page import page_guide
        op = self.op
        timeout = Timer(150, count=3).start()
        # An in-flight settlement normally loads for ~18 seconds. Preserve
        # its detection window when a worker resumes during that transition.
        unknown = Timer(45 if self.active and self.active.get('pending_settlement') else 8, count=3).start()
        entering_du = Timer(10, count=3)
        initial_saved = False
        while not timeout.reached():
            op.snapshot()
            if op.image.mean() < 3:
                continue
            if not initial_saved:
                op.save('entry_initial')
                initial_saved = True
            if self.world_visible() or self.selection_kind():
                logger.info('DU resume current exploration')
                return True
            if self.active and (self.adventure_intro_visible() or self.forge_panel_visible() or self.adventure_result_button()
                                or self.discard_confirmation_visible()):
                return True
            if self.is_combat_executing():
                if self.progress.data.get('active'):
                    return True
                # Let native combat finish before returning to the common entry.
                super().combat_execute()
                continue
            if self.lobby_visible():
                if self.config.DivergentUniverse_StopAtWeeklyLimit:
                    points = self.weekly_points()
                    if points and points[0] >= points[1]:
                        return False
                return True
            header = self.header_text()
            if '事件' in header and op.text('差分宇宙', (0.02, 0, 0.26, 0.065)):
                return True
            if self.settlement_title():
                return True
            if op.text(('结束并结算', '退出并结算', '确定要结束进程'), (0.15, 0.2, 1, 1)):
                return True
            if op.text(('周期演算', '常规演算'), (0, 0, 1, 0.85)):
                return True
            if op.text('确认退出游戏', (0.25, 0.3, 0.8, 0.65)):
                op.click_text('取消', (0.25, 0.4, 0.55, 0.7), exact=True)
                continue
            if ('积分奖励' in header or any(word in header for word in
                    ('稳态数组', '拟合等级', '模因拓扑', '差分图鉴', '演算记录'))):
                op.back()
                continue
            # The world HUD can linger after opening DU. Check the expected
            # DU pages above on every screenshot before falling back to the
            # native guide route; do not route away during this transition.
            if entering_du.started() and not entering_du.reached():
                continue
            if self.is_in_main():
                interact = op.text('差分宇宙', (0.5, 0.25, 1, 0.82))
                if interact:
                    if op.click_box(interact):
                        entering_du.reset()
                else:
                    self.dungeon_tab_goto(KEYWORDS_DUNGEON_TAB.Simulated_Universe)
                unknown.reset()
                continue
            if self.ui_page_appear(page_guide):
                # The universe tab remembers its last selected activity.
                # A visible DU label in the sidebar does not select its row.
                self.dungeon_tab_goto(KEYWORDS_DUNGEON_TAB.Simulated_Universe)
                self.dungeon_nav_goto(KEYWORDS_DUNGEON_NAV.Divergent_Universe)
                op.snapshot()
                if op.click_text(('前往参与', '前往'), (0.5, 0.65, 1, 1), interval=3):
                    entering_du.reset()
                unknown.reset()
                continue
            if op.text('差分宇宙', (0.1, 0.28, 0.82, 0.73)):
                if not op.click_text(('前往参与', '前往'), (0.5, 0.65, 1, 1)):
                    if op.click_text('差分宇宙', (0.1, 0.28, 0.82, 0.73)):
                        entering_du.reset()
                else:
                    entering_du.reset()
                continue
            if self.handle_misc() or self.ui_additional():
                continue
            if self.is_in_login_confirm() or op.text(
                    ('正在检查数据', '正在载入', '正在加载'), (0, 0.70, 1, 1)):
                self.login_from_current()
                timeout.reset()
                unknown.reset()
                continue
            if self.return_to_main():
                unknown.reset()
                continue
            if unknown.reached():
                # No usable page/control: the native login route returns us
                # to the common main page without abandoning a saved DU run.
                op.save('entry_unknown')
                self.login_from_current(restart=True)
                timeout.reset()
                unknown.reset()
        raise RuntimeError('未能从当前页面回到差分宇宙入口')

    def return_to_main(self):
        from tasks.base.page import Page, page_main
        # SRC owns the page graph and each known page's return button.
        for page in Page.iter_pages():
            if page.check_button is not None and self.ui_page_appear(page):
                self.ui_goto(page_main)
                return True
        return self.op.back()

    def start_or_resume(self):
        op = self.op
        from tasks.divergent_universe.entry import EntrySettings
        entry = EntrySettings(self)
        launch = entry.launch_button()
        retained = launch and '继续进度' in normalize(launch.source)
        if retained and self.handle_expired_checkpoint():
            return True
        if (launch and (self.active.get('node') or self.active.get('pending_settlement'))
                and not retained):
            if self.active.get('stop_requested') and not self.active.get('settlement_observed'):
                raise RequestHumanTakeover('请求结束的探索已无可继续进度，但未观察到真实结算；保留记录并停止')
            # The game offers a fresh start, so the old local checkpoint is
            # no longer resumable. Keep it separately, without a win/loss.
            self.progress.supersede('Game entry offers a new exploration instead of retained progress')
            self.active = self.progress.begin(self.config.DivergentUniverse_Mode,
                                              self.config.DivergentUniverse_Calculation)
            self._entry_prepared = False
            self._node_done = False
            logger.info('DU stale checkpoint retained as unconfirmed; apply configured calculation')
            return True
        mode_selection = '模式选择' in self.header_text()
        if self.active.get('pending_settlement') and not mode_selection:
            return False  # Continue the requested exit, not a new exploration.
        if (not self._entry_prepared and launch) or mode_selection:
            entry.prepare(self.active.get('calculation', 'periodic'))
            self._entry_prepared = True
            return True
        if launch and op.template('download_empty', (0.43, 0.78, 0.72, 0.96), confidence=0.93):
            self.prepare_downloads()
            return True
        if self.lobby_visible():
            op.click_text('开始游戏', (0.70, 0.84, 0.88, 0.94))
            return True
        if launch:
            op.click_box(launch)
            return True
        return False

    def handle_expired_checkpoint(self):
        op = self.op
        if not (op.text('已过期', (0.46, 0.77, 0.62, 0.86), exact=True)
                and op.text('结束并结算', (0.46, 0.83, 0.72, 0.94), exact=True)):
            return False
        identity = f'{self.config.config_name}:{self.active["id"]}'
        if os.environ.get('DU_APPROVED_EXPIRED_RUN') != identity:
            reason = '周期进度已过期；保留原局，等待确认是否通过游戏结束并结算'
            self.progress.data['error'] = reason
            self.progress.save('error')
            self.progress.record('expired_checkpoint', requires_user_decision=True)
            raise RequestHumanTakeover(reason)
        # Explicit approval is scoped to this profile and this old run only.
        # quit_run still waits for the game's actual confirmation/result pages.
        self.progress.record('expired_settlement_requested')
        self.active['stop_requested'] = True
        self.quit_run()
        return True

    def prepare_downloads(self):
        op = self.op
        from tasks.abyss.prep import AbyssPrep
        from tasks.abyss.assets.assets_abyss_prep import TAB_PRESET_CHECK, TAB_PRESET_CLICK
        picker = AbyssPrep(config=self.config, device=self.device)
        selected = False
        timeout = Timer(90, count=3).start()
        while not timeout.reached():
            op.snapshot()
            launch = op.text(('启动「差分宇宙」', '启动差分宇宙', '进入星阶模式'), (0.3, 0.65, 1, 1))
            empty = op.template('download_empty', (0.43, 0.78, 0.72, 0.96), confidence=0.93)
            panel = op.text('预设编队', (0.02, 0.03, 0.4, 0.18))
            if launch and not empty:
                return
            if launch and not panel:
                op.click_box(empty)
                continue
            if not selected:
                if picker.appear(TAB_PRESET_CHECK):
                    picker._abyss_click_preset(self.config.DivergentUniverse_TeamPreset)
                    selected = True
                    continue
                if picker.appear(TAB_PRESET_CLICK):
                    picker.appear_then_click(TAB_PRESET_CLICK, interval=1)
                    continue
                if op.click_text(('当前队伍', '当前编队'), (0, 0, 1, 0.45)):
                    selected = True
                    continue
                if op.click_text(('预设编队', '队伍预设'), (0, 0, 0.6, 0.35)):
                    continue
            if selected:
                op.click_text(('下载', '确认', '应用'), (0.45, 0.65, 1, 1), exact=True)
        op.save('download_picker_unknown')
        raise RuntimeError('角色下载页面未能确认已下载队伍')

    def play_run(self):
        op = self.op
        idle_since = time.monotonic()
        self._periodic_selected = False
        self._node_done = self.active.get('node_done', False)
        while True:
            op.snapshot()
            if self.world_visible():
                if self.collapse_status_panel():
                    continue
                if self._native_event is not None:
                    self._native_event.event_title = None
                if self.active.pop('event_pending', False):
                    self.active['event_completed'] = True
                    self.active['node_done'] = True
                    self._node_done = True
                    self.progress.save('event_finished')
                self.update_station_header()
                if self._recovery_probe_path is not None:
                    from dev_tools.du_recovery_probe import check_recovery_probe
                    check_recovery_probe(self)
                if self.active['station'] == '冒险':
                    self.request_adventure_exit(self.active.get('adventure_kind', ''))
                if self.active.get('stop_requested'):
                    self.quit_run()
                elif self.active['mode'] == 'first_station' and (self.active['battles'] > 0 or self._node_done):
                    # Technique rewards count as the first encounter too. A
                    # second enemy must not erase that completed encounter and
                    # send farming mode through a full-room exit search.
                    logger.info('DU first encounter completed; settle first-station rewards')
                    self.quit_run()
                else:
                    self.check_remaining_enemy()
                    if self.active['station'] == '冒险' and self._node_done:
                        self.check_adventure_pending()
                    if self.active['station'] == '冒险' and not self._node_done:
                        self.adventure_station()
                    elif not self._node_done and any(t in self.active['station'] for t in ('战斗', '精英', '首领', '转化', '储蓄间')):
                        self.fight_station()
                    else:
                        self.navigate_station()
                idle_since = time.monotonic()
                continue
            kind = 'discard' if self.discard_confirmation_visible() else self.selection_kind()
            if kind:
                self.handle_settlement()  # Clear an unconfirmed stale exit on a real choice page.
                self.progress.save('selecting_' + kind)
                self.handle_choice(kind)
                idle_since = time.monotonic()
                continue
            header = self.header_text()
            if '乐园漫记' in header and self.lobby_visible():
                if self.active.get('pending_settlement') and self.active.get('settlement_observed'):
                    return self.active.get('result', 'farm')
                op.click_text('开始游戏', (0.70, 0.84, 0.88, 0.94))
                idle_since = time.monotonic()
                continue
            if (not self.active.get('node') and not self.active.get('pending_settlement')
                    and any(title in header for title in ('模式选择', '周期演算', '常规演算', '星阶模式'))
                    and self.start_or_resume()):
                idle_since = time.monotonic()
                continue
            # Once the native event page is identified, avoid repeatedly OCRing
            # settlement dialogs and launch controls before every dialogue tap.
            if (any(word in header for word in ('事件',) + self.REWARD_TITLES)
                    and self.handle_misc()):
                idle_since = time.monotonic()
                continue
            result = self.handle_settlement()
            if isinstance(result, str):
                return result
            if result:
                idle_since = time.monotonic()
                continue
            if (self.active['mode'] == 'first_station' or self.active.get('stop_requested')) and op.text(
                    ('结束并结算', '退出并结算'), (0.05, 0.2, 1, 1)):
                self.quit_run()
                continue
            if self.is_combat_executing():
                self.combat_execute()
                idle_since = time.monotonic()
                continue
            if self.start_or_resume():
                idle_since = time.monotonic()
                continue
            if self.handle_misc():
                idle_since = time.monotonic()
                continue
            if time.monotonic() - idle_since > 45:
                op.save('unknown_screen')
                self.go_to_lobby()
                idle_since = time.monotonic()

    def handle_choice(self, kind):
        op = self.op
        if (not self._node_done and self.active.get('node')
                and any(t in self.active.get('station', '') for t in ('战斗', '精英', '首领', '转化'))
                and op.text('你战胜了', (0.32, 0.115, 0.70, 0.17))):
            # A map technique can show a reward before fight_station sees it,
            # including after a worker resumes halfway through the rewards.
            self._node_done = self.active['node_done'] = True
            self.progress.save('station_rewards')
        if kind == 'next_station':
            self.choose_station()
            return
        if kind == 'station_card':
            # This screen uses small draw/discard tiles, not the tall blessing
            # cards. SRA confirms the selected tile; do not await a card title
            # in the middle of the screen where there is no card.
            def station_card_ready():
                button = op.text('确定', (0.64, 0.78, 1, 0.96), exact=True)
                return button and self.confirm_enabled(button)
            op.wait_until(station_card_ready, action=lambda: op.click_text(
                ('战斗', '精英', '首领', '商店', '事件', '奖励', '异常', '空白', '休整', '财富'),
                (0.03, 0.24, 0.60, 0.51)), name='站点卡选择')
            self.confirm_selection(kind)
            self.device.click_record_clear()
            self.active['selections'] += 1
            self.progress.save()
            return
        if kind == 'discard' and self.discard_confirmation_visible():
            # A restarted worker can resume on the modal itself. Do not read
            # or click the blurred cards behind it.
            self.confirm_selection(kind)
        elif kind == 'mask':
            page_changed = object()
            def mask_ready():
                current = self.selection_kind()
                if (current and current != 'mask') or self.world_visible() or self.is_combat_executing():
                    return page_changed
                return op.text('确定', (0.6, 0.8, 1, 1), exact=True)
            def choose_mask():
                # A mask information/obtained overlay has a close footer,
                # not another confirm button. Close only that observed page
                # and re-check: a preview may return to the mask chooser.
                close = self.reward_close_button()
                if close:
                    clicked = op.click_box(close)
                    if clicked:
                        logger.info('DU mask overlay closed; recheck the actual next page')
                    return clicked
                return op.click_text('面具', (0.03, 0.65, 0.5, 0.95))
            ready = op.wait_until(mask_ready, action=choose_mask, name='面具确认页')
            if ready is page_changed:
                return
            self.confirm_selection(kind)
        else:
            priority_text = (self.config.DivergentUniverse_StationPriority if kind == 'area'
                             else self.config.DivergentUniverse_ChoicePriority)
            priorities = tuple(p.strip() for p in (priority_text or '').split('>') if p.strip())
            previous = None
            page_changed = object()
            def choices_ready():
                nonlocal previous
                if self.selection_kind() != kind:
                    return page_changed
                choices = read_choices(op, kind)
                signature = tuple((normalize(c.title), c.uncollected, c.recommended, c.rarity) for c in choices)
                ready = bool(choices and any(c.title or c.uncollected for c in choices) and signature == previous)
                previous = signature
                return choices if ready else False
            # Require consistent card contents across frames, not an assumed
            # animation duration. New badges can appear after the card title.
            detection_started = time.monotonic()
            choices_ready()  # The caller already captured and classified the first real frame.
            choices = op.wait_until(choices_ready, name=kind + '卡片内容')
            if choices is page_changed:
                return  # The reward animation has already advanced to another page.
            op.save('choice_' + kind)
            if kind == 'area':
                # The user prefers another route over adventure rooms. Keep
                # collection/recommendation/rarity order among viable cards.
                choices = [c for c in choices if '冒险' not in c.title] or choices
            choice = choose(choices, self.config.DivergentUniverse_PreferUncollected, priorities, discard=kind == 'discard')
            logger.info(f'DU choose {kind}: uncollected={choice.uncollected}, recommended={choice.recommended}, rarity={choice.rarity}, {choice.title}, detection={time.monotonic() - detection_started:.3f}s')
            op.click_point(choice.box.center[0] / 1280, (choice.box.top + choice.box.height * 0.3) / 720,
                           tag='DU_CHOICE_' + kind)
            self.confirm_selection(kind, choice=choice)
        self.active['selections'] += 1
        self.device.click_record_clear()
        self.progress.save()

    def selection_names(self, region):
        labels = self.op.read_region(region, snapshot=False)
        if not labels:
            return ()
        typical_height = np.median([box.height for box in labels])
        names = []
        for box in sorted(labels, key=lambda box: box.center[0]):
            title = normalize(box.source)
            # OCR order changes with a card's highlight, and the lower edge
            # can briefly contain a small numeric annotation. Neither means
            # the card set changed. Keep numeric titles at normal title size.
            if not title or (re.fullmatch(r'[0-9.+/xX-]+', title) and box.height < typical_height * 0.6):
                continue
            names.append(title)
        return tuple(names)

    def confirm_selection(self, kind, choice=None):
        op = self.op
        names_region = ((0.08, 0.49, 0.96, 0.55) if kind in ('miracle', 'area') else
                        (0.07, 0.66, 0.95, 0.79) if kind == 'next_station' else
                        (0.08, 0.42, 0.96, 0.50))
        names_before = (None if kind == 'discard' and self.discard_confirmation_visible()
                        else self.selection_names(names_region))
        confirmed = False
        select_attempts = 1
        confirm_attempts = 0
        changed_frames = 0
        station_warning_seen = False
        station_choice_frames = 0
        station_mismatch = None
        station_mismatch_frames = 0
        timeout = Timer(45, count=3).start()
        while not timeout.reached():
            op.snapshot()
            if kind == 'mask' and confirmed:
                close = self.reward_close_button()
                if close:
                    if op.click_box(close):
                        logger.info('DU confirmed mask overlay closed; await the next page')
                    continue
            if kind == 'discard' and self.discard_confirmation_visible():
                confirmed = bool(self.handle_popup_confirm(interval=1)) or confirmed
                continue
            if kind == 'next_station' and self.handle_station_warning():
                if not station_warning_seen:
                    confirm_attempts = 0
                station_warning_seen = True
                continue
            current = self.selection_kind()
            if current != kind:
                if current or self.world_visible() or self.is_combat_executing() or self.lobby_visible():
                    return
                if self.handle_misc():
                    if kind != 'next_station':
                        return  # Obtained-reward page confirms this selection finished.
                # A blank/loading frame is not confirmation of a transition.
                continue
            names = self.selection_names(names_region)
            if kind == 'next_station' and choice is not None and not confirmed:
                # Reroll's counter can update before the old cards disappear.
                # Revalidate the intended card on the current frame before
                # confirming; stale coordinates can select adventure instead.
                labels = [box for box in op.read_region(names_region, snapshot=False)
                          if any(word in box.source for word in self.STATION_TYPES)
                          and '空白处' not in normalize(box.source)]
                nearby = min(labels, key=lambda box: abs(box.center[0] - choice.box.center[0]), default=None)
                if nearby is not None and abs(nearby.center[0] - choice.box.center[0]) >= 90:
                    nearby = None
                same = nearby is not None and normalize(nearby.source) == normalize(choice.title)
                button = self.choice_confirm_button()
                enabled = button and self.confirm_enabled(button)
                if not same and enabled:
                    # Selected cards enlarge. If the row detector misses that
                    # title, inspect just its local label band before rejecting
                    # a valid selection, preserving the original coordinates.
                    cx = choice.box.center[0]
                    local = op.read_region((max(0, cx - 100) / 1280, 0.68,
                                            min(1280, cx + 100) / 1280, 0.84), snapshot=False)
                    same = any(normalize(box.source) == normalize(choice.title)
                               and abs(box.center[0] - cx) < 90 for box in local)
                # Selection enlarges the card and can briefly hide its title.
                # An enabled selection with a missing label is not evidence
                # that reroll replaced it. Wait for its actual label to return.
                mismatch = ((normalize(nearby.source) if nearby else 'absent',
                             tuple(sorted(normalize(box.source) for box in labels)))
                            if labels and not same and (nearby is not None or not enabled) else None)
                station_mismatch_frames = (station_mismatch_frames + 1
                                           if mismatch is not None and mismatch == station_mismatch
                                           else 1 if mismatch is not None else 0)
                station_mismatch = mismatch
                if station_mismatch_frames >= 2:
                    logger.warning(f'DU station cards changed before confirmation: expected={choice.title}, current={names}; select again')
                    self.progress.record('station_choice_changed', expected=choice.title, current=names)
                    return False
                station_choice_frames = station_choice_frames + 1 if same else 0
                if station_choice_frames < 2:
                    continue
            if names_before is None and confirmed:
                # The old names were obscured. Await a real page change or a
                # stable unselected next set; don't click the old footer again.
                button = self.choice_confirm_button()
                ready = bool(names and button and not self.confirm_enabled(button))
                changed_frames = changed_frames + 1 if ready else 0
                if changed_frames >= 2:
                    return
                continue
            changed_frames = changed_frames + 1 if confirmed and names and names != names_before else 0
            if changed_frames >= 2 and kind != 'next_station':
                if kind != 'mask':
                    return  # Another choice set of the same type has arrived.
                # A mask obtained/info page can change the title without
                # presenting another choice. Require a real unselected
                # chooser before treating it as a new set of masks.
                button = self.choice_confirm_button()
                if button and not self.confirm_enabled(button) and op.text(
                        '面具', (0.03, 0.65, 0.5, 0.95)):
                    return
            # Keep the selected station after its warning. If the game still
            # shows the same enabled confirm, retry it within the same budget;
            # never return to the outer loop and select another card here.
            if choice is not None:
                # Retry the selected card only while confirmation remains grey.
                button = self.choice_confirm_button()
                enabled = button and self.confirm_enabled(button)
                if confirmed and names and names != names_before and button and not enabled:
                    return  # New named cards plus a disabled confirm identify the next set.
                if not enabled:
                    if not confirmed and select_attempts < 3:
                        if op.click_point(choice.box.center[0] / 1280,
                                          (choice.box.top + choice.box.height * 0.3) / 720, tag='DU_CHOICE_' + kind):
                            select_attempts += 1
                    continue
            if confirm_attempts < 3 and op.click_box(self.choice_confirm_button()):
                confirmed = True
                confirm_attempts += 1
        raise RuntimeError(f'差分宇宙{kind}选择未确认')

    def discard_confirmation_visible(self):
        from tasks.base.assets.assets_base_popup import POPUP_TITLE_TIP
        return bool(self.appear(POPUP_TITLE_TIP) and self.op.text(
            ('确认丢弃祝福', '确认丢弃奇物'), (0.30, 0.44, 0.78, 0.54)))

    def choice_confirm_button(self):
        labels = ('确定', '确认', '确认选择', '选择', '丢弃', '确认丢弃', '摧毁', '推毁')
        # Normal cards share this footer. Keep the broader fallback for
        # alternate layouts, without rereading the entire lower third first.
        return (self.op.text(labels, (0.73, 0.84, 0.97, 0.95), exact=True)
                or self.op.text(labels, (0.05, 0.83, 0.97, 0.96), exact=True))

    def confirm_enabled(self, button):
        # Enabled DU confirmations have a light fill; disabled ones are dark.
        x, y = button.center
        region = self.op.image[max(0,y-12):y+13, max(0,x-100):max(1,x-55)]
        return region.size and float(cv2.cvtColor(region, cv2.COLOR_RGB2GRAY).mean()) > 130

    def choose_station(self):
        op = self.op
        order = [t.strip() for t in self.config.DivergentUniverse_StationPriority.split('>') if t.strip()]
        station_types = self.STATION_TYPES
        def candidates_ready():
            if self.selection_kind() == 'next_station':
                return [box for box in op.match(station_types, (0.07, 0.65, 0.95, 0.83))
                        if '空白处' not in normalize(box.source)]
            return False
        def refresh_count():
            text = op.read_line((0.31, 0.87, 0.42, 0.92), snapshot=False).source
            count = re.search(r'(\d+)\s*$', text)
            return int(count[1]) if count else None
        candidates = op.wait_until(candidates_ready, name='站点候选')
        for attempt in range(4):
            safe = [box for box in candidates if '冒险' not in box.source]
            target = next((box for word in order for box in safe if word in box.source), None)
            if target or attempt == 3:
                break
            refresh = op.text(('刷新', '重掷', '重抽'), (0.1, 0.65, 0.95, 1))
            remaining = refresh_count()
            if not refresh or remaining is None or remaining <= 0:
                break
            reroll_retry = Timer(2, count=2)
            reroll_attempts = 0
            previous_reroll = None
            def rerolled():
                nonlocal previous_reroll
                items = candidates_ready()
                current = refresh_count()
                key = ((current, tuple(sorted((normalize(box.source), round(box.center[0] / 8)) for box in items)))
                       if items and current is not None and current < remaining else None)
                ready = key is not None and key == previous_reroll
                previous_reroll = key
                return items if ready else False
            def reroll_action():
                nonlocal reroll_attempts
                if self.handle_popup_confirm():
                    reroll_retry.reset()
                elif (reroll_attempts < 3 and reroll_retry.reached()
                      and refresh_count() == remaining):
                    if op.click_text(('刷新', '重掷', '重抽'), (0.1, 0.65, 0.95, 1), interval=2):
                        reroll_attempts += 1
                        reroll_retry.reset()
            try:
                candidates = op.wait_until(rerolled, action=reroll_action, name='站点刷新')
            except RuntimeError as error:
                # Reroll is optional. If the game rejected it but still offers
                # valid stations, proceed with those instead of restarting.
                available = candidates_ready()
                if str(error).startswith('站点刷新超时') and available:
                    logger.warning('DU reroll not applied; continue with visible stations')
                    candidates = available
                    break
                raise
        # Refresh can fail or exhaust its budget. Even the fallback must
        # prefer any non-adventure station over the first displayed card.
        safe = [box for box in candidates if '冒险' not in box.source]
        target = next((box for word in order for box in safe if word in box.source), None)
        target = target or (safe or candidates)[0]
        if not safe:
            # Recognition alone cannot establish that no alternative exists.
            # Preserve this decision frame/labels for any future missing type
            # instead of calling the adventure choice unavoidably forced.
            folder = ROOT / 'log/divergent_universe' / self.config.config_name
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'adventure_candidates_{time.time_ns()}.jpg'
            saved = cv2.imwrite(str(path), cv2.cvtColor(op.image, cv2.COLOR_RGB2BGR),
                                [cv2.IMWRITE_JPEG_QUALITY, 90])
            labels = [box.source for box in op.read_region((0.07, 0.65, 0.95, 0.83), snapshot=False)]
            self.progress.record('adventure_only_recognized', candidates=[box.source for box in candidates],
                                 labels=labels, screenshot=str(path.relative_to(ROOT)) if saved else None)
            logger.warning(f'DU only adventure station recognized; candidate labels={labels}, frame_saved={saved}')
        op.click_box(target)
        from tasks.divergent_universe.selection import Choice
        if self.confirm_selection('next_station', choice=Choice(target, target.source)) is False:
            return  # The cards changed; keep this room until a current choice is confirmed.
        self.active['station'] = next((word for word in station_types if word in target.source), target.source)
        self._node_done = False
        self.active['node_done'] = False
        self.active.pop('navigation_reentry', None)
        self.active.pop('navigation_reentry_completed', None)
        self.progress.save('next_station')

    def move(self, direction, seconds=0.5, run=True, interaction_text=None):
        self.op.check()
        # The timer bounds a touch gesture, not a wait for the next page.
        # Screenshots continue during movement and can stop the gesture early.
        gesture = Timer(seconds)
        with JoystickContact(self) as stick:
            stick.set(direction, run=run)
            gesture.reset()
            while not gesture.reached():
                self.op.snapshot()
                if not self.world_visible():
                    break
                if (interaction_text is None or interaction_text) and self.interaction_visible():
                    # None keeps native arrival behavior; an empty tuple lets
                    # a detour leave an unrelated interactable's range.
                    if interaction_text is None or (interaction_text and self.op.text(
                            interaction_text, (0.58, 0.48, 0.92, 0.70))):
                        break

    def interact_with_label(self, label, interval=1):
        # Multiple nearby objects can occupy different interaction rows.
        # Restrict the native icon matcher to the row of the observed target.
        from tasks.combat.assets.assets_combat_interact import DUNGEON_COMBAT_INTERACT
        buttons = (self.INTERACT_BUTTON, DUNGEON_COMBAT_INTERACT)
        # Wrapper variants have different original search rectangles. Saving
        # only wrapper.search would overwrite every variant with one rectangle.
        previous_search = [(asset, asset.search) for button in buttons for asset in button.iter_buttons()]
        search = (max(0, label.left - 90), max(0, label.top - 18),
                  min(1280, label.left + 60), min(720, label.top + label.height + 18))
        for button in buttons:
            button.load_search(search)
        try:
            return self.handle_combat_interact(interval=interval)
        finally:
            for asset, previous in previous_search:
                asset.load_search(previous)

    def collapse_status_panel(self):
        button = self.op.template('status_collapse', (0.24, 0.05, 0.31, 0.14), confidence=0.93)
        return self.op.click_box(button, interval=2) if button else False

    def interaction_visible(self):
        from tasks.combat.assets.assets_combat_interact import DUNGEON_COMBAT_INTERACT
        if self.appear(DU_INTERACT):
            return True
        if self.loot_interaction():
            return True
        if (getattr(self, 'active', None) or {}).get('station') in ('事件', '奖励', '异常', '财富', '铸造', '储蓄间'):
            if self.appear(DUNGEON_COMBAT_INTERACT):
                return True
        # Shops contain NPC conversations (for example Ruan Mei). Their bubble
        # must not cancel every movement gesture toward the actual exit.
        return bool(self.appear(DUNGEON_COMBAT_INTERACT) and self.op.text(
            ('随意门', '前往下一区域', '战利品', '事件', '奖励'), (0.58, 0.48, 0.92, 0.70)))

    def handle_combat_interact(self, interval=2):
        from tasks.combat.assets.assets_combat_interact import DUNGEON_COMBAT_INTERACT
        if super().handle_combat_interact(interval=interval):
            return True
        if self.appear_then_click(DUNGEON_COMBAT_INTERACT, interval=interval):
            return True
        return self.op.click_box(self.loot_interaction(), interval=interval)

    def loot_interaction(self):
        # DU treasure prompts have a chest icon, not the native NPC bubble or
        # portal arrow. Match their visible label only on the walking screen.
        if (getattr(self, 'active', None) or {}).get('station') in ('财富', '奖励') and self.world_visible():
            return self.op.text('战利品', (0.60, 0.52, 0.85, 0.65))
        if (getattr(self, 'active', None) or {}).get('station') == '储蓄间' and self.world_visible():
            return self.op.text(('储蓄', '扑满'), (0.60, 0.52, 0.85, 0.65))
        return None

    def try_map_technique(self):
        # DU can show eight points, beyond the native five-diamond counter.
        # Read only the HUD number and the displayed cost, then use SRC's E.
        points = re.search(r'\d+', self.op.read_line(
            (838 / 1280, 580 / 720, 878 / 1280, 614 / 720), snapshot=False).source)
        if points is None or int(points[0]) == 0:
            logger.info('DU technique points empty or unreadable; continue normal approach')
            return False
        cost = re.search(r'\d+', self.op.read_line(
            (922 / 1280, 638 / 720, 950 / 1280, 661 / 720), snapshot=False).source)
        if cost is None or not 1 <= int(cost[0]) <= int(points[0]) <= 8:
            logger.info('DU technique cost not available; continue normal approach')
            return False
        return self.handle_map_E()

    def fight_station(self):
        op = self.op
        self.progress.save('approaching_combat')
        if self.config.DivergentUniverse_UseTechnique:
            self.try_map_technique()
        attempt = 0
        timeout = Timer(60, count=3).start()
        while attempt < 8 and not timeout.reached():
            op.snapshot()
            if self.is_combat_executing():
                self.combat_execute()
                return
            if self.selection_kind():
                # DU can defeat an enemy directly on the map and grant its
                # rewards without ever showing the turn-based combat UI.
                self._node_done = True
                self.active['node_done'] = True
                self.progress.save('station_rewards')
                return
            if op.text('随意门', (0.58, 0.48, 0.92, 0.70)):
                self._node_done = True
                self.active['node_done'] = True
                self.progress.save('station_exit_available')
                return
            if not self.world_visible():
                if self.handle_misc():
                    return
                continue
            enemy_visible = self.enemy_visible()
            if attempt >= 4 and not enemy_visible and self.find_door():
                # On reconnect the game may have saved the cleared room before
                # our local reward checkpoint. First approach and attack: the
                # enemy's label can appear late in a newly loaded boss room.
                self.navigate_station()
                return
            if attempt == 4:
                if enemy_visible:
                    # A DU chest can block the direct path to a visible enemy.
                    # Keep the camera on that enemy and sidestep using SRC.
                    logger.info('DU enemy still visible after approach; sidestep the obstruction')
                    self.move(-90, 0.8)
                else:
                    self.rotation_swipe(-40, box=self.ROTATION_BOX)
            self.move(0, 0.65 if attempt == 0 else 0.35)
            if self.world_visible():
                self.handle_map_A()
            attempt += 1
        # Losing the enemy's header while walking does not prove the room is
        # clear. Search the other views for its actual target cue first.
        self.seek_enemy()

    def find_enemy_target(self):
        # The enemy nameplate stays visible when its target is behind us.
        # Locate DU's red target cue inside the walking view instead.
        candidates = []
        for name in ('enemy_target_front', 'enemy_target_side', 'enemy_target_ring', 'enemy_target_ring_side',
                     'enemy_alert'):
            if name == 'enemy_alert' and not self.enemy_visible():
                continue
            boxes = self.op.template_matches(str(self.op.templates / f'{name}.png'),
                                             (0.03, 0.20, 0.82, 0.65), confidence=0.80,
                                             scales=(0.75, 0.85, 1, 1.15, 1.3))
            for box in boxes:
                hsv = cv2.cvtColor(self.op.image[box.top:box.top + box.height,
                                                 box.left:box.left + box.width], cv2.COLOR_RGB2HSV)
                if name == 'enemy_alert':
                    # Some aggroed enemies show this orange lightning cue
                    # above their body instead of the red targeting ring.
                    # Require the live enemy header as well as shape/color.
                    color = ((hsv[:, :, 0] >= 4) & (hsv[:, :, 0] <= 28)
                             & (hsv[:, :, 1] > 130) & (hsv[:, :, 2] > 130))
                else:
                    color = (((hsv[:, :, 0] < 15) | (hsv[:, :, 0] > 165))
                             & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 100))
                if np.mean(color) >= 0.2:
                    candidates.append(box)
        return max(candidates, key=lambda box: box.score) if candidates else None

    def is_in_main(self, interval=0):
        if getattr(self, '_du_native_combat_retry', False):
            # Native poor-try captures device.image directly. Its usual main
            # HUD predicate does not match DU, and the adapter's last frame
            # must not authorize an attack on a newly opened reward page.
            self.op.image = self.device.image
            self.op._ocr_cache.clear()
            self.op.frame_cache.clear()
            return self.world_visible()
        return super().is_in_main(interval=interval)

    def combat_poor_try(self, skip_first_screenshot=True):
        previous = getattr(self, '_du_native_combat_retry', False)
        self._du_native_combat_retry = True
        try:
            logger.info('DU stationary combat retry: native controls with current DU map detection')
            # Keep SRC's stationary attack cadence, attempt limit and combat
            # handling. Only its walking-page predicate needs adapting.
            return super().combat_poor_try(skip_first_screenshot=skip_first_screenshot)
        finally:
            self._du_native_combat_retry = previous

    def seek_enemy(self):
        # Keep movement, camera and attack in native SRC. Only adapt the DU
        # target cue; the native SU aim detector does not match this reticle.
        self.progress.save('seeking_enemy')
        self.device.click_record_clear()
        # The target may already be within attack range after approach.
        # Let SRC perform its stationary, throttled combat retry before
        # rotating away; continuous movement can interrupt a map attack.
        if self.combat_poor_try():
            return
        timeout = Timer(45, count=3).start()
        turns = moves = 0
        while not timeout.reached() and turns < 9 and moves < 8:
            self.op.snapshot()
            if self.is_combat_executing():
                self.combat_execute()
                return
            if self.selection_kind():
                self._node_done = self.active['node_done'] = True
                self.progress.save('station_rewards')
                return
            if not self.world_visible():
                if self.handle_misc():
                    return
                continue
            target = self.find_enemy_target()
            if target:
                logger.info(f'DU enemy target: {target.center}, score={target.score:.3f}')
                self.move(RogueExit.screen2direction(target.center), 0.5)
                if self.world_visible():
                    self.handle_map_A()
                moves += 1
            else:
                self.rotation_swipe(-40, box=self.ROTATION_BOX)
                turns += 1
        if self.enemy_visible():
            raise RuntimeError('敌人尚在，但定向接近未能入战；保留进度恢复房间入口')
        self.navigate_station()

    def request_adventure_exit(self, kind):
        # Called only for a recognized adventure station or its help page.
        # The user wants every adventure skipped, including unknown subtypes.
        # Detection alone is never a completed exploration.
        kind = normalize(kind) or '冒险'
        if not self.active.get('stop_requested'):
            self.active.update(stop_requested=True, exit_reason='skip_adventure:' + normalize(kind))
            self.progress.save('adventure_exit_requested')
            self.progress.record('adventure_exit_requested', reason=self.active['exit_reason'])
            logger.info(f'DU skip adventure via normal settlement: {kind}')
        return True

    def adventure_station(self):
        self.request_adventure_exit(self.active.get('adventure_kind', ''))
        self.quit_run()

    def combat_expected_end(self):
        # The generic SRC combat loop owns screenshots and auto/speed controls;
        # only its DU-specific end screens belong in this adapter.
        # Native damage-change detection renews the stuck timer while a fight
        # progresses. A fixed battle deadline would restart long boss fights.
        self.op.check()
        self.op.image = self.device.image
        self.op._ocr_cache.clear()
        self.op.frame_cache.clear()
        return bool(self.selection_kind() or self.world_visible()
                    or self.op.text(('获得祝福', '获得奇物', '方程展开', '已修复以下奇物'), (0, 0, 1, 0.24))
                    # Conversion rooms end on their own reward overlay. The
                    # main loop then closes it through the observed prompt.
                    or self.op.text('转化结束', (0.3, 0.2, 0.72, 0.37), exact=True)
                    or self.settlement_title())

    def handle_combat_state(self, auto=True, speed_2x=True):
        # Native combat may optimistically cache auto=True while the button is
        # hidden by an animation. Revalidate a visibly disabled button across
        # frames, then let native combat perform its normal toggle/retry.
        if auto and self._combat_auto_checked and self.is_combat_executing():
            if self.is_combat_auto():
                self._du_auto_off_confirm.reset()
            elif self._du_auto_off_confirm.reached():
                logger.info('DU auto combat is visibly off; recheck native controls')
                self._combat_auto_checked = False
                self._du_auto_off_confirm.reset()
        else:
            self._du_auto_off_confirm.reset()
        return super().handle_combat_state(auto=auto, speed_2x=speed_2x)

    def combat_execute(self, expected_end=None):
        self.progress.save('combat')
        self._du_auto_off_confirm = Timer(1, count=2).start()
        super().combat_execute(expected_end=expected_end or self.combat_expected_end)
        self.active['battles'] += 1
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN
        ending = self.settlement_title()
        self._node_done = not (self.appear(COMBAT_AGAIN) or (ending and normalize(ending.source) == '战斗失败'))
        self.active['node_done'] = self._node_done
        self.progress.save('combat_finished')

    def find_door_frame(self):
        # A character can cover both eyes. A visible flat pink lintel and a
        # long straight luminous side identify the remaining portal frame.
        # Search only the walking view, excluding the HUD and action controls.
        hsv = cv2.cvtColor(self.op.image[90:575, 180:1180], cv2.COLOR_RGB2HSV)
        pink = cv2.inRange(hsv, np.array((130, 40, 80)), np.array((179, 255, 255)))
        contours, _ = cv2.findContours(pink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
            x, y, w, h = cv2.boundingRect(contour)
            if x == 0 or y == 0 or x + w == hsv.shape[1] or y + h == hsv.shape[0]:
                continue  # A clipped HUD/background shape is not a full frame.
            if not (40 <= w <= 230 and y + 90 <= 320 and 50 <= h <= 430 and 1 < h / w < 4):
                continue
            # Pink building facades can have a flat top and bright sides too.
            # A DU portal also has a dark central slit edged in gold. Check
            # the visible upper part above the character's usual occlusion.
            window = hsv[y + round(w * 0.2):y + round(w * 0.5),
                         x + round(w * 0.35):x + round(w * 0.65)]
            gold = cv2.inRange(window, np.array((10, 80, 90)), np.array((40, 255, 255)))
            if np.mean(gold > 0) < 0.04 or np.mean(window[:, :, 2] < 90) < 0.025:
                continue
            band = pink[y:y + max(5, int(h * 0.15)), x:x + w]
            fill = np.mean(band > 0)
            if fill < 0.45:
                continue
            columns = np.arange(int(w * 0.1), int(w * 0.9))
            present = np.any(band[:, columns], axis=0)
            if np.mean(present) < 0.9:
                continue
            xx = columns[present]
            yy = np.argmax(band[:, xx], axis=0)
            line = np.polyfit(xx, yy, 1)
            residual = np.abs(yy - np.polyval(line, xx))
            consistent = residual <= np.quantile(residual, 0.7)
            line = np.polyfit(xx[consistent], yy[consistent], 1)
            if abs(line[0]) > 0.15 or np.mean(np.abs(yy - np.polyval(line, xx)) <= 2) < 2 / 3:
                continue
            straight_edges = 0
            for left in (x - 8, x + w - 8):
                strip = hsv[y:y + h, max(0, left):min(hsv.shape[1], left + 16)]
                light = cv2.inRange(strip, np.array((75, 40, 140)), np.array((145, 255, 255)))
                white = cv2.inRange(strip, np.array((0, 0, 180)), np.array((179, 110, 255)))
                light = cv2.bitwise_or(light, white)
                lines = cv2.HoughLinesP(light, 1, np.pi / 180, threshold=max(20, int(h * 0.5)),
                                        minLineLength=int(h * 0.65), maxLineGap=8)
                if lines is not None and any(abs(x2 - x1) <= abs(y2 - y1) * 0.1
                                             for x1, y1, x2, y2 in lines[:, 0]):
                    straight_edges += 1
            # Bright stars can interrupt the pink top. A partly illuminated
            # top is accepted only with straight luminous edges on both sides.
            if straight_edges >= (2 if fill < 0.6 else 1):
                # Match the existing top-template aspect for SRC's floor
                # projection; the partly hidden prop's bottom is unknown.
                return Box(x + 180, y + 90, w, round(w * 0.375), 'door_top_frame', float(fill))
        return None

    def find_sleeping_door(self):
        matches = self.op.template_matches(str(self.op.templates / 'door_sleeping.png'),
                                           (0.30, 0, 0.93, 0.67), confidence=0.72,
                                           scales=np.geomspace(0.4, 2.5, 28))
        active = getattr(self, 'active', None) or {}
        if not matches and active.get('station') in ('冒险', '事件', '铸造', '奖励', '异常', '财富'):
            distant = self.op.template_matches(str(self.op.templates / 'door_sleeping.png'),
                                               (0.14, 0.07, 0.93, 0.42), confidence=0.72,
                                               scales=np.geomspace(0.14, 0.4, 18))
            for box in distant:
                # At the far staircase the Z can be only 10px wide. It must
                # still sit next to the actual pink portal body, excluding
                # small yellow UI/decorative shapes elsewhere in the view.
                h = box.height
                crop = self.op.image[max(0, box.top - h):min(720, box.top + 4 * h),
                                     max(0, box.left - h):min(1280, box.left + 6 * h)]
                hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
                pink = cv2.inRange(hsv, np.array((130, 40, 80)), np.array((179, 255, 255)))
                if np.mean(pink > 0) >= 0.12:
                    matches.append(box)
        if not matches and active.get('station') in ('冒险', '事件', '铸造', '奖励', '异常', '财富'):
            # The floating Z rotates and becomes a few pixels wide at range.
            # The two closed eyelids remain fixed on the portal's face.
            matches = self.op.template_matches(str(self.op.templates / 'door_sleeping_eyes.png'),
                                               (0.14, 0.07, 0.93, 0.80), confidence=0.80,
                                               scales=np.geomspace(0.7, 6, 22))
            valid = []
            for box in matches:
                hsv = cv2.cvtColor(self.op.image[box.top:box.top + box.height,
                                                box.left:box.left + box.width], cv2.COLOR_RGB2HSV)
                # Low-saturation violet clothing plus a gold seam can match
                # the eyelids and window stripe. The actual portal body is
                # chromatic pink; retain the original hue/template thresholds.
                pink = cv2.inRange(hsv, np.array((130, 60, 80)), np.array((179, 255, 255)))
                # The eye pair alone resembles small UI/decorative shapes.
                # A real door has a continuous gold window edge between them.
                middle = hsv[:, round(box.width * 0.35):round(box.width * 0.65)]
                gold = cv2.inRange(middle, np.array((10, 60, 90)), np.array((40, 255, 255)))
                if (np.mean(pink > 0) >= 0.2 and np.mean(gold > 0) >= 0.08
                        and np.mean(np.any(gold > 0, axis=1)) >= 0.8):
                    valid.append(box)
            matches = valid
        return max(matches, key=lambda box: box.width * box.height) if matches else None

    def find_door(self):
        # The sleeping portal is locked until this room's events are finished.
        # Its pink frame also matches an open portal, so reject the visible Z.
        if self.find_sleeping_door():
            return None
        frame = self.find_door_frame()
        if frame:
            # Far portals have a Z smaller than the global template range.
            # Check that feature locally before using the otherwise valid rim.
            w = frame.width
            region = (max(0, frame.left - w * 0.4) / 1280,
                      max(0, frame.top - w * 0.4) / 720,
                      min(1280, frame.left + w * 1.2) / 1280,
                      min(720, frame.top + w * 1.2) / 720)
            if self.op.template_matches(str(self.op.templates / 'door_sleeping.png'), region,
                                        confidence=0.72, scales=np.geomspace(0.17, 0.55, 30) * w / 71):
                return None
            return frame
        # DU's door is a distinct pink prop with two round eyes. Recognize the
        # stable eye feature first: glow changes make a narrow HSV range lose
        # the portal between adjacent frames, and pink hair is not a portal.
        def match_eyes(name):
            found = []
            eyes = self.op.template_matches(str(self.op.templates / f'{name}.png'),
                                            (0.14, 0, 0.93, 0.80), confidence=0.72,
                                            # Dense sizes plus perspective
                                            # variants cover far and side views.
                                            scales=np.geomspace(0.4, 4.5, 35))
            for eye in eyes:
                crop = self.op.image[eye.top:eye.top + eye.height, eye.left:eye.left + eye.width]
                hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
                pink = cv2.inRange(hsv, np.array((135, 40, 80)), np.array((179, 255, 255)))
                if np.count_nonzero(pink) / pink.size >= 0.12:
                    found.append(eye)
            return found
        # Keep both common front views serial and cheap. The rarer variants
        # only read this frame, and all jobs finish before it can be replaced.
        found = match_eyes('door_eyes')
        if not found:
            found = match_eyes('door_eyes_front')
        if not found:
            with ThreadPoolExecutor(max_workers=2) as pool:
                variants = list(pool.map(match_eyes, ('door_eyes_narrow', 'door_eyes_side')))
            # Preserve the existing first-matching-template priority.
            found = next((matches for matches in variants if matches), [])
        if found:
            return max(found, key=lambda box: box.score)
        # A character/umbrella can hide the eyes immediately after combat.
        # The portal's top frame remains visible in the same forward view.
        tops = []
        for name in ('door_top', 'door_top_distant'):
            tops = self.op.template_matches(str(self.op.templates / f'{name}.png'),
                                            (0.3, 0, 0.9, 0.6), confidence=0.74,
                                            scales=np.geomspace(0.4, 4.5, 35))
            if tops:
                break
        for top in tops:
            hsv = cv2.cvtColor(self.op.image[top.top:top.top + top.height,
                                             top.left:top.left + top.width], cv2.COLOR_RGB2HSV)
            pink = cv2.inRange(hsv, np.array((130, 40, 80)), np.array((179, 255, 255)))
            if np.count_nonzero(pink) / pink.size >= 0.18:
                found.append(top)
        if found:
            return max(found, key=lambda box: box.score)
        # Edge-on doors expose no eyes. Keep SRA's pink-prop fallback, but
        # require a long straight upright edge and the adjacent cyan glow.
        # Pink character hair alone fails these two geometric checks.
        hsv = cv2.cvtColor(self.op.image[75:575, 380:1065], cv2.COLOR_RGB2HSV)
        pink = cv2.inRange(hsv, np.array((130, 40, 80)), np.array((179, 255, 255)))
        pink = cv2.morphologyEx(pink, cv2.MORPH_CLOSE, np.ones((9, 1), np.uint8))
        pink = cv2.morphologyEx(pink, cv2.MORPH_OPEN, np.ones((150, 1), np.uint8))
        contours, _ = cv2.findContours(pink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if not (4 <= w <= 80 and h >= 160 and h > 3 * w):
                continue
            nearby = hsv[y:y + h, max(0, x - 25):x + w + 26]
            cyan = cv2.inRange(nearby, np.array((75, 50, 140)), np.array((115, 255, 255)))
            coverage = np.count_nonzero(np.any(cyan, axis=1)) / h
            if coverage >= 0.5:
                lines = cv2.HoughLinesP(cyan, 1, np.pi / 180, threshold=40,
                                        minLineLength=h * 0.6, maxLineGap=8)
                if lines is None or not any(abs(y2 - y1) >= h * 0.6
                                             and abs(x2 - x1) <= abs(y2 - y1) * 0.2
                                             for x1, y1, x2, y2 in lines[:, 0]):
                    continue  # A blue pet beside pink hair has no straight portal border.
                # Eye/window cutouts can split the pink edge. Its cyan border
                # continues to the floor, so retain that full vertical extent.
                border = hsv[:, max(0, x - 25):x + w + 26]
                light = cv2.inRange(border, np.array((75, 50, 140)), np.array((115, 255, 255)))
                rows = np.flatnonzero(np.count_nonzero(light, axis=1) >= 3)
                bottom = max(y + h, int(rows[-1]) + 1) if len(rows) else y + h
                found.append(Box(x + 380, y + 75, w, bottom - y, 'door_edge', coverage))
        # Keep the established anchors when available. If they all miss,
        # the character may cover one eye of a nearby portal. Reuse the
        # open-eye feature before turning away from this visible exit.
        return max(found, key=lambda box: box.score) if found else (
            self.find_near_portal() or self.find_portal_panel())

    def find_portal_panel(self, for_view=False):
        # The portal's back has no eyes. Use its tall gold-rimmed dark window
        # only in an observed cleared combat room; it cannot prove clearance.
        active = getattr(self, 'active', None) or {}
        if not for_view and (not active.get('node_done') or active.get('station') not in ('战斗', '精英', '首领', '转化')):
            return None
        # A complete window in the omitted left band is also a physical view
        # cue. This mode may only turn the camera, never declare an open exit.
        x0, y0, x1, y1 = (0, 150, 384, 612) if for_view else (38, 150, 1216, 612)
        hsv = cv2.cvtColor(self.op.image[y0:y1, x0:x1], cv2.COLOR_RGB2HSV)
        gold = cv2.inRange(hsv, np.array((10, 70, 80)), np.array((42, 255, 255)))
        gold = cv2.morphologyEx(gold, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(gold, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if (not (8 <= w <= 100 and 40 <= h <= 420 and 3 < h / w < 15)
                    or x <= 1 or y <= 1 or x + w >= gold.shape[1] - 1 or y + h >= gold.shape[0] - 1):
                continue  # A cut-off window cannot provide a floor anchor.
            coverage = cv2.contourArea(contour) / (w * h)
            if coverage < 0.6:
                continue
            inner = hsv[y + round(h * 0.1):y + round(h * 0.9),
                        x + round(w * 0.3):x + round(w * 0.7)]
            if not inner.size or np.mean(inner[:, :, 2] < 120) < 0.45:
                continue
            surround = hsv[max(0, y - round(h * 0.1)):min(hsv.shape[0], y + round(h * 1.1)),
                           max(0, x - w):min(hsv.shape[1], x + 2 * w)]
            pink = cv2.inRange(surround, np.array((130, 40, 80)), np.array((179, 255, 255)))
            if np.mean(pink > 0) < 0.28:
                continue
            # Restore the prop's extent from the complete window. Unlike the
            # eye templates, this box already reaches its ground contact.
            center = x0 + x + w / 2
            if for_view and center >= 180:
                continue
            # Trim symmetrically if the restored panel extends off-screen;
            # clipping just one edge would shift the observed window center.
            half_width = min(2.5 * w, center, 1280 - center)
            left, right = round(center - half_width), round(center + half_width)
            top, bottom = max(0, round(y0 + y - 0.2 * h)), min(720, round(y0 + y + 1.4 * h))
            candidates.append((w * h, Box(left, top, right - left, bottom - top, 'door_panel', coverage)))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    def event_placard_rectangles(self, target):
        # Existing geometry allows a 340px-wide plaque whose centre differs
        # from its label by at most 0.3 widths: no candidate can extend beyond
        # +/-272px. Crop there with edge context, and share this frame's work
        # between title validation and native floor projection.
        tx, ty = target.center
        key = ('event_placard_rectangles', tx, ty)
        if key in self.op.frame_cache:
            return self.op.frame_cache[key]
        height, width = self.op.image.shape[:2]
        left, right = max(0, int(tx) - 276), min(width, int(tx) + 277)
        top, bottom = max(0, int(ty) - 4), min(height, 584)
        plaques = []
        if left >= right or top >= bottom:
            return plaques
        gray = cv2.cvtColor(self.op.image[top:bottom, left:right], cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 60, 140)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if ((x == 0 and left > 0) or (y == 0 and top > 0)
                    or (x + w >= gray.shape[1] and right < width)
                    or (y + h >= gray.shape[0] and bottom < height)):
                continue
            if (abs(left + x + w / 2 - tx) < w * 0.3 and ty < top + y < ty + 150
                    and 40 <= w <= 340 and 70 <= h <= 450 and 1.2 < h / w < 4
                    and 260 < top + y + h < 580):
                border = edges[y:y + h, x:x + w]
                coverage = (np.mean(np.any(border[:, :4], axis=1)),
                            np.mean(np.any(border[:, -4:], axis=1)),
                            np.mean(np.any(border[:4, :], axis=0)),
                            np.mean(np.any(border[-4:, :], axis=0)))
                plaques.append(((left + x, top + y, w, h), min(coverage) >= 0.7))
        self.op.frame_cache[key] = plaques
        return plaques

    def event_direction(self, target):
        # DU event plaques are much taller than SU's exit nameplates. Passing
        # their high label directly to the SU projection makes a nearby event
        # look almost entirely sideways. Use the observed plaque's bottom.
        plaques = [rect for rect, _ in self.event_placard_rectangles(target)]
        if plaques:
            x, y, w, h = max(plaques, key=lambda box: box[2] * box[3])
            return RogueExit.screen2direction((x + w / 2, y + h), at_floor=True)
        return RogueExit.screen2direction(target.center)

    def has_event_placard(self, target):
        # DU adds event titles that are absent from SU's keyword catalogue.
        # Accept new text only when it labels four visible frame edges below it.
        if target.score < 0.8 or len(normalize(target.source)) < 2 or target.source.isascii():
            return False
        return any(closed for _, closed in self.event_placard_rectangles(target))

    def enemy_visible(self):
        enemy = self.op.read_line((0.42, 0.035, 0.75, 0.10), snapshot=False).source
        return bool(re.search(r'等级\s*\d+', enemy))

    def check_remaining_enemy(self):
        if self._node_done and self.active['station'] in ('战斗', '精英', '首领', '转化', '储蓄间'):
            if self.enemy_visible():
                logger.info('DU enemy remains after reconnect; resume this battle')
                self._node_done = False
                self.active['node_done'] = False
                self.progress.save('combat_pending')
                return True
        return False

    def check_adventure_pending(self):
        active = getattr(self, 'active', None) or {}
        if active.get('station') != '冒险':
            return False
        return self.request_adventure_exit(active.get('adventure_kind', ''))

    def find_near_portal(self):
        # A nearby face can differ in perspective or be partly covered by
        # the player/party list. One open eye, its blush and gold window edge
        # remain observable. Normal navigation rejects sleeping doors first.
        found = []
        for name, offset in (('door_eye_right_near', -129), ('door_eye_left_near', 24)):
            boxes = self.op.template_matches(str(self.op.templates / f'{name}.png'),
                                             (0.25, 0.15, 0.99, 0.75), confidence=0.82,
                                             scales=np.geomspace(0.8, 2.6, 22))
            for box in boxes:
                crop = self.op.image[box.top:box.top + box.height, box.left:box.left + box.width]
                hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
                pink = cv2.inRange(hsv, np.array((130, 40, 80)), np.array((179, 255, 255)))
                if np.mean(pink > 0) < 0.2:
                    continue
                # Restore the paired-face extent for SRC's existing ground
                # projection, rather than walking toward the eye itself.
                scale = box.width / 125
                left = max(0, round(box.left + offset * scale))
                top = max(0, round(box.top - 2 * scale))
                right = min(self.op.image.shape[1], round(box.left + (offset + 241) * scale))
                bottom = min(self.op.image.shape[0], round(box.top + 119 * scale))
                if right > left and bottom > top:
                    found.append(Box(left, top, right - left, bottom - top, 'door_face_near', box.score))
        return max(found, key=lambda box: box.score) if found else None

    def wait_door_transition(self, approach_direction=None):
        # The first interact may land during the final walking animation.
        # Remain still and let SRC retry the still-visible portal control.
        self.progress.save('entering_next_station')
        missing_prompt = Timer(1.5, count=3).start()
        adjustments = 0
        last_observed_direction = None
        last_gate = None
        backed_off = False
        def retry_visible_prompt():
            label = self.op.text(('随意门', '前往下一区域'), (0.58, 0.48, 0.92, 0.70))
            if label and self.interaction_visible():
                missing_prompt.reset()
                self.interact_with_label(label, interval=1)
                return True
            return False
        def retry():
            nonlocal adjustments, last_observed_direction, last_gate, backed_off
            if retry_visible_prompt():
                return
            if adjustments < (3 if backed_off else 2) and missing_prompt.reached():
                door = self.find_near_portal() or self.find_door()
                if door and door.height >= 70:
                    # The interaction can disappear after the last movement
                    # ends near its activation boundary. The earlier approach
                    # can now point away from the gate after a camera change;
                    # always derive this short step from the current frame.
                    ratio = 1 if door.source in ('door_edge', 'door_panel') else 4 if door.source.startswith('door_top') else 2.45
                    bottom = max(280, min(610, door.top + door.height * ratio))
                    last_observed_direction = RogueExit.screen2direction((door.center[0], bottom), at_floor=True)
                    logger.info(f'DU portal prompt lost; current gate {door.button}, direction {last_observed_direction}')
                    folder = ROOT / 'log/divergent_universe' / self.config.config_name
                    folder.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(folder / f'door_retry_{adjustments}.jpg'),
                                cv2.cvtColor(self.op.image, cv2.COLOR_RGB2BGR),
                                [cv2.IMWRITE_JPEG_QUALITY, 90])
                    anchor = np.array((door.center[0], door.top, door.height))
                    if (not backed_off and last_gate is not None and door.height >= 120
                            and abs(last_observed_direction) > 60
                            and np.max(np.abs(anchor - last_gate)) < 12):
                        # Actual retry frames showed the same very close,
                        # lateral portal after a short approach. Repeating
                        # that heading presses against its solid front/edge.
                        # Make room once, then use a fresh observed gate; no
                        # stale direction is carried across this backoff.
                        logger.info('DU close lateral portal did not move; back off once and reacquire')
                        self.progress.record('portal_backoff', gate=door.button)
                        self.move(180, 0.4, run=False,
                                  interaction_text=('随意门', '前往下一区域'))
                        backed_off = True
                        last_observed_direction = None
                    else:
                        self.move(last_observed_direction, 0.2, run=False,
                                  interaction_text=('随意门', '前往下一区域'))
                    last_gate = anchor
                    adjustments += 1
                elif door is None and last_observed_direction is not None:
                    # One remaining short step may use the immediately prior
                    # observation when a very close gate clips out of view.
                    # Never use the older caller heading without a fresh gate.
                    self.move(last_observed_direction, 0.2, run=False,
                              interaction_text=('随意门', '前往下一区域'))
                    adjustments += 1
                missing_prompt.reset()
        # A disappearing prompt also occurs after an accepted interaction.
        # Observe its page transition before introducing any movement that
        # could interrupt the entry animation. Visible prompts can be retried.
        try:
            self.op.wait_until(lambda: not self.world_visible(), action=retry_visible_prompt,
                               timeout=10, name='随意门交互响应')
            return
        except RuntimeError as error:
            if not str(error).startswith('随意门交互响应超时') or not self.world_visible():
                raise
        self.progress.record('portal_transition_retry', reason='world unchanged after response window')
        missing_prompt.reset()
        self.op.wait_until(lambda: not self.world_visible(), action=retry,
                           timeout=10, name='随意门交互转场')

    def wait_event_transition(self):
        # NPC/event panels open after an animation. Do not resume the map
        # approach while an accepted native interaction is still opening.
        self.progress.save('entering_event')
        def retry():
            label = self.op.text(('事件', '区域'), (0.58, 0.48, 0.92, 0.70))
            if label and self.interaction_visible():
                self.interact_with_label(label, interval=1)
        self.op.wait_until(lambda: not self.world_visible(), action=retry,
                           timeout=10, name='事件交互转场')

    def navigation_banner_visible(self):
        title = self.op.read_line((0.42, 0.12, 0.61, 0.16), snapshot=False).source
        return bool(re.search(r'第[一二三四五六七八九十0-9]+位面\d+/\d+', normalize(title)))

    def find_event_plaques(self):
        templates = ('event_unknown_glyph', 'event_gold_glyph', 'event_unknown_board',
                     'event_anomaly_board', 'event_reward_board', 'event_forge_board')
        def match(template):
            return self.op.template_matches(str(self.op.templates / f'{template}.png'),
                                            (0.14, 0.10, 0.94, 0.75),
                                            confidence=0.88 if template == 'event_unknown_glyph' else 0.80,
                                            scales=np.geomspace(0.6, 3.5, 61))
        # Keep common positive matches cheap. Independent rare templates read
        # the same immutable frame; join all jobs before the next screenshot.
        for template in templates[:3]:
            if plaques := match(template):
                return plaques
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(match, templates[3:]))
        # Preserve the original template priority, regardless of finish order.
        if plaques := next((plaques for plaques in results if plaques), []):
            return plaques
        # This observed revealed-event artwork has no title at long range.
        # Its inner motif survives partial frame occlusion; keep all earlier
        # template priorities and restore the frame for native projection.
        plaques = self.op.template_matches(str(self.op.templates / 'event_stars_glyph.png'),
                                          (0.14, 0.10, 0.94, 0.75), confidence=0.86,
                                          scales=np.geomspace(0.5, 3.5, 61))
        if plaques:
            return plaques
        if plaques := self.find_dark_event_plaques():
            return plaques
        return self.op.template_matches(str(self.op.templates / 'event_birds_glyph.png'),
                                        (0.14, 0.10, 0.94, 0.75), confidence=0.86,
                                        scales=np.geomspace(0.4, 4.0, 61))

    def find_dark_event_plaques(self):
        # An unrevealed plaque's back has no known artwork and its title may
        # sit under the HUD. The dark upright face and blue light below it
        # provide a physical approach cue; interaction still confirms arrival.
        if (getattr(self, 'active', None) or {}).get('station') not in ('事件', '奖励', '异常', '铸造'):
            return []
        op = self.op
        if 'dark_event_plaques' in op.frame_cache:
            return list(op.frame_cache['dark_event_plaques'])
        x0, y0, x1, y1 = 10, 160, 1216, 610
        hsv = cv2.cvtColor(op.image[y0:y1, x0:x1], cv2.COLOR_RGB2HSV)
        dark = cv2.inRange(hsv, np.array((0, 0, 0)), np.array((179, 130, 65)))
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            fill = cv2.contourArea(contour) / (width * height)
            if not (25 <= width <= 330 and 60 <= height <= 430
                    and 1.15 < height / width < 4.5 and fill >= 0.78):
                continue
            # The HUD may cover its top, but the base and both sides must be
            # observed so the existing floor projection has a real anchor.
            if x <= 1 or x + width >= dark.shape[1] - 1 or y + height >= dark.shape[0] - 1:
                continue
            left, top = x0 + x, y0 + y
            bottom = top + height
            band = op.image[bottom:min(650, bottom + round(min(65, height * 0.4))),
                            max(0, left - width // 4):min(1280, left + width + width // 4)].astype(np.int16)
            if not band.size:
                continue
            blue = band[:, :, 2] - np.maximum(band[:, :, 0], band[:, :, 1])
            if np.mean((blue > 20) & (band[:, :, 2] > 80)) < 0.20:
                continue
            found.append(Box(left, top, width, height, 'event_dark_board', float(fill)))
        op.frame_cache['dark_event_plaques'] = tuple(found)
        return found

    def navigate_station(self):
        op = self.op
        self.progress.save('navigating')
        # Same operation boundary as MapControl._goto: previous combat
        # attacks must not be counted as repeated navigation clicks.
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        searches = 0
        scan_offset = False
        side_steps = 0
        repositioned = False
        last_direction = None
        last_direction_steps = 0
        door_anchor = None
        door_stalls = 0
        detours = 0
        lost_door_adjustments = 0
        locked_event_steps = 0
        last_named_event = None
        event_change_saved = False
        event_anchor = previous_event_anchor = None
        occlusion_peek_done = False
        next_scan_rotation = -45
        edge_view_adjustments = 0
        # Confirm absence on two fresh frames, not three full template scans.
        missing = Timer(2, count=1).start()
        def reset_view_wait(scanning=False):
            nonlocal next_scan_rotation
            # Keep the initial/post-movement render grace. A controlled
            # camera sweep only needs two fresh negative observations;
            # otherwise faster recognition just repeats work until 2s pass.
            missing.limit = 0 if scanning else 2
            missing.reset()
            if not scanning:
                # Any approach changes the view; a previous split scan no
                # longer defines this camera's next angle.
                next_scan_rotation = -45
        def observe_event(target, identity):
            nonlocal event_anchor, searches
            anchor = np.array((target.center[0], target.top, target.height))
            if (previous_event_anchor is not None and previous_event_anchor[0] == identity
                    and np.max(np.abs(anchor - previous_event_anchor[1])) > 12):
                # Two consecutive detections separated by native approach
                # show movement. A single glimpse must not reset the sweep
                # budget while leaving the native SWIPE watchdog accumulated.
                self.device.stuck_record_clear()
                self.device.click_record_clear()
                searches = 0
            event_anchor = (identity, anchor)
        timeout = Timer(300, count=3).start()
        step = 0
        while not timeout.reached():
            previous_event_anchor, event_anchor = event_anchor, None
            op.snapshot()
            if self.config.DivergentUniverse_SaveEvidence:
                from module.base.utils import save_image
                folder = ROOT / 'log/divergent_universe' / self.config.config_name
                save_image(op.image, folder / f'navigation_{step:02d}.png')
            step += 1
            scan_started = time.monotonic()
            event_template_seconds = 0.0
            # Handle a nearby exit before slower selection OCR. The prompt can
            # disappear as the last movement animation finishes.
            if self.interaction_visible():
                label = op.text(('随意门', '前往下一区域', '战利品', '事件', '奖励'),
                                (0.58, 0.48, 0.92, 0.70))
                if label and self.interact_with_label(label, interval=1):
                    if any(word in label.source for word in ('随意门', '前往下一区域')):
                        if (getattr(self, 'active', None) or {}).get('station') == '冒险':
                            self._node_done = self.active['node_done'] = True
                            self.progress.save('adventure_exit_available')
                        self.wait_door_transition(approach_direction=last_direction)
                    elif '事件' in label.source:
                        self.wait_event_transition()
                    continue
            if not self.world_visible():
                if self.selection_kind():
                    return
                if self.is_combat_executing():
                    self.combat_execute()
                    return
                if self.settlement_title():
                    return
                if self.handle_misc():
                    return
                continue
            if self.check_remaining_enemy() or self.check_adventure_pending():
                return
            if self.collapse_status_panel():
                continue
            if self.navigation_banner_visible():
                # The entry progress overlay covers an event's marker/frame.
                # A miss on that image is not evidence the target is absent.
                reset_view_wait()
                continue
            if self.active['station'] == '储蓄间' and op.text(
                    '击败扑满', (0.3, 0.2, 0.85, 0.6)):
                if op.click_box(self.reward_close_button()):
                    continue
            # A completed normal event has returned to the walking view.
            # Re-scanning its plaque on every exit approach repeats the full
            # OCR/multi-scale search. Abnormal/wealth rooms can have more than
            # one interaction, so keep their existing search until the exit.
            event_finished = self.active['station'] in ('铸造', '事件') and self.active.get('event_completed')
            if event_finished and (locked_exit := self.find_sleeping_door()):
                # An earlier version treated closing the optional forge setup
                # as completing the room. A visibly locked exit disproves it.
                logger.info(f'DU exit is still locked ({locked_exit.source}); resume unfinished room events')
                if locked_exit.source == 'door_sleeping_eyes':
                    # Keep the decision frame for this new fallback, without
                    # another device screenshot or an extra OCR session.
                    folder = ROOT / 'log/divergent_universe' / self.config.config_name
                    folder.mkdir(parents=True, exist_ok=True)
                    # Preserve exact decision pixels for color-boundary
                    # regressions; JPEG can change a near-threshold match.
                    cv2.imwrite(str(folder / 'locked_exit.png'), cv2.cvtColor(op.image, cv2.COLOR_RGB2BGR),
                                [cv2.IMWRITE_PNG_COMPRESSION, 1])
                    logger.attr('DU locked exit eye bounds', locked_exit.button)
                self.active.pop('event_completed', None)
                self._node_done = self.active['node_done'] = False
                self.progress.save('event_required')
                event_finished = False
            if (self.active['station'] in ('事件', '奖励', '异常', '财富', '铸造', '储蓄间')
                    and not event_finished and self.interaction_visible()):
                labels = op.read_region((0.58, 0.48, 0.92, 0.70), snapshot=False)
                # The setup console can overlap a required regional event.
                # Select the actual event row with SRC's icon matcher.
                interacted = next((label for label in labels if '造物调试台' not in normalize(label.source)
                                   and self.interact_with_label(label, interval=1)), None)
                if interacted:
                    if any(word in interacted.source for word in ('事件', '区域')):
                        self.wait_event_transition()
                    continue
            # Some abnormal rooms contain several events. Finishing one must
            # not suppress the remaining question-mark plaques in this room.
            if self.active['station'] in ('事件', '奖励', '异常', '财富', '铸造', '储蓄间') and not event_finished:
                # Nearby event plaques put their labels against the top edge.
                # Keep the world HUD on the left out of this search.
                targets = list(op.read_region((0.30, 0, 0.80, 0.46), snapshot=False))
                # Event labels can sit left of the character, below DU's
                # collapsed HUD. Cover that omitted band while keeping the
                # party list and upper-left menu out of the OCR input. The
                # overlap preserves titles near the original left boundary.
                targets += op.read_region((0.03, 0.21, 0.40, 0.46), snapshot=False)
                def event_label(box):
                    return (re.fullmatch(r'[?？\s]{2,}', box.source)
                            or normalize(box.source) in self.EVENT_NAMES
                            # Regional events may be absent from the SU catalogue.
                            or re.search(r'[（(]区域[）)]', box.source)
                            or (self.active['station'] != '财富' and self.has_event_placard(box)))
                unknown = [box for box in targets if event_label(box)]
                if not unknown:
                    # A nearby label can cross the old right boundary. Read
                    # only above the party names and below the top HUD icons.
                    unknown = [box for box in op.read_region((0.70, 0.05, 0.88, 0.18), snapshot=False)
                               if event_label(box)]
                unknown += op.template_matches(str(op.templates / 'event_unknown.png'),
                                                (0.30, 0, 0.80, 0.46), confidence=0.80)
                if not unknown:
                    sample = cv2.imread(str(op.templates / 'event_unknown.png'), cv2.IMREAD_GRAYSCALE)
                    sample = cv2.inRange(sample, 185, 255)
                    frame = cv2.inRange(cv2.cvtColor(op.image[:332, 384:1024], cv2.COLOR_RGB2GRAY), 185, 255)
                    for scale in (0.75, 0.85, 1.0, 1.15):
                        glyph = cv2.resize(sample, None, fx=scale, fy=scale)
                        values = cv2.matchTemplate(frame, glyph, cv2.TM_CCOEFF_NORMED)
                        _, score, _, (x, y) = cv2.minMaxLoc(values)
                        if score >= 0.72:
                            unknown.append(Box(x + 384, y, glyph.shape[1], glyph.shape[0], 'event_unknown', score))
                if unknown:
                    target = min(unknown, key=lambda box: box.left)
                    logger.info(f'DU event target: {target.source!r} {target.center}, score={target.score:.3f}')
                    direction = self.event_direction(target)
                    observe_event(target, normalize(target.source))
                    named = normalize(target.source) and not target.source.startswith('event_')
                    if named and not event_change_saved:
                        observation = dict(name=target.source, box=target.button, direction=float(direction))
                        if last_named_event and normalize(last_named_event[0]['name']) != normalize(target.source):
                            # A name change before interaction may be another
                            # target, an OCR variant, or clipping. Preserve
                            # both actual decision frames before changing any
                            # navigation policy based on that interpretation.
                            folder = ROOT / 'log/divergent_universe' / self.config.config_name
                            folder.mkdir(parents=True, exist_ok=True)
                            stamp = time.time_ns()
                            paths = []
                            for label, image in (('before', last_named_event[1]), ('after', op.image)):
                                path = folder / f'event_target_{stamp}_{label}.jpg'
                                saved = cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
                                                    [cv2.IMWRITE_JPEG_QUALITY, 90])
                                paths.append(str(path.relative_to(ROOT)) if saved else None)
                            self.progress.record('event_target_name_changed', before=last_named_event[0],
                                                 after=observation, screenshots=paths)
                            event_change_saved = True
                            last_named_event = None
                        else:
                            last_named_event = (observation, op.image.copy())
                    near = target.center[1] < 110
                    self.move(direction, 0.25 if near else 0.5, run=not near,
                              interaction_text=(target.source, '区域', '事件', '奖励', '战利品'))
                    if self.active['station'] == '储蓄间' and self.world_visible():
                        self.handle_map_A()
                    last_direction = direction
                    last_direction_steps = 0
                    reset_view_wait()
                    continue
                # Revealed abnormal events use an eye plaque without a ???
                # label; they still need interaction before the door wakes.
                # Regional events use the same blue framed artwork as forge
                # rooms, including when the title is clipped above the screen.
                match_started = time.monotonic()
                plaques = self.find_event_plaques()
                event_template_seconds = time.monotonic() - match_started
                if plaques:
                    target = max(plaques, key=lambda box: box.score)
                    plaque_source = target.source
                    if target.source in ('event_unknown_glyph', 'event_gold_glyph', 'event_stars_glyph', 'event_birds_glyph'):
                        # The outer frame changes with lighting/perspective.
                        # Restore its extent from the stable inner artwork so
                        # native floor projection still aims at the plaque base.
                        if target.source == 'event_stars_glyph':
                            scale = target.width / 53
                            left, top, width, height = 14, 15, 82, 112
                        elif target.source == 'event_birds_glyph':
                            scale = target.width / 58
                            left, top, width, height = 15, 17, 88, 118
                        else:
                            scale = target.width / 50
                            left, top, width, height = ((13, 14, 77, 107) if target.source == 'event_unknown_glyph'
                                                       else (11, 14, 71, 96))
                        target = Box(round(target.left - left * scale), round(target.top - top * scale),
                                     round(width * scale), round(height * scale), 'event_board', target.score)
                    direction = RogueExit.screen2direction(
                        (target.center[0], min(580, target.top + target.height)), at_floor=True)
                    logger.info(f'DU revealed event plaque ({plaque_source}): {target.center}, score={target.score:.3f}')
                    observe_event(target, plaque_source)
                    self.move(direction, 0.25 if target.height > 220 else 0.5,
                              run=target.height <= 220,
                              interaction_text=('区域', '事件', '奖励', '战利品'))
                    last_direction = direction
                    last_direction_steps = 0
                    reset_view_wait()
                    continue
                locked_exit = self.find_sleeping_door()
                distant_lock = locked_exit and (
                    locked_exit.height < 32 if locked_exit.source == 'door_sleeping'
                    else locked_exit.width < 80 and locked_exit.height < 40)
                if distant_lock and locked_event_steps < 4:
                    # Revealed cards can have no readable title at range.
                    # Their visible locked portal is an approach cue, never
                    # room completion. Bring the event area closer before
                    # searching an entire circle from the same position.
                    # Stop using this cue once close: remaining events can
                    # be beside the portal, and running into it hides them.
                    ratio = 6 if locked_exit.source == 'door_sleeping' else 2.45
                    bottom = max(280, min(580, locked_exit.top + locked_exit.height * ratio))
                    direction = RogueExit.screen2direction((locked_exit.center[0], bottom), at_floor=True)
                    logger.info(f'DU locked event area: {locked_exit.source} {locked_exit.button}; approach {locked_event_steps + 1}/4')
                    self.progress.save('approaching_hidden_event')
                    self.move(direction, 0.6, run=True,
                              interaction_text=('区域', '事件', '奖励', '战利品'))
                    locked_event_steps += 1
                    last_direction = None
                    reset_view_wait()
                    continue
            match_started = time.monotonic()
            door = self.find_door()
            door_seconds = time.monotonic() - match_started
            if door:
                searches = 0
                reset_view_wait()
                if door_anchor is None:
                    logger.info(f'DU exit target: {door.source} {door.button}, score={door.score:.3f}')
                anchor = np.array((door.center[0], door.top, door.height))
                if door_anchor is not None and np.max(np.abs(anchor - door_anchor)) < 12:
                    door_stalls += 1
                else:
                    if door_anchor is not None:
                        # JoystickContact sends native touches directly, so
                        # renew the watchdog only on observed target movement.
                        self.device.stuck_record_clear()
                        self.device.click_record_clear()
                    door_stalls = 0
                    door_anchor = anchor
                if door_stalls >= 4:
                    # A fixed exit after repeated movement means an obstacle,
                    # for example the large chest in a wealth room. SRC owns
                    # the lateral joystick movement and screenshot polling.
                    if detours >= 3:
                        raise RuntimeError('随意门可见但绕障后仍无法接近，保留当前站点')
                    logger.info('DU exit did not move after four approaches; sidestep obstacle')
                    # A bounded recovery step starts a new movement attempt;
                    # the room timeout and three-detour limit still apply.
                    self.device.stuck_record_clear()
                    side = -90 if door.center[0] < 640 else 90
                    if detours == 1:
                        side = -side
                    # Back off a solid prop before going around the visible
                    # exit's side; a short walk against it cannot clear it.
                    self.move(180, 0.5, run=False, interaction_text=())
                    self.move(side, 0.9, run=True, interaction_text=())
                    detours += 1
                    door_anchor = None
                    door_stalls = 0
                    last_direction = None
                    continue
                if (door.source == 'door_edge' and door.height > 240
                        and abs(door.center[0] - 640) < 200 and side_steps < 3):
                    # The DU prop interacts from its front. Its cyan glow is
                    # on that face; step around the solid edge instead of
                    # continually walking into the door's side.
                    x, y, w, h = door.left, door.top, door.width, door.height
                    hsv = cv2.cvtColor(op.image[y:y + h, max(0, x - 40):x + w + 40], cv2.COLOR_RGB2HSV)
                    cyan = cv2.inRange(hsv, np.array((75, 50, 140)), np.array((115, 255, 255)))
                    right = np.count_nonzero(cyan[:, 40 + w:])
                    left = np.count_nonzero(cyan[:, :40])
                    self.move(90 if right >= left else -90, 0.6, run=False,
                              interaction_text=('随意门', '前往下一区域'))
                    side_steps += 1
                    last_direction = None
                    continue
                # DU supplies its unique door's screen anchor. Perspective
                # projection and movement direction are the native SU method.
                # DU has a much taller portal and no SU domain label. Its
                # floor contact is the compatible native projection anchor.
                ratio = 1 if door.source in ('door_edge', 'door_panel') else 4 if door.source.startswith('door_top') else 2.45
                bottom = door.top + door.height * ratio
                # A close portal can extend below the screenshot. Keep its
                # visible target in front of the native player foot plane.
                # Final-room doors stand above stairs: their visible base can
                # be above the current floor's horizon. Project toward them
                # on the walkable plane until approaching raises the camera.
                bottom = max(280, min(bottom, 610))
                direction = RogueExit.screen2direction((door.center[0], bottom), at_floor=True)
                # screen2direction is a ground-plane joystick direction, not
                # a camera yaw. Feed it to SRC's joystick directly; turning
                # the camera by it overshoots nearby lateral exits.
                near = (bottom > 480 if door.source == 'door_panel' else
                        door.source == 'door_edge' or door.height > 70)
                self.move(direction, 0.25 if near else 0.6, run=not near,
                          interaction_text=('随意门', '前往下一区域'))
                last_direction = direction
                last_direction_steps = 0
            elif last_direction is not None:
                if (door_anchor is not None and abs(door_anchor[0] - 640) < 120
                        and lost_door_adjustments < 2):
                    # A centred portal can move behind the character during
                    # approach. Inspect it from a slightly different view
                    # before walking blindly or beginning a full-circle scan.
                    logger.info('DU centred portal lost during approach; adjust native view and reacquire')
                    self.rotation_swipe(10 if door_anchor[0] >= 640 else -10, box=self.ROTATION_BOX)
                    lost_door_adjustments += 1
                    last_direction = None  # The old heading belongs to the old camera view.
                    last_direction_steps = 0
                    reset_view_wait()
                    continue
                self.move(last_direction, 0.3, interaction_text=('随意门', '前往下一区域'))
                # Retain a recently observed target through brief occlusion;
                # each short native movement still stops on an interaction.
                last_direction_steps += 1
                if last_direction_steps >= 3:
                    last_direction = None
            else:
                # Keep checking this view while the post-combat animation or
                # a stale screenshot clears; turn only after repeated misses.
                if not missing.reached():
                    continue
                logger.info(f'DU navigation miss: recognition={time.monotonic() - scan_started:.3f}s, '
                            f'event_templates={event_template_seconds:.3f}s, door={door_seconds:.3f}s')
                if edge_view_adjustments < 2 and (edge_hint := self.find_portal_panel(for_view=True)):
                    # The actual window can be outside the eye detector's
                    # left boundary. Native positive yaw turns toward a target
                    # on the left (rotation_diff is current minus target).
                    # Reobserve its face; a window alone cannot unlock it.
                    logger.info(f'DU left portal window at {edge_hint.button}; turn native view and verify the face')
                    self.progress.record('navigation_left_portal_view', window=edge_hint.button, degrees=22.5)
                    self.rotation_swipe(22.5, box=self.ROTATION_BOX)
                    edge_view_adjustments += 1
                    next_scan_rotation = -45
                    reset_view_wait(scanning=True)
                    continue
                if (not occlusion_peek_done and not scan_offset and not repositioned and searches == 0
                        and self.active['station'] in ('事件', '奖励', '异常', '财富', '铸造', '储蓄间')):
                    # A frontal plaque can sit directly behind the character.
                    # Inspect that blind spot before sweeping past it. If the
                    # peek also misses, finish the same first 45-degree turn;
                    # all original coarse/interleaved views remain available.
                    logger.info('DU event view obscured or empty; inspect a small native camera offset')
                    self.progress.record('navigation_occlusion_peek', degrees=-10)
                    self.rotation_swipe(-10, box=self.ROTATION_BOX)
                    occlusion_peek_done = True
                    next_scan_rotation = -35
                    reset_view_wait(scanning=True)
                    continue
                searches += 1
                if searches >= 9:
                    if not scan_offset:
                        # A narrow gate/name can stay at the HUD edge between
                        # the coarse 45-degree views. Interleave one bounded
                        # sweep before changing the player's position.
                        logger.info('DU full view sweep missed; inspect the intermediate angles')
                        self.progress.record('navigation_scan_offset', degrees=22.5)
                        self.device.click_record_clear()
                        self.rotation_swipe(-22.5, box=self.ROTATION_BOX)
                        scan_offset = True
                        searches = 0
                        reset_view_wait(scanning=True)
                        continue
                    if (not repositioned and self.active['station'] in
                            ('事件', '奖励', '异常', '财富', '铸造', '储蓄间')):
                        # SRA retries an event scan from closer range. DU hides
                        # plaque labels at a distance, so rotating at the same
                        # spawn point forever cannot reveal them.
                        logger.info('DU event labels not visible; approach once and rescan')
                        self.move(180 if self.active['station'] == '储蓄间' else 0,
                                  0.9 if self.active['station'] == '储蓄间' else 0.6)
                        repositioned = True
                        searches = 0
                        reset_view_wait()
                        timeout.reset()
                        self.device.click_record_clear()
                        continue
                    if not self.active.get('navigation_reentry_completed'):
                        self.reenter_station()
                        return
                    break
                # Keep the latest bounded scan for diagnosing missed targets;
                # reuse the decision frame without another device capture.
                folder = ROOT / 'log/divergent_universe' / self.config.config_name / 'search'
                folder.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(folder / f'{int(repositioned)}_{int(scan_offset)}_{searches}.jpg'),
                            cv2.cvtColor(op.image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
                self.rotation_swipe(next_scan_rotation, box=self.ROTATION_BOX)
                next_scan_rotation = -45
                reset_view_wait(scanning=True)
        raise RuntimeError('差分宇宙未找到可交互的事件或随意门')

    def reenter_station(self):
        op = self.op
        logger.info('DU exit search exhausted; leave temporarily and resume the same run')
        left = False
        timeout = Timer(90, count=3).start()
        while not timeout.reached():
            op.snapshot()
            if self.adventure_intro_visible():
                # This help overlay can arrive after native login has already
                # returned a world frame. Close its observed footer before
                # attempting the temporary-leave menu.
                self.handle_misc()
                continue
            if left and (self.lobby_visible() or (self.is_in_main() and not self.world_visible())
                         or op.text('差分宇宙', (0.58, 0.45, 0.96, 0.68))):
                self.active['navigation_reentry_completed'] = True
                self.progress.save('reentry_confirmed')
                self._periodic_selected = False
                self._entry_prepared = False
                self.device.click_record_clear()
                self.go_to_lobby()
                return
            if op.text(('暂离', '暂时离开'), (0.3, 0.3, 1, 1)):
                if op.click_text(('暂离', '暂时离开'), (0.3, 0.3, 1, 1)):
                    left = True
                    self.active['navigation_reentry'] = True
                    self.progress.save('reentering')
                continue
            if self.world_visible():
                op.back()
            elif left:
                op.click_text('确认', (0.4, 0.4, 0.9, 0.9), exact=True)
        raise RuntimeError('差分宇宙暂离后未能返回入口，当前进度已保留')

    def forge_panel_visible(self):
        return bool('造物调试台' in self.header_text()
                    and self.op.text('选择加权奇物', (0.58, 0.38, 0.97, 0.53)))

    def adventure_result_button(self):
        if ((getattr(self, 'active', None) or {}).get('station') == '冒险'
                and self.op.text('拍摄结束', (0.73, 0.33, 0.87, 0.40), exact=True)):
            return self.op.text('退出', (0.78, 0.88, 0.85, 0.94), exact=True)
        return None

    def reward_close_button(self):
        labels = ('点击空白处关闭', '点击空白处继续')
        # Normal rewards and conversion results use different footer heights.
        # Keep the existing region OCR as a fallback for other layouts.
        for region in ((550 / 1280, 639 / 720, 730 / 1280, 673 / 720),
                       (550 / 1280, 581 / 720, 730 / 1280, 615 / 720)):
            box = self.op.read_line(region, snapshot=False)
            if normalize(box.source) in labels:
                return box
        return self.op.text(labels, (0, 0.5, 1, 1))

    def handle_station_warning(self):
        if (self.op.text('最后一次', (0.2, 0.35, 0.85, 0.56))
                and self.op.text('储蓄间', (0.2, 0.35, 0.85, 0.56))):
            self.handle_popup_confirm()
            return True
        return False

    def handle_misc(self):
        op = self.op
        if self.adventure_intro_visible():
            folder = ROOT / 'log/divergent_universe' / self.config.config_name
            folder.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(folder / 'adventure_intro.jpg'), cv2.cvtColor(op.image, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 90])
            if self.active:
                self._node_done = self.active['node_done'] = False
                self.active.pop('adventure_started', None)
                self.active['adventure_kind'] = normalize(op.read_line(
                    (0.37, 0.33, 0.68, 0.38), snapshot=False).source)
                self.request_adventure_exit(self.active['adventure_kind'])
            self.progress.save('closing_adventure_intro')
            # The observed ray-help footer overlaps the character's white
            # clothes: line OCR misses it and detection reads 白 as 自. Only
            # accept this exact variant behind the verified help icon.
            close = op.text(('点击空白处关闭', '点击空自处关闭'),
                            (0.35, 0.70, 0.65, 0.90), exact=True)
            return op.click_box(close or self.reward_close_button())
        if self.world_visible():
            return False
        result_exit = self.adventure_result_button()
        if result_exit:
            self.progress.save('closing_adventure_result')
            op.click_box(result_exit)
            return True
        if normalize(op.read_line((0.43, 0.145, 0.57, 0.215), snapshot=False).source) == '快速恢复':
            # Reuse the native cancel control if this popup was already open
            # when resuming. Do not toggle the user's auto-consumable setting.
            self.progress.save('closing_quick_recovery')
            return self.handle_popup_cancel()
        # A recognized reward/event page does not need login and unrelated
        # popup OCR before every dialogue or close action.
        if self.handle_known_page():
            return True
        if self.handle_station_warning():
            return True
        if self.forge_panel_visible():
            # This optional setup panel is not a map or a forced reward choice.
            # Closing it does not finish the separate regional event in front
            # of the locked exit. Only an actual event may set event_pending.
            from tasks.base.assets.assets_base_page import GUIDE_CLOSE
            self.progress.save('closing_forge_panel')
            self.appear_then_click(GUIDE_CLOSE, interval=2)
            return True
        from tasks.combat.assets.assets_combat_finish import COMBAT_AGAIN, COMBAT_EXIT
        if self.appear(COMBAT_AGAIN) and self.appear(COMBAT_EXIT):
            # Native combat returns on the retry screen too. Leave the failed
            # battle through its native button; do not mark this room cleared.
            self._node_done = False
            self.active['node_done'] = False
            self.progress.save('combat_retry')
            self.appear_then_click(COMBAT_EXIT, interval=3)
            return True
        from tasks.login.assets.assets_login import LOGIN_LOADING
        login_page = self.is_in_login_confirm() or self.appear(LOGIN_LOADING)
        if not login_page:
            # A reconnect can begin with the train animation, before buttons
            # appear. Its build footer is distinct from the in-game UID.
            footer = op.read_line((0.02, 0.95, 0.47, 0.99), snapshot=False).source.replace(' ', '')
            login_page = bool(re.search(r'CNPR[O0]DAndroid|D\d{7,}[-_]?A\d{7,}[-_]?L\d{7,}', footer))
        if login_page:
            logger.info('DU interrupted by login; resume through native Login')
            self.progress.save('reconnecting')
            self.login_from_current()
            return True
        if op.click_box(self.reward_close_button()):
            return True
        return self.handle_tutorial()

    def handle_known_page(self):
        op = self.op
        title = self.header_text()
        if any(word in title for word in self.REWARD_TITLES):
            if op.click_box(self.reward_close_button()):
                return True
            if not op.click_text(('确定', '确认', '继续'), (0.1, 0.6, 1, 1)):
                op.back()
            return True
        if '事件' in title:
            if not self.active.get('event_pending'):
                self.active['event_pending'] = True
                self.progress.save('event')
                # A confirmed map-to-dialogue transition ends navigation;
                # its camera swipes must not count as repeated dialogue input.
                self.device.click_record_clear()
                self.device.stuck_record_clear()
            from tasks.divergent_universe.events import DivergentEvent
            from tasks.rogue.assets.assets_rogue_event import CHOOSE_OPTION_CONFIRM, CHOOSE_STORY
            from tasks.rogue.assets.assets_rogue_ui import PAGE_EVENT
            if self._native_event is None:
                self._native_event = DivergentEvent(self.config, device=self.device)
                self._native_event.event_title = None
            handler = self._native_event
            if handler.appear(CHOOSE_OPTION_CONFIRM):
                if handler.appear_then_click(CHOOSE_OPTION_CONFIRM, interval=2):
                    handler.interval_reset([PAGE_EVENT, CHOOSE_STORY])
                return True
            if handler.handle_event_option() or handler.options:
                return True
            confirm = op.text(('确认', '确定', '继续'), (0.3, 0.4, 1, 1), exact=True)
            if confirm:
                op.click_box(confirm)
                return True
            arrow = op.template('event_select', (0.3, 0.2, 1, 0.9))
            star = op.template('event_selection', (0.3, 0.2, 1, 0.9))
            if star or arrow:
                op.click_box(star or arrow)
            else:
                next_story = op.template('event_next', (0.3, 0.4, 1, 1))
                if next_story:
                    op.click_box(next_story)
                else:
                    # Native PAGE_EVENT continues at BLESSING_CONFIRM, which
                    # lies outside DU's shorter dialogue panel. Only reuse
                    # the explicitly detected native story control here.
                    handler.appear_then_click(CHOOSE_STORY, interval=2)
            return True
        return False

    def update_station_header(self):
        labels = self.op.read_region((0.025, 0, 0.5, 0.065), snapshot=False)
        text = ' '.join(box.source for box in labels)
        number = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if not number or not 1 <= int(number[1]) <= int(number[2]) <= 30:
            return
        node = int(number[1])
        previous = self.active.get('node')
        previous_station = self.active.get('station')
        station = next((name for name in ('战斗', '精英', '首领', '转化', '商店', '事件', '冒险',
                        '铸造', '奖励', '休整', '异常', '财富', '储蓄间', '空白') if name in text), previous_station)
        changed = previous != node or previous_station != station
        if previous is not None and changed:
            self._node_done = False
            self.active['node_done'] = False
            self.active.pop('navigation_reentry', None)
            self.active.pop('navigation_reentry_completed', None)
            self.active.pop('event_completed', None)
            self.active.pop('adventure_started', None)
            self.active.pop('adventure_kind', None)
        self.active['node'] = node
        self.active['node_total'] = int(number[2])
        self.active['station'] = station
        if changed:
            logger.info(f'DU entered node {node}: {self.active["station"]}')
            self.progress.save('node_entered')
            recovery = self.progress.data.get('recovery')
            if recovery and recovery['run_id'] == self.active['id'] and recovery['node'] != node:
                # A requested abandonment must survive incidental transitions
                # until its actual settlement is observed.
                if not self.active.get('stop_requested'):
                    self.progress.record('recovery_progress_confirmed', previous_node=recovery['node'])
                    self.progress.data.pop('recovery', None)
                    self.apply_recovery_deadline()
                    self.progress.save()

    def quit_run(self):
        op = self.op
        def retry_menu():
            # A first-entry tutorial may arrive after the world exit was
            # tapped. Let SRC advance/close its observed controls before
            # reopening the quit menu; waiting alone leaves that page stuck.
            if self.handle_tutorial():
                return
            if self.adventure_intro_visible():
                self.handle_misc()
                return
            # A tap during the reward animation can be ignored. Retry only
            # the observed world exit icon; a generic back could close a
            # menu which has opened since a delayed screenshot was captured.
            if self.world_visible() and op.click_box(
                    op.template('divergent_universe_quit', (0, 0, 0.13, 0.18)), interval=5):
                logger.info('DU exit menu not visible; retry observed world exit button')

        timeout = Timer(60, count=3).start()
        while not timeout.reached():
            op.snapshot()
            # An enemy can interrupt opening the exit menu or confirmation.
            # Let the main loop run SRC combat before requesting the exit again.
            if self.is_combat_executing():
                logger.info('DU exit interrupted by combat; return to native combat handling')
                return
            # The quit menu can linger for a frame after requesting settlement.
            # A resumed first-station task may already be at its confirmation.
            if self.handle_settlement():
                return
            if op.click_text(('结束并结算', '退出并结算'), (0.05, 0.2, 1, 1)):
                self.active['pending_settlement'] = True
                self.progress.save('settling')
                # A stale walking/menu frame must not send another back tap
                # that closes the confirmation while it is opening.
                op.wait_until(lambda: self.is_combat_executing() or self.settlement_confirmation()
                              or self.settlement_title() or self.lobby_visible(),
                              name='结束演算确认')
                return
            if self.settlement_title():
                return
            if self.world_visible():
                if op.back():
                    op.wait_until(lambda: self.is_combat_executing()
                                  or op.text(('结束并结算', '退出并结算', '确定要结束进程'),
                                                 (0.05, 0.2, 1, 1))
                                  or self.settlement_title(), action=retry_menu, name='结束演算菜单')
            else:
                self.handle_misc()
        raise RuntimeError('未能打开差分宇宙结束并结算入口')

    def settlement_title(self):
        ending = (self.op.text(self.SETTLEMENT_TITLES, (0.07, 0.30, 0.28, 0.40), exact=True)
                  or self.op.text(self.SETTLEMENT_TITLES, (0.05, 0.05, 0.95, 0.4), exact=True))
        if ending and normalize(ending.source) == '战斗失败' and not self.op.text(
                '终止战斗并结算', (0.18, 0.80, 0.5, 0.96), exact=True):
            return None
        if ending and any(t in ending.source for t in ('星阶提升', '智瞳点亮')) and not self.op.text(
                '确认结算', (0.25, 0.80, 0.78, 0.98), exact=True):
            return None
        return ending

    def settlement_confirmation(self):
        # In-room exits include a reward table; the retained-run entry uses
        # a compact modal with the same question one row lower on the screen.
        for region in ((0.40, 0.335, 0.61, 0.395), (0.40, 0.48, 0.61, 0.535)):
            question = self.op.read_line(region, snapshot=False)
            if '确定要结束进程' in normalize(question.source):
                return question
        # Expired weekly saves have a different reward-table confirmation.
        # It may only be accepted for the exact user-approved retained run.
        active = getattr(self, 'active', None) or {}
        if active.get('pending_settlement') and active.get('stop_requested'):
            identity = f'{self.config.config_name}:{active.get("id")}'
            if os.environ.get('DU_APPROVED_EXPIRED_RUN') == identity:
                expired = self.op.text('玩法已过期', (0.11, 0.30, 0.70, 0.35))
                if expired and '存档非本周演算进度' in normalize(expired.source):
                    return expired
        return self.op.text('结束本场战斗并重置', (0.2, 0.2, 0.9, 0.5))

    def handle_settlement(self):
        op = self.op
        if self.selection_kind():
            if self.active.get('pending_settlement') and not self.active.get('settlement_confirmed'):
                # Old checkpoints could mistake a curio description mentioning
                # "exploration interrupted" for the actual settlement title.
                self.active['pending_settlement'] = False
                self.active.pop('settlement_observed', None)
                self.active.pop('result', None)
                self.progress.save('selecting')
            return None
        if self.active.get('pending_settlement') and op.text(
                ('当前尚未拥有存档', '是否确认退出'), (0.2, 0.3, 0.9, 0.6)):
            if op.click_text('确认', (0.52, 0.60, 0.79, 0.70), exact=True, interval=3):
                self._settlement_exit_wait.reset()
            return True
        if op.text('确认退出游戏', (0.25, 0.3, 0.8, 0.65)):
            op.click_text('取消', (0.25, 0.4, 0.55, 0.7), exact=True)
            return True
        confirmation = self.settlement_confirmation()
        if confirmation:
            self.active['pending_settlement'] = True
            region = (0.5, 0.5, 0.85, 0.86)
            if '确定要结束进程' in normalize(confirmation.source):
                region = (0.52, 0.60, 0.77, 0.72) if confirmation.top > 300 else (0.52, 0.73, 0.77, 0.83)
            if op.click_text('确认', region, exact=True):
                self.active['settlement_confirmed'] = True
                self._settlement_exit_wait.reset()
                self.progress.save('settling')
            return True
        ending = self.settlement_title()
        if ending:
            if normalize(ending.source) == '战斗失败':
                # This is a battle result, not a completed exploration. Finish
                # through the observed DU exit and await the real settlement.
                self._node_done = self.active['node_done'] = False
                self.active.pop('settlement_observed', None)
                if self._settlement_exit_wait.reached() and op.click_text(
                        '终止战斗并结算', (0.18, 0.80, 0.5, 0.96), exact=True, interval=3):
                    self.active.update(pending_settlement=True, result='loss')
                    self.progress.save('settling_defeat')
                    # A frame captured before the modal opens can still show
                    # the defeat footer. Clicking it again dismisses the modal.
                    # Observe the requested transition before any further tap.
                    self._settlement_exit_wait.reset()
                    op.wait_until(lambda: op.text('结束本场战斗并重置', (0.2, 0.2, 0.9, 0.5)),
                                  name='战败退出确认')
                return True
            first_observation = not self.active.get('settlement_observed')
            self.active['pending_settlement'] = True
            self.active['settlement_observed'] = True
            self.active['result'] = ('interrupted' if self.active.get('stop_requested') else
                                     'win' if any(t in ending.source for t in ('成功', '星阶提升', '智瞳点亮')) else
                                     'farm' if self.active['mode'] == 'first_station' else 'loss')
            self.progress.save('settling')
            if first_observation:
                logger.attr('DU settlement', ending.source)
                op.save('settlement_' + self.active['id'])
            if self._settlement_exit_wait.reached():
                op.click_text(('确认结算', '返回', '返回主界面', '确认', '完成'), (0.1, 0.65, 1, 1),
                              exact=True, interval=5)
            return True
        if self.active.get('pending_settlement'):
            if self.lobby_visible():
                if self.active.get('settlement_observed'):
                    return self.active.get('result', 'farm')
                # Login/reentry also returns here while the run is retained.
                # Open its entry to finish the requested exit, without counting
                # the lobby itself as evidence of a game settlement.
                op.click_text('开始游戏', (0.70, 0.84, 0.88, 0.94))
                return True
            if self.active.get('settlement_observed') and not self.world_visible():
                if self.is_in_main() and op.text('差分宇宙', (0.5, 0.25, 1, 0.85)):
                    return self.active.get('result', 'farm')
            if op.text(('祝福/全部', '奇物/全部'), (0.04, 0.035, 0.3, 0.11)):
                op.back()
                return True
            if op.click_text(('确认', '返回', '下一步'), (0.15, 0.45, 1, 1), exact=True):
                return True
        return None

    def weekly_points(self):
        labels = self.op.read_region((0.04, 0.79, 0.38, 0.98), snapshot=False)
        for box in labels:
            matched = re.search(r'(\d+)\s*/\s*(\d+)', box.source)
            if matched and int(matched[2]) >= 1000:
                return int(matched[1]), int(matched[2])
        return None

    def claim_points(self):
        op = self.op
        op.snapshot()
        if not self.lobby_visible():
            return
        opened = False
        timeout = Timer(45, count=3).start()
        while not timeout.reached():
            op.snapshot()
            if self.lobby_visible():
                if opened:
                    return
                if not op.click_text('积分奖励', (0, 0.7, 0.4, 1)) and self.weekly_points():
                    op.click_point(0.15, 0.93, tag='DU_POINT_REWARDS')
                continue
            if '积分奖励' in self.header_text() or op.text('积分奖励', (0, 0.15, 0.4, 0.4)):
                opened = True
                if not op.click_text(('一键领取', '领取'), (0.05, 0.2, 1, 1), exact=True):
                    op.back()
                continue
            if self.handle_reward():
                continue
            self.handle_misc()
        raise RuntimeError('积分奖励页面未能返回入口')
