"""Android port of StarRailAssistant's current Divergent Universe strategy.

AGPL-3.0; see THIRD_PARTY.md. Native SRC supplies login, screenshots, OCR,
joystick contacts, combat auto/speed controls and monthly reward handling.
"""
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
    EVENT_NAMES = frozenset(normalize(event.cn) for event in RogueEventTitle.instances.values())
    CHOICES = {
        'mask': ('选择一张面具', '选择面具'),
        'blessing': ('选择祝福', '选取祝福', '获取祝福'),
        'equation': ('选择方程', '获取方程'),
        'curio': ('选择奇物', '获取奇物'),
        'station_card': ('选择站点卡',),
        'miracle': ('选择惊世奇迹', '选择奇迹', '选择你的奇迹'),
        'area': ('选择区域', '人才管理阶段'),
        'effect': ('选择基础效果',),
        'discard': ('丢弃奇物', '丢弃祝福'),
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
                               action=lambda: self.op.click_text('开始游戏', (0.05, 0.65, 1, 1)) or self.op.back(),
                               name='演算入口')
            EntrySettings(self).prepare(self.config.DivergentUniverse_Calculation)

    def run(self):
        if self.config.Emulator_GameLanguage != 'cn':
            raise RequestHumanTakeover('差分宇宙当前适配简体中文 Android 界面')
        if self.config.DivergentUniverse_Runs < 0 or self.config.DivergentUniverse_RecoveryRetries < 0:
            raise RequestHumanTakeover('差分宇宙运行次数和恢复次数不能为负数')
        lock = STATE_DIR / f'{self.config.config_name}.controller.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(lock), timeout=0):
                self.progress = Progress(self.config.config_name)
                completed = 0
                failures = 0
                previous_progress = None
                while self.config.DivergentUniverse_Runs == 0 or completed < self.config.DivergentUniverse_Runs:
                    try:
                        self._initialize()
                        if not self.go_to_lobby():
                            break  # Explicit weekly point limit, not a completed run.
                        self.active = self.progress.begin(self.config.DivergentUniverse_Mode,
                                                          self.config.DivergentUniverse_Calculation)
                        result = self.play_run()
                        self.progress.finish(result)
                        completed += 1
                        failures = 0
                        logger.info(f'DU completed run {completed}: {result}')
                        self.config.load()
                        self.config.bind(self.config.task)
                    except TaskEnd:
                        self.progress.save('stopped')
                        raise
                    except RequestHumanTakeover:
                        self.progress.save('error')
                        raise
                    except Exception as error:
                        active = self.progress.data.get('active') or {}
                        milestone = (active.get('id'), active.get('battles'), active.get('station'))
                        if previous_progress is not None and milestone != previous_progress:
                            failures = 0
                        previous_progress = milestone
                        self.progress.data['error'] = str(error)
                        self.progress.save('error')
                        logger.exception(f'DU task failed: {type(error).__name__}: {error}')
                        save_error_log(config=self.config, device=self.device)
                        if failures >= self.config.DivergentUniverse_RecoveryRetries:
                            raise RequestHumanTakeover(f'差分宇宙自动恢复后仍失败，已保留现场：{error}') from error
                        failures += 1
                        logger.warning(f'DU recovery {failures}: restart game and resume the checkpoint: {error}')
                        try:
                            self.login_from_current(restart=True)
                        except TaskEnd:
                            self.progress.save('stopped')
                            raise
                        except Exception as restart_error:
                            logger.warning(f'DU login recovery did not finish: {restart_error}')
                            # The next initialization consumes the same bounded
                            # recovery budget instead of abandoning the loop.
                if self.config.DivergentUniverse_ClaimRewards:
                    self.claim_points()
                self.progress.save('finished')
        except Timeout:
            raise RequestHumanTakeover('该配置已有货币战争或差分宇宙控制进程，请先停止它')

    def _initialize(self):
        logger.attr('DU control revision', '2026-10-08-entry-17')
        self.active = self.progress.data.get('active')
        if self.active and self.active.get('station') in ('事件', '异常', '奖励', '财富', '铸造'):
            if not self.active.get('event_completed'):
                self.active['node_done'] = False
        folder = ROOT / 'log/divergent_universe' / self.config.config_name
        self.op = DivergentOperator(self.device, self.config, folder if self.config.DivergentUniverse_SaveEvidence else None)
        self.op.deadline = time.monotonic() + max(1, self.config.DivergentUniverse_MaxMinutes) * 60
        self._node_done = False
        self._entry_prepared = False
        self._native_event = None
        self._settlement_exit_wait = Timer(8)
        self._launch_attempts = 0
        self.combat_state_reset()
        if not self.device.app_is_running():
            self.login_from_current()

    def login_from_current(self, restart=False):
        from tasks.login.login import Login
        def resumed():
            self.op.image = self.device.image
            self.op._ocr_cache.clear()
            self.op.frame_cache.clear()
            return bool(self.world_visible() or self.selection_kind() or self.lobby_visible()
                        or self.op.text('差分宇宙', (0.02, 0, 0.27, 0.065))
                        or self.op.text('差分宇宙', (0.58, 0.45, 0.96, 0.68)))
        login = Login(self.config, device=self.device)
        login.login_expected_end = resumed
        if restart:
            login.app_stop()
        login.app_start()

    def header_text(self):
        if 'header' not in self.op.frame_cache:
            title = self.op.read_line((0.055, 0.046, 0.365, 0.096), snapshot=False).source
            known = [label for labels in self.CHOICES.values() for label in labels]
            known += ['选择下一站', '选择下一个站点', '欢愉假面', '方程展开', '祝福强化',
                      '获得奇物', '获得祝福', '事件', '常规演算', '周期演算', '模式选择']
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

    def world_visible(self):
        if 'world' not in self.op.frame_cache:
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
        return bool(self.op.text('开始游戏', (0.05, 0.65, 1, 1)))

    def go_to_lobby(self):
        from tasks.base.page import page_guide
        op = self.op
        timeout = Timer(150, count=3).start()
        unknown = Timer(8, count=3).start()
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
            if op.text(('探索成功', '探索失败', '探索中断'), (0.05, 0.05, 0.95, 0.4), exact=True):
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
            if self.is_in_main():
                interact = op.text('差分宇宙', (0.5, 0.25, 1, 0.82))
                if interact:
                    op.click_box(interact)
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
                op.click_text(('前往参与', '前往'), (0.5, 0.65, 1, 1), interval=3)
                unknown.reset()
                continue
            if op.text('差分宇宙', (0.1, 0.28, 0.82, 0.73)):
                if not op.click_text(('前往参与', '前往'), (0.5, 0.65, 1, 1)):
                    op.click_text('差分宇宙', (0.1, 0.28, 0.82, 0.73))
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
        if self.active.get('pending_settlement'):
            return False  # Blurred result pages are not a new mode-selection screen.
        from tasks.divergent_universe.entry import EntrySettings
        launch_labels = EntrySettings.LAUNCH
        if not self._entry_prepared and (op.text(launch_labels, (0.3, 0.65, 1, 1))
                                        or op.text(('常规演算', '周期演算'), (0, 0, 0.48, 0.88))):
            from tasks.divergent_universe.entry import EntrySettings
            EntrySettings(self).prepare(self.active.get('calculation', 'periodic'))
            self._entry_prepared = True
            return True
        launch = op.text(('启动「差分宇宙」', '启动差分宇宙', '进入星阶模式'), (0.3, 0.65, 1, 1))
        if launch and op.template('download_empty', (0.43, 0.78, 0.72, 0.96), confidence=0.93):
            self.prepare_downloads()
            return True
        if self.lobby_visible():
            op.click_text('开始游戏', (0.05, 0.65, 1, 1))
            return True
        if op.text(launch_labels, (0.3, 0.65, 1, 1)):
            op.click_text(launch_labels, (0.3, 0.65, 1, 1))
            return True
        return False

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
                if self._native_event is not None:
                    self._native_event.event_title = None
                if self.active.pop('event_pending', False):
                    self.active['event_completed'] = True
                    self.active['node_done'] = True
                    self._node_done = True
                    self.progress.save('event_finished')
                self.update_station_header()
                if self.active['mode'] == 'first_station' and (self.active['battles'] > 0 or self._node_done):
                    self.quit_run()
                elif not self._node_done and any(t in self.active['station'] for t in ('战斗', '精英', '首领', '转化')):
                    self.fight_station()
                else:
                    self.navigate_station()
                idle_since = time.monotonic()
                continue
            # Once the native event page is identified, avoid repeatedly OCRing
            # settlement dialogs and launch controls before every dialogue tap.
            if not self.selection_kind() and '事件' in self.header_text() and self.handle_misc():
                idle_since = time.monotonic()
                continue
            result = self.handle_settlement()
            if isinstance(result, str):
                return result
            if result:
                idle_since = time.monotonic()
                continue
            kind = self.selection_kind()
            if kind:
                self.progress.save('selecting_' + kind)
                self.handle_choice(kind)
                idle_since = time.monotonic()
                continue
            if self.active['mode'] == 'first_station' and op.text(('结束并结算', '退出并结算'), (0.05, 0.2, 1, 1)):
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
        if kind == 'mask':
            def mask_ready():
                return op.text('确定', (0.6, 0.8, 1, 1), exact=True)
            op.wait_until(mask_ready, action=lambda: op.click_text('面具', (0.03, 0.65, 0.5, 0.95)), name='面具确认页')
            self.confirm_selection(kind)
        else:
            priorities = tuple(p.strip() for p in (self.config.DivergentUniverse_ChoicePriority or '').split('>') if p.strip())
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
            choices = op.wait_until(choices_ready, name=kind + '卡片内容')
            if choices is page_changed:
                return  # The reward animation has already advanced to another page.
            op.save('choice_' + kind)
            choice = choose(choices, self.config.DivergentUniverse_PreferUncollected, priorities, discard=kind == 'discard')
            logger.info(f'DU choose {kind}: uncollected={choice.uncollected}, recommended={choice.recommended}, rarity={choice.rarity}, {choice.title}')
            op.click_point(choice.box.center[0] / 1280, (choice.box.top + choice.box.height * 0.3) / 720,
                           tag='DU_CHOICE_' + kind)
            self.confirm_selection(kind, choice=choice)
        self.active['selections'] += 1
        self.device.click_record_clear()
        self.progress.save()

    def confirm_selection(self, kind, choice=None):
        op = self.op
        names_region = ((0.08, 0.49, 0.96, 0.55) if kind == 'miracle' else
                        (0.07, 0.66, 0.95, 0.79) if kind == 'next_station' else
                        (0.08, 0.42, 0.96, 0.50))
        names_before = tuple(normalize(b.source) for b in op.read_region(names_region, snapshot=False))
        confirmed = False
        select_attempts = 1
        confirm_attempts = 0
        changed_frames = 0
        timeout = Timer(45, count=3).start()
        while not timeout.reached():
            op.snapshot()
            current = self.selection_kind()
            if current != kind:
                if current or self.world_visible() or self.is_combat_executing() or self.lobby_visible():
                    return
                if self.handle_misc():
                    return  # Obtained-reward page confirms this selection finished.
                # A blank/loading frame is not confirmation of a transition.
                continue
            names = tuple(normalize(b.source) for b in op.read_region(names_region, snapshot=False))
            changed_frames = changed_frames + 1 if confirmed and names and names != names_before else 0
            if changed_frames >= 2:
                return  # Another choice set of the same type has arrived.
            if choice is not None:
                # Retry the selected card only while confirmation remains grey.
                button = op.text(('确定', '确认', '确认选择', '选择', '丢弃', '确认丢弃'), (0.05, 0.65, 1, 1), exact=True)
                enabled = button and self.confirm_enabled(button)
                if confirmed and names and names != names_before and button and not enabled:
                    return  # New named cards plus a disabled confirm identify the next set.
                if not enabled:
                    if not confirmed and select_attempts < 3:
                        if op.click_point(choice.box.center[0] / 1280,
                                          (choice.box.top + choice.box.height * 0.3) / 720, tag='DU_CHOICE_' + kind):
                            select_attempts += 1
                    continue
            if confirm_attempts < 3 and op.click_text(('确定', '确认', '确认选择', '选择', '丢弃', '确认丢弃'),
                             (0.05, 0.65, 1, 1), exact=True):
                confirmed = True
                confirm_attempts += 1
        raise RuntimeError(f'差分宇宙{kind}选择未确认')

    def confirm_enabled(self, button):
        # Enabled DU confirmations have a light fill; disabled ones are dark.
        x, y = button.center
        region = self.op.image[max(0,y-12):y+13, max(0,x-100):max(1,x-55)]
        return region.size and float(cv2.cvtColor(region, cv2.COLOR_RGB2GRAY).mean()) > 130

    def choose_station(self):
        op = self.op
        order = [t.strip() for t in self.config.DivergentUniverse_StationPriority.split('>') if t.strip()]
        station_types = ('战斗', '精英', '首领', '转化', '商店', '事件', '铸造', '奖励', '休整', '异常', '财富')
        def candidates_ready():
            if self.selection_kind() == 'next_station':
                return op.match(station_types, (0.07, 0.65, 0.95, 0.83))
            return False
        def refresh_count():
            text = op.read_line((0.31, 0.87, 0.42, 0.92), snapshot=False).source
            count = re.search(r'(\d+)\s*$', text)
            return int(count[1]) if count else None
        candidates = op.wait_until(candidates_ready, name='站点候选')
        for attempt in range(4):
            target = next((box for word in order for box in candidates if word in box.source), None)
            if target or attempt == 3:
                break
            refresh = op.text(('刷新', '重掷', '重抽'), (0.1, 0.65, 0.95, 1))
            remaining = refresh_count()
            if not refresh or remaining is None or remaining <= 0:
                break
            popup_seen = False
            def rerolled():
                items = candidates_ready()
                current = refresh_count()
                return items if items and current is not None and current < remaining else False
            def reroll_action():
                nonlocal popup_seen
                if self.handle_popup_confirm():
                    popup_seen = True
                elif not popup_seen and refresh_count() == remaining:
                    op.click_text(('刷新', '重掷', '重抽'), (0.1, 0.65, 0.95, 1), interval=2)
            candidates = op.wait_until(rerolled, action=reroll_action, name='站点刷新')
        target = target or candidates[0]
        self.active['station'] = next((word for word in station_types if word in target.source), target.source)
        op.click_box(target)
        from tasks.divergent_universe.selection import Choice
        self.confirm_selection('next_station', choice=Choice(target, target.source))
        self._node_done = False
        self.active['node_done'] = False
        self.active.pop('navigation_reentry', None)
        self.active.pop('navigation_reentry_completed', None)
        self.progress.save('next_station')

    def move(self, direction, seconds=0.5, run=True):
        self.op.check()
        # The timer bounds a touch gesture, not a wait for the next page.
        # Screenshots continue during movement and can stop the gesture early.
        gesture = Timer(seconds)
        with JoystickContact(self) as stick:
            stick.set(direction, run=run)
            gesture.reset()
            while not gesture.reached():
                self.op.snapshot()
                if self.interaction_visible() or not self.world_visible():
                    break

    def interaction_visible(self):
        from tasks.combat.assets.assets_combat_interact import DUNGEON_COMBAT_INTERACT
        if self.appear(DU_INTERACT):
            return True
        # Shops contain NPC conversations (for example Ruan Mei). Their bubble
        # must not cancel every movement gesture toward the actual exit.
        return bool(self.appear(DUNGEON_COMBAT_INTERACT) and self.op.text(
            ('随意门', '前往下一区域', '战利品', '事件', '奖励'), (0.58, 0.48, 0.92, 0.70)))

    def handle_combat_interact(self, interval=2):
        from tasks.combat.assets.assets_combat_interact import DUNGEON_COMBAT_INTERACT
        if super().handle_combat_interact(interval=interval):
            return True
        return self.appear_then_click(DUNGEON_COMBAT_INTERACT, interval=interval)

    def fight_station(self):
        op = self.op
        self.progress.save('approaching_combat')
        if self.config.DivergentUniverse_UseTechnique:
            self.handle_map_E()
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
            if self.find_door():
                # On reconnect the game may have saved the cleared room before
                # our local reward checkpoint. Follow its visible exit first.
                self.navigate_station()
                return
            if attempt == 4:
                self.rotation_swipe(-40)
            self.move(0, 0.65 if attempt == 0 else 0.35)
            self.handle_map_A()
            attempt += 1
        # A retained run may already have cleared this room before the local
        # checkpoint was saved. Look for its exit before restarting the game.
        self.navigate_station()

    def combat_expected_end(self):
        # The generic SRC combat loop owns screenshots and auto/speed controls;
        # only its DU-specific end screens belong in this adapter.
        self.op.check()
        if time.monotonic() > self._du_combat_deadline:
            raise RuntimeError('差分宇宙战斗等待超时')
        self.op.image = self.device.image
        self.op._ocr_cache.clear()
        self.op.frame_cache.clear()
        return bool(self.selection_kind() or self.world_visible()
                    or self.op.text(('获得祝福', '获得奇物', '方程展开'), (0, 0, 1, 0.24))
                    or self.op.text(('探索成功', '探索失败', '探索中断'), (0.04, 0.05, 0.95, 0.4), exact=True))

    def combat_execute(self, expected_end=None):
        self.progress.save('combat')
        self._du_combat_deadline = time.monotonic() + 600
        super().combat_execute(expected_end=expected_end or self.combat_expected_end)
        self.active['battles'] += 1
        self._node_done = True
        self.active['node_done'] = True
        self.progress.save('combat_finished')

    def find_door(self):
        # The sleeping portal is locked until this room's events are finished.
        # Its pink frame also matches an open portal, so reject the visible Z.
        if self.op.template_matches(str(self.op.templates / 'door_sleeping.png'),
                                    (0.30, 0, 0.93, 0.67), confidence=0.72,
                                    scales=np.geomspace(0.4, 2.5, 28)):
            return None
        # DU's door is a distinct pink prop with two round eyes. Recognize the
        # stable eye feature first: glow changes make a narrow HSV range lose
        # the portal between adjacent frames, and pink hair is not a portal.
        found = []
        for name in ('door_eyes', 'door_eyes_front', 'door_eyes_narrow', 'door_eyes_side'):
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
            if found:
                break
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
        return max(found, key=lambda box: box.score) if found else None

    def event_direction(self, target):
        # DU event plaques are much taller than SU's exit nameplates. Passing
        # their high label directly to the SU projection makes a nearby event
        # look almost entirely sideways. Use the observed plaque's bottom.
        gray = cv2.cvtColor(self.op.image, cv2.COLOR_RGB2GRAY)
        contours, _ = cv2.findContours(cv2.Canny(gray, 60, 140), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        tx, ty = target.center
        plaques = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if (abs(x + w / 2 - tx) < w * 0.3 and ty < y < ty + 150
                    and 40 <= w <= 340 and 70 <= h <= 450 and 1.2 < h / w < 4
                    and 260 < y + h < 580):
                plaques.append((x, y, w, h))
        if plaques:
            x, y, w, h = max(plaques, key=lambda box: box[2] * box[3])
            return RogueExit.screen2direction((x + w / 2, y + h), at_floor=True)
        return RogueExit.screen2direction(target.center)

    def navigate_station(self):
        op = self.op
        self.progress.save('navigating')
        # Same operation boundary as MapControl._goto: previous combat
        # attacks must not be counted as repeated navigation clicks.
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        searches = 0
        side_steps = 0
        repositioned = False
        last_direction = None
        missing = Timer(2, count=2).start()
        timeout = Timer(300, count=3).start()
        step = 0
        while not timeout.reached():
            op.snapshot()
            if self.config.DivergentUniverse_SaveEvidence:
                from module.base.utils import save_image
                folder = ROOT / 'log/divergent_universe' / self.config.config_name
                save_image(op.image, folder / f'navigation_{step:02d}.png')
            step += 1
            # Handle a nearby exit before slower selection OCR. The prompt can
            # disappear as the last movement animation finishes.
            if self.interaction_visible() and op.text(
                    ('随意门', '前往下一区域', '战利品', '事件', '奖励'), (0.58, 0.48, 0.92, 0.70)):
                if self.handle_combat_interact(interval=1):
                    continue
            if not self.world_visible():
                if self.selection_kind():
                    return
                if self.is_combat_executing():
                    self.combat_execute()
                    return
                if op.text(('探索成功', '探索失败', '探索中断'), (0.04, 0.05, 0.95, 0.4), exact=True):
                    return
                if self.handle_misc():
                    return
                continue
            if (self.active['station'] in ('事件', '奖励', '异常', '财富', '铸造')
                    and self.handle_combat_interact(interval=1)):
                continue
            # Some abnormal rooms contain several events. Finishing one must
            # not suppress the remaining question-mark plaques in this room.
            if self.active['station'] in ('事件', '奖励', '异常', '财富', '铸造'):
                # Nearby event plaques put their labels against the top edge.
                # Keep the world HUD on the left out of this search.
                targets = op.read_region((0.30, 0, 0.80, 0.46), snapshot=False)
                unknown = [box for box in targets if re.fullmatch(r'[?？\s]{2,}', box.source)
                           or normalize(box.source) in self.EVENT_NAMES]
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
                    logger.info(f'DU event target: {target.center}, score={target.score:.3f}')
                    direction = self.event_direction(target)
                    near = target.center[1] < 110
                    self.move(direction, 0.25 if near else 0.5, run=not near)
                    last_direction = direction
                    searches = 0
                    missing.reset()
                    continue
                # Revealed abnormal events use an eye plaque without a ???
                # label; they still need interaction before the door wakes.
                plaques = []
                for template in ('event_unknown_board', 'event_anomaly_board', 'event_reward_board'):
                    plaques = op.template_matches(str(op.templates / f'{template}.png'),
                                                  (0.30, 0.10, 0.86, 0.75), confidence=0.80,
                                                  scales=np.geomspace(0.6, 3.5, 61))
                    if plaques:
                        break
                if plaques:
                    target = max(plaques, key=lambda box: box.score)
                    direction = RogueExit.screen2direction(
                        (target.center[0], min(580, target.top + target.height)), at_floor=True)
                    logger.info(f'DU revealed event plaque: {target.center}, score={target.score:.3f}')
                    self.move(direction, 0.25 if target.height > 220 else 0.5,
                              run=target.height <= 220)
                    last_direction = direction
                    searches = 0
                    missing.reset()
                    continue
            door = self.find_door()
            if door:
                searches = 0
                missing.reset()
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
                    self.move(90 if right >= left else -90, 0.6, run=False)
                    side_steps += 1
                    last_direction = None
                    continue
                # DU supplies its unique door's screen anchor. Perspective
                # projection and movement direction are the native SU method.
                # DU has a much taller portal and no SU domain label. Its
                # floor contact is the compatible native projection anchor.
                ratio = 1 if door.source == 'door_edge' else 4 if door.source.startswith('door_top') else 2.45
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
                near = door.source == 'door_edge' or door.height > 70
                self.move(direction, 0.25 if near else 0.6, run=not near)
                last_direction = direction
            elif last_direction is not None:
                self.move(last_direction, 0.3)
                last_direction = None
            else:
                # Keep checking this view while the post-combat animation or
                # a stale screenshot clears; turn only after repeated misses.
                if not missing.reached():
                    continue
                searches += 1
                if searches >= 9:
                    if (not repositioned and self.active['station'] in
                            ('事件', '奖励', '异常', '财富', '铸造')):
                        # SRA retries an event scan from closer range. DU hides
                        # plaque labels at a distance, so rotating at the same
                        # spawn point forever cannot reveal them.
                        logger.info('DU event labels not visible; approach once and rescan')
                        self.move(0, 0.6)
                        repositioned = True
                        searches = 0
                        missing.reset()
                        timeout.reset()
                        self.device.click_record_clear()
                        continue
                    if not self.active.get('navigation_reentry_completed'):
                        self.reenter_station()
                        return
                    break
                self.rotation_swipe(-45)
                missing.reset()
        raise RuntimeError('差分宇宙未找到可交互的事件或随意门')

    def reenter_station(self):
        op = self.op
        logger.info('DU exit search exhausted; leave temporarily and resume the same run')
        left = False
        timeout = Timer(90, count=3).start()
        while not timeout.reached():
            op.snapshot()
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

    def handle_misc(self):
        op = self.op
        if self.world_visible():
            return False
        title = self.header_text()
        if any(word in title for word in ('方程展开', '祝福强化', '获得奇物', '获得祝福')):
            if not op.click_text(('确定', '确认', '继续', '点击空白处关闭'), (0.1, 0.6, 1, 1)):
                op.back()
            return True
        if '事件' in title:
            if not self.active.get('event_pending'):
                self.active['event_pending'] = True
                self.progress.save('event')
            from tasks.rogue.event.event import RogueEvent
            from tasks.rogue.assets.assets_rogue_event import CHOOSE_OPTION_CONFIRM, CHOOSE_STORY
            from tasks.rogue.assets.assets_rogue_ui import PAGE_EVENT
            if self._native_event is None:
                self._native_event = RogueEvent(self.config, device=self.device)
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
            elif handler.handle_event_continue():
                return True
            elif op.template('event_next', (0.3, 0.4, 1, 1)):
                op.click_point(0.78, 0.79, tag='DU_EVENT_DIALOGUE')
            return True
        if op.click_text(('点击空白处关闭', '点击空白处继续'), (0, 0.5, 1, 1)):
            return True
        return self.handle_tutorial()

    def update_station_header(self):
        labels = self.op.read_region((0.025, 0, 0.5, 0.065), snapshot=False)
        text = ' '.join(box.source for box in labels)
        number = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if not number or not 1 <= int(number[1]) <= int(number[2]) <= 30:
            return
        node = int(number[1])
        previous = self.active.get('node')
        if previous is not None and previous != node:
            self._node_done = False
            self.active['node_done'] = False
            self.active.pop('navigation_reentry', None)
            self.active.pop('navigation_reentry_completed', None)
            self.active.pop('event_completed', None)
        self.active['node'] = node
        for station in ('战斗', '精英', '首领', '转化', '商店', '事件', '铸造', '奖励', '休整', '异常', '财富'):
            if station in text:
                self.active['station'] = station
                break
        if previous != node:
            logger.info(f'DU entered node {node}: {self.active["station"]}')
            self.progress.save('node_entered')

    def quit_run(self):
        op = self.op
        timeout = Timer(60, count=3).start()
        while not timeout.reached():
            op.snapshot()
            if op.click_text(('结束并结算', '退出并结算'), (0.05, 0.2, 1, 1)):
                self.active['pending_settlement'] = True
                self.progress.save('settling')
                return
            if op.text(('探索成功', '探索失败', '探索结束', '探索终止', '探索中断'), (0.04, 0.05, 0.95, 0.4), exact=True):
                return
            if self.world_visible():
                op.back()
            else:
                self.handle_misc()
        raise RuntimeError('未能打开差分宇宙结束并结算入口')

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
        if op.text('确定要结束进程', (0.2, 0.2, 0.9, 0.5)):
            self.active['pending_settlement'] = True
            if op.click_text('确认', (0.5, 0.5, 0.85, 0.86), exact=True):
                self.active['settlement_confirmed'] = True
                self.progress.save('settling')
            return True
        ending = op.text(('探索成功', '探索失败', '探索结束', '探索终止', '探索中断', '演算结束'),
                         (0.05, 0.05, 0.95, 0.4), exact=True)
        if ending:
            first_observation = not self.active.get('settlement_observed')
            self.active['pending_settlement'] = True
            self.active['settlement_observed'] = True
            self.active['result'] = 'win' if '成功' in ending.source else 'farm' if self.active['mode'] == 'first_station' else 'loss'
            self.progress.save('settling')
            if first_observation:
                logger.attr('DU settlement', ending.source)
                op.save('settlement_' + self.active['id'])
            if self._settlement_exit_wait.reached():
                op.click_text(('返回', '返回主界面', '确认', '完成'), (0.1, 0.65, 1, 1),
                              exact=True, interval=5)
            return True
        if self.active.get('pending_settlement'):
            if self.lobby_visible():
                return self.active.get('result', 'farm')
            if (self.active.get('settlement_confirmed') or self.active.get('settlement_observed')) and not self.world_visible():
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
