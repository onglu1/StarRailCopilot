"""DU event names and priorities consumed by SRC's native event handler."""
import hashlib
import time
from pathlib import Path

from module.base.button import ClickButton
from module.base.utils import save_image
from module.config.config import TaskEnd
from tasks.rogue.event.preset import STRATEGIES, STRATEGY_COMMON
from tasks.rogue.event import event as native_event
from tasks.rogue.keywords import KEYWORDS_ROGUE_EVENT_OPTION, KEYWORDS_ROGUE_EVENT_TITLE, RogueEventTitle


# Only the observed Chinese DU title is registered; punctuation normalization
# is already supplied by SRC. Its paid services change station cards, and the
# observed Ignore option ends the service without repeated optional purchases.
_TITLE = '维护市容（区域）'
MAINTENANCE_REGION = RogueEventTitle(
    id=1000001, name='DU_Maintenance_Region', cn=_TITLE, cht=_TITLE,
    en=_TITLE, jp=_TITLE, es=_TITLE, option_ids=[15, 17, 18, 19],
)


def configure_event_presets():
    for strategy in [STRATEGY_COMMON, *STRATEGIES.values()]:
        strategy.setdefault(MAINTENANCE_REGION, [KEYWORDS_ROGUE_EVENT_OPTION.Ignore_him])


class DivergentEvent(native_event.RogueEvent):
    def __init__(self, *args, du_main=None, **kwargs):
        self._du_main = du_main
        configure_event_presets()
        super().__init__(*args, **kwargs)

    def _record_decision(self, stage, option=None, target=None):
        """Record the frame used by native input, without observing or choosing again."""
        main = getattr(self, '_du_main', None)
        active = getattr(main, 'active', None) or {}
        if not active.get('star') or active.get('mode') != 'star' or not active.get('id'):
            return
        try:
            def area(button):
                value = getattr(button, 'button', None)
                return [int(x) for x in value] if value is not None else None

            title = getattr(self, 'event_title', None)
            context = (active['id'], active.get('node'), str(title) if title is not None else None)
            confirmation_bound = (stage != 'confirm' or
                                  (title is not None and getattr(self, '_du_confirm_context', None) == context
                                   and time.monotonic()-getattr(self, '_du_confirm_at', 0) < 30))
            options = list(getattr(self, 'options', ())) if confirmation_bound else []
            if not confirmation_bound:
                option = None
            rows = []
            for index, item in enumerate(options):
                button = getattr(item, 'button', None)
                keyword = getattr(button, 'matched_keyword', None)
                raw = getattr(button, 'text', None)
                rows.append(dict(index=index, valid=bool(item.is_valid),
                    bottom_page=bool(item.is_bottom_page), prefix_area=area(item.prefix_icon),
                    matched_area=area(button), raw_text=str(raw) if raw is not None else None,
                    matched_keyword=str(keyword.name) if keyword is not None else None,
                    matched_keyword_cn=str(keyword.cn) if keyword is not None else None))
            payload = dict(stage=stage, node=int(active.get('node') or 0),
                event_title=str(title.name) if title is not None else None,
                event_title_cn=str(title.cn) if title is not None else None,
                selected_index=next((i for i, item in enumerate(options) if item is option), None),
                target_area=area(target), options=rows, input_sent=True,
                source='native_device_image_used_for_input', extra_screenshot=False,
                extra_ocr=False, result_verified=False, screenshot=None,
                selected_option_bound=confirmation_bound and option is not None)
            image = self.device.image
            if getattr(image, 'shape', ())[:2] == (720, 1280):
                digest = hashlib.sha256(image.tobytes()).hexdigest()
                cache = getattr(self, '_du_evidence_cache', None)
                if not cache or cache['run_id'] != active['id']:
                    cache = dict(run_id=active['id'], buckets={})
                    self._du_evidence_cache = cache
                bucket = cache['buckets'].setdefault((payload['node'], stage), dict(images={}, attempts=0))
                screenshot = bucket['images'].get(digest)
                if screenshot is None and bucket['attempts'] < 8:
                    bucket['attempts'] += 1
                    folder = Path(__file__).resolve().parents[2]/'log/divergent_universe'/main.config.config_name/'star_runs'/active['id']
                    folder.mkdir(parents=True, exist_ok=True)
                    path = folder/f'event_{payload["node"]}_{stage}_{time.time_ns()}_{bucket["attempts"]}.png'
                    save_image(image, path)
                    screenshot = bucket['images'][digest] = str(path)
                payload.update(screenshot=screenshot, pixel_sha256=digest,
                    screenshot_limit_reached=screenshot is None, frame_limit_per_node_stage=8,
                    frame_limit_scope='current_worker')
            main.progress.record('star_event_decision_observed', **payload)
        except (TaskEnd, KeyboardInterrupt):
            raise
        except Exception as error:
            # Only this optional recording path is guarded. Native input and
            # its stop/error semantics stay outside the guard.
            try:
                main.progress.record('star_event_evidence_unavailable', stage=stage,
                                     error_type=type(error).__name__)
            except (TaskEnd, KeyboardInterrupt):
                raise
            except Exception:
                pass

    def handle_event_option(self):
        self._du_selected_option = None
        handled = super().handle_event_option()
        if handled:
            option = self._du_selected_option
            if option is None:
                valid = [item for item in self.options if item.is_valid]
                option = valid[0] if len(valid) == 1 else None
            self._du_confirm_option = option
            active = getattr(getattr(self, '_du_main', None), 'active', None) or {}
            title = getattr(self, 'event_title', None)
            self._du_confirm_context = (active.get('id'), active.get('node'),
                                        str(title) if title is not None else None)
            self._du_confirm_at = time.monotonic()
            # Device.click and the following native interval_reset do not
            # replace device.image; it is the post-scroll, pre-input frame.
            self._record_decision('option', option, getattr(option, 'prefix_icon', None))
        return handled

    def appear_then_click(self, button, interval=5, similarity=0.85):
        if button is not native_event.CHOOSE_OPTION_CONFIRM:
            return super().appear_then_click(button, interval=interval, similarity=similarity)
        if interval and not self.interval_is_reached(button, interval=interval):
            return False
        # An option's confirm moves with its selected row. Replaying the
        # Sword Practice failure showed alternating top/bottom selections,
        # while matching the same saved frame twice produced stable offsets.
        # Revalidate fresh frames instead of clicking the earlier row's
        # coordinates, using the unchanged native asset and native input.
        self.device.screenshot()
        if not super().appear(button, similarity=similarity):
            return False
        previous = tuple(button.button)
        self.device.screenshot()
        if not super().appear(button, similarity=similarity):
            return False
        current = tuple(button.button)
        if max(abs(old - new) for old, new in zip(previous, current)) > 3:
            return False
        # Freeze this frame's rectangle; no third match may move its offset.
        # The native name keeps the existing repeated-click guard intact.
        target = ClickButton(area=current, name=str(button))
        self.device.click(target)
        if interval:
            self.interval_reset(button, interval=interval)
        self._record_decision('confirm', getattr(self, '_du_confirm_option', None), target)
        self._du_confirm_context = None
        return True

    def _event_option_filter(self):
        option = self._du_filter_option()
        self._du_selected_option = option
        return option

    def _du_filter_option(self):
        active = getattr(getattr(self, '_du_main', None), 'active', None) or {}
        if active.get('mode') == 'star' and active.get('star'):
            # This actual DU page offers 150 fragments and no further errors.
            # Scope its priority to this native dispatch, including title OCR;
            # other tasks must not inherit a permanent global preset change.
            title = KEYWORDS_ROGUE_EVENT_TITLE.Life_Divergence_I
            strategy = STRATEGIES.get(self.config.RogueWorld_DomainStrategy, STRATEGY_COMMON)
            existed, previous = title in strategy, strategy.get(title)
            strategy[title] = [KEYWORDS_ROGUE_EVENT_OPTION.Perform_corrections]
            try:
                option = super()._event_option_filter()
            finally:
                if existed:
                    strategy[title] = previous
                else:
                    strategy.pop(title, None)
        else:
            option = super()._event_option_filter()
        if self.event_title != MAINTENANCE_REGION:
            return option
        ignore = KEYWORDS_ROGUE_EVENT_OPTION.Ignore_him
        # Native OCR inspects both ends of a scrolling list. Prefer the fresh
        # bottom copy of Ignore so native dispatch does not scroll back to a
        # clipped top copy whose confirmation falls below the viewport.
        bottom = [item for item in self.valid_options if item.is_bottom_page
                  and item.button is not None and item.button.matched_keyword == ignore]
        if bottom:
            return bottom[-1]
        if (not any(item.is_bottom_page for item in self.options)
                and option.button is not None and option.button.matched_keyword == ignore):
            scroll = native_event.SCROLL_OPTION
            if scroll.appear(main=self) and scroll.is_draggable(main=self) and scroll.at_bottom(main=self):
                # A resumed page may already be at the bottom, so native
                # set_bottom did not create a second copy of the option.
                option.is_bottom_page = True
        return option
