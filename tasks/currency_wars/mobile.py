"""Android screens and controls; strategy/placement rules stay in engine.py."""
from copy import copy
from datetime import datetime
from pathlib import Path
import difflib
import json
import re
import time
import os

import cv2
import numpy as np

from module.logger import logger
from tasks.currency_wars.characters import Character, Characters, Positioning
from tasks.currency_wars.engine import CurrencyWars as StrategyEngine, Difficulty, StageName
from tasks.currency_wars.operator import normalize
from tasks.currency_wars.roster_cache import RosterCache
from tasks.currency_wars.paths import STATE_DIR
from tasks.currency_wars.strategy_config import NATIVE_SOURCES, PRESETS, can_resume_strategy, strategy_request


class MobileCurrencyWars(StrategyEngine):
    def __init__(self, operator, runtimes):
        super().__init__(operator, runtimes)
        self.in_hand_area = [(x / 1280, 598 / 720) for x in (206, 311, 416, 522, 627, 732, 837, 942, 1047)]
        self.completed_runs = []
        self.rounds = 0
        self.last_stage = ''
        self.strategy_imported = False
        self.result = None
        self.pending_combat = False
        self.campaign = None
        self.strategy_title = ''
        self.native_strategy = False
        self.evidence_base = getattr(operator, 'evidence_dir', None)
        self.active_run = None
        self.strategy_pending = False
        self.requested_strategy = None
        self.roster_dirty = False
        self.inventory_changed = False
        self.roster_cache = RosterCache()
        self._restore_attempted = False
        self._last_inventory_snapshot = None
        self._sale_refilled_slot = None
        self._equipment_revision = 0
        self._equipment_checked = {}
        self._equipment_signature = None
        self._formation_changed = False
        self._last_review_stage = None
        self._last_health = None
        self._pending_purchases = {}
        self._quick_bench_count = 0
        self.star_plan = None
        self.three_star_cores = []
        self.target_synergies = {}
        self.required_synergies = {}
        self.formation_population = None
        self.formation_snapshot = None
        self.desired_team = None
        self.trait_registry = STATE_DIR / 'character_traits.json'
        self.known_traits = json.loads(self.trait_registry.read_text(encoding='utf-8')) if self.trait_registry.exists() else {}

    def run(self):
        self.is_running = True
        self.requested_strategy = strategy_request(self.operator.config)
        index = 0
        while self.runtimes == 0 or index < self.runtimes:
            if self.campaign is not None:
                active = self.campaign.begin(self.operator.config.CurrencyWars_Mode, self.operator.config.CurrencyWars_Strategy)
                if self.evidence_base is not None:
                    self.operator.evidence_dir = self.evidence_base / active['id']
                if self.active_run is None or self.active_run['id'] != active['id']:
                    self._last_review_stage = None
                    self._last_health = None
                    self._pending_purchases.clear()
                self.active_run = active
                reuse = can_resume_strategy(active, self.requested_strategy)
                self.strategy_pending = not reuse and self.requested_strategy['source'] in NATIVE_SOURCES
                if not reuse and active.get('strategy'):
                    logger.info('CW strategy settings changed; applying the selected source at the next preparation screen')
                if self.strategy_pending and isinstance(active.get('strategy'), dict):
                    # A fight may finish the whole run before the next board.
                    # Keep its original attribution until the replacement loads.
                    current = active['strategy']
                    self.load_native_strategy(current['path'])
                    self.strategy_title = current.get('title', '')
                    self.native_strategy = True
                if not self.strategy_pending:
                    self.prepare_strategy(active)
            logger.info(f'Currency Wars run {index + 1}/{self.runtimes or "continuous"}')
            self.operator.phase = 'entering_game'
            started = self.start_game()
            if not started:
                raise RuntimeError('货币战争对局启动未完成')
            self.game_loop()
            if not self.is_running:
                return False
            index += 1
        self.handle_ending()
        return len(self.completed_runs) == self.runtimes

    def prepare_strategy(self, active):
        self._prepare_strategy(active)
        self.configure_star_plan()
        from tasks.currency_wars.synergy import minimum_team_size, parse_synergy_targets
        required = getattr(self.operator.config, 'CurrencyWars_RequiredSynergies', '') or ''
        self.required_synergies = parse_synergy_targets(f'【{required}】')
        goals = dict(self.target_synergies)
        goals.update(self.required_synergies)
        units = [copy(Characters.get_character(name)) for name in self.strategy_characters if Characters.get_character(name)]
        for unit in units:
            unit.is_locked = False
        self.formation_population = minimum_team_size(units, goals)
        logger.attr('CW formation population', dict(required=self.required_synergies, targets=goals,
                                                   base_units_needed=self.formation_population))
        if goals and self.formation_population is None:
            logger.warning('CW guide targets require additional trait bonuses or missing trait data; the title alone does not prove completion')

    def _prepare_strategy(self, active):
        op = self.operator
        request = self.requested_strategy or strategy_request(op.config)
        setting = request['source']
        current = active.get('strategy')
        if can_resume_strategy(active, request):
            self.unload_strategy()
            if isinstance(current, dict):
                self.load_native_strategy(current['path'])
                self.strategy_title = current.get('title', '')
                self.native_strategy = True
            else:
                self.load_strategy(current)
                self.strategy_title = self.strategy_data.get('title', '')
                self.native_strategy = False
            logger.info(f'CW resume strategy: {self.strategy_title}')
            if request['source'] == 'sequence' and active.get('sequence'):
                step = active['sequence']
                logger.info(f'CW strategy sequence: {step["index"] + 1}/{len(step["codes"])} (cycle {step["cycle"] + 1}, resumed)')
            return
        op.phase = 'selecting_strategy'
        if setting in NATIVE_SOURCES:
            from tasks.currency_wars.native_strategy import NativeStrategy
            resolver = NativeStrategy(op, self)
            if setting == 'code':
                path, data = resolver.open_code(request['code'])
            elif setting == 'code_pool':
                path, data = resolver.open_code(self.campaign.choose(request['codes']))
            elif setting == 'sequence':
                code, step = self.campaign.sequence_choice(request['codes'])
                logger.info(f'CW strategy sequence: {step["index"] + 1}/{len(step["codes"])} (cycle {step["cycle"] + 1})')
                path, data = resolver.open_code(code)
            else:
                path, data = resolver.choose_recommended(self.campaign)
            resolver.return_to_game()
            selected = {'path': str(path.resolve()), 'title': data['title'], 'code': data['share_code']}
            self.unload_strategy()
            self.load_native_strategy(str(path))
            self.native_strategy = True
        else:
            selected = request['path'] if setting == 'file' else self.campaign.choose(list(PRESETS)) if setting == 'preset_pool' else setting
            self.unload_strategy()
            self.load_strategy(selected)
            self.native_strategy = False
            if setting == 'file':
                selected = {'path': selected, 'title': self.strategy_data.get('title', ''), 'code': self.strategy_code}
        self.strategy_title = self.strategy_data.get('title', '')
        self.campaign.set_strategy(selected, request=request)
        self.campaign.reload()
        self.active_run = dict(self.campaign.data['active'][self.campaign.profile])
        self.strategy_imported = False
        self.desired_team = None
        self._last_review_stage = None
        self._restore_attempted = True
        self.roster_cache.clear()
        self._equipment_checked.clear()
        logger.info(f'CW selected strategy ({setting}): {self.strategy_title}')

    def load_native_strategy(self, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        for name, cost in data.get('character_costs', {}).items():
            if Characters.get_character(name) is None and isinstance(cost, int) and 1 <= cost <= 5:
                Characters.characters[name] = Character(name, cost, Positioning.OnOffField)
        self.load_strategy(str(path))
        from tasks.currency_wars.synergy import parse_synergy_targets
        self.target_synergies = data.get('target_synergies') or parse_synergy_targets(data.get('title', ''))
        # Live character panels are the persisted source of truth; a native
        # tooltip can have a different height and omit a badge row.
        for name, traits in data.get('character_traits', {}).items():
            self.known_traits.setdefault(name, traits)
        for name, traits in self.known_traits.items():
            character = Characters.get_character(name)
            if character is not None:
                character.traits = tuple(traits)
        guide = data.get('guide_star_targets', {})
        for group in ('on_field', 'off_field'):
            for name in data.get(group, {}):
                # An unspecified guide star is not a request to stop at one
                # copy. Keep explicit targets and grow unspecified units to 2.
                if guide.get(group, {}).get(name) is None:
                    self.strategy_characters[name] = max(self.strategy_characters[name], data.get('purchase_floor', 2))

    def configure_star_plan(self):
        from tasks.currency_wars.star_plan import build_star_plan
        data = getattr(self, 'strategy_data', {})
        plan = build_star_plan(getattr(self, 'raw_star_targets', self.strategy_characters), data.get('title', self.strategy_title))
        if self.campaign is not None:
            plan = self.campaign.ensure_star_plan(plan)
        self.star_plan = plan
        self.three_star_cores = list(plan['cores'])
        self.strategy_characters = dict(plan['targets'])
        if self.active_run is not None:
            self.active_run['star_plan'] = plan
        logger.attr('CW fixed star plan', plan)

    def prepare_pending_strategy(self):
        if self.strategy_pending:
            self.prepare_strategy(self.active_run)
            self.strategy_pending = False

    def set_actual_mode(self, mode):
        self.is_overclock = mode == 'overclock'
        if self.campaign is not None and self.active_run is not None and self.active_run.get('mode') != mode:
            self.campaign.set_mode(mode)
            self.active_run['mode'] = mode

    def detect_board_mode(self):
        mode = 'overclock' if self.operator.text('OverclockView', (0, 0.65, 0.1, 0.75)) else 'standard'
        self.set_actual_mode(mode)

    def is_board(self):
        if not self.operator.text(('备战阶段', '准备阶段'), (0, 0, 0.35, 0.1)):
            return False
        return not self.operator.text(('盛会之星', '命运卜者', '选择伙伴', '祈愿试炼', '我来当策划', '选择投资策略', '补给阶段', '遭遇节点', '武装箱', '邀请函', '聘用书', '请选择1个'), (0.35, 0, 0.85, 0.18))

    def stage_id(self):
        for box in self.operator.match(('-',), (0, 0, 0.35, 0.14)):
            match = re.search(r'([1-3])\s*-\s*(\d+)', box.source)
            if match:
                return match.group(0)
        return self.last_stage

    def is_interrupted_battle_board(self):
        op = self.operator
        if not self.is_board() or op.text('ShopView', (0, 0, 0.18, 0.18)):
            return False
        if not op.text('出战', (0.8, 0.55, 1, 0.75)) or not op.text('商店', (0.87, 0.85, 1, 0.96)):
            return False
        # An interrupted fight or a pending supply/event can lock the shop,
        # while the orange deployment button stays active. Normal preparation has
        # a white shop panel. Check both so a dimmed modal is not a match.
        shop = np.median(op.image[625:640, 1225:1240], axis=(0, 1))
        deploy = op.image[454:502, 1068:1140].astype(np.int16)
        active = ((deploy[:, :, 0] > 180) & (deploy[:, :, 0] - deploy[:, :, 2] > 55)).mean()
        return bool(70 < shop.min() and shop.max() < 165 and np.ptp(shop) < 30 and active > 0.3)

    def resume_interrupted_battle(self):
        if not self.is_interrupted_battle_board():
            return False
        op = self.operator
        op.sleep(0.4)
        op.snapshot()
        if not self.is_interrupted_battle_board():
            return False
        self.last_stage = self.stage_id()
        logger.info(f'CW resume locked node: {self.last_stage}; shop disabled, enter the pending battle or event')
        op.save('resume_interrupted_battle')
        if not op.click_text('出战', (0.8, 0.55, 1, 0.75), after_sleep=1):
            raise RuntimeError('中断战斗的出战按钮未识别')
        self.is_continue = True
        self.pending_combat = True
        return True

    def back(self):
        self.operator.press_key('esc')
        self.operator.sleep(0.15)

    def close_character(self):
        self.operator.snapshot()
        if self.operator.text(('详情', '出售'), (0.65, 0.85, 0.99, 0.96)):
            self.back()

    def close_shop(self):
        op = self.operator
        for _ in range(8):
            self.close_character()
            op.snapshot()
            if op.dismiss_equipment_combine():
                continue
            if op.text('装备追踪', (0.15, 0.1, 0.55, 0.25)):
                self.back()
                continue
            if self.is_board():
                if op.text('ShopView', (0, 0, 0.18, 0.18)):
                    op.click_point(1193 / 1280, 657 / 720, after_sleep=1.6, tag='CW_SHOP_CLOSE')
                    continue
                return
            if op.dismiss_currency_interrupt():
                continue
            if op.dismiss_currency_tutorial():
                continue
            if not self.handle_pending_selection():
                op.sleep(0.5)
        op.save('board_expected')
        raise RuntimeError('尚未返回备战界面，停止商店或角色操作')

    def is_item_selection(self):
        return bool(self.operator.text(('武装箱', '武器箱', '装备箱', '邀请函', '聘用书', '星徽秘典'),
                                       (0.35, 0, 0.95, 0.18)))

    def handle_pending_selection(self):
        op = self.operator
        if self.is_item_selection():
            self.handle_item_selection()
        elif op.text('选择投资策略', (0.1, 0, 0.9, 0.2)):
            self.handle_invest_strategy(None)
        elif op.text(('选择投资环境', '投资环境'), (0.1, 0, 0.9, 0.2)):
            self.handle_invest_environment()
        elif op.text('补给阶段', (0.1, 0, 0.9, 0.2)):
            self.handle_replenish_stage()
        elif op.text('遭遇节点', (0.1, 0, 0.9, 0.2)):
            self.handle_encounter_node()
        elif op.text(('命运卜者', '盛会之星', '选择伙伴', '祈愿试炼', '我来当策划'), (0.35, 0, 0.85, 0.18)):
            self.handle_special_event()
        elif op.click_text(('点击空白处关闭', '点击空白处继续'), (0.1, 0.5, 0.9, 0.98), after_sleep=0.8):
            pass
        else:
            return False
        return True

    def handle_item_selection(self):
        op = self.operator
        if not self.required_synergies and self.select_uncollected():
            return
        names = op.read_region((0.18, 0.25, 0.92, 0.46), snapshot=False)
        from tasks.currency_wars.synergy import extract_traits
        goals = self.required_synergies or self.target_synergies
        emblems = [(sum(goals.get(trait, 0) for trait in extract_traits(b.source)), b)
                   for b in names if '星徽' in b.source]
        if emblems and max(score for score, _ in emblems) > 0:
            chosen = max(emblems, key=lambda item: item[0])[1]
            logger.info(f'CW choose synergy emblem: {chosen.source}')
            op.click_box(chosen, after_sleep=0.5)
            return
        if self.required_synergies and self.select_uncollected():
            return
        recommended = [(self.character_from_text(b.source), b) for b in names]
        recommended = [(c, b) for c, b in recommended if c and c.name in self.strategy_characters]
        if recommended:
            op.click_box(max(recommended, key=lambda item: item[0].priority)[1], after_sleep=0.5)
        else:
            op.click_point(1120 / 1280, 172 / 720, after_sleep=0.5, tag='CW_ITEM_LAST')

    def open_shop(self):
        self.close_character()
        op = self.operator
        for _ in range(8):
            op.snapshot()
            if op.dismiss_equipment_combine():
                continue
            if op.text('ShopView', (0, 0, 0.18, 0.18)):
                return
            if not self.is_board():
                self.close_shop()
                continue
            if not op.click_text('商店', (0.87, 0.85, 1, 0.96), after_sleep=0.7):
                op.sleep(0.3)
        op.save('shop_open_failed')
        raise RuntimeError('商店未能打开，停止购物')

    def start_game(self):
        self.is_running = True
        self.is_game_over = False
        self.is_continue = False
        self.strategy_imported = bool(self.active_run and self.active_run.get('strategy_applied'))
        self.result = None
        self.rounds = 0
        self.max_team_size = 3
        self.operator.deadline = time.monotonic() + max(1, self.operator.config.CurrencyWars_MaxMinutes) * 60
        deadline = time.monotonic() + 180
        selected_mode = False
        self.set_actual_mode(self.active_run.get('mode', self.operator.config.CurrencyWars_Mode) if self.active_run else self.operator.config.CurrencyWars_Mode)
        while time.monotonic() < deadline:
            op = self.operator
            op.snapshot()
            pending = self.campaign.pending_settlement() if self.campaign is not None else None
            if pending and op.text('开始货币战争', (0.5, 0.75, 1, 1)):
                self.finish_settlement(pending)
                return True
            if op.is_currency_settlement():
                self.is_continue = True
                self.handle_game_over()
                return True
            from tasks.combat.state import CombatState
            combat = CombatState(config=op.config, device=op.device)
            if combat.is_combat_executing() and not op.is_currency_battle():
                op.save('unrelated_combat')
                raise RuntimeError('当前不是货币战争战斗，停止接管')
            if combat.is_combat_executing() or op.text(('继续挑战', '前往结算', '挑战成功', '挑战失败'), (0.2, 0.05, 0.8, 0.98)):
                self.is_continue = True
                self.pending_combat = True
                return True
            if op.text('遭遇节点', (0.1, 0, 0.9, 0.2)):
                self.is_continue = True
                self.handle_encounter_node()
                continue
            if op.text('补给阶段', (0.1, 0, 0.9, 0.2)):
                self.is_continue = True
                self.handle_replenish_stage()
                continue
            if op.text(('命运卜者', '盛会之星', '选择伙伴', '祈愿试炼', '我来当策划'), (0.35, 0, 0.85, 0.18)):
                self.is_continue = True
                self.handle_special_event()
                continue
            if self.is_board():
                if not selected_mode:
                    self.is_continue = True
                op.save('entered')
                if self.resume_interrupted_battle():
                    return True
                self.close_shop()
                self.detect_board_mode()
                self.prepare_pending_strategy()
                if not self.handle_game_entered():
                    return False
                self.sync_roster()
                return self.handle_game_initialized()
            if op.click_text(('点击空白处继续', '点击空白处关闭'), (0.1, 0.5, 0.9, 0.98), after_sleep=0.8):
                continue
            if self.is_item_selection():
                self.is_continue = True
                self.handle_item_selection()
                continue
            if op.text(('热门攻略', '攻略详情', '创业指南', '数据银行'), (0, 0, 0.7, 0.2)):
                self.back()
                continue
            if op.text(('赛季扩充说明', '更新内容'), (0.13, 0.1, 0.85, 0.25)):
                self.back()
                continue
            if op.click_text(('点击空白处关闭', '点击空白处继续'), (0.1, 0.5, 0.9, 0.97), after_sleep=1):
                continue
            if op.text('开始货币战争', (0.5, 0.75, 1, 1)):
                self.prepare_pending_strategy()
                op.snapshot()
                op.click_text('开始货币战争', (0.5, 0.75, 1, 1), after_sleep=0.7)
                selected_mode = False
                continue
            if op.text(('标准博弈', '超频博弈'), (0, 0.18, 0.35, 0.62)):
                if not selected_mode:
                    label = '超频博弈' if self.is_overclock else '标准博弈'
                    if not op.click_text(label, (0, 0.18, 0.35, 0.62), after_sleep=0.7):
                        raise RuntimeError(f'未识别到{label}')
                    selected_mode = True
                    continue
                if op.click_text('继续进度', (0.7, 0.75, 1, 0.98), after_sleep=2):
                    self.is_continue = True
                    continue
                if op.click_text(('标准进入', '进入对局', '进入标准博弈', '进入超频博弈'), (0.6, 0.75, 1, 0.98), after_sleep=0.8):
                    continue
            if op.text('开始对局', (0.55, 0.7, 1, 1)):
                self._select_difficulty()
                op.snapshot()
                op.click_text('开始对局', (0.55, 0.7, 1, 1), after_sleep=1.5)
                continue
            if op.text(('选择投资环境', '投资环境'), (0.1, 0, 0.9, 0.25)):
                op.save('investment_environment')
                self.handle_invest_environment()
                continue
            if op.text('下一步', (0, 0.7, 1, 1)):
                op.save('boss_preview')
                self.handle_boss_info()
                op.snapshot()
                op.click_text('下一步', (0, 0.7, 1, 1), after_sleep=1)
                continue
            if op.text('选择投资策略', (0.1, 0, 0.9, 0.25)):
                self.handle_invest_strategy(None)
                continue
            if op.dismiss_currency_interrupt():
                continue
            if op.dismiss_currency_tutorial():
                continue
            op.sleep(0.7)
        self.operator.save('entry_timeout')
        raise TimeoutError('货币战争进入流程超时')

    def _select_difficulty(self):
        op = self.operator
        if self.difficulty == Difficulty.CURRENT:
            return
        if self.difficulty == Difficulty.HIGHEST:
            for _ in range(4):
                op.snapshot()
                if op.click_text('返回最高职级', (0.5, 0.8, 0.77, 0.97), after_sleep=0.8):
                    return
                # At the highest unlocked rank the shortcut is hidden; the
                # next rank's lock confirms this is already the requested level.
                if op.text('LockedNextDifficulty', (0.45, 0.18, 0.50, 0.30)):
                    logger.info('CW highest unlocked difficulty already selected (next rank locked)')
                    return
                op.sleep(0.3)
            raise RuntimeError('未确认最高职级：返回按钮和下一职级锁定标记均未识别')
        # The Android difficulty selector is calibrated by its visible arrows.
        from tasks.currency_wars.assets import CWIMG
        unchanged = 0
        previous = None
        for _ in range(60):
            op.snapshot()
            rank = normalize(op.read_line((60 / 1280, 222 / 720, 350 / 1280, 270 / 720), snapshot=False).source)
            floor = normalize(op.read_line((200 / 1280, 295 / 720, 277 / 1280, 385 / 720), snapshot=False).source)
            rank = f'{rank}:{floor}'
            if rank != previous:
                op.device.click_record_clear()
                unchanged = 0
                logger.attr('CW difficulty', rank)
            else:
                unchanged += 1
            if unchanged >= 3:
                op.save('lowest_difficulty')
                return
            previous = rank
            if not op.click_img(CWIMG.DOWN_ARROW, after_sleep=1):
                op.save('lowest_difficulty')
                break

    def handle_ending(self):
        self.operator.save('task_finished')

    def reset_character(self):
        super().reset_character()
        self.roster_cache.clear()
        self._equipment_checked.clear()
        self._restore_attempted = False
        self._last_inventory_snapshot = None
        self._pending_purchases.clear()
        # Star targets belong to the next game's inventory, not the previous
        # game's final team. A 1-star target must still be bought in a new run.
        for character in {id(c): c for c in Characters.characters.values()}.values():
            character.stars = 0
            character.is_placed = False
            character.is_locked = character.is_npc
        self.max_team_size = 3

    def handle_game_entered(self):
        applied = False
        if self.campaign is not None:
            self.campaign.reload()
            applied = self.campaign.data['active'].get(self.campaign.profile, {}).get('strategy_applied', False)
        self.strategy_imported = self.strategy_imported or applied
        should_import = not applied
        if should_import and self.strategy_code:
            self.import_strategy()
        return True

    def import_strategy(self):
        from tasks.currency_wars.native_strategy import NativeStrategy
        op = self.operator
        self.close_shop()
        # The strategy page loads through a black transition. Use the same
        # native catalog/input workflow as arbitrary strategy-code parsing.
        NativeStrategy(op, self).open_code(self.strategy_code, read=False)
        for _ in range(20):
            op.snapshot()
            if op.click_text('应用攻略', after_sleep=1):
                break
            op.sleep(0.3)
        else:
            op.save('strategy_import_failed')
            raise RuntimeError('攻略码导入失败，未识别到应用攻略')
        for _ in range(12):
            op.snapshot()
            if self.is_board():
                self.strategy_imported = True
                if self.campaign is not None:
                    self.campaign.mark_strategy_applied()
                logger.info('Android strategy code imported')
                return
            self.back()
            op.sleep(0.4)
        raise RuntimeError('导入攻略后未返回备战界面')

    def handle_invest_environment(self):
        self.choose_card('投资环境')

    def handle_invest_strategy(self, prev_stage=None):
        self.choose_card('投资策略')
        self.post_invest_strategy()
        self.roster_dirty = True
        return False

    def choose_card(self, title):
        op = self.operator
        op.snapshot()
        if self.is_board() or not op.text(title, (0.1, 0, 0.9, 0.2)):
            return False
        if not self.select_uncollected():
            op.click_point(0.5, 0.4, after_sleep=0.3, tag=f'CW_{title}_MIDDLE')
        op.snapshot()
        if not op.click_text(('确认', '确认选择', '选择'), (0, 0.7, 1, 1), after_sleep=1.2, exact=True):
            op.snapshot()
            if self.is_board():
                return True
            op.save('card_confirm_missing')
            raise RuntimeError(f'{title}确认按钮未识别')
        return True

    def select_uncollected(self):
        op = self.operator
        if not getattr(getattr(op, 'config', None), 'CurrencyWars_PreferUncollected', True):
            return False
        badge = op.text(('未收集', '未选择过', '首次获得', 'NEW', 'New', 'new', '新'), (0.08, 0.10, 0.98, 0.55), exact=True)
        if badge:
            logger.info(f'CW prefer collection badge: {badge.source}')
            return op.click_box(badge, after_sleep=0.3)
        return False

    def _get_character_in_area(self, areas, target_character_list, force=False, equip=False, count_stars=False, use_backup_ocr=False):
        self.close_shop()
        op = self.operator
        area = 'in_hand' if target_character_list is self.in_hand_character else 'on_field' if target_character_list is self.on_field_character else 'off_field'
        frame_stale = True
        for index, point in enumerate(areas):
            # Reuse a frame only while no UI action has occurred. After a
            # tooltip/selection, later slots always use the current board.
            if frame_stale:
                op.snapshot(ocr=False)
                board_image = op.image.copy()
                frame_stale = False
            key = f'{area}:{index}'
            cached = target_character_list[index]
            if not force and self.roster_cache.matches(key, board_image, point, cached):
                if cached is not None:
                    cached.is_locked = cached.is_npc or (area == 'in_hand' and self.slot_locked(board_image, point))
                    if equip and cached.name in self.strategy_characters and not cached.is_npc and self._equipment_checked.get(key) != self._equipment_revision:
                        op.click_point(*point, after_sleep=0.3, trace=False)
                        self.equip_recommended()
                        self._equipment_checked[key] = self._equipment_revision
                        self.back()
                        frame_stale = True
                continue
            if not self.slot_occupied(board_image, point):
                target_character_list[index] = None
                self.roster_cache.remember(key, board_image, point, None)
                continue
            op.click_point(*point, after_sleep=0.35, trace=False)
            frame_stale = True
            character = None
            item_consumed = False
            for retry in range(5):
                results = op.read_character_name()
                self.roster_cache.reads += 1
                logger.attr('CW character OCR', [b.source for b in results])
                character = self.character_from_text(''.join(b.source for b in results))
                if character is not None:
                    break
                if retry < 2:
                    # Most misses are the tooltip fading in. Retry the fast
                    # name line before running wider NPC/event recognition.
                    op.sleep(0.1)
                    continue
                op.snapshot()
                npc = op.text_ocr(('Gemi狸', 'Gemi', '狸猫', '佩佩'), (0.65, 0.27, 0.99, 0.62))
                if npc:
                    npc_name = 'Gemi狸' if any(word in npc.source for word in ('Gemi', '狸猫')) else '佩佩'
                    character = Characters.get_character(npc_name) or Characters.new_character(npc_name)
                    character.is_npc = True
                    character.is_locked = True
                    character.position = Positioning.OffField
                    break
                if op.text('ShopView', (0, 0, 0.18, 0.18)):
                    self.close_shop()
                    op.click_point(*point, after_sleep=0.2, trace=False)
                    continue
                if self.is_item_selection():
                    self.handle_item_selection()
                    item_consumed = True
                    break
                op.sleep(0.2)
                if not op.text('出售', (0.86, 0.84, 0.99, 0.97)):
                    op.click_point(*point, after_sleep=0.2, trace=False)
            if item_consumed:
                target_character_list[index] = None
                op.snapshot(ocr=False)
                board_image = op.image.copy()
                continue
            if character is None:
                op.snapshot()
                if not op.text(('详情', '出售'), (0.65, 0.85, 0.99, 0.97)):
                    # Empty slots can contain moving loot/glow effects. A
                    # portrait-like patch alone is not a character panel.
                    target_character_list[index] = None
                    continue
                detailed = op.read_region((0.71, 0.085, 0.97, 0.145), snapshot=False)
                character = next((self.character_from_text(box.source) for box in detailed if self.character_from_text(box.source)), None)
                if character is None and detailed:
                    # The world character uses the account nickname while a
                    # native guide may still label the portrait 开拓者.
                    cost = op.read_line((1208 / 1280, 52 / 720, 1235 / 1280, 84 / 720), snapshot=False).source
                    traits = op.read_region((0.66, 0.19, 0.98, 0.25), snapshot=False)
                    if re.search(r'4', cost) and any('列车同行' in b.source for b in traits) and any('欢愉' in b.source for b in traits):
                        character = Characters.Trailblazer
                        Characters.characters[detailed[0].source.strip()] = character
            if character is None:
                op.save(f'occupied_slot_unreadable_{index}')
                raise RuntimeError(f'已占用角色栏 {index} 未能识别，停止调整编队')
            template = character
            if not character.is_npc:
                from tasks.currency_wars.synergy import extract_traits
                labels = op.read_region((0.66, 0.19, 0.98, 0.25), snapshot=False)
                traits = extract_traits(' '.join(b.source for b in labels))
                if traits and tuple(traits) != template.traits:
                    template.traits = traits
                    self.remember_traits(template.name, traits)
            character = copy(template)
            target_character_list[index] = character
            if character:
                in_hand = target_character_list is self.in_hand_character
                character.is_placed = not in_hand
                character.is_locked = character.is_npc or (in_hand and self.slot_locked(board_image, point))
                if count_stars and not character.is_npc:
                    character.stars = self.count_stars()
                    template.stars = max(template.stars, character.stars)
                if equip and character.name in self.strategy_characters and not character.is_npc:
                    self.equip_recommended()
                    self._equipment_checked[key] = self._equipment_revision
                # Never tap elsewhere: on Android the panel stays open and its
                # Sell button occupies the same corner as the Shop button.
                self.back()
                self.roster_cache.remember(key, board_image, point, character)
            else:
                self.close_character()
        return target_character_list

    def refresh_character(self, force=False):
        self.close_shop()
        self.restore_roster()
        self.check_equipment_change()
        result = super().refresh_character(force=force)
        self.operator.snapshot(ocr=False)
        self._equipment_signature = self.equipment_signature()
        return result

    def swap_character_between_areas(self, source_area_type, source_index, target_area_type, target_index):
        previous = tuple(c.name if c else None for c in self.on_field_character + self.off_field_character)
        result = super().swap_character_between_areas(source_area_type, source_index, target_area_type, target_index)
        self.roster_cache.invalidate(f'{source_area_type}:{source_index}', f'{target_area_type}:{target_index}')
        self._equipment_checked.pop(f'{source_area_type}:{source_index}', None)
        self._equipment_checked.pop(f'{target_area_type}:{target_index}', None)
        if result and previous != tuple(c.name if c else None for c in self.on_field_character + self.off_field_character):
            self._formation_changed = True
        return result

    def equipment_signature(self):
        return cv2.resize(self.operator.image[175:440, 1120:1255], (24, 48), interpolation=cv2.INTER_AREA)

    def check_equipment_change(self):
        self.operator.snapshot(ocr=False)
        signature = self.equipment_signature()
        if self._equipment_signature is not None and np.abs(signature.astype(np.int16) - self._equipment_signature.astype(np.int16)).mean() > 3:
            self._equipment_revision += 1
        self._equipment_signature = signature

    def sync_roster(self):
        started = time.monotonic()
        hits, reads = self.roster_cache.hits, self.roster_cache.reads
        self.refresh_character()
        self.get_in_hand_area()
        self.update_max_team_size()
        self.inventory_changed = False
        self._pending_purchases.clear()
        self.save_roster()
        logger.attr('CW recognition', dict(cached=self.roster_cache.hits - hits, name_ocr=self.roster_cache.reads - reads,
                                           seconds=round(time.monotonic() - started, 2)))

    def roster_path(self):
        if self.campaign is None or self.active_run is None:
            return None
        return self.trait_registry.parent / 'rosters' / f'{self.campaign.profile}.json'

    def save_roster(self):
        path = self.roster_path()
        if path is None:
            return
        areas = {}
        for area in ('on_field', 'off_field', 'in_hand'):
            chars = getattr(self, area + '_character')
            areas[area] = dict(points=getattr(self, area + '_area'), characters=[None if c is None else
                dict(name=c.name, stars=int(c.stars), locked=c.is_locked, npc=c.is_npc, traits=list(c.traits)) for c in chars])
        data = dict(run_id=self.active_run['id'], areas=areas, capacity=self.max_team_size, cache=self.roster_cache.dump(),
                    formation=self.formation_snapshot,
                    last_review_stage=self._last_review_stage, last_health=self._last_health, pending_purchases=self._pending_purchases,
                    equipment_revision=self._equipment_revision, equipment_checked=self._equipment_checked,
                    equipment_signature=self._equipment_signature.tolist() if self._equipment_signature is not None else None)
        encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        if encoded != self._last_inventory_snapshot:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f'.{os.getpid()}.tmp')
            temporary.write_text(encoded, encoding='utf-8')
            temporary.replace(path)
            self._last_inventory_snapshot = encoded

    def restore_roster(self):
        if self._restore_attempted:
            return
        self._restore_attempted = True
        path = self.roster_path()
        if path is None or not path.exists():
            return
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('run_id') != self.active_run['id']:
            return
        self.formation_snapshot = data.get('formation')
        for area, saved in data['areas'].items():
            chars = []
            for item in saved['characters']:
                template = Characters.get_character(item['name']) if item else None
                character = copy(template) if template else None
                if character is not None:
                    character.stars, character.is_locked = item['stars'], item['locked']
                    character.is_npc, character.is_placed = item['npc'], area != 'in_hand'
                    character.traits = tuple(item['traits'])
                chars.append(character)
            setattr(self, area + '_character', chars)
            setattr(self, area + '_area', [tuple(p) for p in saved['points']])
        self.max_team_size = data['capacity']
        self._last_review_stage = data.get('last_review_stage')
        self._last_health = data.get('last_health')
        self._pending_purchases = data.get('pending_purchases', {})
        self.roster_cache.load(data['cache'])
        self._equipment_revision = data.get('equipment_revision', 0)
        self._equipment_checked = data.get('equipment_checked', {})
        if data.get('equipment_signature') is not None:
            self._equipment_signature = np.asarray(data['equipment_signature'], dtype=np.uint8)
        logger.info('CW restored roster; each slot must pass visual validation before reuse')

    def remember_traits(self, name, traits):
        self.known_traits[name] = list(traits)
        from filelock import FileLock
        self.trait_registry.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.trait_registry) + '.lock', timeout=10):
            data = json.loads(self.trait_registry.read_text(encoding='utf-8')) if self.trait_registry.exists() else {}
            data[name] = list(traits)
            temporary = self.trait_registry.with_suffix(f'.{os.getpid()}.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.trait_registry)

    def update_team_plan(self):
        from tasks.currency_wars.synergy import select_team
        field = self.on_field_character + self.off_field_character
        fixed = [c for c in field if c is not None and c.is_locked]
        self.desired_team = select_team(field + self.in_hand_character, self.strategy_characters,
                                       self.target_synergies, self.max_team_size - len(fixed),
                                       len(self.on_field_area) - sum(c is not None and c.is_locked for c in self.on_field_character),
                                       len(self.off_field_area) - sum(c is not None and c.is_locked for c in self.off_field_character),
                                       required=self.required_synergies or None, fixed=fixed)
        logger.attr('CW team plan', dict(synergies=self.target_synergies, selected=sorted(self.desired_team)))
        return field

    def place_character(self):
        field = self.update_team_plan()
        field_names = {c.name for c in field if c is not None}
        bench_selected = [c for c in self.in_hand_character if c is not None and c.name in self.desired_team and c.name not in field_names and not c.is_locked]
        retire_count = max(0, len({c.name for c in bench_selected}) - max(0, self.max_team_size - self.current_team_size))
        for _ in range(retire_count):
            empty_bench = next((i for i, c in enumerate(self.in_hand_character) if c is None), None)
            if empty_bench is None:
                break
            # A change from four front units to more supports needs a real
            # vacant team slot; a full-area drag can otherwise be rejected.
            extras = [(c.cost, c.stars, area, i) for area, chars in (('on_field', self.on_field_character), ('off_field', self.off_field_character))
                      for i, c in enumerate(chars) if c is not None and not c.is_locked and c.name not in self.desired_team]
            extras = [item for item in extras if any(c.position == Positioning.OnOffField or
                       c.position == Positioning.OnField and (item[2] == 'on_field' or any(x is None for x in self.on_field_character)) or
                       c.position == Positioning.OffField and (item[2] == 'off_field' or any(x is None for x in self.off_field_character))
                       for c in bench_selected)]
            if extras:
                _, _, area, index = min(extras)
                if not self.swap_character_between_areas(area, index, 'in_hand', empty_bench):
                    break
            else:
                break
        return super().place_character()

    @staticmethod
    def character_from_text(name):
        exact = Characters.get_character(name.strip())
        if exact is not None:
            return exact
        cleaned = normalize(name)
        matches = {id(c): c for known, c in Characters.characters.items() if normalize(known) == cleaned}
        if not matches:
            prefixes = [(len(normalize(known)), c) for known, c in Characters.characters.items() if cleaned.startswith(normalize(known))]
            if prefixes:
                length = max(item[0] for item in prefixes)
                matches = {id(c): c for size, c in prefixes if size == length}
        if not matches and len(cleaned) >= 2:
            matches = {id(c): c for known, c in Characters.characters.items() if normalize(known).startswith(cleaned)}
        return next(iter(matches.values())) if len(matches) == 1 else None

    def get_in_hand_area(self, force=False):
        self._get_character_in_area(self.in_hand_area, self.in_hand_character, force=force, count_stars=True)
        for character in self.in_hand_character:
            if character is not None:
                character.is_placed = False
        logger.info(f'当前备战席角色：{self.in_hand_character}')

    @staticmethod
    def slot_occupied(image, point):
        x, y = round(point[0] * 1280), round(point[1] * 720)
        crop = image[max(0, y - 25):y + 25, max(0, x - 25):x + 25]
        return bool(crop.size and crop.std(axis=(0, 1)).mean() >= 24)

    @staticmethod
    def slot_locked(image, point):
        x, y = round(point[0] * 1280), round(point[1] * 720)
        crop = image[y - 72:y - 50, x - 35:x + 35]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        gold = cv2.inRange(hsv, np.array((10, 60, 100)), np.array((45, 255, 255)))
        return cv2.countNonZero(gold) >= 25

    def count_stars(self):
        op = self.operator
        crop = op.image[23:48, 970:1105]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, np.array((8, 90, 180)), np.array((42, 255, 255)))
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        intervals = sorted((x, x + w) for x, y, w, h, area in stats[1:] if area >= 8 and h >= 4 and w >= 4)
        merged = []
        for left, right in intervals:
            if merged and left <= merged[-1][1] + 2:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        stars = sum(max(1, round((right - left) / 13)) for left, right in merged)
        return min(3, max(1, stars))

    def equip_recommended(self):
        op = self.operator
        op.snapshot()
        if not op.click_text('装备推荐', (0.65, 0.7, 0.99, 0.87), after_sleep=0.3):
            return
        for _ in range(4):
            op.snapshot()
            actions = op.match(('装备', '合成', '穿戴'), (0.45, 0.3, 0.99, 0.96), exact=True)
            if not actions:
                break
            op.click_box(actions[0], after_sleep=0.3)
        self.back()

    def get_coins(self):
        return self.read_number((0.936, 0.811, 0.965, 0.865), default=None)

    def get_level(self):
        box = self.operator.read_line((44 / 1280, 572 / 720, 128 / 1280, 615 / 720))
        matches = re.findall(r'\d+', box.source)
        value = int(matches[-1]) if matches else self.max_team_size
        return value if 1 <= value <= 10 else self.max_team_size

    def read_number(self, region, default=None):
        op = self.operator
        op.snapshot(ocr=False)
        x1, y1, x2, y2 = op.region_pixels(region)
        crop = op.image[y1:y2, x1:x2]
        text, _ = op.model.ocr_single_line(cv2.resize(crop, None, fx=2, fy=2))
        text = text.translate(str.maketrans({'O': '0', 'o': '0', 'I': '1', 'l': '1'}))
        match = re.search(r'\d+', text)
        return int(match.group(0)) if match else default

    def update_max_team_size(self):
        self.close_shop()
        op = self.operator
        op.snapshot()
        for box in op.match(('/', 'i', 'Ⅰ', 'I'), (0.4, 0.15, 0.56, 0.28)):
            digits = re.findall(r'\d+', box.source)
            if digits:
                value = int(digits[-1]) if len(digits) > 1 else int(digits[0][-1])
                if 3 <= value <= 10:
                    self.max_team_size = value
                    break
        self.max_team_size = max(self.max_team_size, min(10, self.get_level()))
        logger.attr('CW team capacity', self.max_team_size)

    def team_opportunity(self, candidate, extra=()):
        if candidate is None or candidate.is_npc:
            return False, False
        from tasks.currency_wars.synergy import select_team, trait_counts
        units = self.on_field_character + self.off_field_character + self.in_hand_character + list(extra)
        fixed = [c for c in units if c and c.is_locked and c.is_placed]
        args = dict(planned=self.strategy_characters, targets=self.target_synergies,
                    capacity=self.max_team_size - len(fixed),
                    front_slots=len(self.on_field_area) - sum(c in self.on_field_character for c in fixed),
                    back_slots=len(self.off_field_area) - sum(c in self.off_field_character for c in fixed),
                    required=self.required_synergies or None, fixed=fixed)
        before = select_team(units, **args)
        after = select_team(units + [candidate], **args)
        def score(names, pool):
            counts = trait_counts([c for c in pool if c and c.name in names] + fixed)
            required = self.required_synergies or self.target_synergies
            return (sum(counts[t] >= n for t, n in required.items()),
                    sum(min(counts[t], n) / n for t, n in required.items()),
                    sum(min(counts[t], n) / n for t, n in self.target_synergies.items()))
        helps_goal = candidate.name in after and score(after, units + [candidate]) > score(before, units)
        return len(after) > len(before), helps_goal

    def population_goal(self, copies=None):
        stage = re.sub(r'\s+', '', self.last_stage)
        if stage.startswith(('2-', '3-')) and (self.target_synergies or self.required_synergies):
            formation = self.formation_population or min(10, len(self.strategy_characters))
            return max(self.min_level, formation)
        copies = self.owned_copies() if copies is None else copies
        core = self.three_star_cores[0] if self.three_star_cores else next(iter(self.strategy_characters), None)
        if core and copies.get(core, 0) >= 3 ** (self.strategy_characters[core] - 1):
            return max(self.min_level, self.mid_level)
        return self.min_level

    def shopping(self, light=False, fill_vacancies=False):
        op = self.operator
        self.open_shop()
        purchased_units = []
        copies = self.owned_copies()
        for name, amount in self._pending_purchases.items():
            copies[name] = copies.get(name, 0) + amount
        for _ in range(2 if light else 80):
            coins = self.get_coins()
            if coins is None:
                op.save('coins_ocr_failed')
                raise RuntimeError('商店金币未能识别；停止购物避免错误花费')
            level = self.get_level()
            op.snapshot()
            names = op.read_shop_names()
            prices = op.read_shop_prices()
            logger.attr('CW shop', [(box.source, box.center[0]) for box in names])
            logger.attr('CW economy', dict(coins=coins, reserve=self.min_coins, level=level, search_level=self.min_level))
            bought = False
            available = max(0, len(self.in_hand_area) - (self._quick_bench_count if light else self.in_hand_character_count))
            def purchase_order(box):
                character = self.character_from_text(box.source)
                name = character.name if character else ''
                core_rank = self.three_star_cores.index(name) if name in self.three_star_cores else len(self.three_star_cores)
                return (name not in self.strategy_characters, copies.get(name, 0) > 0, core_rank,
                        character.cost if character else 99)
            for box in sorted(names, key=purchase_order):
                char = self.character_from_text(box.source)
                slot = round((box.center[0] - 225) / 224)
                price = prices[slot] if 0 <= slot < len(prices) else None
                owned = copies.get(char.name, 0) if char else 0
                target = self.strategy_characters.get(char.name, 2 if self.desired_team and char.name in self.desired_team else 0) if char else 0
                fills_space, helps_goal = self.team_opportunity(char, purchased_units) if owned == 0 and (not light or fill_vacancies) else (False, False)
                if not target and (fills_space or helps_goal):
                    target = 2 if helps_goal else 1
                first_needed = owned == 0 and (fills_space or helps_goal or bool(char and char.name in self.strategy_characters))
                # Buy between interest thresholds; never require forty coins
                # before improving an early team. Paid XP/rolls keep their reserve.
                purchase_reserve = min(self.min_coins, coins // 10 * 10)
                immediate_upgrade = owned > 0 and owned % 3 == 2 and target >= 2
                can_merge = owned > 0 and (owned + 1) % 3 == 0
                has_space = available > 0 or can_merge
                if char and target and has_space and owned < 3 ** (target - 1) and price is not None and price <= coins and (coins - price >= purchase_reserve or first_needed or immediate_upgrade):
                    op.click_box(box, after_sleep=0.3)
                    actual = self.get_coins()
                    if actual is None:
                        raise RuntimeError('购买后金币未能确认，停止购物')
                    if actual >= coins:
                        continue
                    units = max(1, price // max(1, char.cost))
                    copies[char.name] = owned + units
                    if owned == 0:
                        purchased_units.append(copy(char))
                    if light:
                        self._pending_purchases[char.name] = self._pending_purchases.get(char.name, 0) + units
                    available = min(len(self.in_hand_area), available + 1) if can_merge else available - 1
                    logger.info(f'CW buy {char.name}: {coins}->{actual}, owned copies={copies[char.name]}, target stars={target}')
                    coins = actual
                    bought = self.inventory_changed = True
                    self.roster_cache.invalidate_name(char.name)
                    op.device.click_record_clear()
                    if char == Characters.SilverWolfLV999:
                        self.detect_silver_wolf_lv999()
            if light:
                self._quick_bench_count = len(self.in_hand_area) - available
                free = op.text_ocr('免费', (0.87, 0.48, 0.99, 0.62))
                if free and available > 0 and op.click_text('刷新', (0.85, 0.4, 1, 0.65), after_sleep=0.3):
                    continue
                break
            if self.in_hand_character_count >= 8:
                # Clear surplus immediately after purchases, before refreshing
                # another shop that cannot fit a new unit.
                self.close_shop()
                self.sync_roster()
                self.sell_character()
                self.open_shop()
                coins = self.get_coins()
                if coins is None:
                    raise RuntimeError('清理备战席后金币未能识别')
            # Every discretionary expense observes the reserve, including
            # experience. Overclock uses the same budget guard.
            search_level = self.population_goal(copies)
            if level < search_level and coins - 4 >= self.min_coins:
                op.snapshot()
                if self.buy_experience():
                    after = self.get_coins()
                    if after is not None and after < coins:
                        self.inventory_changed = True
                        op.device.click_record_clear()
                        continue
            missing = any(copies.get(name, 0) < 3 ** (stars - 1) for name, stars in self.strategy_characters.items())
            if level >= search_level and missing and self.in_hand_character_count < 8 and coins - 2 >= self.min_coins:
                op.snapshot()
                if not op.click_text('刷新', (0.85, 0.4, 1, 0.65), after_sleep=0.3):
                    raise RuntimeError('手机商店刷新按钮未识别')
                after = self.get_coins()
                if after is not None and after < coins:
                    op.device.click_record_clear()
                    continue
            break
        self.close_shop()

    def owned_copies(self):
        copies = {}
        for character in self.on_field_character + self.off_field_character + self.in_hand_character:
            if character is not None and not character.is_npc:
                copies[character.name] = copies.get(character.name, 0) + 3 ** (max(1, character.stars) - 1)
        return copies

    def buy_experience(self):
        op = self.operator
        region = (0, 0.7, 0.15, 0.85)
        button = op.text('购买经验', region) or op.text_ocr('购买经验', region)
        return op.click_box(button, after_sleep=0.3)

    def resync_roster(self):
        self.roster_dirty = False
        self.reset_character()
        self._restore_attempted = True
        self.refresh_character()
        self.get_in_hand_area(True)
        self.update_max_team_size()
        self.inventory_changed = False
        self._pending_purchases.clear()
        self.save_roster()
        logger.attr('CW inventory', dict(field=[(c.name, c.stars) for c in self.on_field_character + self.off_field_character if c], bench=[(c.name, c.stars) for c in self.in_hand_character if c]))

    def recover_empty_team(self):
        if self.current_team_size:
            return
        self.resync_roster()
        self.place_character()
        if self.current_team_size:
            return
        op = self.operator
        logger.warning('Empty team after roster change; buying temporary replacements')
        self.open_shop()
        coins = self.get_coins()
        if coins is None:
            raise RuntimeError('空阵容恢复时金币未能识别')
        candidates = [(self.character_from_text(b.source), b) for b in op.read_shop_names()]
        candidates = [(c, b) for c, b in candidates if c and not c.is_locked]
        candidates.sort(key=lambda item: (item[0].name in self.strategy_characters, item[0].position != Positioning.OffField, item[0].cost), reverse=True)
        bought = set()
        for character, box in candidates:
            if character.name in bought or character.cost > coins or len(bought) >= min(3, self.max_team_size):
                continue
            op.click_box(box, after_sleep=0.4)
            coins -= character.cost
            bought.add(character.name)
        self.close_shop()
        self.get_in_hand_area(True)
        self.place_character()
        self.refresh_character()
        if not self.current_team_size:
            op.save('empty_team_recovery_failed')
            raise RuntimeError('空阵容补员未完成，停止出战')

    def harvest_crystals(self):
        self.close_shop()
        op = self.operator
        op.snapshot()
        slots = op.board_rectangles(op.image)
        equipment = op.equipment_rectangles(op.image)
        for start, end in self.loot_swipe_paths(slots, equipment):
            op.device.swipe(start, end, duration=(0.18, 0.24), name='CW_LOOT_SWEEP')
            op.snapshot()
            if op.dismiss_equipment_combine():
                self.close_shop()
                break
            if not self.is_board():
                self.close_shop()
        self.detect_silver_wolf_lv999()
        self.check_equipment_change()

    @staticmethod
    def loot_swipe_paths(slots, equipment=()):
        # Vertical strokes cover the gaps between the old four horizontal
        # drags. The stock icons at x>=1120 are already collected equipment.
        paths = [((x, 130 if x <= 1040 else 180), (x, 350)) for x in (875, 905, 935, 965, 995, 1025, 1055, 1085)]
        for x in (980, 1030):
            if not any(box.left - 8 <= x <= box.left + box.width + 8 and box.top < 528 and box.top + box.height > 342 for box in slots):
                paths.append(((x, 350), (x, 520)))
        return [(start, end) for start, end in paths if not any(
            box.left - 10 <= start[0] <= box.left + box.width + 10 and
            box.top - 10 <= max(start[1], end[1]) and box.top + box.height + 10 >= min(start[1], end[1])
            for box in equipment)]

    def _handle_sell_character(self, force=False):
        op = self.operator
        self._sale_refilled_slot = None
        copies = self.owned_copies()
        candidates = sorted(enumerate(self.in_hand_character), key=lambda item: (item[1].name in self.strategy_characters, item[1].cost, item[1].stars) if item[1] else (True, 99, 99))
        for index, char in candidates:
            if char is None or char.is_locked:
                continue
            field_copies = [c for c in self.on_field_character + self.off_field_character if c is not None and c.name == char.name]
            if field_copies and char.stars > max(c.stars for c in field_copies):
                # A free higher-star unit should replace the field copy before
                # surplus is sold, even when its purchase target is only two.
                continue
            selected = self.desired_team is not None and char.name in self.desired_team
            required = 3 ** (self.strategy_characters.get(char.name, 2 if selected else 1) - 1)
            units = 3 ** (max(1, char.stars) - 1)
            temporary = char.name not in self.strategy_characters and not self.temporary_can_improve_team(char) and not (selected and copies.get(char.name, 0) - units < required)
            # Being benched at today's population is not retirement. Preserve
            # required guide units until they can join the final formation.
            expendable = temporary or (char.name in self.strategy_characters or selected) and copies.get(char.name, 0) - units >= required
            if expendable:
                before = self.get_coins()
                op.click_point(*self.in_hand_area[index], after_sleep=0.2)
                op.snapshot()
                if op.click_text('出售', (0.86, 0.84, 0.98, 0.97), after_sleep=0.3):
                    after = self.get_coins()
                    empty = not self.slot_occupied(op.image, self.in_hand_area[index])
                    if empty or before is not None and after is not None and after > before:
                        self.in_hand_character[index] = None
                        if empty:
                            self.roster_cache.remember(f'in_hand:{index}', op.image, self.in_hand_area[index], None)
                        else:
                            self.roster_cache.invalidate(f'in_hand:{index}')
                            self._sale_refilled_slot = index
                        copies[char.name] = copies.get(char.name, 0) - units
                        logger.info(f'CW sold {char.name}: coins {before}->{after}, slot {index}, empty={empty}')
                        self.close_character()
                        return True
                    else:
                        logger.warning(f'CW sale not confirmed for {char.name}; keeping inventory state')
                self.close_character()
                logger.info(f'CW cannot sell {char.name} now; checking remaining bench candidates')
                continue
        return False

    def temporary_can_improve_team(self, candidate):
        field = self.on_field_character + self.off_field_character
        same = [c for c in field if c is not None and c.name == candidate.name]
        if same:
            return candidate.stars > max(c.stars for c in same) and not any(c.is_locked for c in same)
        if self.desired_team:
            return candidate.name in self.desired_team
        for position, characters in ((Positioning.OnField, self.on_field_character), (Positioning.OffField, self.off_field_character)):
            if candidate.position not in (position, Positioning.OnOffField):
                continue
            for existing in characters:
                if existing is None and self.current_team_size < self.max_team_size:
                    return True
                if existing is not None and not existing.is_locked and existing.name not in self.strategy_characters and (candidate.cost, candidate.stars) > (existing.cost, existing.stars):
                    return True
        return False

    def sell_character(self, proactive=False):
        if not self.in_hand_character_count or self.in_hand_character_count < 8 and not proactive:
            return True
        self.close_shop()
        logger.info(f'CW bench cleanup: {self.in_hand_character_count}/9, reserving space before placement/purchases')
        self.update_team_plan()
        for _ in range(9):
            if not self.in_hand_character_count or self.in_hand_character_count < 8 and not proactive or not self._handle_sell_character():
                break
            if self._sale_refilled_slot is not None:
                # A queued reward filled the freed slot. Visual checks reuse
                # the untouched slots and identify only the new contents.
                self.get_in_hand_area()
                self.update_team_plan()
        self.save_roster()
        if self.in_hand_character_count >= 8:
            logger.info('CW bench keeps upgrade copies; paid refresh pauses until space is available')
        return self.in_hand_character_count < 8

    def battle(self):
        op = self.operator
        self.close_shop()
        self.update_max_team_size()
        if self.current_team_size < self.max_team_size:
            self.sync_roster()
            self.place_character()
            if self.current_team_size < self.max_team_size:
                self.shopping(light=True, fill_vacancies=True)
                if self.inventory_changed:
                    self.sync_roster()
                self.place_character()
            if self.current_team_size < self.max_team_size:
                logger.warning(f'CW remaining vacant slots: {self.current_team_size}/{self.max_team_size}; no deployable unique unit available')
        self.recover_empty_team()
        op.snapshot()
        self.last_stage = self.stage_id()
        from tasks.currency_wars.synergy import trait_counts
        field = self.on_field_character + self.off_field_character
        targets = self.required_synergies or self.target_synergies
        counts = trait_counts(field)
        self.formation_snapshot = dict(stage=self.last_stage, capacity=self.max_team_size,
                                       team=[dict(name=c.name, stars=c.stars, traits=list(c.traits)) for c in field if c],
                                       required=targets, base_counts={t: counts[t] for t in targets},
                                       estimated_targets_met=bool(targets) and all(counts[t] >= goal for t, goal in targets.items()),
                                       reward_verified=False)
        logger.attr('CW formation check', self.formation_snapshot)
        self.save_roster()
        if not op.click_text(('出战', '跳过'), (0.8, 0.55, 1, 0.75), after_sleep=1):
            op.save('battle_button_missing')
            raise RuntimeError('手机端出战按钮未识别')
        return self.wait_battle()

    def wait_battle(self):
        op = self.operator
        op.phase = 'combat'
        from tasks.combat.state import CombatState
        combat = CombatState(config=op.config, device=op.device)
        combat.combat_state_reset()
        deadline = time.monotonic() + 600
        started_at = time.monotonic()
        confirmations = 0
        while time.monotonic() < deadline:
            op.snapshot()
            # A locked board's deployment button can reopen a supply/event,
            # rather than a fight. Hand it to the stage router before trying
            # combat confirmations or waiting for a result that cannot appear.
            if self.is_item_selection() or op.text(
                    ('补给阶段', '遭遇节点', '选择投资策略', '选择投资环境',
                     '命运卜者', '盛会之星', '选择伙伴', '祈愿试炼', '我来当策划'),
                    (0.1, 0.09, 0.95, 0.22)):
                logger.info('CW pending node opened; hand over from combat wait to stage selection')
                return True
            if op.click_text('确认', (0.3, 0.5, 0.85, 0.9), after_sleep=0.5):
                confirmations += 1
                if confirmations >= 3:
                    op.save('battle_confirmation_blocked')
                    return False
                continue
            finish = op.text(('继续挑战', '继续', '前往结算'), (0.1, 0.65, 0.95, 0.96), exact=True)
            if finish:
                if finish.source == '前往结算':
                    if op.text('挑战成功', (0.25, 0.05, 0.8, 0.25)):
                        self.result = 'win'
                    elif op.text('挑战失败', (0.25, 0.05, 0.8, 0.25)):
                        self.result = 'loss'
                op.save(f'battle_{self.rounds + 1:02d}_result')
                op.click_box(finish, after_sleep=1)
                self.rounds += 1
                op.device.click_record_clear()
                return True
            # Reuse SRC's combat button detection and activity watchdog.
            if combat.is_combat_executing():
                combat.handle_combat_state(auto=True, speed_2x=True)
                op.device.stuck_record_clear()
            if self.is_board():
                if self.stage_id() != self.last_stage:
                    self.rounds += 1
                    return True
                if time.monotonic() - started_at >= 8:
                    op.save('battle_not_started')
                    return False
            op.sleep(0.8)
        op.save('battle_timeout')
        raise TimeoutError('货币战争战斗等待超时')

    def stage_transition(self):
        op = self.operator
        op.phase = 'transition'
        deadline = time.monotonic() + 150
        previous = None
        while time.monotonic() < deadline:
            op.snapshot()
            if self.is_board():
                # Node-selection overlays open after the board's entrance
                # animation, so wait for a stable board before scanning cards.
                op.sleep(1.5)
                op.snapshot()
                if not self.is_board():
                    continue
                self.last_stage = self.stage_id()
                op.save(f'round_{self.rounds:02d}_{self.last_stage}')
                if not self.is_board():
                    continue
                return self.handle_stage_transitioned()
            # Result buttons can appear before their entrance animation accepts
            # input. Retry from the observed page instead of waiting for a board
            # that the first click never opened. This does not count another round.
            if op.click_text(('继续挑战', '继续', '前往结算'), (0.1, 0.65, 0.95, 0.96),
                             after_sleep=1, exact=True):
                logger.info('CW result page still visible; retry advancing to the next stage')
                continue
            if op.text('开始货币战争', (0.5, 0.75, 1, 1)):
                self.is_game_over = True
                return True
            if self.is_item_selection():
                self.handle_item_selection()
                continue
            if op.text('选择投资策略', (0.1, 0, 0.9, 0.22)):
                self.handle_invest_strategy(previous)
                previous = StageName.SELECT_INVEST_STRATEGY
                if not self.is_running:
                    return True
                continue
            if op.text('补给阶段', (0, 0, 0.8, 0.2)):
                self.handle_replenish_stage(previous)
                continue
            if op.text('遭遇节点', (0, 0, 0.8, 0.2)):
                self.handle_encounter_node(previous)
                continue
            if op.text(('命运卜者', '盛会之星', '选择伙伴', '祈愿试炼', '我来当策划'), (0.1, 0, 0.9, 0.2)):
                self.handle_special_event()
                continue
            if op.text(('下一步', '下一页', '返回货币战争'), (0, 0.7, 1, 1)):
                self.handle_game_over(previous)
                return True
            if op.click_text(('点击空白处关闭', '点击空白处继续'), (0, 0.5, 1, 1), after_sleep=0.6):
                continue
            op.sleep(0.6)
        op.save('transition_timeout')
        raise TimeoutError('货币战争关卡切换超时')

    def handle_replenish_stage(self, _=None):
        op = self.operator
        op.save(f'supply_{self.rounds}')
        from tasks.currency_wars.synergy import extract_traits
        choices = []
        # Both four- and five-card supplies use this name row. Use the actual
        # name positions so traits and clicks belong to the same offered card.
        for box in op.read_region((0.025, 365 / 720, 0.98, 398 / 720), snapshot=False):
            character = self.character_from_text(box.source)
            if character is None:
                continue
            labels = op.read_region((max(0, box.left - 10) / 1280, 282 / 720,
                                     min(1280, box.left + 175) / 1280, 365 / 720), snapshot=False)
            traits = extract_traits(' '.join(b.source for b in labels))
            score = (sum(t in traits for t in self.required_synergies),
                     sum(t in traits for t in self.target_synergies),
                     character.name in self.strategy_characters, character.cost)
            choices.append((score, box))
        if choices:
            _, chosen = max(choices, key=lambda item: item[0])
            logger.info(f'CW supply choice: {chosen.source}; candidates={len(choices)}')
            op.click_box(chosen, after_sleep=0.4)
        elif not op.text('已选择1/1', (0.7, 0.8, 1, 0.89)):
            raise RuntimeError('补给角色未识别且没有已选项')
        for _ in range(4):
            op.snapshot()
            if not op.text('补给阶段', (0.1, 0, 0.9, 0.2)):
                self.roster_dirty = True
                return
            if not op.click_text(('确认', '确认选择', '选择'), (0.5, 0.7, 1, 1), after_sleep=1.2, exact=True):
                op.sleep(0.4)
        op.save('supply_confirmation_failed')
        raise RuntimeError('补给选择确认后未离开补给界面')

    def handle_encounter_node(self, _=None):
        op = self.operator
        op.save(f'encounter_{self.rounds}')
        op.click_point(0.35, 0.5, after_sleep=0.4, tag='CW_ENCOUNTER_EASY')
        op.snapshot()
        if not op.click_text(('确认', '确认选择', '选择'), (0.1, 0.7, 0.9, 1), after_sleep=1.2, exact=True):
            raise RuntimeError('遭遇节点确认按钮未识别')

    def detect_special_event(self):
        self.operator.snapshot()
        for event, (title, handler) in self.special_events.items():
            if self.operator.text(title, (0.1, 0, 0.9, 0.2)):
                return event
        return ''

    def _handle_selection_event(self, ocr_region, keyword):
        op = self.operator
        op.snapshot()
        region = (0.15, 0.2, 0.85, 0.5)
        wanted = op.match(keyword.split(), region) if keyword.strip() else []
        if self.select_uncollected():
            pass
        elif wanted:
            op.click_box(wanted[0], after_sleep=0.3)
        else:
            candidates = [box for box in op.read_region(region, snapshot=False) if not any(word in box.source for word in ('详情', '请选择', '强化角色', '返回', '备战阶段'))]
            characters = [box for box in candidates if any(name in box.source for name in Characters.characters)]
            candidates = characters or candidates
            if not candidates:
                op.save('event_choices_missing')
                return False
            op.click_box(max(candidates, key=lambda box: box.center[0]), after_sleep=0.3)
        op.snapshot()
        return op.click_text(('确认选择', '确认', '选择'), (0.1, 0.4, 0.99, 0.96), after_sleep=1, exact=True)

    def handle_special_event(self):
        for index in range(8):
            event = self.detect_special_event()
            if not event:
                return
            self.operator.save(f'event_{self.rounds}_{index}_{event}')
            if not self.special_events[event][1]():
                raise RuntimeError(f'特殊事件处理失败：{event}')
        raise RuntimeError('特殊事件连续触发超过上限')

    def handle_game_over(self, _=None):
        op = self.operator
        op.phase = 'settling'
        pending = self.campaign.pending_settlement() if self.campaign is not None else None
        if pending:
            self.result = pending.get('result', self.result)
            self.set_actual_mode(pending.get('mode', 'overclock' if self.is_overclock else 'standard'))
        for index in range(8):
            op.snapshot()
            if op.text(('通关成功', '挑战成功', '博弈胜利', '投资成功', '对局胜利')):
                self.result = 'win'
            elif op.text(('博弈失败', '投资失败', '挑战失败', '对局未完成')):
                self.result = 'loss'
            if op.text('超频博弈', (0, 0.3, 0.4, 0.58)):
                self.set_actual_mode('overclock')
            elif op.text('标准博弈', (0, 0.3, 0.4, 0.58)):
                self.set_actual_mode('standard')
            op.save(f'settlement_{index}')
            if op.text('开始货币战争', (0.5, 0.75, 1, 1)):
                self.finish_settlement()
                return True
            footer = op.text(('下一步', '下一页', '返回货币战争'), (0.1, 0.65, 1, 1))
            if footer:
                if self.campaign is not None:
                    record = self.settlement_record()
                    if pending:
                        record = dict(pending, result=record['result'], mode=record['mode'], strategy_imported=record['strategy_imported'] or pending.get('strategy_imported', False))
                    pending = self.campaign.stage_settlement(record)
                op.click_box(footer, after_sleep=0.8)
            else:
                op.sleep(0.6)
        raise RuntimeError('货币战争结算流程未完成')

    def settlement_record(self):
        op = self.operator
        return {'time': datetime.now().isoformat(timespec='seconds'), 'mode': 'overclock' if self.is_overclock else 'standard', 'strategy': list(self.strategy_characters), 'strategy_title': self.strategy_title, 'share_code': self.strategy_code, 'rounds': self.rounds, 'result': self.result or 'settled', 'continued': self.is_continue, 'strategy_imported': self.strategy_imported, 'formation': self.formation_snapshot, 'evidence_dir': str(op.evidence_dir.resolve()) if op.evidence_dir else None}

    def finish_settlement(self, recovered=None):
        record = recovered or self.settlement_record()
        if self.campaign is not None:
            record = self.campaign.complete_pending_settlement() or self.campaign.settle(record)
        self.is_game_over = True
        self.completed_runs.append(record)
        folders = {Path(folder) for folder in (record.get('evidence_dir'), self.operator.evidence_dir) if folder}
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')

    def abort_and_return(self):
        op = self.operator
        op.snapshot()
        if not self.is_board():
            op.click_text('返回备战界面', (0.7, 0, 1, 0.18), after_sleep=1.5)
        for _ in range(12):
            op.snapshot()
            if op.text('开始货币战争', (0.5, 0.75, 1, 1)):
                return True
            if op.click_text(('撤资并结算', '结束并结算', '放弃并结算'), after_sleep=0.6):
                continue
            if op.click_text(('确认', '下一步', '下一页', '返回货币战争'), (0.1, 0.6, 1, 1), after_sleep=0.6):
                continue
            if self.is_board():
                op.click_point(0.035, 0.05, after_sleep=0.5, tag='CW_EXIT')
            else:
                self.back()
        raise RuntimeError('刷开局退出当前对局失败')

    def game_loop(self):
        if self.pending_combat:
            if not self.wait_battle():
                raise RuntimeError('接管战斗后仍停留在同一关卡')
            self.stage_transition()
            self.pending_combat = False
            if not self.is_game_over and self.is_running:
                self.close_shop()
                self.detect_board_mode()
                self.prepare_pending_strategy()
                self.handle_game_entered()
                self.sync_roster()
        while self.is_running and not self.is_game_over:
            self.close_shop()
            if self.resume_interrupted_battle():
                if not self.wait_battle():
                    raise RuntimeError('恢复中断战斗后仍停留在同一关卡')
                self.pending_combat = False
                if not self.stage_transition():
                    break
                continue
            self.last_stage = self.stage_id()
            progress_callback = getattr(self.operator, 'progress_callback', None)
            if progress_callback and self.active_run:
                progress_callback(self.active_run['id'], re.sub(r'\s+', '', self.stage_id()))
            self.harvest_crystals()
            reason = self.round_review_reason()
            if reason:
                logger.info(f'CW detailed review: {self.stage_id()} ({reason})')
                if self.roster_dirty:
                    self.resync_roster()
                else:
                    self.sync_roster()
                self.sell_character()
                self.place_character()
                self.sell_character()
                self.shopping()
                if self.roster_dirty:
                    self.resync_roster()
                elif self.inventory_changed:
                    self.sync_roster()
                self.sell_character()
                self.place_character()
                self.sell_character(proactive=True)
                if self._formation_changed:
                    self.sort_all_areas_by_priority()
                    self._formation_changed = False
                self._last_review_stage = self.stage_id()
            else:
                logger.info(f'CW fast round: {self.stage_id()}, collect drops and check free shop')
                self.shopping(light=True)
            self.save_roster()
            if not self.battle():
                raise RuntimeError('出战确认后仍在同一备战关卡，停止等待以便接管修复')
            if not self.stage_transition():
                break
            if self.is_game_over or not self.is_running:
                break
        self.reset_character()
        if self.is_running and not self.is_game_over:
            raise RuntimeError('货币战争流程中断，尚未完成结算')
        return self.is_game_over

    @staticmethod
    def parse_checkpoints(value):
        return {f'{int(plane)}-{int(round_)}' for plane, round_ in re.findall(r'([1-3])\s*[-－]\s*(\d+)', value or '')}

    def round_review_reason(self):
        if getattr(self.operator.config, 'CurrencyWars_RunStyle', 'precise') != 'fast':
            return 'precise mode'
        stage = re.sub(r'\s+', '', self.stage_id())
        health = self.read_number((0.712, 0.035, 0.757, 0.092), default=None)
        dropped = health is not None and self._last_health is not None and health < self._last_health
        if health is not None:
            self._last_health = health
        self._quick_bench_count = sum(self.slot_occupied(self.operator.image, p) for p in self.in_hand_area)
        if self.roster_dirty:
            return 'roster-changing event'
        if not self._last_review_stage or not self.current_team_size:
            return 'initial team'
        if dropped:
            return 'health dropped'
        if self._quick_bench_count >= 8:
            return 'bench nearly full'
        checkpoints = self.parse_checkpoints(getattr(self.operator.config, 'CurrencyWars_Checkpoints', ''))
        if stage in checkpoints and stage != self._last_review_stage:
            return 'configured checkpoint'
        if self.operator.text_ocr('首领', (0.30, 0.055, 0.72, 0.105)):
            return 'boss'
        return None
