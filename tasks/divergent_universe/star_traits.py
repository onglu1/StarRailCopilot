"""Explicit one-shot trait-page inspection; never activate or close unknown UI."""
from pathlib import Path
import time

from module.base.utils import save_image
from module.config.config import TaskEnd
from tasks.currency_wars.operator import normalize
from tasks.divergent_universe.operator import DivergentOperator
from tasks.divergent_universe.star_inventory import StarInventory


KEY = 'traits_inspect_v1'
HEADER = (.065, .048, .24, .093)
BUTTON = (970/1280, 18/720, 1030/1280, 58/720)


class TraitInspectionOperator(DivergentOperator):
    def snapshot(self, ocr=False):
        # Normal snapshot may dismiss monthly rewards. This diagnostic must
        # issue only the known inventory navigation and the one trait click.
        self.check()
        self.image = self.device.screenshot()
        self._ocr_cache.clear()
        self.frame_cache.clear()
        self.boxes = []
        if self.image.shape[:2] != (720, 1280) or ocr:
            raise ValueError('特性诊断只允许1280x720原生截图与局部识别')
        return self.boxes


def inspect_traits(config, progress, expected_run):
    """Called only by the locked CLI, which exits normally with this checkpoint."""
    active = progress.data.get('active') or {}
    star = active.get('star') or {}
    saved = star.get('loadout') or {}
    if (not expected_run or active.get('id') != expected_run
            or active.get('mode') != 'star' or active.get('stop_requested')
            or type(active.get('node')) is not int or active['node'] < 7
            or star.get('candidate') not in ('dot', 'dot_blackswan')
            or saved.get('candidate') != star.get('candidate')):
        raise ValueError('特性诊断要求指定保留中的DOT原局、节点至少7且未请求结束')
    if config.stop_event is not None and config.stop_event.is_set():
        raise TaskEnd
    previous = progress.data.get('star_mechanism_pages', {}).get(KEY)
    if previous:
        return dict(status='already_attempted', checkpoint=previous)
    deadline = time.time() + 45
    recovery = progress.data.get('recovery') or {}
    for value in (recovery.get('deadline'), recovery.get('run_deadline'),
                  (recovery.get('combat_pause') or {}).get('hard_deadline')):
        if value is not None:
            deadline = min(deadline, float(value))
    if deadline <= time.time():
        return dict(status='needs_inventory', reason='existing_recovery_deadline_expired')
    # Validate before constructing a device; do not call _initialize(), login,
    # policy migration, preparation recovery or the CLI's 180-second override.
    from tasks.divergent_universe.star_policy import StarLoadout
    loadout = StarLoadout(**saved)
    from tasks.divergent_universe.divergent_universe import DivergentUniverse
    main = DivergentUniverse(config=config, task='DivergentUniverse')
    main.progress, main.active, main.star_loadout = progress, active, loadout
    main.op = op = TraitInspectionOperator(main.device, config)
    op.deadline = min(op.deadline, time.monotonic() + max(0, deadline-time.time()))
    inventory = StarInventory(main)
    op.snapshot()
    if main.world_visible() or main.is_combat_executing():
        return dict(status='needs_inventory', reason='world_or_combat_no_input')
    if not inventory.blessing_page() and main.selection_kind() not in ('equation', 'blessing'):
        return dict(status='needs_inventory', reason='known_reward_or_blessing_inventory_required')
    state = dict(status='preparing_inventory', run_id=expected_run, node=active['node'],
                 attempted_at=time.time(), previous_phase=progress.data.get('phase'),
                 trait_verified=False, return_verified=False, frames=[])
    progress.data.setdefault('star_mechanism_pages', {})[KEY] = state
    progress.data['inspection_checkpoint'] = state
    previous_error = progress.data.get('error')
    had_error = 'error' in progress.data
    active.setdefault('execution', {})['development_inspection'] = True
    progress.data['phase'] = 'inspection_paused'
    progress.record('star_traits_inspection_attempted', **state)
    progress.save()  # Persist before any input; a reload cannot reopen it.
    try:
        if not inventory.blessing_page() and inventory.read(close=False) is None:
            state.update(status='needs_inventory', reason='reward_departed')
            return state
        title = None
        for _ in range(2):
            op.snapshot()
            current = normalize(op.read_line(HEADER, snapshot=False).source)
            if (not inventory.blessing_page() or (title is not None and current != title)):
                state.update(status='needs_inventory', reason='inventory_not_stable')
                return state
            title = current
        controls = [box for box in op.read_region(BUTTON, snapshot=False)
                    if normalize(box.source) == '特性'
                    and 970 <= box.left < box.left+box.width <= 1030
                    and 18 <= box.top < box.top+box.height <= 58]
        if len(controls) != 1:
            state.update(status='needs_inventory', reason='trait_button_not_unique')
            return state
        folder = Path(__file__).resolve().parents[2]/'log/divergent_universe'/config.config_name/'star_runs'/expected_run
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.time_ns()
        before = folder/f'traits_before_{stamp}.png'
        save_image(op.image, before)
        state.update(status='opening_once', before_screenshot=str(before), original_title=title,
                     button=list(controls[0].button))
        progress.save()
        if not op.click_box(controls[0], interval=1):
            state.update(status='not_opened', reason='input_not_sent')
            return state
        state['open_sent'] = True
        for index in range(2):
            op.snapshot()
            path = folder/f'traits_after_open_{stamp}_{index}.png'
            save_image(op.image, path)
            frame = dict(screenshot=str(path), header_roi=list(HEADER))
            state['frames'].append(frame)
            frame['header'] = op.read_line(HEADER, snapshot=False).source
        state.update(status='awaiting_page_review', reason='captured_unverified_page_no_close_or_activation')
        return state
    except (TaskEnd, KeyboardInterrupt):
        state.update(status='interrupted', reason='stop_requested')
        raise
    except Exception as error:
        state.update(status='inspection_incomplete', reason=f'{type(error).__name__}: {error}')
        return state
    finally:
        # No run() error handler: this CLI ends at an intentional inspection
        # checkpoint. Keep the original recovery/error and unfinished run.
        progress.data['phase'] = 'inspection_paused'
        if had_error:
            progress.data['error'] = previous_error
        progress.record('star_traits_inspection_checkpoint', **state)
        progress.save()
