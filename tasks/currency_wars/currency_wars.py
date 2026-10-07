"""Currency Wars task registered with the native SRC scheduler/WebUI."""
from datetime import datetime
from pathlib import Path

from module.config.config import TaskEnd
from module.exception import RequestHumanTakeover
from module.logger import logger, save_error_log
from tasks.base.ui import UI
from tasks.currency_wars.characters import Characters
from tasks.currency_wars.engine import Difficulty
from tasks.currency_wars.mobile import MobileCurrencyWars
from tasks.currency_wars.operator import MobileOperator
from tasks.currency_wars.paths import EVIDENCE_DIR, STATE_DIR


class CurrencyWars(UI):
    def ensure_game(self, operator):
        if not self.device.app_is_running():
            from tasks.login.login import Login
            Login(self.config, device=self.device).app_start()
        from tasks.combat.state import CombatState
        combat = CombatState(config=self.config, device=self.device)
        from tasks.base.page import Page, page_main
        # Ultimates temporarily hide the combat controls. Wait for a known
        # screen before routing, rather than treating that frame as main UI.
        for _ in range(25):
            operator.snapshot()
            if operator.dismiss_currency_tutorial():
                continue
            if operator.dismiss_currency_interrupt():
                continue
            if operator.is_currency_settlement():
                return
            if operator.text('晋升等级', (0.03, 0, 0.25, 0.055), exact=True):
                operator.press_key('esc')
                operator.sleep(0.5)
                continue
            if combat.is_combat_executing() and not operator.is_currency_battle():
                operator.save('unrelated_combat')
                raise RequestHumanTakeover('当前战斗未检测到货币战争关卡编号，停止接管普通战斗')
            if operator.text('积分奖励', (0, 0.2, 0.3, 0.35)):
                operator.press_key('esc')
                operator.sleep(0.5)
                continue
            if combat.is_combat_executing() or operator.text(('备战阶段', '选择投资策略', '投资环境', '赛季扩充说明', '遭遇节点', '补给阶段'), (0, 0, 1, 0.25)) or operator.text('货币战争', (0, 0, 0.4, 0.18)) or operator.text(('继续挑战', '前往结算'), (0.2, 0.7, 0.8, 0.98), exact=True) or operator.text(('点击空白处继续', '点击空白处关闭'), (0.2, 0.6, 0.8, 0.98)):
                return
            if self.ui_page_appear(page_main):
                break
            if any(page.check_button is not None and self.ui_page_appear(page) for page in Page.iter_pages()):
                break
            operator.sleep(0.5)
        else:
            operator.save('startup_screen_unknown')
            raise RequestHumanTakeover('启动时画面未能识别')
        if operator.click_text('货币战争', (0.5, 0.3, 0.9, 0.75), after_sleep=2, exact=True):
            for _ in range(20):
                operator.snapshot()
                if operator.text('开始货币战争', (0.5, 0.75, 1, 1)) or operator.text('备战阶段', (0, 0, 0.4, 0.18)):
                    return
                if operator.click_text(('点击空白处关闭', '点击空白处继续'), after_sleep=0.5):
                    continue
                operator.sleep(0.4)
        # Use SRC's page routing for all existing game UI and login handling.
        from tasks.base.page import page_guide
        self.ui_goto(page_guide)
        operator.click_point(370 / 1280, 112 / 720, after_sleep=0.4, tag='CW_GUIDE_COSMIC')
        selected_currency = False
        for _ in range(20):
            operator.snapshot()
            if operator.text('赛季扩充说明', (0.1, 0.1, 0.9, 0.28)):
                operator.press_key('esc')
                operator.sleep(0.4)
                continue
            if operator.text('开始货币战争', (0.5, 0.75, 1, 1)):
                return
            if operator.click_text(('点击空白处关闭', '点击空白处继续'), after_sleep=0.5):
                continue
            if not selected_currency and operator.click_text('货币战争', (0.05, 0.18, 0.35, 0.52), after_sleep=0.8, exact=True):
                selected_currency = True
                continue
            if selected_currency and operator.click_text('前往参与', (0.5, 0.5, 1, 1), after_sleep=2, exact=True):
                continue
            if operator.text('货币战争', (0.5, 0.3, 0.9, 0.75), exact=True):
                operator.click_text('货币战争', (0.5, 0.3, 0.9, 0.75), after_sleep=2, exact=True)
                continue
            operator.sleep(0.6)
        operator.save('navigation_failed')
        raise RequestHumanTakeover('无法从指南进入货币战争')

    def run(self):
        from filelock import FileLock, Timeout
        from tasks.currency_wars.progress import Campaign
        lock_path = STATE_DIR / f'{self.config.config_name}.controller.lock'
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(lock_path), timeout=0):
                try:
                    self._validate_settings()
                    return self._run_with_recovery(Campaign(profile=self.config.config_name))
                except TaskEnd:
                    Campaign(profile=self.config.config_name).heartbeat('stopped')
                    raise
                except Exception as error:
                    Campaign(profile=self.config.config_name).heartbeat('error', error=error)
                    raise
        except Timeout:
            raise RequestHumanTakeover('该模拟器已有货币战争控制进程，请先停止原进程')

    def _validate_settings(self):
        if self.config.Emulator_GameLanguage != 'cn':
            raise RequestHumanTakeover('当前货币战争素材适配简体中文游戏界面')
        if self.config.CurrencyWars_Runs < 0:
            raise RequestHumanTakeover('运行次数不能为负数；0 表示持续运行')
        if self.config.CurrencyWars_RecoveryRetries < 0:
            raise RequestHumanTakeover('故障自动恢复次数不能为负数')
        from tasks.currency_wars.strategy_config import strategy_request
        from tasks.currency_wars.synergy import parse_synergy_targets
        required = getattr(self.config, 'CurrencyWars_RequiredSynergies', '') or ''
        if required.strip() and not parse_synergy_targets(f'【{required}】'):
            raise RequestHumanTakeover('通关必需羁绊格式未识别，请填写如“4贝洛伯格”或“6持续伤害4贝洛伯格”')
        try:
            strategy_request(self.config)
        except (ValueError, OSError) as error:
            raise RequestHumanTakeover(str(error)) from error

    def _check_recovery_stop(self):
        event = self.config.stop_event
        if event is not None and event.is_set():
            raise TaskEnd

    def _mark_recovery_progress(self, run_id, stage):
        progress = (run_id, stage)
        if stage and progress != self._recovery_progress:
            if self._recovery_attempts:
                logger.info(f'CW recovery confirmed progress: {stage}; retry budget reset')
            self._recovery_progress = progress
            self._recovery_attempts = 0

    def _restart_currency_game(self):
        from tasks.login.login import Login
        self._check_recovery_stop()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        login = Login(self.config, device=self.device)
        login.app_stop()
        self._check_recovery_stop()
        # app_restart() also delays the bound task until tomorrow. Use SRC's
        # stop/start/login primitives so recovery resumes CurrencyWars now.
        login.app_start()
        self._check_recovery_stop()
        self.device.stuck_record_clear()
        self.device.click_record_clear()

    def _run_with_recovery(self, campaign):
        requested = self.config.CurrencyWars_Runs
        limit = self.config.CurrencyWars_RecoveryRetries
        campaign.reload()
        initial_completed = sum(item['profile'] == campaign.profile for item in campaign.data['settlements'])
        self._recovery_attempts = 0
        self._recovery_progress = None
        restart = False
        while True:
            self._check_recovery_stop()
            campaign.reload()
            completed = sum(item['profile'] == campaign.profile for item in campaign.data['settlements']) - initial_completed
            if requested and completed >= requested:
                break
            remaining = requested - completed if requested else 0
            try:
                if restart:
                    self._restart_currency_game()
                self._run(remaining)
                break
            except TaskEnd:
                raise
            except Exception as error:
                self._check_recovery_stop()
                logger.exception(error)
                try:
                    save_error_log(config=self.config, device=self.device)
                except Exception as save_error:
                    logger.warning(f'CW unable to save recovery evidence: {save_error}')
                if self._recovery_attempts >= limit:
                    # Convert to terminal takeover so the outer SRC scheduler
                    # cannot start another independent restart loop.
                    raise RequestHumanTakeover(
                        f'货币战争自动恢复 {limit} 次后仍未推进，已停止并保留现场：{error}'
                    ) from error
                self._recovery_attempts += 1
                logger.warning(f'CW recovery {self._recovery_attempts}/{limit}: restart game, then resume the saved run: {error}')
                campaign.heartbeat('recovering', error=error)
                restart = True
        self._finish_task(campaign)

    def _run(self, runtimes=None):
        logger.hr('Currency Wars', level=1)
        runtimes = self.config.CurrencyWars_Runs if runtimes is None else runtimes
        folder = EVIDENCE_DIR / f'{self.config.config_name}-{datetime.now():%Y%m%d-%H%M%S}' if self.config.CurrencyWars_SaveEvidence else None
        operator = MobileOperator(self.device, self.config, evidence_dir=folder)
        from tasks.currency_wars.progress import Campaign
        campaign = Campaign(profile=self.config.config_name)
        operator.campaign = campaign
        operator.progress_callback = self._mark_recovery_progress
        self.ensure_game(operator)
        # One task process owns the strategy state; clear state from previous runs.
        for char in {id(c): c for c in Characters.characters.values()}.values():
            char.reset()
            char.stars = 0
            char.is_placed = False
        username = (self.config.CurrencyWars_Username or '').strip()
        if username:
            Characters.set_username(username)
        game = MobileCurrencyWars(operator=operator, runtimes=runtimes)
        game.campaign = campaign
        game.set_difficulty({'lowest': Difficulty.LOWEST, 'highest': Difficulty.HIGHEST, 'current': Difficulty.CURRENT}[self.config.CurrencyWars_Difficulty])
        game.set_overclock(self.config.CurrencyWars_Mode == 'overclock')
        if not game.run():
            operator.save('task_failed')
            raise RequestHumanTakeover('货币战争没有完整结束，查看实战记录定位失败环节')
        if len(game.completed_runs) != runtimes:
            raise RequestHumanTakeover('货币战争未完成要求的对局次数')
        logger.info(f'Currency Wars finished: {game.completed_runs}')

    def _finish_task(self, campaign):
        with self.config.multi_set():
            self.config.task_delay(server_update=True)
            if not self.config.CurrencyWars_RepeatDaily:
                self.config.Scheduler_Enable = False
        campaign.heartbeat('finished')
        if not self.config.CurrencyWars_RepeatDaily and self.config.stop_event is not None:
            self.config.get_next_task()
            if not self.config.pending_task and not self.config.waiting_task:
                self.config.stop_event.set()
