"""DU event names and priorities consumed by SRC's native event handler."""
from tasks.rogue.event.preset import STRATEGIES, STRATEGY_COMMON
from tasks.rogue.event import event as native_event
from tasks.rogue.keywords import KEYWORDS_ROGUE_EVENT_OPTION, RogueEventTitle


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
    def __init__(self, *args, **kwargs):
        configure_event_presets()
        super().__init__(*args, **kwargs)

    def _event_option_filter(self):
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
