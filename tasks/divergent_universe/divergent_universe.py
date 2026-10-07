"""Android port of StarRailAssistant's current Divergent Universe strategy.

AGPL-3.0; see THIRD_PARTY.md. Native SRC supplies login, screenshots, OCR,
joystick contacts, combat auto/speed controls and monthly reward handling.
"""
import re
import time

import cv2
import numpy as np
from filelock import FileLock, Timeout

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
from tasks.dungeon.keywords import KEYWORDS_DUNGEON_TAB
from tasks.map.control.joystick import JoystickContact
from tasks.map.control.control import MapControl
from tasks.rogue.route.exit import RogueExit


class DivergentUniverse(DungeonUINav, MapControl):
    INTERACT_BUTTON = DU_INTERACT
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
                        self.active = self.progress.begin(self.config.DivergentUniverse_Mode)
                        result = self.play_run()
                        self.progress.finish(result)
                        completed += 1
                        failures = 0
                        logger.info(f'DU completed run {completed}: {result}')
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
                        save_error_log(config=self.config, device=self.device)
                        if failures >= self.config.DivergentUniverse_RecoveryRetries:
                            raise RequestHumanTakeover(f'差分宇宙自动恢复后仍失败，已保留现场：{error}') from error
                        failures += 1
                        logger.warning(f'DU recovery {failures}: restart game and resume the checkpoint: {error}')
                        from tasks.login.login import Login
                        login = Login(self.config, device=self.device)
                        try:
                            login.app_stop()
                            login.app_start()
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
        if not self.device.app_is_running():
            from tasks.login.login import Login
            Login(self.config, device=self.device).app_start()
        folder = ROOT / 'log/divergent_universe' / self.config.config_name
        self.op = DivergentOperator(self.device, self.config, folder if self.config.DivergentUniverse_SaveEvidence else None)
        self.op.deadline = time.monotonic() + max(1, self.config.DivergentUniverse_MaxMinutes) * 60
        self._node_done = False
        self._launch_attempts = 0
        self.combat_state_reset()

    def selection_kind(self):
        op = self.op
        if op.text(('选择下一站', '选择下一个站点'), (0.02, 0, 0.4, 0.13)):
            return 'next_station'
        if op.text('选择一张面具', (0.48, 0.58, 0.98, 0.83)):
            return 'mask'
        if op.text('欢愉假面', (0, 0, 0.3, 0.15)) and op.text('确定', (0.6, 0.8, 1, 1), exact=True):
            return 'mask'
        for kind, labels in self.CHOICES.items():
            if op.text(labels, (0.02, 0, 0.96, 0.23)):
                return kind
        if op.text(('选择下一个站点', '选择下一站'), (0.1, 0, 0.95, 0.25)):
            return 'next_station'
        if op.template('select_next_station', (0.1, 0, 0.9, 0.25), confidence=0.9):
            return 'next_station'
        return None

    def world_visible(self):
        # Attack artwork changes with the active character. The DU plane/
        # station header and exit control identify the map independently.
        from tasks.base.assets.assets_base_page import MAP_EXIT_OE
        return bool((self.op.template('world_menu', (0.09, 0.04, 0.20, 0.15), confidence=0.90)
                     or self.op.text('位面', (0, 0, 0.45, 0.075)))
                    and (self.appear(MAP_EXIT_OE) or self.op.template('divergent_universe_quit', (0, 0, 0.13, 0.18))))

    def lobby_visible(self):
        return bool(self.op.text('开始游戏', (0.05, 0.65, 1, 1)))

    def go_to_lobby(self):
        op = self.op
        deadline = time.monotonic() + 150
        chose_du = False
        unknown_since = time.monotonic()
        initial_saved = False
        while time.monotonic() < deadline:
            op.snapshot()
            if not initial_saved:
                op.save('entry_initial')
                initial_saved = True
            if op.text('确认退出游戏', (0.25, 0.3, 0.8, 0.65)):
                op.click_text('取消', (0.25, 0.4, 0.55, 0.7), after_sleep=0.5, exact=True)
                continue
            if op.text('积分奖励', (0, 0.15, 0.4, 0.4)):
                op.back()
                continue
            if self.lobby_visible():
                if self.config.DivergentUniverse_StopAtWeeklyLimit:
                    points = self.weekly_points()
                    if points and points[0] >= points[1]:
                        logger.info('DU weekly point limit reached')
                        return False
                return True
            if self.selection_kind() or self.world_visible():
                logger.info('DU resume current exploration')
                return True
            if self.is_combat_executing():
                if not self.progress.data.get('active'):
                    raise RequestHumanTakeover('当前正在战斗且没有差分宇宙接管记录，请先返回差分宇宙入口')
                return True
            if op.text(('探索成功', '探索失败', '探索结束', '探索终止', '探索中断'), (0.04, 0.05, 0.95, 0.4), exact=True):
                return True
            if op.text(('结束并结算', '退出并结算'), (0.05, 0.2, 1, 1)):
                return True
            if op.text('确定要结束进程', (0.2, 0.2, 0.9, 0.5)):
                return True
            if op.text(('周期演算', '常规演算'), (0, 0, 1, 0.9)):
                return True
            if op.text(('稳态数组', '拟合等级', '模因拓扑', '差分图鉴', '演算记录'), (0, 0, 0.55, 0.16)):
                op.back()
                unknown_since = time.monotonic()
                continue
            if op.click_text(('点击空白处关闭', '点击空白处继续'), (0, 0.6, 1, 1), after_sleep=0.6):
                continue
            if op.text('差分宇宙', (0.1, 0.28, 0.82, 0.73)) and not chose_du:
                op.click_text('差分宇宙', (0.1, 0.28, 0.82, 0.73), after_sleep=0.8)
                chose_du = True
                unknown_since = time.monotonic()
                continue
            if chose_du and op.click_text(('前往参与', '前往'), (0.5, 0.65, 1, 1), after_sleep=2):
                unknown_since = time.monotonic()
                continue
            interact = op.text('差分宇宙', (0.5, 0.25, 1, 0.82))
            if interact and self.is_in_main():
                op.click_box(interact, after_sleep=2)
                unknown_since = time.monotonic()
                continue
            if self.is_in_main():
                self.dungeon_tab_goto(KEYWORDS_DUNGEON_TAB.Simulated_Universe)
                unknown_since = time.monotonic()
                continue
            if self.handle_popup_confirm() or self.ui_additional():
                continue
            if time.monotonic() - unknown_since > 15:
                op.save('entry_unknown')
                raise RuntimeError('差分宇宙入口页面未识别，已保留现场')
            op.sleep(0.5)
        raise RuntimeError('未能进入差分宇宙周期演算入口')

    def start_or_resume(self):
        op = self.op
        launch = op.text(('启动「差分宇宙」', '启动差分宇宙'), (0.3, 0.65, 1, 1))
        if launch and op.template('download_empty', (0.43, 0.78, 0.72, 0.96), confidence=0.93):
            self.prepare_downloads()
            return True
        if launch:
            if self._launch_attempts >= 3:
                op.save('launch_not_advancing')
                raise RuntimeError('差分宇宙启动页未推进，请检查已下载的队伍和难度')
            self._launch_attempts += 1
        if op.click_text('开始游戏', (0.05, 0.65, 1, 1), after_sleep=1):
            return True
        if op.text('周期演算', (0, 0, 1, 0.85)):
            # Select the requested calculation before launching/continuing.
            if not getattr(self, '_periodic_selected', False):
                op.click_text('周期演算', (0, 0, 1, 0.85), after_sleep=0.8)
                self._periodic_selected = True
                return True
            if op.click_text(('继续进度', '启动「差分宇宙」', '启动差分宇宙'), (0.3, 0.65, 1, 1), after_sleep=1):
                return True
        if op.click_text(('启动「差分宇宙」', '启动差分宇宙', '继续进度'), (0.3, 0.65, 1, 1), after_sleep=1):
            return True
        return False

    def prepare_downloads(self):
        op = self.op
        empty = op.template('download_empty', (0.43, 0.78, 0.72, 0.96), confidence=0.93)
        if not empty:
            return
        op.click_box(empty, after_sleep=0.8)
        op.snapshot()
        op.save('download_picker')
        from tasks.abyss.prep import AbyssPrep
        from tasks.abyss.assets.assets_abyss_prep import TAB_PRESET_CHECK, TAB_PRESET_CLICK
        picker = AbyssPrep(config=self.config, device=self.device)
        if op.click_text(('当前队伍', '当前编队'), (0, 0, 1, 1), after_sleep=0.5):
            pass
        elif picker.appear(TAB_PRESET_CHECK) or picker.appear(TAB_PRESET_CLICK):
            if not picker.appear(TAB_PRESET_CHECK):
                self.device.click(TAB_PRESET_CLICK)
                op.sleep(0.5)
            picker._abyss_click_preset(self.config.DivergentUniverse_TeamPreset)
        elif op.click_text(('预设编队', '队伍预设'), (0, 0, 0.6, 0.35), after_sleep=0.5):
            picker._abyss_click_preset(self.config.DivergentUniverse_TeamPreset)
        else:
            raise RuntimeError('角色下载面板未识别到当前队伍或预设编队入口')
        for _ in range(6):
            op.snapshot()
            if op.text(('启动「差分宇宙」', '启动差分宇宙'), (0.3, 0.65, 1, 1)):
                if not op.template('download_empty', (0.43, 0.78, 0.72, 0.96), confidence=0.93):
                    return
            if not op.click_text(('下载', '确认', '应用'), (0.45, 0.65, 1, 1), after_sleep=0.7, exact=True):
                op.sleep(0.5)
        raise RuntimeError('差分宇宙队伍下载未确认')

    def play_run(self):
        op = self.op
        idle_since = time.monotonic()
        self._periodic_selected = False
        self._node_done = self.active.get('node_done', False)
        while True:
            op.snapshot()
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
            if self.world_visible():
                self.update_station_header()
                if self.active['mode'] == 'first_station' and (self.active['battles'] > 0 or self._node_done):
                    self.quit_run()
                elif not self._node_done and any(t in self.active['station'] for t in ('战斗', '精英', '首领', '转化')):
                    self.fight_station()
                else:
                    self.navigate_station()
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
                raise RuntimeError('差分宇宙画面45秒未能推进')
            op.sleep(0.5)

    def handle_choice(self, kind):
        op = self.op
        if kind == 'next_station':
            self.choose_station()
            return
        if kind == 'mask':
            if op.text('确定', (0.6, 0.8, 1, 1), exact=True):
                self.confirm_selection(kind)
                self.active['selections'] += 1
                self.progress.save()
                return
            masks = op.match('面具', (0.03, 0.65, 0.50, 0.95))
            if not masks:
                raise RuntimeError('面具选择页未识别到可选面具')
            logger.info(f'DU choose mask: {masks[0].source}')
            op.click_box(masks[0], after_sleep=0.5)
            self.confirm_selection(kind)
            self.active['selections'] += 1
            self.progress.save()
            return
        priorities = tuple(p.strip() for p in (self.config.DivergentUniverse_ChoicePriority or '').split('>') if p.strip())
        # Titles can appear before the cards and collection badges finish
        # fading in. Decide from the stable frame also saved as evidence.
        op.sleep(0.6)
        op.snapshot()
        op.save('choice_' + kind)
        for _ in range(4):
            choices = read_choices(op, kind)
            if any(c.title or c.uncollected for c in choices):
                break
            op.sleep(0.5)
            op.snapshot()
        else:
            raise RuntimeError(f'{kind}卡片内容尚未加载完成')
        choice = choose(choices, self.config.DivergentUniverse_PreferUncollected, priorities, discard=kind == 'discard')
        logger.info(f'DU choose {kind}: uncollected={choice.uncollected}, recommended={choice.recommended}, {choice.title}')
        # Avoid the collection badge and title; tap the observed card body.
        op.click_point(choice.box.center[0] / 1280, (choice.box.top + choice.box.height * 0.3) / 720,
                       after_sleep=0.4, tag='DU_CHOICE_' + kind)
        self.confirm_selection(kind)
        self.active['selections'] += 1
        self.progress.save()

    def confirm_selection(self, kind):
        op = self.op
        op.snapshot()
        before = cv2.resize(op.image[140:600, 180:1160], (80, 40))
        names_before = tuple(normalize(b.source) for b in op.read_region((0.10, 0.30, 0.95, 0.58), snapshot=False))
        for _ in range(6):
            op.snapshot()
            if self.selection_kind() != kind:
                return
            current_names = tuple(normalize(b.source) for b in op.read_region((0.10, 0.30, 0.95, 0.58), snapshot=False))
            if current_names and names_before and current_names != names_before:
                return
            if op.click_text(('确定', '确认', '确认选择', '选择', '丢弃', '确认丢弃'), (0.05, 0.65, 1, 1), after_sleep=0.9, exact=True):
                op.snapshot()
                after = cv2.resize(op.image[140:600, 180:1160], (80, 40))
                names_after = tuple(normalize(b.source) for b in op.read_region((0.10, 0.30, 0.95, 0.58), snapshot=False))
                if self.selection_kind() != kind or names_after != names_before or np.abs(before.astype(float) - after).mean() > 18:
                    return
            else:
                op.sleep(0.4)
        raise RuntimeError(f'差分宇宙{kind}选择未确认')

    def choose_station(self):
        op = self.op
        order = [t.strip() for t in self.config.DivergentUniverse_StationPriority.split('>') if t.strip()]
        station_types = ('战斗', '精英', '首领', '转化', '商店', '事件', '铸造', '奖励', '休整', '异常', '财富')
        for attempt in range(4):
            candidates = op.match(station_types, (0.07, 0.4, 0.95, 0.83))
            target = next((b for t in order for b in candidates if t in b.source), None)
            if target or attempt == 3:
                break
            if not op.click_text(('刷新', '重掷', '重抽'), (0.1, 0.65, 0.95, 1), after_sleep=0.6):
                break
            op.snapshot()
            # Current SRA also confirms the reroll popup, when present.
            if not self.selection_kind():
                op.click_text('确认', (0.25, 0.4, 0.95, 0.85), after_sleep=0.6, exact=True)
            op.snapshot()
        if not candidates:
            raise RuntimeError('未识别到可选择的差分宇宙站点')
        target = target or candidates[0]
        self.active['station'] = next((t for t in station_types if t in target.source), target.source)
        op.click_box(target, after_sleep=0.4)
        self.confirm_selection('next_station')
        self._node_done = False
        self.active['node_done'] = False
        self.active.pop('navigation_reentry', None)
        self.progress.save('next_station')

    def move(self, direction, seconds=0.5, run=True):
        self.op.check()
        with JoystickContact(self) as stick:
            stick.set(direction, run=run)
            self.op.sleep(seconds)
        # Read the position after finger release, not the last running frame.
        self.op.sleep(0.3)

    def fight_station(self):
        op = self.op
        self.progress.save('approaching_combat')
        if self.config.DivergentUniverse_UseTechnique:
            self.handle_map_E()
            op.sleep(0.5)
        for attempt in range(8):
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
                    continue
                op.sleep(0.5)
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
            op.sleep(0.7)
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
        # DU's door is a distinct pink prop with two round eyes. Recognize the
        # stable eye feature first: glow changes make a narrow HSV range lose
        # the portal between adjacent frames, and pink hair is not a portal.
        found = []
        for name in ('door_eyes', 'door_eyes_narrow', 'door_eyes_side'):
            eyes = self.op.template_matches(str(self.op.templates / f'{name}.png'),
                                            (0.14, 0.12, 0.93, 0.80), confidence=0.72,
                                            # Dense sizes plus perspective
                                            # variants cover far and side views.
                                            scales=np.geomspace(0.4, 4.5, 35))
            for eye in eyes:
                if eye.top + eye.height * 2.45 <= 260:
                    continue  # The inferred floor must be below the horizon.
                crop = self.op.image[eye.top:eye.top + eye.height, eye.left:eye.left + eye.width]
                hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
                pink = cv2.inRange(hsv, np.array((135, 40, 80)), np.array((179, 255, 255)))
                if np.count_nonzero(pink) / pink.size >= 0.12:
                    found.append(eye)
            if found:
                break
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
                # Eye/window cutouts can split the pink edge. Its cyan border
                # continues to the floor, so retain that full vertical extent.
                border = hsv[:, max(0, x - 25):x + w + 26]
                light = cv2.inRange(border, np.array((75, 50, 140)), np.array((115, 255, 255)))
                rows = np.flatnonzero(np.count_nonzero(light, axis=1) >= 3)
                bottom = max(y + h, int(rows[-1]) + 1) if len(rows) else y + h
                found.append(Box(x + 380, y + 75, w, bottom - y, 'door_edge', coverage))
        return max(found, key=lambda box: box.score) if found else None

    def navigate_station(self):
        op = self.op
        self.progress.save('navigating')
        # Same operation boundary as MapControl._goto: previous combat
        # attacks must not be counted as repeated navigation clicks.
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        searches = 0
        side_steps = 0
        last_direction = None
        for step in range(36):
            op.snapshot()
            if self.config.DivergentUniverse_SaveEvidence:
                from module.base.utils import save_image
                folder = ROOT / 'log/divergent_universe' / self.config.config_name
                save_image(op.image, folder / f'navigation_{step:02d}.png')
            # Handle a nearby exit before slower selection OCR. The prompt can
            # disappear as the last movement animation finishes.
            if self.appear(DU_INTERACT) and op.text(
                    ('随意门', '前往下一区域', '战利品', '事件', '奖励'), (0.58, 0.48, 0.92, 0.70)):
                if self.handle_combat_interact(interval=1):
                    op.sleep(1.5)
                    continue
            if self.selection_kind():
                return
            if self.is_combat_executing():
                self.combat_execute()
                return
            if op.text(('探索成功', '探索失败', '探索中断'), (0.04, 0.05, 0.95, 0.4), exact=True):
                return
            if self.handle_misc():
                continue
            if not self.world_visible():
                op.sleep(0.5)
                continue
            # Floating object names are not touch controls. Interact only in
            # the Android prompt area, after approaching the object.
            interaction = op.text(('随意门', '前往下一区域', '战利品', '事件', '奖励'), (0.58, 0.48, 0.92, 0.70))
            if interaction:
                if self.handle_combat_interact(interval=1):
                    op.sleep(0.5)
                    continue
            if (not self._node_done and self.active['station'] in ('事件', '奖励', '异常', '财富', '铸造')
                    and self.handle_combat_interact(interval=1)):
                op.sleep(0.8)
                continue
            door = self.find_door()
            if door:
                searches = 0
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
                bottom = door.top + door.height * (1 if door.source == 'door_edge' else 2.45)
                # A close portal can extend below the screenshot. Keep its
                # visible target in front of the native player foot plane.
                bottom = min(bottom, 610)
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
                searches += 1
                if searches >= 9:
                    if not self.active.get('navigation_reentry'):
                        self.reenter_station()
                        return
                    break
                self.rotation_swipe(-45)
        raise RuntimeError('差分宇宙未找到可交互的事件或随意门')

    def reenter_station(self):
        """SRA's retained-progress fallback when the DU exit is occluded."""
        op = self.op
        logger.info('DU exit search exhausted; leave temporarily and resume the same run')
        op.back()
        op.sleep(2)
        deadline = time.monotonic() + 60
        left = False
        while time.monotonic() < deadline:
            op.snapshot()
            if not left and op.click_text(('暂离', '暂时离开'), (0.3, 0.3, 1, 1), after_sleep=1):
                left = True
                self.active['navigation_reentry'] = True
                self.progress.save('reentering')
                continue
            if left:
                if self.lobby_visible() or (self.is_in_main() and not self.world_visible()):
                    self._periodic_selected = False
                    self.device.click_record_clear()
                    self.go_to_lobby()
                    return
                if op.text('暂离', (0.2, 0.2, 0.9, 0.6)):
                    op.click_text('确认', (0.4, 0.4, 0.9, 0.9), after_sleep=0.6, exact=True)
            op.sleep(0.5)
        raise RuntimeError('差分宇宙暂离后未能返回入口，当前进度已保留')

    def handle_misc(self):
        op = self.op
        if op.text(('方程展开', '祝福强化', '获得奇物', '获得祝福'), (0, 0, 1, 0.24)):
            for _ in range(6):
                if op.click_text(('确定', '确认', '继续', '点击空白处关闭'), (0.1, 0.6, 1, 1), after_sleep=0.5):
                    return True
                op.sleep(0.5)
                op.snapshot()
                if not op.text(('方程展开', '祝福强化', '获得奇物', '获得祝福'), (0, 0, 1, 0.24)):
                    return True
            # Some expansion panels have a return arrow rather than a footer.
            op.back()
            return True
        if op.text('事件', (0, 0, 0.36, 0.2)) and not self.world_visible():
            self._node_done = True
            self.active['node_done'] = True
            arrow = op.template('event_select', (0.3, 0.2, 1, 0.9))
            star = op.template('event_selection', (0.3, 0.2, 1, 0.9))
            if star or arrow:
                op.click_box(star or arrow, after_sleep=0.5)
                if star:
                    op.snapshot()
                    op.click_text(('确认', '确定'), (0.3, 0.4, 1, 1), after_sleep=0.5, exact=True)
            elif not op.click_text(('继续', '确认'), (0.3, 0.4, 1, 1), after_sleep=0.5):
                op.click_point(0.78, 0.79, after_sleep=0.5, tag='DU_EVENT_DIALOGUE')
            return True
        if op.click_text(('点击空白处关闭', '点击空白处继续'), (0, 0.5, 1, 1), after_sleep=0.6):
            return True
        if self.handle_tutorial():
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
        if previous is not None and previous != node:
            self._node_done = False
            self.active['node_done'] = False
            self.active.pop('navigation_reentry', None)
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
        opened_at = 0
        deadline = time.monotonic() + 40
        captured = False
        while time.monotonic() < deadline:
            op.snapshot()
            if op.click_text(('结束并结算', '退出并结算'), (0.05, 0.2, 1, 1), after_sleep=0.8):
                self.active['pending_settlement'] = True
                self.progress.save('settling')
                return
            if op.text(('探索成功', '探索失败', '探索结束', '探索终止', '探索中断'), (0.04, 0.05, 0.95, 0.4), exact=True):
                return
            if self.world_visible() and time.monotonic() - opened_at > 5:
                op.back()
                opened_at = time.monotonic()
                op.sleep(2)
            elif not captured and op.image.mean() > 10 and not self.world_visible():
                op.save('quit_menu')
                captured = True
            else:
                op.sleep(0.5)
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
        if op.text('确认退出游戏', (0.25, 0.3, 0.8, 0.65)):
            op.click_text('取消', (0.25, 0.4, 0.55, 0.7), after_sleep=0.5, exact=True)
            return True
        if op.text('确定要结束进程', (0.2, 0.2, 0.9, 0.5)):
            self.active['pending_settlement'] = True
            if op.click_text('确认', (0.5, 0.5, 0.85, 0.86), after_sleep=1, exact=True):
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
            op.click_text(('返回', '返回主界面', '确认', '完成'), (0.1, 0.65, 1, 1), after_sleep=1, exact=True)
            return True
        if self.active.get('pending_settlement'):
            if self.lobby_visible():
                return self.active.get('result', 'farm')
            if (self.active.get('settlement_confirmed') or self.active.get('settlement_observed')) and not self.world_visible():
                if self.is_in_main() and op.text('差分宇宙', (0.5, 0.25, 1, 0.85)):
                    return self.active.get('result', 'farm')
            if op.click_text(('确认', '返回', '下一步'), (0.15, 0.45, 1, 1), after_sleep=0.8, exact=True):
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
        if not op.click_text('积分奖励', (0, 0.7, 0.4, 1), after_sleep=0.6):
            if not self.weekly_points():
                return
            op.click_point(0.15, 0.93, after_sleep=0.6, tag='DU_POINT_REWARDS')
        for _ in range(8):
            op.snapshot()
            if op.click_text(('一键领取', '领取'), (0.05, 0.2, 1, 1), after_sleep=0.5, exact=True):
                continue
            if self.handle_reward():
                continue
            op.back()
            return
